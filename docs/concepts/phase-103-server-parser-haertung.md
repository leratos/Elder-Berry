# Phase 103 – Server-/Parser-Härtung (Konzept)

**Befunde:** S1 (Fail-open-Auth Bind-Pfad) · S2 (XML-Härtung) · S4 (SQL-Allowlist)
**Branch:** `feature/phase-103-server-parser-haertung`
**Quelle:** `docs/analyse-sicherheit-codequalitaet-2026-06-09.md`, am Code
re-verifiziert 2026-06-16.

## Ziel

Die drei kurzfristigen Sicherheits-Befunde der Analyse schließen, ohne den
Happy-Path zu ändern. Alle drei sind additive Härtungen:

1. **S1** – Die zwei real offenen Server-Einstiegspunkte (Robot-Simulator,
   AgentServer) fail-closed machen und die bereits in `start_rpi5.py`
   existierende Bind-Policy an *eine* wiederverwendbare Stelle heben.
2. **S2** – Externe XML-Antworten (CardDAV, Nextcloud/WebDAV) gegen
   XXE / Entity-Expansion / DTD härten (`defusedxml`-Drop-in).
3. **S4** – Defensiven Spalten-Allowlist-Guard vor die f-String-SQL in
   `contact_store`/`proposal_store` ziehen (heute kein Injection-Vektor, aber
   gegen künftiges Kippen absichern).

## S1 – Fail-open-Auth: Bind-Policy zentralisieren

### Problemanalyse (am Code verifiziert 2026-06-16)

Die Fail-open-Stellen in den Middlewares (`agent/server.py:67-69`,
`robot/server.py:262-264`, jeweils `if not self._token: return await
call_next(request)`) sind **by design** — der Schutz gehört in den Start-/Bind-Pfad.
Stand pro Server-Einstieg:

- **RPi-RobotServer** (`scripts/start_rpi5.py`): **bereits fail-closed** seit
  Phase 64 (H-2). `_resolve_robot_token()` liest `ELDER_BERRY_ROBOT_TOKEN` aus der
  Env; `_enforce_robot_token_policy(token, host)` bricht mit `sys.exit(2)` ab,
  wenn kein Token gesetzt ist UND der Bind nicht Loopback ist; Default-Bind
  `127.0.0.1`. Voll getestet (`tests/test_start_rpi5_token.py`). **Keine Änderung.**
- **Robot-Simulator** (`src/elder_berry/robot/simulator.py:234-270`,
  `python -m elder_berry.robot.simulator`): **noch fail-open**. Bei `--bind 0.0.0.0`
  nur `logger.warning`, dann `uvicorn.run`. `create_simulator()` reicht nie einen
  `robot_token` durch → die Middleware ist dauerhaft im Bypass. Das ist die real
  offene S1-Lücke (deckt zugleich Befund S5 ab).
- **AgentServer** (`src/elder_berry/agent/server.py`): hat **keinen** produktiven
  Start-Pfad. Wird nur in Tests instanziiert; `run_agent()` in `start_saleria.py`
  startet den TowerServer, nicht den AgentServer. README/architecture beschreiben
  ihn aber als Laptop-LAN-Dienst (Client-Default `…192.168.1.51:8001`). Die
  Fail-open-Lücke existiert im Code, ist heute aber nicht über einen offiziellen
  Start exponiert.

Die fail-closed-Logik existiert genau einmal, im Script `scripts/start_rpi5.py`
(außerhalb des installierbaren Packages) — Simulator/Agent können sie ohne
fragilen `scripts→src`-Import nicht sauber wiederverwenden. Genau deshalb ist der
Simulator-Pfad noch offen.

### Lösung

**103-S1-a – Bind-Policy ins Package heben.** Neues Modul
`src/elder_berry/core/bind_policy.py`:

```python
def is_loopback_host(host: str) -> bool: ...

def enforce_token_policy(
    token: str | None,
    host: str,
    *,
    token_env_name: str,
    server_label: str,
    logger: logging.Logger,
) -> None:
    """Fail-closed: ohne Token auf Non-Loopback-Bind -> logger.error + sys.exit(2).
    Loopback ohne Token -> logger.warning. Mit Token -> ok."""
```

- `scripts/start_rpi5.py` behält `_is_loopback_host` / `_enforce_robot_token_policy`
  als **dünne Re-Export-Wrapper** (delegieren an `bind_policy`), damit
  `tests/test_start_rpi5_token.py` (lädt die Helfer als Modul-Attribute,
  caplog-Assertion auf Logger `elder_berry.rpi5`) **unverändert grün** bleibt.
  Der Logger wird durchgereicht (nicht im Helper hartkodiert).

**103-S1-b – Simulator fail-closed.** In `simulator.py.__main__` nach argparse,
vor `uvicorn.run`: `ELDER_BERRY_ROBOT_TOKEN` lesen, `enforce_token_policy(...)`.
`create_simulator()` bekommt einen optionalen `robot_token`-Parameter (Default
`None`), der an `RobotServer(..., robot_token=...)` durchgereicht wird — so kann
der Simulator mit Token bewusst auf `0.0.0.0` laufen. Aufrufer
`scripts/demo_integration.py:151` (Loopback `127.0.0.1`) bricht nicht.

**103-S1-c – AgentServer fail-closed konstruieren.** `AgentServer.__init__`
bekommt einen `bind_host`-Parameter mit **fail-closed**-Semantik: ist
`agent_token` `None`, MUSS `bind_host` explizit gesetzt sein **und** Loopback
sein, sonst `ValueError`. Damit scheitert auch ein ad-hoc-uvicorn-Wrapper, der
`AgentServer(controller)` ohne Token/Bind baut (genau der vom Review genannte
Pfad), statt eine ungeschützte App zu erzeugen, die später ans LAN bindet. Mit
gesetztem Token ist `bind_host` frei (das Token schützt jeden Bind). Die
tokenlosen Test-Konstruktionen in `tests/test_agent_protocol.py` setzen
`bind_host="127.0.0.1"` (Loopback).

> **Out-of-Scope (Follow-up):** Ein vollwertiges `scripts/start_agent.py` (analog
> `start_rpi5.py`). Der AgentServer hat heute keinen produktiven Start; der
> Konstruktor-Guard sichert die künftige Verwendung ab. Ein eigenes Start-Skript
> wäre eine eigene Mini-Phase (Controller-Init auf Windows etc.).

### Betroffene Dateien (S1)

| Datei | Änderung |
|---|---|
| `src/elder_berry/core/bind_policy.py` *(neu)* | `is_loopback_host`, `enforce_token_policy` (Logger injiziert) |
| `scripts/start_rpi5.py` | Helfer als Re-Export-Wrapper auf `bind_policy` |
| `src/elder_berry/robot/simulator.py` | `__main__`-Guard; `create_simulator(robot_token=None)` durchreichen |
| `src/elder_berry/agent/server.py` | fail-closed Konstruktor-Guard (`bind_host` bei tokenlos verpflichtend + Loopback) |

### Tests (S1)

- `tests/test_bind_policy.py` *(neu)*: `is_loopback_host` (127.0.0.1/localhost/::1
  vs. 0.0.0.0/LAN-IP), `enforce_token_policy` (exit 2 bei Non-Loopback ohne Token,
  warn bei Loopback ohne Token, ok mit Token).
- `tests/test_start_rpi5_token.py`: bleibt unverändert grün (Re-Export-Vertrag).
- `tests/test_robot_simulator_bind.py` *(neu)*: `sys.exit(2)` bei `bind=0.0.0.0`
  ohne Token, Pass bei Loopback, Pass bei `0.0.0.0` mit Token; `create_simulator`
  reicht Token durch.
- `tests/test_agent_protocol.py`: Konstruktor-Guard (ValueError bei Non-Loopback
  ohne Token), bestehende tokenlose Konstruktionen bleiben grün.

## S2 – XML-Härtung (defusedxml)

### Problemanalyse

Drei Parse-Stellen verarbeiten externe Server-Antworten mit stdlib-ET, ungehärtet
gegen XXE / Billion-Laughs / DTD:

- `tools/carddav_sync.py:21` (Import), `:764` (`ET.fromstring(resp.text)` der
  CardDAV-PROPFIND-Antwort), `:771` (`except ET.ParseError`).
- `tools/nextcloud_files.py:14` (Import), `:371` + `:585` (`ET.fromstring`),
  `:590` (`except ET.ParseError`).

Genutzte ET-Modul-API: **ausschließlich** `ET.fromstring` (3×) und `ET.ParseError`
(2×). Alle Baum-Navigation (`.findall`/`.find`/`.text`, Namespaces `{DAV:}` /
`{http://owncloud.org/ns}`, Descendant-XPath `.//`) läuft über Element-Instanzen,
die `defusedxml` nicht berührt. → Reiner Import-Swap ist ein vollständiger Drop-in.

`defusedxml` ist heute **keine** Dependency (nirgends gelistet). **Lera-Freigabe
erteilt** (2026-06-16): hinzufügen.

### Lösung

- **Zentraler gehärteter Parser** `src/elder_berry/tools/safe_xml.py` mit
  `safe_fromstring(text) -> ET.Element`, das
  `defusedxml.ElementTree.fromstring(text, forbid_dtd=True)` aufruft. Wichtig:
  `defusedxml` blockt per Default nur Entity-Expansion (`forbid_entities`) und
  externe Entities (`forbid_external`), **nicht** die DOCTYPE-/DTD-Deklaration
  selbst (`forbid_dtd` ist defaultmäßig `False`). Erst `forbid_dtd=True` macht
  die zugesagte DTD-Härtung wirksam. Ein reiner Import-Swap allein hätte einen
  DTD-only-Response nicht abgewehrt.
- `carddav_sync.py` und `nextcloud_files.py`: nutzen `safe_fromstring` an allen
  drei Parse-Stellen (stdlib-`ET` bleibt für die getypte Element-/ParseError-API
  importiert).
- **Fail-closed an allen drei Stellen:** Die `except`-Blöcke fangen jetzt
  `(ET.ParseError, DefusedXmlException)` → saubere `NextcloudError` bzw. „nichts
  gefunden". Insbesondere wird **auch** `NextcloudFilesClient._parse_propfind`
  (Verzeichnis-Listing, hatte vorher keinen umgebenden Catch) gewrappt, damit
  bösartiges WebDAV-XML als `NextcloudError` endet statt als rohe
  `DefusedXmlException` nach oben zu propagieren.
- `pyproject.toml`: `defusedxml>=0.7.1` in `nextcloud`, `server` **und** `tower`.
  `tower` muss dabei sein, weil `scripts/start_saleria.py` (Tower) bei
  konfiguriertem `nextcloud_url` `NextcloudFilesClient` top-level importiert; ohne
  die Dep schlüge `.[tower]` mit `ImportError` fehl.

### Betroffene Dateien (S2)

| Datei | Änderung |
|---|---|
| `src/elder_berry/tools/safe_xml.py` *(neu)* | `safe_fromstring` (defusedxml, `forbid_dtd=True`) |
| `pyproject.toml` | `defusedxml>=0.7.1` in `nextcloud` + `server` + `tower` |
| `src/elder_berry/tools/carddav_sync.py` | `safe_fromstring`; except auf `DefusedXmlException` |
| `src/elder_berry/tools/nextcloud_files.py` | `safe_fromstring` (2×); `_parse_propfind` gewrappt; except erweitert; Docstring |

### Tests (S2)

- `tests/test_carddav_sync.py` / `tests/test_nextcloud_files.py`: bestehende
  gutartige PROPFIND-Mocks bleiben grün (identisches Parsing).
- `tests/test_xml_hardening.py` *(neu)*: drei bösartige Payloads
  (Billion-Laughs, externe Entity, **reine DTD ohne Entities**) →
  `_parse_propfind` wirft `NextcloudError`, `_list_vcf_hrefs` liefert `[]`. Der
  DTD-only-Fall deckt gezielt `forbid_dtd=True` ab (ohne das Flag würde der
  DOCTYPE ungehindert geparst).

## S4 – SQL-Allowlist-Guard

### Problemanalyse

bandit B608 an 6 Stellen (`contact_store.py:542/569/594`,
`proposal_store.py:423/436/451/457/536`). Belegt **kein** Injection-Vektor: die
interpolierten Bezeichner sind ausschließlich Spaltennamen aus den Konstanten
`_ALL_FIELDS` (Klassenattribut) bzw. `_PROPOSAL_COLS` / `_PROPOSAL_COLS_PREFIXED`
(Modul-Konstanten); kwargs-Keys werden nie als Spaltenname iteriert (nur
`.get(field)` als Wert); alle Werte sind parametrisiert (`?`). Heute sicher, aber
ohne expliziten Guard brüchig.

> **Hinweis:** bandit ist im Repo **nirgends** konfiguriert (nicht in CI,
> pre-commit, pyproject). Die `# nosec`-Annotation hätte heute keinen Konsumenten.
> **Lera-Entscheid (2026-06-16):** nur der defensive Guard + erklärender Kommentar
> — **kein** Bandit-Wiring in dieser Phase. Der erklärende Kommentar nennt B608
> referenziell, ohne dass ein aktiver Bandit-Lauf erforderlich ist.

### Lösung

- `contact_store.py`: Klassenattribut
  `_ALLOWED_COLUMNS: frozenset[str] = frozenset(_ALL_FIELDS) | {"user_id",
  "created_at", "updated_at", "id"}` + `@staticmethod _assert_known_columns(cols)`
  (wirft `ValueError` bei unbekanntem Bezeichner). Aufruf vor den 3 f-Strings.
  Benötigt `from collections.abc import Iterable`.
- `proposal_store.py`: explizites `_ALLOWED_PROPOSAL_COLUMNS: frozenset[str]` als
  Literal + Konsistenz-Assert beim Import, dass jede Spalte aus `_PROPOSAL_COLS`
  und (ohne `p.`-Prefix) `_PROPOSAL_COLS_PREFIXED` Mitglied ist. Da hier kein
  dynamischer Input einfließt, genügt der Konstanten-Assert (kein Hot-Path-Guard).
- Erklärender Kommentar (`# B608 false positive: nur Konstanten-Spalten aus
  _ALLOWED_*; Werte via '?'`) an jede f-String-Stelle.

### Betroffene Dateien (S4)

| Datei | Änderung |
|---|---|
| `src/elder_berry/tools/contact_store.py` | `_ALLOWED_COLUMNS` + `_assert_known_columns` + 3 Guards/Kommentare; `Iterable`-Import |
| `src/elder_berry/tools/proposal_store.py` | `_ALLOWED_PROPOSAL_COLUMNS` + Konsistenz-Assert + Kommentare |

### Tests (S4)

- `tests/test_contact_store.py`: bestehende add/update-Pfade grün (Guard ist
  No-op im Normalpfad); neuer Test `_assert_known_columns` (ok / ValueError).
- `tests/test_proposal_store.py`: Konsistenz-Test (jede Spalte in der Allowlist;
  `_PROPOSAL_COLS` und `_PROPOSAL_COLS_PREFIXED` gleiche Menge/Reihenfolge,
  schützt zugleich gegen Drift gegen `_row_to_proposal`).

## YAGNI-Grenzen

- **Kein** `scripts/start_agent.py` (eigener Follow-up; nur Konstruktor-Guard).
- **Kein** globales `defusedxml.defuse_stdlib()` (impliziter, fernwirkender;
  lokaler Import-Swap ist explizit + testbar).
- **Kein** Bandit-CI-Wiring (Lera-Entscheid).
- **Keine** Änderung an den fail-open-Middlewares selbst (Schutz lebt im
  Bind-Pfad; Middleware bleibt backwards-kompatibel für Tests/Token-frei-Loopback).

## Bekannte Risiken

- Re-Export-Vertrag in `start_rpi5.py`: `test_start_rpi5_token.py` lädt Helfer als
  Modul-Attribute und prüft caplog auf Logger `elder_berry.rpi5` → der geteilte
  Helper muss den **übergebenen** Logger nutzen, nicht einen eigenen.
- defusedxml verbietet DTD/Entities — WebDAV/CardDAV-Multistatus nutzt keine, also
  praktisch kein Funktionsverlust; der Negativ-Test sichert das Härtungsverhalten.
- S4-Guard: `_ALLOWED_COLUMNS` muss die Literale (`id`/`user_id`/`created_at`/
  `updated_at`) enthalten, sonst bricht der Normalpfad → Regressionstest sichert das.

## Definition of Done

1. Code committed (Branch `feature/phase-103-server-parser-haertung`), **kein PR**
   (macht Lera) — Ausnahme: Lera hat für diese Aufgabe „push alles" erteilt.
2. Voller `pytest` grün; `ruff` + `mypy` (core/tools strict) auf geänderten Modulen.
3. **S1-Akzeptanz:** `python -m elder_berry.robot.simulator --bind 0.0.0.0` ohne
   `ELDER_BERRY_ROBOT_TOKEN` bricht mit Exit 2 ab; mit Token läuft er.
4. **S2-Akzeptanz:** bösartiges PROPFIND-XML (Entity-Expansion, externe Entity
   **und reine DTD**) wird von beiden Modulen abgewehrt, nicht expandiert/geparst.
5. **S4-Akzeptanz:** `_assert_known_columns(['evil; DROP'])` wirft `ValueError`;
   Normalpfad unverändert.
6. Append-only Journal-Eintrag mit ausgeführten Tests + nächstem Schritt.
