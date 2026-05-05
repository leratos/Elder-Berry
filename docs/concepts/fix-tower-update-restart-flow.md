# Hotfix – Tower-Update + Self-Respawn 🔁

**Status:** Konzept (2026-05-05)
**Branch:** `fix/tower-update-restart-flow`
**Aufwand:** ~2 h (Code + Tests)
**Voraussetzung:** Phase 77.5 gemerged (`main` @ 33a262c)
**Roadmap-Referenz:** Bug-Fix außerhalb der Phasen-Nummerierung; Phase 78 bleibt unberührt.

## 1. Ausgangslage

Der Tower-Auto-Agent wird auf Windows über den Aufgabenplaner gestartet:

```
Aktion:    python scripts/start_saleria.py --mode agent
```

`run_agent()` startet uvicorn auf Port 8090 (`tower.tower_server:app`).
Beim Befehl `update alles` (vom Server-Bot via Matrix) passiert Folgendes:

1. `comms/commands/update_commands.py:_cmd_update_all` → ruft RPi → Tower → Server
   nacheinander.
2. Tower-Update geht über HTTP-POST an `/system/update` auf dem Tower.
3. Tower-Endpoint (`tower/tower_server.py`, ~Z. 619–719):
   - `git fetch`, prüft `commits behind`.
   - **Wenn `behind == 0`:** Returns `{"success": True, "message": "Alles aktuell"}`. Kein Exit.
   - **Wenn `behind > 0`:** `git pull` + `pip install` + `os._exit(1)` nach 2 s Verzögerung.

### 1.1 Zwei Fehlerbilder

**A. „Update terminiert sauber, Aufgabenplaner reaktiviert nicht."**

Der `os._exit(1)` triggert in der Praxis nicht den Aufgabenplaner-Restart.
Grund: Die Option „Falls Aufgabe scheitert, neu starten alle X Min." reagiert
nur auf **Start-Fehler** (Task konnte nicht gestartet werden — Pfad falsch,
User nicht eingeloggt etc.), **nicht** auf einen non-zero Exit-Code eines
Prozesses, der erfolgreich gestartet ist und sich danach beendet.
Vom User mit Screenshot bestätigt (1 Min, 10 Versuche aktiviert — ohne Effekt).

Konsequenz: Der Tower beendet sich, der neue Code liegt zwar auf der Platte,
aber der Service ist down bis zum nächsten Trigger (Login / Boot).

**B. „Lokal aktuell — Restart wird stillschweigend übersprungen."**

Wenn der Tower bereits den neuesten Commit hat (häufig, weil parallel
am Code gearbeitet und manuell gepullt wurde), läuft der laufende Prozess
mit altem Modulstand weiter — das letzte `pip install -e .` wird nie
ausgeführt, gestartete Module behalten ihren In-Memory-Stand. Der
Server-Pfad (`_cmd_update`) fragt in diesem Fall „Soll ich trotzdem
neustarten?" via `pending_confirmation` — der Tower-Pfad nicht.

`_cmd_update_all` leitet zudem nur die `pending_confirmation` des
Servers weiter (`update_commands.py:441`). Tower- und RPi-Pendings
gehen verloren.

## 2. Ziel

1. Tower-Restart funktioniert unabhängig von Aufgabenplaner-Settings
   (Self-Respawn aus dem Prozess heraus).
2. Bei lokal aktuellem Tower fragt das System „Trotzdem neustarten?"
   — analog zum Server-Pfad.
3. Bei `update alles` werden Tower- und RPi-Pendings genauso berücksichtigt
   wie Server-Pendings (Sammelfrage statt Verschlucken).
4. Keine Regression im normalen Update-Pfad mit neuen Commits.

**Nicht-Ziele:**

- Aufgabenplaner-Konfiguration ändern (deployment-only, nicht im Code).
- Restart-Flag-Mechanismus für den Tower einbauen (Server-only; Tower hat
  keine Matrix-Verbindung, also keine „Bin wieder da"-Nachricht).
- RPi-Pfad anfassen — der RPi nutzt systemd, das funktioniert; nur das
  Verschlucken der pending_confirmation in `_cmd_update_all` wird gefixt.

## 3. Vorgehen

### 3.1 Tower – `/system/update` umbauen

Datei: `tower/tower_server.py`

**Neue Signatur:**
```python
@app.post("/system/update")
async def system_update(force: bool = False):
    ...
```

**Änderungen am `behind == 0`-Pfad:**
```python
if behind == 0 and not force:
    return {
        "success": True,
        "up_to_date": True,
        "message": "Alles aktuell -- kein Update noetig.",
    }
```

`up_to_date` wird vom Server-Bot ausgewertet, um „trotzdem neustarten?"
zu fragen. Mit `force=true` wird der Restart-Pfad auch ohne neue
Commits durchlaufen (überspringt git pull + pip, geht direkt zum
Respawn — siehe 3.2).

**Änderungen am Restart-Pfad:**

`_delayed_exit()` umbenennen zu `_delayed_respawn()` und so umbauen:

```python
def _delayed_respawn() -> None:
    import time
    time.sleep(2)  # HTTP-Response flushen
    logger.info("Tower-Update: spawne neuen Prozess vor Exit...")

    # Detached, damit Child den Parent-Exit ueberlebt
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP \
        if sys.platform == "win32" else 0

    subprocess.Popen(
        [sys.executable, *sys.argv],
        cwd=os.getcwd(),
        creationflags=creationflags,
        close_fds=True,
    )
    time.sleep(1)  # Child kurz Zeit zum Starten
    logger.info("Beende aktuellen Prozess (Exit 0).")
    os._exit(0)
```

Exit-Code wird auf **0** geändert — der Aufgabenplaner-„Last Run Result"
soll nicht mehr nach Failure aussehen, weil wir den Restart selbst übernehmen.

### 3.2 Port-Race vermeiden

Datei: `scripts/start_saleria.py:run_agent`

Der Child-Prozess (frisches `start_saleria.py --mode agent`) startet,
während der alte Prozess noch ~1 s läuft und Port 8090 belegt. Ohne
Wartezeit knallt uvicorn beim Bind. Lösung: Port-Free-Polling am Anfang
von `run_agent()`:

```python
def _wait_for_port_free(host: str, port: int, timeout: float = 15.0) -> None:
    """Poll, bis der Port nicht mehr belegt ist (alter Prozess weg)."""
    import socket as _socket
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.connect((host, port))
            except (OSError, ConnectionRefusedError):
                return  # Port ist frei
        time.sleep(0.5)
    logger.warning("Port %d nach %ds noch belegt -- versuche Bind trotzdem.",
                   port, timeout)
```

Aufgerufen vor `uvicorn.run(...)` mit `("127.0.0.1", port)`. Bei
**Erst-Start** (kein alter Prozess vorhanden) hängt der `connect`
sofort mit ConnectionRefused ab → kein Verzug.

### 3.3 Comms-Side – Sammelfrage

Datei: `src/elder_berry/comms/commands/update_commands.py`

**`_cmd_update_tower` umbauen:**

Wenn die HTTP-Antwort `up_to_date: true` enthält, gib ein
`CommandResult(pending_confirmation=True, pending_data={"action": "restart_tower"})`
zurück, anstatt nur Text.

**`_cmd_update_all` umbauen:**

Aktuell wird nur `server_result.pending_confirmation` weitergereicht
(Z. 441–442). Stattdessen Pendings aus allen drei Komponenten sammeln:

```python
actions: list[str] = []
if rpi_result.pending_confirmation and rpi_result.pending_data:
    actions.append(rpi_result.pending_data.get("action", ""))
if tower_result.pending_confirmation and tower_result.pending_data:
    actions.append(tower_result.pending_data.get("action", ""))
if server_result.pending_confirmation and server_result.pending_data:
    actions.append(server_result.pending_data.get("action", ""))
actions = [a for a in actions if a]

return CommandResult(
    command="update_all",
    success=server_result.success,
    text="\n\n".join(steps),
    restart=False,  # Sammel-Restart laeuft ueber confirmation
    pending_confirmation=bool(actions),
    pending_data={"action": "restart_all", "actions": actions} if actions else None,
)
```

Wenn `_cmd_update()` für den Server bereits `restart=True` setzt
(neue Commits), wird der Server sich selbst restarten, **bevor** die
Sammelfrage greift — der Server killt seine Matrix-Connection. Das ist
OK: Tower-Pendings schicken wir VOR dem Server-Restart raus, weil
HTTP-Calls synchron sind und in `_cmd_update_all` nacheinander laufen.
Aber: Wenn Server `restart=True` hat (neue Commits) UND Tower
`up_to_date` (Sammelfrage gewollt), gilt: **Server-Restart hat Vorrang,
Sammelfrage entfällt.** Der frische Server-Bot kann dem User dann
manuell „update tower" empfehlen — ist eh selten und besser als ein
toter Restart.

### 3.4 Confirmation-Handler

Datei: `src/elder_berry/comms/confirmation_handlers.py`

`_execute_restart_confirm` (Z. 412–438) erweitern:

```python
async def _execute_restart_confirm(self, msg, action):
    self._p._pending.clear(msg.sender)
    self._p._chat_history.add(msg.sender, "user", "ja")
    self._p._chat_history.add(msg.sender, "assistant", "🔄 Neustart bestaetigt.")

    if time.monotonic() < self._p.restart_cooldown_until:
        ...
        return

    # Sammelfall: actions aus pending_data abarbeiten
    if action.action_type in ("update_all", "restart_all"):
        actions: list[str] = action.data.get("actions", [])
        for sub_action in actions:
            await self._dispatch_restart(msg, sub_action)
        return

    # Einzelfall (Bestand)
    sub_action = action.data.get("action") or "restart"
    await self._dispatch_restart(msg, sub_action)


async def _dispatch_restart(self, msg, sub_action: str) -> None:
    """Dispatcht einen Sub-Restart (restart, restart_tower, restart_rpi)."""
    if sub_action == "restart_tower":
        await self._p._channel.send_text(msg.room_id, "🔄 Tower-Neustart...")
        # HTTP-POST mit force=true, fire-and-forget (Tower ist gleich weg)
        ...
    elif sub_action == "restart_rpi":
        # Optional fuer Phase X -- jetzt nur Stub mit Text
        await self._p._channel.send_text(
            msg.room_id, "ℹ Manueller RPi-Restart noetig.",
        )
    else:  # restart (Server, Bestand)
        await self._p._channel.send_text(msg.room_id, "🔄 Starte neu …")
        from elder_berry.comms.restart_manager import perform_restart
        await perform_restart(self._p._channel, self._p._scheduler_mgr,
                              msg.room_id, msg_server_ts=msg.timestamp)
```

Wichtig: Wenn die actions-Liste BEIDES enthält (`restart_tower` + `restart`),
muss zuerst `restart_tower` (HTTP-Call) laufen, dann `restart` (Server killt
sich selbst). Reihenfolge in `_cmd_update_all`: rpi → tower → server (= so
hängen wir die Liste auch in der gleichen Reihenfolge an).

## 4. Test-Plan

Datei: `tests/test_self_update.py` (existiert)
Datei: `tests/test_update_commands.py` (existiert)

Neue / geänderte Tests:

1. `test_update_tower_up_to_date_returns_pending` — Tower-HTTP-Antwort
   `{"up_to_date": True, ...}` → `CommandResult` hat
   `pending_confirmation=True`, `pending_data["action"] == "restart_tower"`.
2. `test_update_all_aggregates_pendings` — Mock RPi=ok, Tower=up_to_date,
   Server=up_to_date → `pending_data["actions"] == ["restart_tower", "restart"]`.
3. `test_update_all_server_restart_wins` — Server hat neue Commits
   (`restart=True`), Tower up_to_date → `restart=True`, keine Sammelfrage.

Neuer Test-File: `tests/test_tower_server_update.py` mit `httpx.TestClient`:

4. `test_system_update_up_to_date_no_exit` — `git rev-list --count` gemockt
   auf 0 → Response hat `up_to_date=True`, kein Thread-Spawn.
5. `test_system_update_force_skips_pull_and_respawns` — `force=true`,
   `behind=0` → `_delayed_respawn` wird gespawnt, kein git pull.
6. `test_system_update_normal_path_respawns` — `behind=2` → git pull +
   pip + Respawn (Popen-Mock, kein echter Exit).

Neue Confirmation-Handler-Tests (`tests/test_message_handlers.py`):

7. `test_restart_confirm_dispatches_tower` — `action_type="restart_tower"`
   → HTTP-POST `/system/update?force=true` an Tower.
8. `test_restart_confirm_dispatches_all` — `action_type="restart_all"` mit
   actions=["restart_tower", "restart"] → erst Tower-POST, dann
   `perform_restart`.

Voller Lauf: `.venv\Scripts\python.exe -m pytest tests/test_self_update.py
tests/test_update_commands.py tests/test_message_handlers.py
tests/test_tower_server_update.py -x` muss grün durchlaufen.
Anschließend voller Suite-Lauf zur Sicherheit.

## 5. Risiken & Mitigation

- **Bind-Race trotz `_wait_for_port_free`**: Falls 15 s Polling nicht
  reichen → Warning loggen, trotzdem Bind versuchen. Uvicorn-Bind-Fehler
  ist non-fatal hinsichtlich Datenverlust, der nächste Aufgabenplaner-
  Trigger oder manueller Start hilft. Akzeptierter Worst Case.
- **Detached-Child stirbt früh** (Crash im run_agent vor Bind): Dann ist
  der Tower-Service bis zum nächsten Login down. Mitigation: Logging im
  Child klar erkennbar (`logger.info("Tower respawn started")` ganz am
  Anfang); User merkt es schnell. Längerfristig: separater Watchdog-Service.
- **HTTP-Timeout im `_dispatch_restart` für `restart_tower`**: Tower ist
  ja gleich weg, der POST kriegt evtl. keinen Response. Lösung: kurzes
  Timeout (5 s), Exception fangen und „Tower-Restart eingeleitet" melden.
- **Pending-Confirmation-Konflikt**: Wenn der User schon eine andere
  Pending-Action offen hat (Mail-Reply etc.), wird die neu mit der
  Sammelfrage überschrieben. Bestehende Library hat das Verhalten — kein
  Regress, aber dokumentieren.

## 6. Akzeptanzkriterien

- [ ] `update alles` mit „Tower aktuell, Server aktuell" → Sammelfrage
      „Trotzdem neustarten?" erscheint im Matrix-Chat.
- [ ] „ja" → Tower bekommt POST `force=true`, beendet sich, neuer
      Tower-Prozess läuft auf Port 8090 ohne Aufgabenplaner-Hilfe.
- [ ] „ja" → Server-Bot startet sich selbst neu (Bestand).
- [ ] „nein" → keine Aktion, Pending wird gelöscht.
- [ ] `update alles` mit neuen Commits auf Tower → automatischer
      Self-Respawn nach git pull + pip install, keine Sammelfrage.
- [ ] Aufgabenplaner-„Last Run Result" zeigt `0` statt `1` nach
      automatischem Tower-Update.
- [ ] Pytest grün, mypy unverändert (104 Files Success).
