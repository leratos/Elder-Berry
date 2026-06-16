# Phase 104 – Fehler-Disziplin & Beobachtbarkeit (Konzept)

**Befunde:** S3 (Silent Exception Swallows) · Q2 (breite `except Exception`) ·
Q5 (Schuld-Marker → Journal)
**Branch (geplant):** `feature/phase-104-fehler-disziplin`
**Status:** Konzept. Umsetzung nach Phase 103.

## Ziel

Diagnostizierbarkeit erhöhen, ohne den Bot-Loop instabil zu machen: echte stille
Fehler-Swallows loggen, die breiten Catches in den netz-/extern-exponierten
Pfaden verengen, und die offenen Schuld-Marker ins Journal/Backlog überführen.

## Wichtige Re-Verifikation (2026-06-16)

Die Analyse zählte „~15 Silent Swallows" — die Re-Verifikation zeigt: die große
Mehrheit der `except: pass/continue`-Stellen fängt **enge, spezifische**
Exceptions (`ValueError`, `JSONDecodeError`, `OSError`, `psutil.*`, `ImportError`,
`UnicodeDecodeError`, `NextcloudCookbookError`) und ist korrektes best-effort-/
Kontrollfluss-Idiom. **Genau eine** Stelle hat echtes Daten-/Funktions-Risiko.

## S3 – Silent Swallows (priorisiert)

### Echter Fund (Priorität 1)

- **`tools/carddav_sync.py:799`** — breiter `except Exception: continue` im
  Fallback-Loop von `_find_vcard_href`. Ein transienter Netzfehler (httpx) ist
  nicht von „Href existiert nicht" unterscheidbar → Methode liefert `None`
  („Kontakt nicht gefunden"), obwohl nur das Netz zuckte. **Folge (Codex-Review
  PR #320):** `_update_existing_vcard` behandelt das `None` als „nicht gefunden"
  und **legt einen neuen vCard an → Kontakt-Duplikat.** Loggen allein reicht
  daher nicht. **Entscheidung:** transiente HTTP-Fehler (`httpx.HTTPError`/
  `RequestError`) **propagieren/abbrechen** statt still `continue` — der Sync
  bricht lieber sichtbar ab, als ein Duplikat zu erzeugen. Nur ein echtes
  „Href 404/weg" zählt als „nicht gefunden". Test: transienter Fetch-Fehler →
  `_find_vcard_href` propagiert (kein stilles `None`, kein Duplikat).

### Kleinere Diagnose-Lücken (Priorität 2, reine Log-Adds)

- `comms/commands/system_commands.py:356` — `except ImportError: pass`
  (psutil-Disk-Block) → `logger.debug`.
- `web/settings_dashboard.py:1008` — `except ValueError: pass` (ungültiger
  `STT_TIMEOUT` aus Secret-Store) → `logger.warning` (User-Config wird ignoriert).
- `tools/caldav_tasks.py:207` — `except Exception: continue` in `_find_todo_by_uid`.
  **Folge (Codex-Review PR #320):** der breite Catch schluckt auch die
  retry-fähigen Connection-/Timeout-Fehler des Clients, sodass `_call_with_retry`
  nie zum Zug kommt → `complete`/`reopen`/`update`/`delete` melden „nicht
  gefunden" nach einem transienten CalDAV-Fehler. **Fix:** retry-fähige Fehler
  vor dem `continue` **re-raisen** (bzw. den Catch auf die echten „UID nicht in
  dieser Liste"-Fälle verengen) und nur dann loggen+weitergehen; nicht pauschal
  `logger.debug` über alles.

### Bewusst korrekt – belassen (mit Begründungs-Kommentar/noqa)

- `close()`-Swallows (`contact_store:802`, `todo_store:284`,
  `proposal_store:555` — letzteres schon `# noqa: BLE001`): Kommentar/noqa
  angleichen, Verhalten unverändert.
- `core/error_collector.py:83` — **niemals loggen** (wird vom Logging-System
  aufgerufen → Rekursionsgefahr). Nur Kommentar.
- Mehrstufige LLM-JSON-Parser (`claude_agent`, `assistant`, `task_chain`): pro
  Zwischen-Versuch `pass` ist korrekt; der **finale** Fallback loggt bereits
  (verifiziert, inkl. `task_chain.py:300`). Nichts zu tun.

## Q2 – Breite `except Exception` (357×, schrittweise)

`comms/` ist mit ~150+ der größte Cluster, hat aber das höchste Regressionsrisiko
(„nichts darf den Handler killen"). `agent/server.py` ist bereits das Vorbild
(getrennte `KeyError/TypeError` vs. `Exception`, durchgehendes Logging,
sanitisierte „Details im Log"-Messages).

**Verengungs-Reihenfolge (Sicherheitsnutzen vor Volumen):**

1. **Netz-/extern-exponiert zuerst:** `robot/server.py` (7×),
   `robot/alexa_skill_handler.py` (8×, externer Payload). Äußerer Catch-all bleibt
   (kein Stacktrace-Leak), aber durchgehend `logger.exception` + Layer-Trennung
   (Validation → 400, IO/Net → 502, Rest → 500). Leak-Audit: schreibt ein Endpoint
   je Exception-Details in die HTTP-Antwort?
2. **web/** (auth-geschützt): `settings_dashboard.py` (5×, Config-Writes) verengen;
   `setup_tests.py` (9×) bleibt bewusst breit (Diagnose-Feature), aber Leak-Check
   ob rohe Exception-Message ins HTML rendert.
3. **comms/** zuletzt: erst ein **AST-Lint-Gate** „`except Exception` ohne
   Log-Call/Re-Raise im Body" (trennt geloggte breite Catches von echten stillen
   Swallows ohne sofort 357 Stellen anzufassen), dann `message_handlers.py` (29×)
   gezielt nach konkreten Typen aufschlüsseln.

## Q5 – Schuld-Marker

~49 `TODO/FIXME/HACK/XXX` in `src/`. In Bramble-Backlog-Einträge überführen
(`project="elder-berry"`, mit `resolves`-Verknüpfung beim Abarbeiten); im Code
nur die wirklich obsoleten entfernen. Reiner Prozess-Schritt am Phasenende.

## YAGNI / Risiken

- **Keine** breite comms-Verengung in einem Schwung (Regressionsrisiko: der
  Bot-Loop verlässt sich auf tolerierte transiente Fehler, z. B. Matrix-Reconnect).
- Verengung netz-exponierter Endpoints darf **keine** Exception ungefangen nach
  außen lassen (500/Stacktrace-Leak) und den Alexa-Response-Contract nicht brechen.

## Definition of Done

1. Branch `feature/phase-104-fehler-disziplin`, voller pytest grün.
2. Der eine echte S3-Fund (`carddav_sync:799`) behoben + getestet; die 3
   Diagnose-Lücken geloggt; bewusste Stellen kommentiert.
3. Q2-Stufe 1 (robot/agent) verengt + Leak-Audit dokumentiert; AST-Lint-Gate für
   comms eingeführt.
4. Schuld-Marker im Journal; Journal-Abschlusseintrag.
