# Phase 96 – RobotClient-Resilienz & RPi-Token-Provisionierung (Konzept)

## Ziel

Verhindern, dass ein einmaliger Verbindungs- oder Auth-Fehler beim Bot-Start
die RPi5-Funktionen **dauerhaft** lahmlegt, und Auth-Fehler (401) klar von
Netzfehlern (ConnError) unterscheidbar machen. Auslöser war ein realer Incident
(2026-06-03): alle RPi-Commands meldeten „RobotClient nicht verfügbar (RPi5
nicht verbunden)", obwohl RPi-Server und Tunnel liefen — die Wurzel war ein
fehlender `robot_auth_token` auf Bot-Seite, der wegen verschluckter
401-Antwort wie ein Netzproblem aussah.

## Leitprinzipien

- **Fehlerklassen trennen statt verschlucken**: 401/403 (Auth), 429
  (Rate-Limit) und ConnError/Timeout (Netz) müssen im Log und in der
  Nutzer-Meldung unterscheidbar sein.
- **Nicht latchen**: Ein Boot-Zeitpunkt-Fehler darf RPi-Features nicht bis zum
  Bot-Neustart deaktivieren. Recovery ohne Neustart.
- **YAGNI**: Kein Reconnect-Thread, kein Health-Poller, keine
  Provider-Abstraktion. Der `RobotClient` arbeitet ohnehin live pro Call — es
  fehlt nur, dass der Bot das nutzt statt einmalig zu prüfen und wegzuwerfen.
- **Composition/DI bleibt**: keine neuen Parallelstrukturen.

## Problemanalyse (am Code verifiziert, 2026-06-03)

**Symptom**: `update rpi` und alle RPi-abhängigen Commands (Kamera etc.)
scheitern mit „RobotClient nicht verfügbar (RPi5 nicht verbunden)".

**Wurzelkette:**

1. `scripts/start_saleria.py` (~Z. 1722–1762): RobotClient wird **einmal beim
   Start** gebaut und sofort per `is_online()` geprüft. Bei `False` →
   `robot = None`. Dieses `None` wird in *alle* Command-Handler verdrahtet:

   ```python
   robot = RobotClient(base_url=robot_host, robot_token=robot_token)
   if robot.is_online():
       logger.info("RobotClient: verbunden mit %s", robot_host)
   else:
       logger.warning("RobotClient: %s nicht erreichbar", robot_host)
       robot = None        # Latch: bleibt None bis Bot-Neustart
   ```

2. `src/elder_berry/robot/client.py` (`is_online()`): fängt **jede** Exception
   ab und gibt `False` zurück:

   ```python
   def is_online(self) -> bool:
       try:
           resp = self.health()           # GET /health, raise_for_status()
           return resp.status == "ok"
       except (httpx.HTTPError, Exception):
           return False
   ```

   Damit ist ein **401 (Auth)** nicht von einem **ConnError (Netz)**
   unterscheidbar — beides wird zu „nicht erreichbar". Genau das hat die
   Diagnose um Stunden verzögert.

3. `src/elder_berry/robot/server.py` (`RobotTokenMiddleware`): schützt alle
   Endpoints inkl. `/health`. Server-Token gesetzt → Request ohne gültigen
   `X-Saleria-Robot-Token` → **401**; nach 10 Fehlversuchen/Minute **429**
   (10 min Lockout). Token-freier Betrieb = Bypass (nur wenn server-seitig
   kein Token gesetzt ist).

4. **Provisionierungs-Lücke**: Der RPi (`start_rpi5.py`,
   `_enforce_robot_token_policy`) erzwingt den Token aus
   `ELDER_BERRY_ROBOT_TOKEN`. Auf Bot-Seite war weder die Env noch der
   SecretStore-Key `robot_auth_token` gesetzt → RobotClient sendet keinen
   Header → 401 → `is_online()=False` → `robot=None`. Der RPi wurde also auf
   Token-Pflicht gehärtet, ohne den passenden Secret auf dem Rootserver
   nachzuziehen.

**Sofort-Fix (bereits erledigt, Lera 2026-06-03)**: `robot_auth_token` im
SecretStore (Rootserver) = `ELDER_BERRY_ROBOT_TOKEN` des RPi; Saleria neu
gestartet; `curl -H "X-Saleria-Robot-Token: …" http://127.0.0.1:12800/health`
→ 200. Dieses Konzept behebt die strukturellen Ursachen, nicht das Symptom.

## Lösung / Architektur

Drei Eingriffe, alle additiv, keine neuen Klassenhierarchien:

### 96-A – Fehlerklassifikation im RobotClient

`is_online()` bleibt für Backwards-Compat als `bool`, bekommt aber eine
differenzierte Logzeile. Zusätzlich eine schmale Probe-Methode, die den Grund
liefert (kein neues großes Result-Objekt — ein Enum/Literal reicht):

```python
def probe(self) -> Literal["ok", "auth", "rate_limited", "unreachable"]:
    try:
        r = self._client.get("/health")
    except httpx.HTTPError:
        return "unreachable"
    if r.status_code in (401, 403):
        return "auth"
    if r.status_code == 429:
        return "rate_limited"
    return "ok" if r.json().get("status") == "ok" else "unreachable"
```

`is_online()` wird auf `probe() == "ok"` zurückgeführt; der Aufrufer kann den
Grund loggen. **Wichtig**: die nackte `except (... , Exception)` muss weg —
nur `httpx`-Fehler abfangen, alles andere durchreichen (verschluckte
Programmierfehler waren mit drin).

### 96-B – Kein robot=None-Latch in start_saleria.py

Bei gesetztem `robot_host` wird der RobotClient **immer** durchgereicht. Die
Boot-Probe dient nur noch der Startup-Summary-Anzeige, nicht der
Deaktivierung:

```python
robot = RobotClient(base_url=robot_host, robot_token=robot_token)
state = robot.probe()
# robot bleibt gesetzt, egal was state sagt
```

Startup-Summary-Zeile „RPi5 (Robot)" zeigt differenziert: `ok` / „Auth-Fehler
– Token prüfen" (state=auth) / „nicht erreichbar" (unreachable) / „Rate-Limit".
`robot=None` nur noch, wenn `robot_host` gar nicht konfiguriert ist.

### 96-C – Graceful Per-Call-Degradation in den Handlern

Weil `robot` nicht mehr auf `None` latcht, dürfen die RPi-Commands bei einem
Live-Fehler nicht mehr crashen. Jeder robot-Call in den Command-Handlern wird
in try/except gewrappt und übersetzt:

- ConnError/Timeout → „RPi gerade nicht erreichbar, versuch's gleich nochmal."
- 401/403 → „RPi-Token ungültig – Konfiguration prüfen." (nicht „nicht
  verbunden" — das war irreführend)

`assistant.py` umschließt die robot-Calls bereits mit try/except; die
Command-Handler (`camera_commands.py:104` u.a.) müssen nachgezogen werden.

## Betroffene Dateien / Klassen

| Datei | Änderung |
|-------|----------|
| `src/elder_berry/robot/client.py` | `probe()` + differenziertes Logging; `is_online()` auf `probe()=="ok"`; nackte `except Exception` entfernen |
| `scripts/start_saleria.py` (~Z. 1722–1762) | Latch entfernen; Startup-Summary differenziert; `robot=None` nur bei fehlendem `robot_host` |
| `src/elder_berry/comms/commands/camera_commands.py` | Per-Call try/except + differenzierte Meldung (Auth vs. Netz) statt Pauschal-„nicht verbunden" |
| weitere RPi-abhängige Handler (Audit nötig: `harmony_commands.py`, RPi-Pfade in `remote_commands.py`/`cmd_utils.py`) | analog graceful |
| `src/elder_berry/robot/server.py` | **Decision D3**: Bind `0.0.0.0:8000` → `127.0.0.1:8000` |
| `docs/` (`INSTALLATION.md` / `rpi5_setup.md` + neues Runbook) | Provisionierung `robot_auth_token` + Key-Rotation-Schritt |

## Tests

- `tests/test_robot_client_resilience.py` (neu): `probe()` gegen gemockte
  httpx-Antworten — 200/ok, 401, 429, `ConnectError` → korrekte Klassifikation;
  `is_online()`-Delegation.
- Handler-Test: Live-ConnError und 401 ergeben die jeweils richtige
  Nutzer-Meldung (kein Crash).
- **Kern-Akzeptanztest**: `probe()`/`is_online()` beim „Boot" = Fehler
  (401), danach erreichbar → ein RPi-Command funktioniert **ohne**
  Bot-Neustart. Das ist der Regressionsschutz gegen genau diesen Incident.
- pytest asyncio_mode=auto, eine Testklasse pro Datei.

## Offene Entscheidungen (für Lera)

- **D1 – Token-Ablage Bot-Seite**: SecretStore `robot_auth_token` (gewählt,
  symmetrisch zu `tower_auth_token`) vs. Env. → im Konzept als gewählt
  dokumentiert; nur Bestätigung nötig.
- **D2 – Boot-Härtung analog RPi**: Soll der Bot bei gesetztem `robot_host`
  **ohne** Token laut warnen (Startup-Summary = warn, „Token fehlt") —
  analog `_enforce_robot_token_policy` auf dem RPi? Empfehlung: ja, als WARN
  (nicht hart abbrechen, sonst killt es den ganzen Bot-Start).
- **D3 – Bind 0.0.0.0 → 127.0.0.1**: jetzt mit rein oder separat? Vorab
  prüfen, ob irgendein Pfad (z.B. `robot_proxy`) den RPi über die LAN-IP
  direkt anspricht. Wenn nein: kleiner Security-Gewinn, mitnehmen.

## YAGNI-Grenzen

- **Kein** Reconnect-Thread / Health-Poller: Der Client ist live-pro-Call;
  das Problem war ausschließlich der Latch, nicht fehlendes Polling.
- **Kein** Live-Status-Indikator im Dashboard (separate Mini-Phase, falls je
  gewünscht).
- **Keine** RobotProvider-Abstraktion, **keine** Änderung am
  Token-Mechanismus selbst (Header/Middleware bleiben).

## Bekannte Risiken

- Sobald `robot=None` nicht mehr gesetzt wird, könnten Handler-Pfade, die
  bisher implizit auf „robot is None = Feature aus" gebaut haben, jetzt live
  HTTP-Fehler werfen. → Deshalb ist 96-C (graceful per Call) **Pflicht**, nicht
  optional, und muss alle RPi-Handler abdecken (Audit vor Umsetzung).
- D3 (Bind-Wechsel) bricht alles, was den RPi über LAN-IP statt Tunnel
  erreicht. Vor der Änderung verifizieren.

## Plan B

Falls 96-C über viele Handler zu invasiv wird: Minimal-Variante = nur Latch
entfernen (96-B) + Logging differenzieren (96-A). Die bestehenden
Handler-Guards (`if not self._robot`) bleiben, müssen dann aber jeden
robot-Call in try/except führen. Geringere Reichweite, gleicher Recovery-Effekt.

## Definition of Done

- RobotClient wird bei gesetztem `robot_host` immer konstruiert; `robot=None`
  nur bei fehlendem `robot_host`.
- `probe()` unterscheidet ok/auth/rate_limited/unreachable; Startup-Summary und
  Logs zeigen den Grund.
- RPi-Commands liefern bei Live-Fehler eine differenzierte, freundliche
  Meldung; kein Crash, kein Latch nötig für Recovery.
- Kern-Akzeptanztest grün (Fehler beim Boot → Recovery ohne Neustart).
- Setup-Doku/Runbook um `robot_auth_token`-Provisionierung + Key-Rotation
  ergänzt.
- Voller pytest grün; ruff + mypy strict auf allen geänderten Modulen.

## Entscheidungen (Lera, 2026-06-03)

Diese Sektion ist gegenüber dem obigen Block „Offene Entscheidungen"
maßgeblich (append-only, der ältere Block bleibt als Historie stehen).

- **D1 → JA**: SecretStore-Key `robot_auth_token` ist die kanonische
  Token-Ablage auf Bot-Seite (symmetrisch zu `tower_auth_token`).
- **D2 → JA** (WARN, kein harter Abbruch): Beim Start, wenn `robot_host`
  gesetzt ist, aber **weder** Env `ELDER_BERRY_ROBOT_TOKEN` **noch** SecretStore
  `robot_auth_token` einen Token liefern → Startup-Summary „RPi5 (Robot):
  Token fehlt" (status=warn). Der Bot startet trotzdem durch.
- **D3 → offen** (Bind 0.0.0.0 → 127.0.0.1).

### Token-Invariante (Provisionierung & Key-Rotation)

Der Token wird auf **zwei Speicherorten mit identischem Wert** gehalten — das
ist **bewusst asymmetrisch und wird nicht vereinheitlicht**:

| Seite | Speicherort |
|-------|-------------|
| RPi (`start_rpi5.py`, `_resolve_robot_token`) | Env `ELDER_BERRY_ROBOT_TOKEN` (in der systemd-Unit) |
| Rootserver/Bot (`start_saleria.py`) | SecretStore `robot_auth_token` (kein Env-Gegenstück) |

**Invariante**: RPi-Env-Wert == Rootserver-SecretStore-Wert. Bei
Token-Rotation **beide Seiten im Gleichschritt** ändern. Anti-Scope: kein
`ELDER_BERRY_ROBOT_TOKEN` auf dem Server nachrüsten (die `or`-Kette
Env→SecretStore im Bot bleibt unverändert, server-seitig greift nur der
SecretStore-Zweig).

Gehört so ins Setup-/Rotation-Runbook (Teil von Phase 96).

## Entscheidungen — Abschluss (2026-06-03)

Ergänzt die obige Sektion; alle offenen Punkte sind damit entschieden.

- **D3 → JA**: RobotServer-Bind `0.0.0.0:8000` → `127.0.0.1:8000`. Code-Audit
  zeigt keinen LAN-IP-Konsumenten: `robot_proxy` und `RobotClient` gehen über
  `127.0.0.1:12800` (Tunnel), das RPi-Ende des Tunnels verbindet lokal auf
  `127.0.0.1:8000`. Wird als **letzter** Umsetzungsschritt (96-E) ausgeführt;
  Gate: server-seitig `curl http://127.0.0.1:12800/health` → weiter 200.
  Restrisiko nur für hypothetischen Heim-LAN-Direktzugriff (Tower/Laptop im
  Dev) — in Produktion nicht vorhanden, trivial reversibel.
- **96-D → JA**: `robot_auth_token` als first-class Dashboard-Key in
  `web/secrets_registry.py` (Kategorie Infrastruktur, `sensitive`,
  `requires_restart`, `risk_level: high`), analog `tower_auth_token`. Behebt,
  dass der Token im Dashboard weder sichtbar noch editierbar war.

### Finale Etappen-Liste

- **96-A** `robot/client.py`: `probe()`-Klassifikation (ok/auth/rate_limited/
  unreachable); `is_online()` darauf zurückführen; nackte
  `except (httpx.HTTPError, Exception)` entfernen.
- **96-B** `scripts/start_saleria.py`: `robot=None`-Latch raus; differenzierte
  Startup-Summary; **D2**-WARN bei gesetztem `robot_host` + leerem Token.
- **96-C** RPi-Command-Handler (`camera_commands.py` u.a., Audit aller
  RPi-Pfade): graceful per-call (ConnError vs. 401 unterscheiden).
- **96-D** `web/secrets_registry.py`: `robot_auth_token`-Eintrag (s.o.).
- **96-E** `robot/server.py`: Bind auf `127.0.0.1`, als letzter Schritt mit
  `curl :12800`-Gate.

**Status: alle Entscheidungen (D1–D3) getroffen → Konzept branch-fertig.**
Branch: `feature/phase-96-robot-client-resilience`. `PROJECT_ROADMAP.md`
aktualisiert Lera selbst. Umsetzung via Claude Code.
