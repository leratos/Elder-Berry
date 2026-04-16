# Phase 57 – Security-Härtung: Loopback-Bind, First-Run-Gate & Tower-Auth 🛡️

**Status:** Konzept (2026-04-15)
**Branch (geplant):** `feature/phase-57-security-haertung`
**Roadmap-Referenz:** PROJECT_ROADMAP.md Phase 57

## 1. Ausgangslage

Phase 52 hat die Sicherheitsbasis für das Settings-Dashboard gelegt
(Loopback-Only Default-Bind, statischer Token-Header, constant-time
Vergleich via `secrets.compare_digest`). Ein anschließendes Code-Review
des restlichen Stacks (2026-04-15) hat vier Lücken offengelegt, die
diese Basis wieder unterwandern.

### K1 – Setup-Wizard standalone bindet auf `0.0.0.0`

In [`setup_wizard.py:470`](../../src/elder_berry/web/setup_wizard.py)
läuft `run_setup_wizard()` als Standalone-Server auf `host="0.0.0.0"`.
Der Wizard wird von `start_saleria.py` gestartet, sobald noch kein
Matrix-Token vorhanden ist – also genau in dem Fenster, in dem der
Nutzer Anthropic-API-Keys, Matrix-Tokens und E-Mail-Passwörter
eintippt. Jedes Gerät im selben LAN kann diese Requests mitlesen oder
eigene POST-Requests an `/api/setup/*` senden (siehe K3).

### K2 – TowerServer ohne Auth auf `0.0.0.0`

`tower/tower_server.py` exponiert `/tts`, `/stt`, `/action` und
`/screenshot`. Eine Suche im Modul findet weder `Depends`, noch
`Header`, noch einen Token-Vergleich – es gibt schlicht **keine**
Authentifizierung. Der Start-Mode in
[`start_saleria.py:538`](../../scripts/start_saleria.py) bindet auf
`host="0.0.0.0"`. Die Architektur verlässt sich allein auf den
SSH-Tunnel in [`ssh-tunnel.ps1`](../../scripts/ssh-tunnel.ps1) – wer
den vergisst oder die Tower-Instanz direkt im LAN startet, gibt
Tastatur, Maus und Screenshot an jeden Host im Netz frei. Der
`/action`-Endpoint ist der gravierendste Fall: er erlaubt beliebige
Eingaben über `WindowsActionController`.

### K3 – Wizard-Exemption der Settings-Token-Middleware

Die [`SettingsTokenMiddleware`](../../src/elder_berry/web/settings_token_middleware.py)
aus Phase 52.1a exempted `/api/setup` dauerhaft von der Token-Prüfung
(`EXEMPT_PREFIXES = ("/api/setup",)`). Der Kommentar im Code verweist
auf „Phase 52.3 … dann kann die Ausnahme verschärft werden". Phase
52.3 wurde aber als „erledigt durch 52.0" gestrichen – der
First-Run-Marker existiert zwar bereits als Konstante
`SETUP_COMPLETE_KEY = "setup_wizard_completed"` in
[`setup_wizard.py:129`](../../src/elder_berry/web/setup_wizard.py),
wird aber von der Middleware nicht ausgewertet. Die Exemption bleibt
daher **permanent** offen. Die gestrichene Arbeit war nicht die
YAML-Umstellung, sondern die Middleware-Verschärfung – das ist die
eigentliche Lücke.

### K4 – `matrix_allowed_senders` fail-closed unklar

`matrix_allowed_senders` ist die einzige Zugangskontrolle für die
Matrix-Steuerung. Unklar ist, wie die Bridge und der
`BridgeMessageHandler` reagieren, wenn diese Liste leer oder nicht
gesetzt ist: fail-closed (niemand darf) oder fail-open (jeder darf).
Eine leere Liste kann durch Tippfehler im Setup, eine fehlgeschlagene
Registry-Migration oder einen pausierten Setup-Lauf entstehen. Der
Fall muss fail-closed sein, sonst ist die Whitelist in genau diesem
Randfall wirkungslos.

## 2. Ziele

1. **Loopback-Only als Default** für alle lokalen HTTP-Services. Eine
   Bindung an LAN-Adressen ist nur noch per expliziter Env-Variable
   möglich und wird beim Start mit einem Warn-Log kenntlich gemacht.
2. **First-Run-Gate** für die Wizard-Exemption der
   `SettingsTokenMiddleware`. Nach Abschluss des Wizards (gesetztes
   `setup_wizard_completed=true`) entfällt die Exemption und `/api/setup`
   verlangt den Token wie jeder andere schreibende Endpoint.
3. **Tower-Token** als zweite Authentifizierungs-Barriere zusätzlich
   zum SSH-Tunnel. Defense-in-Depth: Tunnel weg → Token schützt; Token
   leakt → Tunnel schützt.
4. **Audit + Regressionstest** für `matrix_allowed_senders` fail-closed,
   damit dieser Randfall dauerhaft festgeschrieben ist.

## Nicht-Ziele

- **Kein OAuth, kein Login-System.** Single-User-Setup, statischer
  Token reicht.
- **Kein mTLS.** Der SSH-Tunnel bleibt die Transport-Ebene.
- **Kein Reverse-Proxy** (nginx, Traefik). Würde die Einrichtung
  verkomplizieren und den Fokus der Phase verfehlen.
- **Keine Token-Rotation** beim normalen Start. Rotation bleibt ein
  manueller Akt (Token-Datei löschen → neuer Token beim nächsten
  Start), analog zum Phase-52.1a-Muster.
- **Keine strukturierte Audit-Log-Datei**. `logger.warning` für 401er
  genügt für Phase 57.

## 3. Architektur-Entscheidungen

### 3.1 Loopback-Default (Phase 57.1)

**Scope:** `scripts/start_saleria.py`,
`src/elder_berry/web/setup_wizard.py`,
`tests/test_start_saleria_bind.py` (neu)

**Änderungen:**

- `run_setup_wizard(secret_store, port)` bekommt einen
  `bind`-Parameter (Default `"127.0.0.1"`). `start_saleria.py` liest
  vor dem Aufruf `os.environ.get("ELDER_BERRY_SETUP_BIND", "127.0.0.1")`
  und reicht den Wert an `uvicorn.run(host=...)` durch.
- Wenn der Bind-Wert ungleich `127.0.0.1` / `localhost` / `::1` ist,
  wird beim Start ein Warn-Log emittiert:

  ```text
  WARNING: Setup-Wizard lauscht auf <bind>:<port> – Secrets werden
  im Klartext übertragen, nur im vertrauenswürdigen Netz nutzen.
  ```

- Der Tower-Agent-Modus in `start_saleria.py` (`run_tower_agent`,
  Block um Zeile 538) liest analog `ELDER_BERRY_TOWER_BIND`
  (Default `"127.0.0.1"`). Gleicher Warn-Log-Mechanismus.
- **Konsistenz**: Phase 52 hat `ELDER_BERRY_SETTINGS_BIND` in
  `start_saleria.py:1124` etabliert. Die zwei neuen Variablen folgen
  demselben Namens-Schema.
- **Getrennte Variablen** statt einer globalen `ELDER_BERRY_ALLOW_LAN`,
  damit Setup und Tower unabhängig freigegeben werden können. Der
  Tower muss z.B. für die Laptop→Tower-Route evtl. auf eine konkrete
  LAN-IP binden, während der Setup-Wizard Loopback-Only bleibt.
- **Breaking Change (abgeschwächt durch 57.1a)**: Dauerhaft headless
  laufende Installationen müssen die Env-Variable neu setzen. Der
  einmalige Upgrade-Fall wird durch die Grace-Period (siehe 3.1a)
  abgefangen. Dokumentation in `INSTALLATION.md` und im Startlog.

### 3.1a Kompatibilitäts-Grace-Period (Phase 57.1a)

Damit Nutzer nach einem Upgrade nicht kommentarlos aus dem Setup-
Wizard ausgesperrt werden, gibt es eine **einmalige** Grace-Period:

- `start_saleria.py` prüft vor dem Wizard-Start auf zwei Bedingungen:
  1. `~/.elder-berry/.phase57_migration_done` existiert **nicht**
  2. `setup_wizard_completed` ist im `SecretStore` **nicht** gesetzt
- Sind beide Bedingungen wahr (= frisches Upgrade, Setup läuft noch),
  bindet der Wizard einmalig auf `0.0.0.0` **und**:
  - emittiert eine fette Warn-Meldung im Log (Box-Drawing-Banner),
  - reicht eine Template-Variable `compat_mode: bool` an die Wizard-
    HTML durch, die ein sichtbares gelbes Banner rendert:

    ```text
    Dieser Setup-Wizard läuft einmalig im LAN-Kompatibilitätsmodus.
    Ab dem nächsten Neustart bindet er auf 127.0.0.1 (Loopback).
    Setze ELDER_BERRY_SETUP_BIND=0.0.0.0 wenn du den LAN-Zugriff
    dauerhaft brauchst.
    ```

- Nach erfolgreichem Wizard-Finish (POST `/api/setup/finish`) wird
  die Marker-Datei `~/.elder-berry/.phase57_migration_done` angelegt.
  Zukünftige Starts sind Loopback-Default.
- Existiert die Marker-Datei oder ist `setup_wizard_completed=true`,
  gilt sofort der Loopback-Default ohne Kompat-Modus.
- **Frische Neuinstallationen** (weder Marker noch `setup_wizard_completed`)
  zählen technisch als Upgrade-Fall und würden den Kompat-Modus
  auslösen. Das ist bewusst akzeptiert: auch ein frischer Neuling mit
  Headless-Server soll den Wizard im LAN erreichen können, muss die
  Env-Variable aber beim zweiten Start setzen wenn er LAN-Zugriff
  dauerhaft will. Ein zusätzlicher Check auf „leere `secrets.enc`"
  würde das verhindern, der Aufwand lohnt sich für Phase 57 nicht,
  wird aber im Implementierungs-Review nochmal diskutiert.

**Sicherheitshinweis**: Die Grace-Period ist nur dann akzeptabel, wenn
**57.2 (First-Run-Gate) vor 57.1 gemerged ist**. Sonst steht im
Upgrade-Fenster sowohl das LAN-Bind offen als auch die permanente
Wizard-Exemption der Middleware – doppeltes Risiko. Diese Reihenfolge
ist in Kapitel 5 festgeschrieben und nicht verhandelbar.

### 3.2 First-Run-Gate für Wizard-Exemption (Phase 57.2)

**Scope:** `src/elder_berry/web/settings_token_middleware.py`,
`src/elder_berry/web/setup_wizard.py` (Cache-Invalidation),
`tests/test_settings_token_middleware.py` (erweitern)

**Änderungen:**

- Die Middleware bekommt eine Constructor-Dependency auf `SecretStore`:

  ```python
  def __init__(
      self,
      app,
      token_manager: SettingsTokenManager,
      secret_store: SecretStore,
  ) -> None: ...
  ```

- Neuer interner Cache `self._setup_done: bool | None = None`. Bei
  jedem Request prüft die Middleware:

  ```python
  if self._setup_done is None:
      self._setup_done = (
          self._secret_store.get_or_none("setup_wizard_completed")
          == "true"
      )
  if self._setup_done and path.startswith("/api/setup"):
      # Exemption entfällt – Token verlangt wie bei allen
      # anderen geschützten Prefixen.
      pass
  else:
      # Wie bisher: /api/setup ist exempted
      ...
  ```

- **Cache-Invalidation**: Der Setup-Wizard-Finish-Endpoint (heute
  schreibt er `setup_wizard_completed="true"`) ruft anschließend
  `middleware.invalidate_completion_cache()` auf. Das setzt
  `_setup_done = None`, der nächste Request lädt neu.
- **Zeitkritik**: Der Cache-Lookup darf nicht bei jedem Request
  `secrets.enc` entschlüsseln. Der Cache hält das bis zum Finish in
  der Middleware-Instanz. Ein Server-Neustart lädt beim ersten
  Request neu.
- **Backwards-Kompatibilität**: Solange `setup_wizard_completed`
  nicht gesetzt ist, bleibt `_setup_done = False` und die Exemption
  aktiv. Bestehende Nutzer, die ihren Setup noch nicht abgeschlossen
  haben, spüren keine Änderung.
- **Re-Open-Semantik**: Wer den Wizard nach Setup-Abschluss erneut
  öffnen will, braucht den Settings-Token im Header. Das Wizard-UI
  sollte dafür einen Token-Input anbieten (Phase 57.2 selbst ändert
  nur die Middleware, die UI-Integration ist minimal: 401-Antwort
  triggert einen Prompt).

### 3.3 Tower-Token (Phase 57.3)

**Scope:** `tower/tower_server.py`,
`src/elder_berry/web/secrets_api.py` (Registry-Eintrag),
`scripts/start_saleria.py` (Auto-Migration),
`src/elder_berry/robot/client.py` (Header-Versand),
`tests/test_tower_auth.py` (neu)

**Änderungen:**

- **Header-Name:** `X-Saleria-Tower-Token` (konsistent zu
  `X-Saleria-Settings-Token`).
- **Token-Quelle (Priorität):**
  1. Env `ELDER_BERRY_TOWER_TOKEN` (CI- und Dev-tauglich)
  2. `SecretStore.get_or_none("tower_auth_token")`
- **Fail-closed beim Start:** Wenn keine der beiden Quellen einen
  Token liefert, **weigert sich der TowerServer zu starten**:

  ```text
  ERROR: Kein Tower-Token konfiguriert.
  Setze ELDER_BERRY_TOWER_TOKEN oder lege 'tower_auth_token' im
  SecretStore an (Settings-Dashboard → Kategorie Tower).
  ```

  Das ist ein **bewusster Breaking Change**: bisher startete der
  Server ohne Auth, ab 57.3 verlangt er explizite Einrichtung.

- **Auto-Migration beim Upgrade (Token)**: `start_saleria.py` prüft
  vor dem Tower-Start, ob `tower_auth_token` im `SecretStore`
  existiert. Wenn nein → generiert einen neuen
  (`secrets.token_hex(32)`), speichert ihn und loggt ihn einmalig in
  voller Länge (analog Phase 52.1a).

- **Auto-Migration beim Upgrade (Host)**: Zusätzlich zum Token wird
  die lokale, nach außen sichtbare IP des Tower-Hosts ermittelt und
  als `tower_advertised_host` im `SecretStore` abgelegt. Der Client
  (RobotClient) zieht **beide Werte aus demselben Store** – ein
  Dashboard-Eintrag weniger für den Nutzer.

  **Fallback-Kette** für die IP-Ermittlung (in dieser Reihenfolge):

  1. Env `ELDER_BERRY_TOWER_ADVERTISED_HOST` – expliziter Override
     für Multi-NIC-Systeme, hinter NAT, oder wenn der Nutzer einen
     DNS-Namen statt IP verwenden will.
  2. **UDP-Route-Heuristik**: Ein UDP-Socket wird zu `8.8.8.8:80`
     „connected" (kein echter Paketversand nötig). `getsockname()`
     gibt die Route-gebundene lokale IP zurück. Robust gegen
     Multi-Interface, funktioniert aber nicht offline.
  3. `socket.gethostbyname(socket.gethostname())` als zweite
     Heuristik. Gibt auf manchen Linux-Systemen `127.0.1.1` zurück
     – akzeptiert, aber mit Log-Warnung.
  4. Letzter Fallback: `"127.0.0.1"` mit einer prominenten Log-
     Warnung, dass der Nutzer `tower_advertised_host` manuell
     im Settings-Dashboard setzen muss.

  Der gewählte Wert wird einmalig beim Speichern geloggt, damit der
  Nutzer sofort sieht, was ermittelt wurde. Falls die Heuristik
  danebenliegt, korrigiert der Nutzer den Wert im Dashboard (ein
  einziges Feld).

- **Zwei Registry-Einträge** (nicht nur einer):

  ```python
  {
      "key": "tower_auth_token",
      "label": "Tower-Token",
      "category": "Tower & Agent",
      "sensitive": True,
      "requires_restart": True,
      "risk_level": "high",
      "description":
          "Header-Token für Tower-Server (X-Saleria-Tower-Token). "
          "Wird beim ersten Start automatisch generiert.",
  },
  {
      "key": "tower_advertised_host",
      "label": "Tower-Host",
      "category": "Tower & Agent",
      "sensitive": False,
      "requires_restart": True,
      "type": "str",
      "risk_level": "low",
      "description":
          "Hostname oder IP, unter der der Tower-Server für die "
          "Client-Seite erreichbar ist. Wird beim ersten Upgrade "
          "automatisch ermittelt, kann hier manuell korrigiert werden.",
  },
  ```

  Falls „Tower & Agent" als neue Kategorie entsteht, muss sie auch
  in `CATEGORY_LABELS` und `HELP_SECTIONS` (beide in
  `help_sections.py`) ergänzt werden, sonst taucht sie im Dashboard
  nicht auf.

So verlieren existierende Installationen weder ihren Tower noch die
Host-Konfiguration bei einem Upgrade, und der Nutzer muss im
Normalfall nichts manuell eintragen.

- **Dependency-Injection im Server**: Beim FastAPI-Startup wird der
  Token aus der Quelle geladen und in einem Modul-Singleton gehalten.
  Eine `require_tower_token()`-Dependency wird via `Depends()` pro
  Endpoint eingebunden. Constant-time Vergleich mit
  `secrets.compare_digest`. Fehlender Header → 401. Server-seitig
  fehlender Token → 500 (darf durch Startup-Check nie passieren).

- **Client-Anpassung (Token + Host gemeinsam):** `RobotClient` und
  die Audio-Pipeline-Route zum Tower ziehen **Token UND Host**
  gemeinsam aus dem `SecretStore`. Der Constructor bekommt zwei neue
  Parameter `tower_host: str | None = None` und
  `tower_token: str | None = None`. `None` triggert beim ersten Call
  einen Fetch aus dem Store (Env schlägt Store, wie beim Token-Gate).
  So reicht ein einziger Registry-Eintrag pro Wert für die komplette
  Tower-Anbindung, der Nutzer pflegt Host und Token nicht mehr an
  zwei verschiedenen Stellen.

- **Registry-Eintrag** in `SECRET_REGISTRY`:

  ```python
  {
      "key": "tower_auth_token",
      "label": "Tower-Token",
      "category": "Tower & Agent",
      "sensitive": True,
      "requires_restart": True,
      "risk_level": "high",
      "description":
          "Header-Token für Tower-Server (X-Saleria-Tower-Token). "
          "Wird beim ersten Start automatisch generiert.",
  },
  ```

  Falls „Tower & Agent" als neue Kategorie entsteht, muss sie auch
  in `CATEGORY_LABELS` und `HELP_SECTIONS` (beide in
  `help_sections.py`) ergänzt werden, sonst taucht sie im Dashboard
  nicht auf.

- **SSH-Tunnel bleibt erhalten**: Auth ist zusätzlich, nicht
  ersetzend. Das ist die Defense-in-Depth-Logik der Phase.

### 3.4 `matrix_allowed_senders` Design-Umkehrung (Phase 57.4)

**Scope:** `src/elder_berry/comms/bridge.py`,
`src/elder_berry/comms/allowed_senders.py` (neu),
`scripts/start_saleria.py`, `tests/test_bridge.py` (Test umgedreht),
`tests/test_comms.py` (Shadow-Wrapper),
`tests/test_allowed_senders_fail_closed.py` (neu)

**Audit-Ergebnis (2026-04-15):** Fall B (fail-open). Der Filter in
`bridge.py:332` lautete:

```python
if self._allowed_senders and msg.sender not in self._allowed_senders:
    return
```

Die Wahrheitswert-Prüfung `if self._allowed_senders` greift bei `None`
**und** bei `frozenset()` nicht – beide Fälle lassen jede Nachricht
durch. Der Startup-Code in `start_saleria.py` loggte nur eine
*Warnung* („alle Absender werden akzeptiert") und fuhr fort.

**Besondere Lage:** Im Unterschied zur ursprünglich im Konzept
skizzierten „unbemerkten Lücke" ist das keine vergessene Edge-Case.
Im `journal.txt:2530` (Phase 32) steht explizit:

> *Bridge: frozenset() (leer) ist falsy → leere allowed_senders = kein
> Filter (Design-Entscheidung, kein Bug).*

Die Autoren wussten es und haben es bewusst so gelassen – vermutlich
aus Dev-Convenience im Single-User-Setup. Damit passt der im Konzept
geplante Hotfix-Eskalationspfad **nicht**: ein Hotfix-Branch außerhalb
von 57 würde eine Design-Entscheidung zurücknehmen, die nie als Bug
registriert war. Der saubere Weg ist eine **bewusste Design-
Umkehrung** innerhalb von Phase 57.4 – hier dokumentiert und im
gleichen Zug mit dem Regression-Test implementiert.

**Umgesetzte Änderungen:**

1. **Filter-Logik strikt fail-closed** (`bridge.py:332`):

   ```python
   # Sender-Whitelist (Phase 57.4: strikt fail-closed).
   if not self._allowed_senders:
       logger.warning(
           "allowed_senders ist leer/None – Nachricht abgelehnt: %s",
           msg.sender,
       )
       return
   if msg.sender not in self._allowed_senders:
       logger.warning("Nachricht von unbekanntem Sender ignoriert: %s", msg.sender)
       return
   ```

   Weder `None` noch `frozenset()` lassen jetzt Nachrichten durch.
   Die Unterscheidung aus der Design-Diskussion („`None` als bewusster
   Dev-Override") wurde verworfen (Variante A: maximale Sicherheit,
   keine Ausnahmen, Tests setzen bei Bedarf explizit ein populated
   Set).

2. **Start-Code hart abbrechen** (`start_saleria.py`):
   Die bisherige `logger.warning`-Zeile wurde zu `logger.error`
   + `sys.exit(1)`. Fehlt `matrix_allowed_senders` oder ist die
   Liste leer/whitespace/komma-only, startet die Matrix-Bridge
   nicht. Andere Start-Modi (Terminal, Voice, Tower-Agent) sind
   unberührt, weil sie diesen Codepfad nicht durchlaufen.

3. **Neues Comms-Modul** `src/elder_berry/comms/allowed_senders.py`
   mit der Lade-/Parse-Funktion `load_allowed_senders(secret_store)`.
   Die Funktion wurde bewusst **nicht** in `start_saleria.py` inline
   gelassen, weil ein Test-Import aus `scripts.start_saleria` das
   Modul lädt und damit `logging.config.dictConfig` triggert, was
   einen `ErrorCollectorHandler` persistent an den Root-Logger hängt
   und `TestErrorAlerting::test_setup_with_collector_handler` im
   Batch-Lauf verunreinigt. Das eigene Modul ist side-effect-frei
   und sauber testbar.

4. **Tests umgedreht** (`test_bridge.py::TestSenderWhitelist`):
   `test_no_whitelist_allows_all` → `test_no_whitelist_rejects_all`
   (Assertion invertiert), plus neuer `test_empty_whitelist_rejects_all`.
   Der `_make_bridge`-Helper nutzt jetzt einen `_UNSET`-Sentinel,
   damit Tests explizit `None` reinreichen können (für die Regression)
   und der normale Default eine populated Menge ist.

5. **Neue Regression-Datei** `tests/test_allowed_senders_fail_closed.py`:
   - `TestLoadAllowedSenders` (8 Tests): valid single, valid multi,
     missing key, empty string, whitespace only, comma only, comma
     + whitespace only, mixed valid/empty.
   - `TestBridgeFailClosed` (4 Tests): None rejects, empty set
     rejects, listed passes, unlisted rejected.

6. **Shadow-Wrapper in `test_comms.py`**: ~44 Stellen rufen dort
   direkt `MatrixBridge(...)` auf – das Aufwand-Nutzen-Verhältnis
   für individuelle Anpassungen ist zu schlecht. Stattdessen shadowt
   eine Subclass `class MatrixBridge(_RealMatrixBridge)` den Import
   und setzt per `dict.setdefault` eine Default-Whitelist mit allen
   in den Tests vorkommenden Sendern. Tests, die explizit eine
   andere Whitelist prüfen wollen (z.B. den `@unknown:test`-Block),
   überschreiben den Default per Keyword-Argument. **Subclass statt
   Funktions-Wrapper**, damit `TestExtractClaudeMessage` weiter
   `MatrixBridge.extract_claude_message` als Klassen-/Static-Methode
   nutzen kann.

**Test-Ergebnis:** 131/131 grün in `test_bridge.py` +
`test_comms.py` + `test_allowed_senders_fail_closed.py`. Der volle
Suite-Run wird zusätzlich im Journal-Eintrag dokumentiert.

**Retroaktive Notiz:** Die Entscheidung aus `journal.txt:2530`
(Phase 32) bleibt historisch korrekt stehen und wird nicht editiert.
Der neue Journal-Eintrag für Phase 57.4 nimmt sie explizit zurück –
Single-Source-of-Truth für die Historie ist wichtiger als Konsistenz
zwischen zwei Zeitpunkten.

## 4. Test-Plan

Gesamt ~14 neue Tests, verteilt auf Sub-Phasen:

### 57.1 Loopback-Default & Grace-Period
- `test_start_saleria_bind.py::test_setup_wizard_default_loopback`
- `test_start_saleria_bind.py::test_setup_wizard_env_override_logs_warning`
- `test_start_saleria_bind.py::test_tower_agent_default_loopback`
- `test_start_saleria_bind.py::test_tower_agent_env_override_logs_warning`
- `test_start_saleria_bind.py::test_grace_mode_binds_lan_on_fresh_upgrade`
- `test_start_saleria_bind.py::test_grace_mode_inactive_after_marker`
- `test_start_saleria_bind.py::test_grace_mode_inactive_when_setup_completed`
- `test_start_saleria_bind.py::test_grace_mode_writes_marker_on_wizard_finish`
- `test_setup_wizard.py::test_compat_mode_flag_in_template_context`

### 57.2 First-Run-Gate
- `test_settings_token_middleware.py::test_setup_exemption_before_completion`
  (aktuelles Verhalten festschreiben, falls nicht schon abgedeckt)
- `test_settings_token_middleware.py::test_setup_exemption_after_completion_requires_token`
- `test_settings_token_middleware.py::test_completion_cache_invalidation_after_finish`

### 57.3 Tower-Token & Host-Discovery
- `test_tower_auth.py::test_server_refuses_start_without_token`
- `test_tower_auth.py::test_action_endpoint_rejects_missing_header`
- `test_tower_auth.py::test_action_endpoint_accepts_valid_token`
- `test_tower_auth.py::test_action_endpoint_rejects_wrong_token`
- `test_tower_auth.py::test_env_beats_secret_store`
- `test_tower_auth.py::test_auto_generate_token_on_first_start`
- `test_tower_host_discovery.py::test_env_override_beats_heuristics`
- `test_tower_host_discovery.py::test_udp_route_heuristic_returns_local_ip`
- `test_tower_host_discovery.py::test_gethostbyname_fallback`
- `test_tower_host_discovery.py::test_loopback_final_fallback_warns`
- `test_tower_host_discovery.py::test_discovery_persists_to_secret_store`
- `test_robot_client_auth.py::test_client_reads_token_and_host_from_store`
- `test_robot_client_auth.py::test_client_constructor_params_override_store`

### 57.4 Allowed-Senders
- `test_allowed_senders_fail_closed.py::test_empty_list_rejects_all`
- `test_allowed_senders_fail_closed.py::test_missing_key_rejects_all`
- `test_allowed_senders_fail_closed.py::test_listed_sender_passes`

Zusätzlich muss die bestehende `test_settings_token_middleware.py`
angepasst werden, weil die Middleware einen neuen Constructor-
Parameter `secret_store` bekommt. Die betroffenen Tests sind aus der
Dependency-Injection leicht umrüstbar.

## 5. Rollout & Risiken

### Breaking Changes

1. **Setup-Wizard LAN-Zugriff (57.1)**
   Bisher ging er ohne Env-Variable, ab 57.1 nicht mehr – aber die
   Grace-Period (57.1a) fängt den **ersten** Upgrade-Start ab, damit
   existierende headless Installationen nicht kommentarlos ausgesperrt
   werden. Nach diesem einen Start gilt der Loopback-Default. Betroffen
   bleibt nur, wer den Wizard **dauerhaft** headless im LAN braucht –
   dort muss `ELDER_BERRY_SETUP_BIND=0.0.0.0` explizit gesetzt werden.
   Mitigation: Grace-Period für Erstfall, `INSTALLATION.md` und
   Startup-Log dokumentieren die Variable für Dauer-Nutzer.

2. **Wizard-Exemption entfällt nach First-Run (57.2)**
   Wer nach dem Setup den Wizard erneut aufrufen will (z.B. zum
   Re-Setup), muss den Settings-Token kennen. Erwartetes Verhalten,
   wird im Wizard-UI als 401-Fehler sichtbar.

3. **TowerServer ohne Token (57.3)**
   Bisher startete er kommentarlos, ab 57.3 verweigert er den Start
   ohne Token. Mitigation: Auto-Migration in `start_saleria.py`
   generiert beim ersten Upgrade automatisch einen Token und loggt
   ihn einmalig.

### Risiken

- **Tower-Token-Migration bricht**: Wenn der Auto-Generator in 57.3
  fehlschlägt, geht nach dem Update kein Tower-Call mehr durch.
  Mitigation: Migration läuft **vor** dem TowerServer-Start mit
  Exit-Code-Check. Ein Integration-Test verifiziert den Migrationspfad.
- **Completion-Cache-Stale**: Wenn `setup_wizard_completed` gesetzt
  wird, aber der Cache nicht invalidiert, bleibt die Exemption
  „hängen". Mitigation: Der Finish-Endpoint ruft explizit
  `middleware.invalidate_completion_cache()` auf, Test festgeschrieben.
- **57.4 Fall B verzögert Phase**: Wenn ein Hotfix nötig wird, muss
  die Phase pausiert werden. Mitigation: Der Audit ist Schritt 1,
  noch vor den anderen Sub-Phasen. Kein Code wird vorher angefasst.
- **Header-Name nicht eindeutig**: Wenn irgendwo Client-seitig
  versehentlich `X-Saleria-Settings-Token` statt `X-Saleria-Tower-Token`
  mitgesendet wird, geht der Tower-Request auf 401. Mitigation: Test
  der exakten Header-Namen im Client-Modul.

### Implementierungs-Reihenfolge

1. **57.4 Audit zuerst** – entscheidet, ob die Phase planmäßig läuft
   oder für einen Hotfix unterbrochen wird.
2. **57.2 First-Run-Gate** – kleinster Scope, gute Test-Grundlage,
   kein Breaking Change für existierende First-Run-Installationen.
   **Muss vor 57.1 gemerged sein**, sonst ist das Grace-Period-Fenster
   in 57.1 doppelt riskant (LAN-Bind + offene Middleware-Exemption
   gleichzeitig). Diese Reihenfolge ist nicht verhandelbar.
3. **57.1 Loopback-Default + Grace-Period (57.1a)** – mittlerer
   Scope, Einmal-Breaking-Change für Upgrade-User per Grace-Period
   abgefangen, dauerhafter Breaking Change nur für LAN-Dauer-Nutzer.
4. **57.3 Tower-Token + Host-Discovery** – größter Scope, größter
   Breaking Change, braucht Auto-Migration für Token **und** Host.

## 6. Offene Punkte

- **Dokumentation**: `INSTALLATION.md`, `docs/ssh-tunnel.md` und ggf.
  `USAGE.md` müssen nach Abschluss der Phase die neuen Env-Variablen
  und den Tower-Header erklären. Wird als letzter Schritt von 57.3
  erledigt.
- **Rotation**: Phase 57 führt keine Token-Rotation ein. Manuell:
  Datei/Secret löschen → neuer Token beim Start. Falls sich das als
  zu unkomfortabel erweist, wäre eine Folge-Phase „Token-Rotation UI"
  ein Kandidat, ist aber nicht Teil von 57.
- **Audit-Trail**: Strukturierte `~/.elder-berry/audit.log` für 401er
  und andere Security-Events wäre eine sinnvolle Erweiterung, ist
  aber explizit nicht Teil dieser Phase.
- **`SecretStore`-Performance**: Die First-Run-Gate-Logik in 57.2 und
  die Tower-Token-Auflösung in 57.3 lesen jeweils Secrets beim
  Startup. Wenn sich herausstellt, dass die mehrfache Fernet-
  Entschlüsselung den Startup spürbar bremst, ist ein In-Memory-
  Cache mit `mtime`-Invalidierung eine Folge-Optimierung, nicht Teil
  von 57.
