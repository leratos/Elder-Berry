# Phase 78 – Plugin Self-Suggestion 💡

**Status:** Konzept (2026-04-29)
**Branch:** `feature/phase-78-plugin-self-suggestion`
**Aufwand:** ~2–3 Sessions
**Voraussetzung:** Phase 77 (Plugin-Registry) abgeschlossen
**Roadmap-Referenz:** Erweiterung des Plugin-Systems um selbstlernende
Capability-Erkennung

## 1. Ausgangslage

Mit Phase 77 ist das Plugin-Manifest etabliert. Heute passiert bei einer
Anfrage, die kein Command matcht, folgendes:

- `RemoteCommandHandler.parse_command(text)` → `None`
- Bridge gibt an Saleria (LLM) weiter, die improvisiert eine Antwort.
- Das Signal „hier hätte ein Command sein sollen" verpufft.

Bei wiederkehrenden Aufgabentypen (z. B. „spiel was von Hans Zimmer",
„starte Pomodoro 25min", „sperr meinen PC") müsste Lera selbst erkennen:
*„das wäre ein Plugin"*. Die Idee: **Saleria erkennt Capability-Lücken
selbst und legt einen Vorschlag in einem Review-Workflow ab.**

Wichtige Designentscheidung: **Saleria generiert keine ladbare Code-Datei**.
Sie schreibt eine Spezifikation (Markdown-Dokument mit Funktionsbeschreibung,
Beispielanfragen, Datenfluss) — Lera reviewt, implementiert manuell, schaltet
scharf. Der Workflow ist ein Vorschlagswesen, kein Auto-Coder.

## 2. Ziel

1. Reaktiver Trigger: Bei LLM-Fallback markiert Saleria die Anfrage mit
   einem Plugin-Kandidaten-Intent.
2. Aggregations-Heuristik: Vorschlag entsteht erst ab Schwelle
   (3× in 7 Tagen pro Intent).
3. Storage auf `fern.last-strawberry.com` (Rootserver, 24/7-verfügbar) als
   SQLite-Datenbank.
4. Dedupe-Check: Saleria liest bestehende Vorschläge vor Erstellung,
   verhindert Duplikate.
5. Status-Workflow im Settings-Dashboard: `in_pruefung` → `in_bearbeitung`
   / `abgelehnt` → `fertiggestellt`.
6. Notifications via Matrix: Saleria meldet aktiv neue Vorschläge.
7. Saleria darf NUR `in_pruefung` setzen — alle weiteren Status-Wechsel
   erfolgen manuell durch Lera im Dashboard.

**Nicht-Ziele dieser Phase:**
- Auto-Load: Vorschläge werden niemals automatisch zu lauffähigen Plugins.
  Auch in zukünftigen Phasen explizit nicht geplant — bewusste Designentscheidung.
- Proaktiver Trigger („Saleria schlägt Plugins ohne konkreten Fail-Trigger
  vor"). Folgephase, wenn die reaktive Variante stabil läuft.
- Code-Generierung: Vorschläge enthalten höchstens Pseudo-Code, niemals
  ausführbare Python-Dateien.
- Plugin-Hot-Reload nach Implementierung — bleibt manueller Saleria-Restart.

## 3. Architektur

### 3.1 Topologie

Die produktive Saleria läuft auf dem Rootserver (`fern.last-strawberry.com`)
und ist 24/7 erreichbar. Tower ist Fallback-Backend: nur wenn Claude-API
nicht erreichbar ist, schaltet die Server-Saleria auf das lokale LLM auf
dem Tower um (analog zu ElevenLabs → lokales TTS). Tower selbst hält
keinen `ProposalStore` und schreibt nichts direkt in die DB — der gesamte
Trigger-Pfad inkl. Persistenz läuft auf dem Server.

```
┌────────────────────┐         ┌──────────────────────────────┐
│  Tower (Fallback)  │         │  Rootserver (24/7)           │
│  Lokales LLM       │         │  fern.last-strawberry.com    │
│  (nur wenn Claude- │  ◄───   │                              │
│  API offline)      │  LLM-   │  ┌────────────────────────┐  │
└────────────────────┘  Call   │  │ Saleria-Server-Instanz │  │
                               │  │ (Matrix, Briefing, etc)│  │
                               │  └────────┬───────────────┘  │
                               │           │                  │
                               │           ▼                  │
                               │  ┌────────────────────────┐  │
                               │  │ ProposalStore (SQLite) │  │
                               │  │ data/proposals.db      │  │
                               │  └────────┬───────────────┘  │
                               │           │                  │
                               │           ▼                  │
                               │  ┌────────────────────────┐  │
                               │  │ Settings-Dashboard     │  │
                               │  │ /api/proposals         │  │
                               │  │ /proposals (Tab)       │  │
                               │  └────────────────────────┘  │
                               └──────────────────────────────┘
                                       ▲
                                       │ HTTPS + Login (Phase 58)
                                       │ + VPN
                                       │
                                  Lera (Browser)
```

### 3.2 Datenmodell (SQLite)

Datei: `data/proposals.db` auf Rootserver, Speicherort konfigurierbar
über `SecretStore.get("proposal_db_path")`.

```sql
-- Hauptverzeichnis
CREATE TABLE plugin_proposals (
    id TEXT PRIMARY KEY,
        -- normalisierter Intent, snake_case
        -- z.B. 'spotify_play_song', 'pomodoro_timer'
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'in_pruefung'
        CHECK (status IN ('in_pruefung', 'in_bearbeitung',
                          'abgelehnt', 'fertiggestellt')),
    description_md TEXT NOT NULL,
        -- vollständiger Markdown-Body (Saleria-generiert)
    suggested_category TEXT,
        -- Vorschlag für CATEGORY_LABELS (z.B. 'medien', 'system')
    suggested_priority INTEGER,
        -- Vorschlag für CommandPlugin.priority
    created_at TEXT NOT NULL,
        -- Anlagezeitpunkt; wird auch als Beginn des 7-Tage-Fensters
        -- benutzt (kein separates first_seen_at).
    updated_at TEXT NOT NULL,
    trigger_count INTEGER NOT NULL DEFAULT 1,
        -- Lifetime-Counter, NICHT für Threshold (siehe §3.5).
    last_triggered_at TEXT NOT NULL,
    notified_at TEXT,
        -- NULL solange Threshold-Notification noch nicht versendet
        -- wurde. Einmaliges Setzen, kein Re-Notify.
    last_confidence REAL,
        -- Letzter vom LLM gelieferter Confidence-Wert (0..1).
        -- Aggregiert pro Proposal für Tuning des Schwellwerts (R7).
    -- Status-Felder
    rejected_reason TEXT,
        -- Optional: Begründung bei Ablehnung
    implemented_in TEXT,
        -- Pfad zum echten Plugin nach Fertigstellung
        -- z.B. 'src/elder_berry/comms/commands/spotify_commands.py'
    -- Beziehungen
    related_proposals TEXT
        -- JSON-Array von Proposal-IDs mit ähnlichem Intent
);

-- Trigger-History (für Audit + Heuristik)
CREATE TABLE plugin_proposal_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL REFERENCES plugin_proposals(id) ON DELETE CASCADE,
    triggered_at TEXT NOT NULL,
    sample_message TEXT NOT NULL,
        -- Anonymisierte Original-Anfrage (siehe §6 R5)
    sender_hash TEXT,
        -- SHA256(matrix_user_id + salt) — Privacy-by-Design
    confidence REAL
        -- Vom LLM gelieferter Wert dieses einzelnen Triggers (0..1).
        -- Erlaubt spätere Korrelation Confidence ↔ Akzeptanzquote.
);

-- Index für 7-Tage-Window-Query (siehe §3.5) und Standard-Listings.
CREATE INDEX idx_triggers_proposal_time
    ON plugin_proposal_triggers(proposal_id, triggered_at);

-- Status-Wechsel-Audit
CREATE TABLE plugin_proposal_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL REFERENCES plugin_proposals(id) ON DELETE CASCADE,
    timestamp TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_by TEXT NOT NULL CHECK (changed_by IN ('saleria', 'lera')),
    note TEXT
);

CREATE INDEX idx_history_proposal_time
    ON plugin_proposal_history(proposal_id, timestamp);

-- Volltextsuche für Dedupe-Check
CREATE VIRTUAL TABLE plugin_proposals_fts USING fts5(
    id UNINDEXED,
    title,
    description_md,
    content='plugin_proposals',
    content_rowid='rowid'
);

-- Trigger für FTS-Sync
CREATE TRIGGER plugin_proposals_fts_insert
AFTER INSERT ON plugin_proposals BEGIN
    INSERT INTO plugin_proposals_fts(rowid, id, title, description_md)
    VALUES (new.rowid, new.id, new.title, new.description_md);
END;
-- ähnlich update + delete
```

FTS5 für Volltextsuche kommt aus Phase 16 (NoteStore) — bewährtes Pattern.

### 3.3 Klassen-Layout

```
src/elder_berry/tools/
├── proposal_store.py            (SQLite-Wrapper, ABC + Impl)
└── intent_aggregator.py         (Heuristik + Threshold-Logik)

src/elder_berry/comms/
└── proposal_notifier.py         (Matrix-Notification beim Erstellen)

src/elder_berry/web/
├── proposals_api.py             (FastAPI-Routen, hinter Login)
└── markdown_renderer.py         (markdown-it-py + bleach.clean()
                                  fuer description_md -> HTML)

src/elder_berry/webapp/dashboard/
└── modules/proposals.js         (PWA-Modul, eigene View "Vorschlaege"
                                  -- analog zum Plugin-Inspector aus
                                  Phase 77.5)
```

DB-Anlage erfolgt im `ProposalStore.__init__()` (Pattern wie `NoteStore`,
`ContactStore`, `TodoStore`) — kein separates Migrations-Skript für Phase 78.
Falls in einer Folgephase echte Schema-Änderungen anfallen, wird dann ein
versioniertes Migrations-System (z. B. via `PRAGMA user_version`) angelegt.

### 3.4 Trigger-Pfad (reaktiv)

```python
# Pseudocode, gehört in MatrixBridge
async def handle_message(self, text: str, sender: str) -> None:
    cmd = self._handler.parse_command(text)
    if cmd is not None:
        result = self._handler.execute(cmd, text)
        await self._send(result)
        return

    # Kein Command → LLM-Fallback
    response = await self._assistant.reply(text)
    await self._send_text(response.text)

    # Phase 78: Plugin-Kandidat?
    if response.is_plugin_candidate:
        await self._proposal_aggregator.record(
            intent=response.normalized_intent,
            sample=text,
            sender=sender,
            confidence=response.candidate_confidence,
        )
```

`response.is_plugin_candidate` und `response.normalized_intent` kommen aus
einer Erweiterung des System-Prompts:

> *„Beurteile am Ende deiner Antwort, ob die Anfrage eine wiederkehrende
> automatisierbare Aufgabe sein könnte. Falls ja, antworte mit einem
> JSON-Block am Ende: `<plugin-candidate>{"intent": "spotify_play_song",
> "title": "Spotify-Steuerung", "confidence": 0.8}</plugin-candidate>`.
> Falls nein, lass den Block weg."*

Der Block wird aus der finalen Antwort entfernt, bevor sie an den Nutzer
geht. Confidence-Threshold (z. B. ≥0.7) filtert weiteres Rauschen.

### 3.5 Aggregations-Heuristik

```python
class ProposalIntentAggregator:
    THRESHOLD_COUNT = 3
    THRESHOLD_DAYS = 7

    async def record(
        self,
        intent: str,
        sample: str,
        sender: str,
        confidence: float,
    ) -> None:
        existing = self._store.get_by_id(intent)
        if existing is None:
            # Neuer Intent — create_pending() legt Proposal UND ersten
            # Trigger transaktional an (siehe ProposalStore-Vertrag).
            # Keine Notification beim ersten Mal.
            self._store.create_pending(
                intent=intent,
                sample=sample,
                sender=sender,
                confidence=confidence,
            )
            return

        if existing.status in ("abgelehnt", "fertiggestellt"):
            # Bereits entschieden — kein neuer Vorschlag, aber Trigger zählen
            self._store.add_trigger(existing.id, sample, sender, confidence)
            return

        if existing.status == "in_pruefung":
            self._store.add_trigger(existing.id, sample, sender, confidence)
            # Threshold-Check über 7-Tage-Fenster (NICHT lifetime counter).
            recent = self._store.count_triggers_since(
                existing.id, days=self.THRESHOLD_DAYS,
            )
            if recent >= self.THRESHOLD_COUNT and existing.notified_at is None:
                await self._notifier.notify(existing)
                self._store.mark_notified(existing.id)
            return

        # in_bearbeitung — Trigger zählen, keine Aktion
        self._store.add_trigger(existing.id, sample, sender, confidence)
```

Wichtig:

- **Threshold-Semantik:** „3× in 7 Tagen" wird über
  `count_triggers_since(proposal_id, days=7)` geprüft, das auf
  `plugin_proposal_triggers.triggered_at >= now() - 7 days` filtert.
  `trigger_count` ist Lifetime-Anzeige für Dashboard und nicht
  schwell-relevant — sonst würde ein Intent über 30 Tage 4× ungewollt
  feuern.
- **Erster Trigger:** `create_pending()` legt den Proposal-Eintrag und
  den ersten `plugin_proposal_triggers`-Row in derselben Transaktion an.
  Nach Rückkehr existiert der Proposal mit `trigger_count = 1` und
  genau einem Trigger-Row. Kein separater `add_trigger()`-Call nötig.
- **Notification:** Wird beim erstmaligen Erreichen der Schwelle
  versendet. `notified_at` wird auf den Sendezeitpunkt gesetzt und
  bleibt gesetzt — kein Re-Notify.
- `abgelehnt` → kein neuer Vorschlag, aber Trigger werden weiterhin gezählt
  (für Statistik, falls Lera später umentscheidet).
- `fertiggestellt` → wenn das Plugin trotzdem nicht greift, kann Saleria
  einen *neuen* Vorschlag mit anderer ID erstellen (`spotify_play_song_v2`),
  aber das ist Edge-Case.

### 3.6 Dedupe-Check (Saleria-Seite)

Bevor Saleria einen Plugin-Kandidaten-JSON-Block emittiert, soll sie
selbst prüfen, ob das Intent schon existiert. Dazu bekommt sie im
System-Prompt eine Liste:

```text
[Vorhandene Plugin-Vorschläge (kein neuer Vorschlag, wenn Match):
- spotify_play_song (in_pruefung): Spotify-Steuerung
- pomodoro_timer (fertiggestellt): Pomodoro-Timer
- pc_lock (abgelehnt): PC sperren via Matrix]
```

Diese Liste wird beim System-Prompt-Build aus `proposal_store.list_active()`
generiert (nur `in_pruefung`/`in_bearbeitung`, sortiert nach
`last_triggered_at DESC`). Cap bei **10–15 Einträgen**, nur `id`, `title`
und `status` — kein `description_md`. Wenn die aktive Liste regelmäßig
größer wird, ist die Heuristik selbst das Problem (Threshold zu lasch
oder Saleria halluziniert) — dann wird in einer Folgephase nachjustiert,
nicht der Cap erhöht.

### 3.7 Notification-Format

Beim Erreichen des Threshold-Counts:

```text
💡 Plugin-Vorschlag: Spotify-Steuerung (3× in 5 Tagen)

Du hast wiederholt nach Spotify-Funktionen gefragt
("spiel was von Hans Zimmer", "mach mir Filmmusik an", "pause die Musik").
Ich denke, das wäre ein Plugin-Kandidat.

Details: https://fern.last-strawberry.com/proposals/spotify_play_song
```

Über `_notifier.notify()` als Matrix-Direktnachricht an Lera (nicht in den
Hauptraum, um Spam zu vermeiden).

### 3.8 Dashboard-Tab

Vierter Header-Tab nach `Fernbedienung`, `Einstellungen`, `Avatar`:
**`Vorschläge`**.

Routen:
- `GET /api/proposals?status=in_pruefung` → Liste
- `GET /api/proposals/<id>` → Detail-View mit Markdown-Body, Trigger-History
- `POST /api/proposals/<id>/status` → Status-Wechsel
  (Body: `{"new_status": "in_bearbeitung", "note": "..."}`)
- `POST /api/proposals/<id>/implementation` → setze `implemented_in`-Pfad
  (für Status `fertiggestellt`)

UI:
- Tabelle mit Spalten: Title, Status, Trigger-Count, First Seen, Actions.
- Filter nach Status (Default: nur `in_pruefung`).
- Detail-View: Markdown wird **server-side** gerendert
  (`markdown-it-py` oder `mistune`) und mit `bleach.clean()` gegen eine
  enge Allowlist gesäubert (`p, ul, ol, li, code, pre, h1-h4, strong,
  em, blockquote, a[href]`). Kein `<script>`, `<style>`, `<iframe>` —
  siehe §6 R3. DOMPurify im Browser ist nur Defense-in-Depth.
- Status-Buttons: „In Bearbeitung", „Ablehnen" (öffnet Modal für
  Begründung), „Fertiggestellt" (öffnet Modal für `implemented_in`-Pfad).

## 4. Format des generierten Markdown-Bodys

Saleria erstellt das `description_md` nach folgendem Template:

```markdown
# <Titel des Vorschlags>

**Intent:** `<normalisierter_intent>`
**Erstellt:** <ISO-Datum>
**Trigger:** <count> × in <days> Tagen

## Beschreibung

<Saleria-Generated: was die Capability tun würde, in 2–4 Sätzen>

## Beispielanfragen

- "<Original-Anfrage 1>"
- "<Original-Anfrage 2>"
- "<Original-Anfrage 3>"

## Vorgeschlagene Patterns

```regex
^<example pattern hier>
```

## Benötigte Services

- <z.B. "Spotify Web API mit OAuth-Token in SecretStore">
- <z.B. "Optional: HarmonyHub für Lautsprecher-Routing">

## Vorschlag für CommandPlugin-Manifest

```python
PLUGIN = CommandPlugin(
    name="<intent>",
    priority=50,  # Vorschlag, anpassen
    category="<vorschlag>",
    help_section=...,
    factory=_factory,
)
```

## Bemerkungen

<Saleria-Generated: weitere Hinweise, z.B. zu Konflikten mit bestehenden
Plugins, Sicherheits-Aspekten, Implementierungs-Reihenfolge>
```

**Wichtig:** Das ist eine *Spezifikation*, nicht ladbarer Code. Saleria
darf keine `.py.draft`-Anhänge erstellen — auch in Folgephasen nicht
(siehe §9, R1-Guard bleibt). Spec bleibt Markdown, immer.

## 5. Etappen / Vorgehen

Jede Etappe bekommt einen eigenen Branch und einen eigenen PR — auch
wenn mehrere Etappen in derselben Session entstehen. PR-Reihenfolge ist
linear: Etappe 2 baut auf Etappe 1 (Store-Import), Etappe 3 auf Etappe 2
(Aggregator wird im Dashboard nicht direkt referenziert, aber Schema-
Migration muss vorher gelaufen sein). Etappe N+1 erst beginnen, wenn
Etappe N gemerged ist.

### 5.1 Etappe 1 — DB-Schema + Store (1 Session)

- `proposal_store.py` mit Schema (siehe §3.2). DB-Anlage im Konstruktor
  via `_create_tables()` (Pattern wie `NoteStore`).
- Default-Pfad: `Path.home() / ".elder-berry" / "proposals.db"`.
  Override für Server-Deploy via `SecretStore.get("proposal_db_path")`
  in der Composition-Wurzel.
- Tests in `tests/test_proposal_store.py` (CRUD, FTS-Suche, Status-Wechsel,
  7-Tage-Window-Query, Transaktion `create_pending`).
- **Branch:** `feature/phase-78-proposal-store`
- **Akzeptanzkriterium:** DB lokal angelegt, alle CRUD-Operationen
  funktionieren, FTS-Dedupe-Suche findet ähnliche Intents,
  `count_triggers_since()` filtert korrekt nach Zeitfenster.

### 5.2 Etappe 2 — Trigger-Pipeline + System-Prompt (1 Session)

- `intent_aggregator.py` mit Threshold-Logik.
- System-Prompt-Erweiterung in `assistant.py` für `<plugin-candidate>`-Block.
- Parser für den Block, Removal vor User-Antwort.
- Bridge-Integration: Aggregator wird nach LLM-Fallback aufgerufen.
- `proposal_notifier.py` für Matrix-DM.
- Tests:
  - `test_intent_aggregator.py` (Threshold, Status-Vorhandensein)
  - `test_proposal_notifier.py` (Matrix-DM mit Mock)
- **Branch:** `feature/phase-78-trigger-pipeline`
- **Akzeptanzkriterium:** Drei simulierte Anfragen mit gleichem Intent
  führen zu einem Vorschlag in DB plus Matrix-DM.

### 5.3 Etappe 3 — Dashboard-Tab + API (1 Session)

- `proposals_api.py` mit allen Routen, hinter Login (Phase 58).
- `proposals.html` mit Tabelle + Detail-View.
- JS für Status-Wechsel + Markdown-Render.
- Auth: Eingeloggte Session = darf alles. Anonyme Requests = 401.
- Tests:
  - `test_proposals_api.py` (Auth, Status-Wechsel, History-Logging)
  - Manuell: Dashboard öffnen, Vorschlag durchklicken, Status setzen.
- **Branch:** `feature/phase-78-dashboard`
- **Akzeptanzkriterium:** Lera kann im Browser einen Vorschlag von
  `in_pruefung` über `in_bearbeitung` auf `fertiggestellt` setzen, jeder
  Wechsel landet in `plugin_proposal_history`.

## 6. Risiken / aktive Hinweise

- **R1 – Auto-Load-Verlockung.** Diese Phase implementiert *bewusst* nur
  manuelle Reviews. Die Versuchung, später irgendwann „die guten 80 %
  automatisch zu laden" abzukürzen, muss aktiv widerstanden werden.
  Begründung in dieser Datei dokumentiert: ein selbstmodifizierendes
  System mit Matrix-Command-Zugriff, Filesystem-Zugriff und PC-Steuerung
  ist eine Sicherheits-Schwelle, die nicht überschritten wird.
  **In zukünftigen Phasen ebenfalls nicht implementieren.**

- **R2 – Saleria-Halluzinationen als Vorschläge.** Saleria könnte für
  Smalltalk Vorschläge generieren („joke_telling_plugin"). Mitigation:
  - Confidence-Threshold ≥0.7 im Plugin-Candidate-Block.
  - Negative Liste fest im Code (`SMALLTALK_INTENTS = {"jokes",
    "compliments", "philosophy", ...}`) — solche Intents werden vom
    Aggregator ignoriert.
  - Threshold (3× in 7 Tagen) statt sofortige Notification.

- **R3 – Prompt-Injection durch Matrix-Sender.** Wenn jemand weiß, dass
  Saleria Vorschläge generiert, könnte er versuchen, manipulierte
  Specs einzuschleusen (z. B. mit eingebetteten Code-Snippets, die
  später kopiert werden). Mitigation:
  - Saleria's Generator-Prompt ist **strikt strukturiert** (siehe §4):
    keine ausführbaren Codeblöcke länger als 10 Zeilen, immer als
    Pseudo-Code markiert.
  - Dashboard rendert Markdown **server-side** mit `markdown-it-py`
    bzw. `mistune`, dann durchläuft das HTML `bleach.clean()` mit
    enger Allowlist (`p, ul, ol, li, code, pre, h1-h4, strong, em,
    blockquote, a[href]`). `<script>`/`<style>`/`<iframe>` werden
    gestripped, *bevor* das HTML den Browser erreicht. CSP aus
    Phase 70 (`script-src 'self'`) und DOMPurify sind zusätzliche
    Schichten, nicht der primäre Schutz.
  - Neue Dependency: `bleach` — gehört in optionale Gruppe `[remote]`
    in `pyproject.toml`.
  - Beim manuellen Review prüft Lera den Inhalt — *insbesondere*
    Codeblöcke werden nicht 1:1 kopiert, sondern als Inspiration
    verwendet.

- **R4 – Storage-Verfügbarkeit.** Rootserver hostet sowohl Saleria-
  Server-Instanz als auch `proposals.db` — fällt der Server aus, fällt
  beides gleichzeitig aus. Das ist akzeptabel: ohne Server gibt es
  ohnehin keine Matrix-Bridge, also auch keine Trigger zum Verlieren.
  Mitigation: SQLite ist robust, regelmäßiges Backup über bestehende
  Backup-Pipeline. Tower hält **keinen** lokalen Proposal-Buffer; er
  ist nur LLM-Fallback-Backend, nicht Trigger-Quelle (siehe §3.1).

- **R5 – Privacy: Trigger-Samples enthalten User-Anfragen.** Original-
  Anfragen aus Matrix landen in der DB. Mitigation:
  - `sender_hash` (SHA256 + Salt) statt Klartext-User-ID. **Hinweis:**
    Bei Single-User-Deployment (nur Lera + Saleria im Raum) ist der
    Hash trivial reversibel und schützt vor allem gegen Drittbeobachter
    bei DB-Leak — nicht gegen den Operator selbst. Der Mechanismus
    bleibt trotzdem drin, weil dieses Repo Public/OSS ist und auch
    Multi-User-Setups (mehrere Personen im Matrix-Raum mit derselben
    Saleria-Instanz) abdecken muss; dort ist der Schutz substantiell.
  - DB liegt auf Rootserver hinter Login.
  - Sample-Trim auf 200 Zeichen.
  - Optional: Sample mit LLM-Pass anonymisieren („Eigennamen entfernen")
    — als Folgeoptimierung wenn die Daten je geteilt werden.

- **R6 – DB-Wachstum.** Bei viel Matrix-Traffic kann die `triggers`-
  Tabelle groß werden. Mitigation: Cron-Skript löscht Trigger-Einträge
  älter als 90 Tage, lässt aber den Proposal-Eintrag selbst stehen
  (mit `trigger_count` und `last_triggered_at` als aggregierte Werte).

- **R7 – Confidence-Score ist LLM-generiert, nicht kalibriert.**
  „Confidence 0.8" heißt nicht 80 % Wahrscheinlichkeit. Mitigation:
  Threshold ≥0.7 ist heuristisch, kann nach Praxis-Erfahrung angehoben
  / gesenkt werden. Setting im SecretStore: `proposal_confidence_threshold`.

## 7. Tests / Akzeptanzkriterien

- `pytest tests/test_proposal_store.py` (Schema, CRUD, FTS).
- `pytest tests/test_intent_aggregator.py` (Threshold, Status-Mapping,
  Dedupe).
- `pytest tests/test_proposals_api.py` (Auth, Status-Workflow, History).
- `pytest tests/test_proposal_notifier.py` (Matrix-DM, Mock).
- E2E-Smoketest manuell:
  1. Drei simulierte Matrix-Anfragen mit gleichem Intent senden.
  2. Vorschlag erscheint in `/proposals` Dashboard-Tab.
  3. Matrix-DM ist eingegangen.
  4. Status auf `in_bearbeitung` setzen, dann auf `fertiggestellt` mit
     `implemented_in`-Pfad.
  5. Vier weitere Anfragen mit gleichem Intent → kein neuer Vorschlag,
     aber Trigger-Counter steigt.
  6. Anfrage mit `abgelehnt`-Status → kein neuer Vorschlag.
- mypy strict für `proposal_store.py`, `intent_aggregator.py`,
  `proposal_notifier.py`, `proposals_api.py`.

## 8. Out of Scope

- Auto-Load (siehe R1, dauerhaft Out-of-Scope — auch in Folgephasen).
- Ausführbare Code-Dateien als Anhang (`.py.draft` o. ä.). In Phase 78
  und 79 ausgeschlossen; alles bleibt im Markdown-Body. Spätere
  Phasen, die das Modell ändern wollen, brauchen eine eigene
  Sicherheits-Bewertung und stehen aktuell nicht auf der Roadmap.
- Proaktive Vorschläge ohne Trigger („mir ist aufgefallen…"). Folgephase.
- Inter-Saleria-Sharing: Vorschläge aus mehreren Saleria-Instanzen
  zusammenziehen. Aktuell nur eine Instanz pro Lera.
- Plugin-Vorschlags-Reviews durch andere Personen (Multi-User-Workflow).
- Statistik-Dashboard („wie viele Vorschläge pro Monat"). Folgephase
  wenn relevant.

## 9. Folge-Phasen

- **Phase 79 (offen, unter Vorbehalt R1) – reichere Pseudocode-
  Anhänge:** Erweiterung, bei der Saleria im Markdown-Body zusätzliche
  Pseudocode-Snippets liefert (z. B. konkretere `execute()`-Skizzen,
  Beispiel-Tests). **Niemals als ladbare `.py`-Datei** — der R1-Guard
  bleibt auch in 79 in Kraft. Alles was über reicheren Markdown-
  Inhalt hinausgeht (Filesystem-Drops, ausführbare Skelette,
  Sandbox-Lint-Pipelines), erfordert eine separate Sicherheits-
  Bewertung und ist in dieser Roadmap-Linie nicht vorgesehen.
- **Phase 80 (offen) – Proaktive Vorschläge:** Saleria reflektiert
  über Tagebuch-/Briefing-Daten und schlägt Plugins ohne konkreten
  Fail-Trigger vor.
- **Phase 81 (offen) – Vorschlags-Statistiken:** Dashboard-Erweiterung
  mit Charts (Vorschläge pro Monat, Akzeptanz-Rate, Top-Trigger).
