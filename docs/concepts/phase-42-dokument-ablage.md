# Phase 42 – Dokument-Ablage (Cloud Aufräumen)

## Ziel

Saleria analysiert Dokumente in einem Eingangs-Ordner auf Nextcloud,
schlägt nach der bestehenden Dateinamenskonvention einen Namen und
Zielordner vor, und verschiebt die Datei nach Bestätigung.

Textanalyse läuft über das lokale LLM (Ollama, phi4:14b auf dem Tower).
Private Dokumente verlassen nie die eigene Infrastruktur.

## Dateinamenskonvention (bestehend)

```
YYYY-MM-DD_Kategorie_Beschreibung.ext
│          │         │
Datum      Bereich   Firma-Dokumenttyp (Bindestriche innerhalb)
```

Beispiele:
```
2026-03-31_Haus_Aero-Angebot-Unterschrieben.pdf
2026-03-31_Haus_RK-Bedachung-Angebot.pdf
2026-04-01_Vertrag_Mietvertrag-Wohnung.pdf
2026-04-01_Rechnung_Zahnarzt-Dr-Weber.pdf
```

Regeln: Keine Leerzeichen (Bindestriche), keine Umlaute im Dateinamen,
Unterstriche nur als Block-Trenner.

## Kategorie → Zielordner Mapping

| Kategorie   | Zielordner                     | Beispiel-Inhalt                            |
|-------------|--------------------------------|--------------------------------------------|
| `Vertrag`   | `/Dokumente/Vertraege/`        | Mietvertrag, Arbeitsvertrag, Versicherung  |
| `Rechnung`  | `/Dokumente/Rechnungen/`       | Arztrechnungen, Handwerker, Bestellungen   |
| `Behoerden` | `/Dokumente/Behoerden/`        | Steuerbescheid, Anträge, Behördenbriefe    |
| `Haus`      | `/Dokumente/Haus/`             | Grundriss, Angebote, Verträge Sanierung    |
| `Steuer`    | `/Dokumente/Behoerden/`        | Lohnsteuerbescheinigung, Steuererklärung   |
| `Manual`    | `/Manuale/{Unterordner}/`      | 3D-Druck, Elektronik, Netzwerk, Smart-Home |
| `Projekt`   | `/Projekte/{Projektname}/`     | Elder-Berry, andere Projekte               |
| `Notiz`     | `/Notizen/`                    | Freitext, Ideen, Listen                    |
| `Sonstiges` | `/Sonstiges/`                  | Alles was nicht zugeordnet werden kann      |

Hinweis: `Steuer` mappt auf `Behoerden` (kein eigener Ordner).
`Manual`-Unterordner (3D-Druck, Elektronik, Netzwerk, Smart-Home) wird vom
LLM mitbestimmt. Saleria versucht zuzuordnen, fragt bei Unsicherheit nach.

**Ausgeschlossene Ordner** (Saleria legt dort nie ab):
- `/Archiv/` — rein manuell verwaltet
- `/Saleria/` — Salerias eigener Workspace (Berichte, Notizen, Vorlagen)
- `/Deck/` — Nextcloud Deck Boards

## Eingangs-Ordner

`/Eingang/` auf Nextcloud Root-Ebene. Nutzer schiebt Dateien dort rein
(per Nextcloud App, Desktop Client, Web-UI, oder reMarkable-Export).

## Flow: "cloud aufräumen"

### Auslöser
- Command: `cloud aufräumen` / `räum cloud auf` / `eingang aufräumen`
- Keywords: `aufräumen`, `eingang`, `ablegen`

### Ablauf pro Datei (Einzelbestätigung)

```
1. list_dir("/Eingang/") → N Dateien gefunden
2. Saleria: "📂 N Dateien im Eingang. Starte mit: Scan_001.pdf"
3. Download auf Tower (temp) — bleibt lokal
4. Text extrahieren:
   a) PDF → DocumentReader (pymupdf, lokal auf Tower)
   b) PDF ohne Text → StirlingPDF OCR (Server) → erneut pymupdf
   c) Bild (JPG/PNG) → Ollama Vision (lokal auf Tower)
   d) Sonstige → nur Dateiname als Kontext
5. Extrahierten Text → Ollama (phi4:14b, lokal)
   → Antwort: {datum, kategorie, beschreibung}
6. Saleria schickt Vorschlag via Matrix:
   "📄 Scan_001.pdf
    → 2026-04-02_Haus_RK-Bedachung-Angebot.pdf
    → Ziel: /Dokumente/Haus/
    Passt das?"
7. User: "ja" → WebDAV MOVE
   User: "nein, Kategorie ist Rechnung" → Ollama korrigiert → neuer Vorschlag
   User: "Haus Angebot-Dach-RK-Bedachung" → manueller Name
   User: "überspringen" → nächste Datei
8. Nächste Datei oder "✅ Eingang ist leer."
```

### Sonderfälle
- **Eingang leer**: "Eingang ist leer – nichts zu tun."
- **Ollama nicht erreichbar**: "LLM nicht verfügbar. Bitte Kategorie und
  Titel manuell angeben: `Kategorie Beschreibung`"
- **Datei bereits im Zielordner vorhanden**: Warnen und Suffix anfügen
  (`-2`, `-3`) oder User fragen.
- **Nicht-unterstütztes Format**: Dateiname als einziger Kontext, LLM
  versucht trotzdem, sonst direkt nachfragen.

## Architektur

### Neue Klassen

#### 1. `tools/document_classifier.py` — DocumentClassifier

Extrahiert Text und klassifiziert Dokumente via lokalem LLM.

```python
@dataclass(frozen=True)
class FilingSuggestion:
    """Vorschlag für Dateiname und Zielordner."""
    date: str              # "2026-04-02"
    category: str          # "Haus"
    description: str       # "RK-Bedachung-Angebot"
    target_folder: str     # "Dokumente/Haus"
    filename: str          # "2026-04-02_Haus_RK-Bedachung-Angebot.pdf"
    confidence: str        # "high" | "medium" | "low"

class DocumentClassifier:
    """Analysiert Dokumente und schlägt Dateinamen vor."""

    def __init__(
        self,
        ollama: OllamaClient,
        document_reader: DocumentReader,
        stirling_pdf: StirlingPDFClient | None = None,
    ) -> None: ...

    def classify(self, file_path: Path) -> FilingSuggestion: ...
        # 1. Text extrahieren (pymupdf → OCR Fallback → Bild-Vision)
        # 2. Ollama-Prompt mit Kategorien-Liste + extrahiertem Text
        # 3. JSON-Antwort parsen → FilingSuggestion

    def classify_with_hint(
        self, file_path: Path, hint: str,
    ) -> FilingSuggestion: ...
        # User-Korrektur einarbeiten: "Kategorie ist Rechnung"
        # oder "Haus Angebot-Dach-RK-Bedachung" als vollständiger Name

    def _extract_text(self, file_path: Path) -> str: ...
        # PDF: DocumentReader.read_pdf() → text
        # PDF ohne Text: StirlingPDF.ocr() → temp-OCR-PDF → DocumentReader
        # Bild: Ollama Vision (base64) → Beschreibung
        # Sonstige: "" (nur Dateiname als Kontext)

    def _build_prompt(self, text: str, filename: str) -> str: ...
        # System-Prompt mit Kategorien-Tabelle + Regeln
        # User-Prompt mit extrahiertem Text (max 3000 Zeichen)
```

**Ollama System-Prompt (Entwurf):**
```
Du bist ein Dokumenten-Klassifizierer. Analysiere den Text und bestimme:
1. Datum (aus dem Dokument oder heute falls nicht erkennbar)
2. Kategorie (EXAKT eine aus der Liste)
3. Beschreibung (Firma-Dokumenttyp, Bindestriche, keine Leerzeichen, keine Umlaute)

Kategorien: Vertrag, Rechnung, Behoerden, Haus, Steuer, Manual, Projekt, Notiz, Sonstiges
Manual-Unterordner: 3D-Druck, Elektronik, Netzwerk, Smart-Home

Antworte NUR mit JSON:
{"datum": "2026-04-02", "kategorie": "Haus", "beschreibung": "RK-Bedachung-Angebot"}
```

#### 2. `comms/commands/filing_commands.py` — FilingCommandHandler

Neuer CommandHandler für den Aufräum-Flow.

```python
# Patterns
FILING_PATTERN = re.compile(
    r"^(?:cloud\s+aufr[aä]umen|r[aä]um\s+cloud\s+auf|eingang\s+aufr[aä]umen)$",
    re.IGNORECASE,
)

# Keywords für remote_commands.py KEYWORD_MAP
FILING_KEYWORDS = [
    "aufräumen", "eingang", "cloud aufräumen",
    "räum cloud auf", "eingang aufräumen", "ablegen",
]

class FilingCommandHandler(CommandHandler):
    def __init__(
        self,
        nextcloud_files: NextcloudFilesClient | None = None,
        document_classifier: DocumentClassifier | None = None,
        pending_store: PendingConfirmationStore | None = None,
    ) -> None: ...

    def handles(self, text: str) -> bool: ...
    def execute(self, text: str, user_id: str = "") -> CommandResult: ...

    def _cmd_aufräumen(self, user_id: str) -> CommandResult: ...
        # list_dir("/Eingang/") → erste Datei → classify → Vorschlag
        # PendingAction setzen mit action_type="filing"

    def _handle_confirm(self, action: PendingAction) -> CommandResult: ...
        # WebDAV MOVE + nächste Datei oder "Eingang leer"

    def _handle_correction(
        self, action: PendingAction, hint: str,
    ) -> CommandResult: ...
        # classify_with_hint() → neuer Vorschlag

    def _handle_skip(self, action: PendingAction) -> CommandResult: ...
        # Nächste Datei ohne Verschieben
```

**PendingAction.data Struktur:**
```python
{
    "source_path": "Eingang/Scan_001.pdf",      # Quell-Pfad in NC
    "local_temp": "C:\\Users\\...\\temp\\...",   # Lokale Temp-Datei
    "suggestion": {                               # Letzter Vorschlag
        "filename": "2026-04-02_Haus_RK-Bedachung-Angebot.pdf",
        "target_folder": "Dokumente/Haus",
    },
    "remaining_files": ["Scan_002.pdf", "IMG_001.jpg"],  # Warteschlange
}
```

### Erweiterung bestehender Klassen

#### 3. `NextcloudFilesClient.move()` — WebDAV MOVE

```python
def move(self, source_path: str, dest_path: str) -> str:
    """Verschiebt/benennt eine Datei auf Nextcloud um.

    Args:
        source_path: Quell-Pfad relativ zum User-Root.
        dest_path: Ziel-Pfad relativ zum User-Root.

    Returns:
        Neuer Pfad nach dem Verschieben.

    Raises:
        NextcloudError: Verschieben fehlgeschlagen.
    """
    # HTTP MOVE mit Destination-Header (volle URL)
    # _ensure_directories() für Ziel-Ordner
    # Destination-Header: volle WebDAV-URL des Ziels
```

**WebDAV MOVE Request:**
```
MOVE /remote.php/dav/files/user/Eingang/Scan_001.pdf HTTP/1.1
Destination: https://cloud.example.com/remote.php/dav/files/user/Dokumente/Haus/2026-04-02_Haus_RK-Bedachung-Angebot.pdf
Overwrite: F
```

`Overwrite: F` → 412 Precondition Failed wenn Ziel existiert (kein
versehentliches Überschreiben).

## Textextraktion — Kette mit Fallbacks

```text
Datei-Typ?
  │
  ├─ PDF ──→ DocumentReader.read_pdf() (pymupdf, lokal auf Tower)
  │            │
  │            ├─ Text vorhanden → ✅ weiter zu Ollama
  │            │
  │            └─ Kein Text (gescannt) → StirlingPDF.ocr() (Server)
  │                  │
  │                  ├─ OCR-Text vorhanden → ✅ weiter zu Ollama
  │                  │
  │                  └─ OCR fehlgeschlagen → User fragen
  │
  ├─ Bild (JPG/PNG/WEBP) ──→ Ollama Vision (lokal auf Tower)
  │            │
  │            ├─ Beschreibung erhalten → ✅ weiter zu Klassifizierung
  │            │
  │            └─ Vision fehlgeschlagen → User fragen
  │
  └─ Sonstige (DOCX, TXT, etc.) ──→ Nur Dateiname als Kontext
               │
               └─ Ollama versucht anhand des Dateinamens → bei Unsicherheit User fragen
```

**Ollama Vision für Bilder:**

OllamaClient braucht eine neue Methode `generate_with_image()`:
```python
def generate_with_image(
    self, prompt: str, image_base64: str, system: str = "",
) -> str:
    """Sendet Prompt + Bild an ein multimodales Ollama-Modell.

    Nutzt llava oder ein anderes Vision-Modell (nicht phi4).
    """
    # POST /api/chat mit images: [base64_string]
```

Modell-Auswahl: `llava:13b` oder `llava:7b` je nach VRAM-Budget.
phi4:14b hat kein Vision-Support → separates Modell nötig.
VRAM-Hinweis: llava:13b + phi4:14b zusammen = ~20 GB, passt auf RTX 4070 Ti Super (16 GB)
nur wenn eines entladen wird. Empfehlung: llava:7b (~4.5 GB) als Vision-Modell.

**Datenschutz-Kette:**
- PDF-Text: pymupdf lokal auf Tower → nie übers Netz
- OCR: Datei ist bereits auf Nextcloud (eigener Server) → Stirling-PDF lokal auf Server
- Bilder: lokal auf Tower → Ollama lokal
- Ollama: lokal auf Tower → kein externer API-Call
- Einziger Netzwerk-Hop: Tower ↔ Strato-Server (für NC-Download/Upload/OCR)

## Integration

### `comms/remote_commands.py`

- Import: `FilingCommandHandler`, `DocumentClassifier`
- `__init__`: Neue Parameter `document_classifier: DocumentClassifier | None`
- Handler instanziieren und in `self._handlers` einfügen
- KEYWORD_MAP: Filing-Keywords ergänzen
- HELP_TEXT ergänzen:
  ```
  Dokument-Ablage:
    cloud aufräumen – Dateien im Eingang klassifizieren und ablegen
  ```

### `comms/message_handlers.py`

- PendingAction-Check für `action_type="filing"` erweitern
- Bestätigungs-Wörter: "ja", "passt", "ok" → `_handle_confirm`
- Ablehnungs-Wörter: "überspringen", "skip", "weiter" → `_handle_skip`
- Alles andere bei aktivem Filing-Pending → `_handle_correction`
  (User-Text als Korrektur-Hint interpretieren)

### `scripts/start_saleria.py`

- DocumentClassifier instanziieren (DI: OllamaClient + DocumentReader + StirlingPDFClient)
- An RemoteCommandHandler durchreichen

### Bestätigungs-Flow (PendingConfirmationStore)

Erweiterte CONFIRM_WORDS für Filing:
```python
FILING_CONFIRM = frozenset({"ja", "yes", "passt", "ok", "ablegen"})
FILING_SKIP = frozenset({"überspringen", "skip", "weiter", "nächste"})
```
Alles was nicht CONFIRM und nicht SKIP ist → Korrektur-Hint.

## Tests

### `tests/test_document_classifier.py` (~20 Tests)

Ollama-Antworten gemockt (kein echter LLM-Call in Tests).

**Klassifizierung:**
- `test_classify_rechnung` — Rechnung erkannt, Datum + Firma extrahiert
- `test_classify_vertrag` — Vertrag erkannt
- `test_classify_haus_angebot` — Haus-Kategorie, Angebot im Titel
- `test_classify_manual_elektronik` — Manual mit Unterordner Elektronik
- `test_classify_manual_unknown_sub` — Manual ohne erkannten Unterordner → "Manual"
- `test_classify_projekt` — Projekt erkannt, Projektname im Pfad
- `test_classify_low_confidence` — LLM unsicher → confidence="low"
- `test_classify_no_text` — Kein Text extrahiert → confidence="low", Sonstiges
- `test_classify_with_hint_category` — User-Korrektur "Kategorie ist Haus"
- `test_classify_with_hint_full_name` — User gibt vollständigen Namen
- `test_classify_date_from_document` — Datum aus Dokumentinhalt statt heute
- `test_classify_date_fallback_today` — Kein Datum im Dokument → heute

**Textextraktion:**
- `test_extract_pdf_with_text` — pymupdf liefert Text
- `test_extract_pdf_scanned_ocr_fallback` — pymupdf leer → Stirling OCR
- `test_extract_pdf_no_stirling` — Gescannt + kein Stirling → leerer Text
- `test_extract_image_ollama_vision` — Bild → Ollama Vision Beschreibung
- `test_extract_image_no_vision` — Vision fehlgeschlagen → leerer Text
- `test_extract_unknown_format` — Unbekanntes Format → nur Dateiname

**JSON-Parsing:**
- `test_parse_valid_json` — Saubere JSON-Antwort
- `test_parse_json_in_markdown` — ```json ... ``` Wrapper entfernt

### `tests/test_filing_commands.py` (~18 Tests)

Nextcloud + Classifier gemockt.

**Pattern-Matching:**
- `test_aufräumen_pattern` — "cloud aufräumen"
- `test_räum_cloud_auf_pattern` — "räum cloud auf"
- `test_eingang_aufräumen_pattern` — "eingang aufräumen"
- `test_no_collision_with_cloud_commands` — Kein Overlap mit cloud upload/suche

**Aufräum-Flow:**
- `test_eingang_empty` — Keine Dateien → "Eingang ist leer"
- `test_eingang_one_file` — 1 Datei → Vorschlag + PendingAction gesetzt
- `test_eingang_multiple_files` — 3 Dateien → erste wird vorgeschlagen, Rest in Queue
- `test_confirm_moves_file` — "ja" → WebDAV MOVE aufgerufen
- `test_confirm_next_file` — Nach MOVE → nächste Datei vorgeschlagen
- `test_confirm_last_file` — Letzte Datei → "Eingang ist leer"
- `test_skip_next_file` — "überspringen" → nächste Datei ohne MOVE
- `test_correction_new_suggestion` — User-Hint → neuer Vorschlag
- `test_correction_manual_name` — "Haus Angebot-Dach" → manueller Name
- `test_file_exists_at_target` — Ziel existiert → Warnung + Suffix
- `test_no_nextcloud` — NC nicht verfügbar → Fehlermeldung
- `test_no_classifier` — Classifier fehlt → Fehlermeldung
- `test_move_error_rollback` — MOVE fehlgeschlagen → Datei bleibt im Eingang
- `test_commands_in_help` — command_descriptions vorhanden

### `tests/test_nextcloud_move.py` (~6 Tests)

- `test_move_success` — MOVE 201 → neuer Pfad zurück
- `test_move_creates_target_dir` — MKCOL für Ziel-Ordner
- `test_move_file_exists` — Overwrite:F → 412 → NextcloudError
- `test_move_source_not_found` — 404 → NextcloudError
- `test_move_auth_error` — 401 → NextcloudAuthError
- `test_move_connection_error` — Timeout → NextcloudConnectionError

## Zu ändernde Dateien (Zusammenfassung)

| Datei | Änderung |
|---|---|
| `tools/nextcloud_files.py` | `move()` Methode hinzufügen |
| `tools/document_classifier.py` | **NEU** — Textextraktion + LLM-Klassifizierung |
| `llm/ollama_client.py` | `generate_with_image()` Methode hinzufügen |
| `comms/commands/filing_commands.py` | **NEU** — FilingCommandHandler |
| `comms/remote_commands.py` | FilingCommandHandler registrieren, KEYWORD_MAP, HELP_TEXT |
| `comms/message_handlers.py` | PendingAction `filing` Typ behandeln |
| `scripts/start_saleria.py` | DocumentClassifier DI-Verdrahtung |
| `tests/test_document_classifier.py` | **NEU** — ~20 Tests |
| `tests/test_filing_commands.py` | **NEU** — ~18 Tests |
| `tests/test_nextcloud_move.py` | **NEU** — ~6 Tests |

## Dependencies

| Dependency | Status | Zweck |
|---|---|---|
| `httpx` | vorhanden | WebDAV MOVE, Ollama API |
| `pymupdf` | vorhanden (`[documents]`) | PDF-Textextraktion |
| Ollama phi4:14b | vorhanden (Tower) | Dokument-Klassifizierung |
| Ollama llava:7b | **NEU installieren** | Bild-Analyse (Vision) |
| Stirling-PDF | vorhanden (Server) | OCR-Fallback |
| Nextcloud | vorhanden (Server) | Datei-Storage + WebDAV |

Keine neuen Python-Dependencies nötig. Nur `ollama pull llava:7b` auf dem Tower.

## Architektur-Entscheidungen

### Warum lokales LLM statt Cloud?
Private Dokumente (Verträge, Rechnungen, Behördenpost) dürfen nicht an
externe APIs gesendet werden. Ollama auf dem Tower hält alles lokal.
Trade-off: phi4:14b ist weniger präzise als Claude/GPT bei
Dokument-Analyse, aber für Kategorisierung + Dateinamen reicht es.

### Warum Einzelbestätigung statt Batch?
- Privatsphäre: User prüft jedes Dokument bevor es abgelegt wird
- Fehlerkorrektur: Sofort bei falschem Vorschlag, nicht am Ende einer Liste
- Robustheit: Ein Fehler blockiert nicht den Rest
- UX: Matrix-Nachrichten bleiben kurz und lesbar

### Warum `/Eingang/` statt Matrix-Dateiempfang?
- Kein neuer Code für Matrix-Datei-Events nötig
- Geräte-unabhängig (Handy-App, Desktop Client, Web-UI, reMarkable)
- Batch-fähig (10 Dateien auf einmal reinwerfen)
- Entkopplung: Dateien sammeln und aufräumen sind getrennte Schritte

### Warum WebDAV MOVE statt Download+Upload+Delete?
- Atomare Operation (kein Zwischenzustand mit Datei an zwei Orten)
- Schneller (kein Daten-Transfer, nur Metadaten-Update auf dem Server)
- Server-seitige Operation (kein Netzwerk-Traffic für die Datei selbst)

## Aufwand-Schätzung

| Komponente | Aufwand | Neue Tests |
|---|---|---|
| DocumentClassifier | Mittel | ~20 |
| FilingCommandHandler | Mittel | ~18 |
| NextcloudFilesClient.move() | Klein | ~6 |
| OllamaClient.generate_with_image() | Klein | ~4 |
| Integration (remote_commands, bridge, start_saleria) | Klein | — |
| **Gesamt** | **Mittel** | **~48** |

## Kosten

- Ollama: kostenlos (lokal)
- Stirling-PDF OCR: kostenlos (eigener Server)
- Nextcloud: kostenlos (eigener Server)
- Kein externer API-Call nötig
- VRAM: llava:7b muss ggf. vor/nach Nutzung geladen/entladen werden

## Voraussetzungen

- ✅ Nextcloud läuft (Phase 36)
- ✅ NextcloudFilesClient (Phase 36.1)
- ✅ StirlingPDFClient (Stirling-PDF Integration)
- ✅ DocumentReader (Phase 11)
- ✅ OllamaClient (Phase 1/5)
- ✅ PendingConfirmationStore (Phase 28)
- ⬜ `/Eingang/` Ordner auf Nextcloud anlegen (manuell, 1 Minute)
- ⬜ `ollama pull llava:7b` auf Tower (einmalig)
