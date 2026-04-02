# Phase 42 – Dokument-Ablage (Cloud Aufräumen) — Implementierungs-Prompt

## Kontext

Saleria kann Dateien im `/Eingang/`-Ordner auf Nextcloud klassifizieren und
nach Bestätigung in den richtigen Ordner mit korrektem Namen verschieben.
Analyse läuft lokal über Ollama (phi4:14b für Text, llava:7b für Bilder).

**Konzeptdokument**: `docs/concepts/phase-42-dokument-ablage.md`

## Vorbereitung

1. Lies `docs/journal.txt` (letzte 80 Zeilen) für den aktuellen Stand
2. Lies `docs/concepts/phase-42-dokument-ablage.md` vollständig
3. Lies diese bestehenden Dateien bevor du anfängst:
   - `src/elder_berry/tools/nextcloud_files.py` (NextcloudFilesClient)
   - `src/elder_berry/tools/document_reader.py` (DocumentReader)
   - `src/elder_berry/tools/stirling_pdf.py` (StirlingPDFClient)
   - `src/elder_berry/llm/ollama_client.py` (OllamaClient)
   - `src/elder_berry/llm/base.py` (LLMClient ABC)
   - `src/elder_berry/comms/pending_confirmation.py` (PendingConfirmationStore)
   - `src/elder_berry/comms/commands/cloud_commands.py` (Referenz für Handler-Muster)
   - `src/elder_berry/comms/remote_commands.py` (Handler-Registrierung)
   - `src/elder_berry/comms/message_handlers.py` (PendingAction-Handling)
   - `scripts/start_saleria.py` (DI-Verdrahtung)
4. Erstelle Branch: `feature/phase-42-dokument-ablage`

## Implementierungsreihenfolge

### Schritt 1: `NextcloudFilesClient.move()` erweitern

Datei: `src/elder_berry/tools/nextcloud_files.py`

Neue Methode nach `delete()`:

```python
def move(self, source_path: str, dest_path: str) -> str:
    """Verschiebt/benennt eine Datei auf Nextcloud via WebDAV MOVE.

    Args:
        source_path: Quell-Pfad relativ zum User-Root.
        dest_path: Ziel-Pfad relativ zum User-Root.

    Returns:
        Ziel-Pfad nach dem Verschieben.

    Raises:
        NextcloudConnectionError: Server nicht erreichbar.
        NextcloudAuthError: Authentifizierung fehlgeschlagen.
        NextcloudError: Verschieben fehlgeschlagen (404, 412 etc.).
    """
```

Technische Details:
- HTTP MOVE Request auf `self._webdav_url(source_path)`
- Header `Destination`: volle WebDAV-URL des Ziels (`self._webdav_url(dest_path)`)
- Header `Overwrite: F` (kein versehentliches Überschreiben → 412 bei Konflikt)
- `_ensure_directories()` für den Ziel-Ordner aufrufen
- Credentials-Check wie bei anderen Methoden
- Erfolg: 201 (Created) oder 204 (No Content)
- 404 → `NextcloudError("Quelldatei nicht gefunden")`
- 412 → `NextcloudError("Zieldatei existiert bereits")`
- 401/403 → `_check_auth_error()`

Tests für move() — in bestehendes `tests/test_nextcloud_files.py` einfügen
(oder eigene Datei `tests/test_nextcloud_move.py`):

- `test_move_success` — MOVE 201 → Ziel-Pfad zurück
- `test_move_204_success` — MOVE 204 → auch Erfolg
- `test_move_creates_target_dir` — MKCOL wird für Ziel-Ordner aufgerufen
- `test_move_file_exists_412` — Overwrite:F → 412 → NextcloudError
- `test_move_source_not_found_404` — 404 → NextcloudError
- `test_move_auth_error` — 401 → NextcloudAuthError
- `test_move_connection_error` — Timeout → NextcloudConnectionError
- `test_move_no_credentials` — Credentials fehlen → NextcloudError

Mocke `httpx.request` wie in den bestehenden Tests.
Führe nach dem Schritt aus: `.venv\Scripts\python.exe -m pytest tests/test_nextcloud_files.py -v`
(oder die neue Testdatei falls separat)

---

### Schritt 2: `OllamaClient.generate_with_image()` erweitern

Datei: `src/elder_berry/llm/ollama_client.py`

Neue Methode:

```python
VISION_MODEL = "llava:7b"

def generate_with_image(
    self, prompt: str, image_base64: str, system: str = "",
    model: str | None = None,
) -> str:
    """Sendet Prompt + Bild an ein multimodales Ollama-Modell.

    Args:
        prompt: Der Benutzer-Prompt.
        image_base64: Base64-kodiertes Bild (ohne data:image/... Prefix).
        system: Optionaler System-Prompt.
        model: Modell-Override (Default: VISION_MODEL).

    Returns:
        Antwort-Text des Modells.

    Raises:
        RuntimeError: Modell nicht verfügbar oder Anfrage fehlgeschlagen.
    """
```

Technische Details:
- POST `/api/chat` mit `images: [image_base64]` im Message-Objekt
- Model: `model or VISION_MODEL` (Default `llava:7b`)
- Timeout: `self.timeout` (120s, reicht für Vision)
- Gleiche Fehlerbehandlung wie `generate()`

Ollama /api/chat mit Bildern (Referenz):
```json
{
    "model": "llava:7b",
    "messages": [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "...", "images": ["base64..."]}
    ],
    "stream": false
}
```

Tests — in `tests/test_ollama_client.py` ergänzen:
- `test_generate_with_image_success` — Bild + Prompt → Antwort
- `test_generate_with_image_custom_model` — Model-Override
- `test_generate_with_image_connection_error` — RuntimeError
- `test_generate_with_image_http_error` — RuntimeError

Führe aus: `.venv\Scripts\python.exe -m pytest tests/test_ollama_client.py -v`

---

### Schritt 3: `DocumentClassifier` (neue Klasse)

Datei: `src/elder_berry/tools/document_classifier.py`

```python
"""DocumentClassifier – Dokumente analysieren und Dateinamen vorschlagen.

Extrahiert Text aus Dokumenten (PDF, Bilder) und nutzt das lokale LLM
(Ollama) um Kategorie, Datum und Beschreibung zu bestimmen.

Datenschutz: Alle Analyse-Schritte laufen lokal auf dem Tower.
Einzige Ausnahme: OCR-Fallback über Stirling-PDF auf dem eigenen Server.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.llm.ollama_client import OllamaClient
    from elder_berry.tools.document_reader import DocumentReader
    from elder_berry.tools.stirling_pdf import StirlingPDFClient

logger = logging.getLogger(__name__)
```

Konstanten und Mapping:

```python
# Max Zeichen die an Ollama geschickt werden (Text-Extrakt)
MAX_CLASSIFY_CHARS = 3000

# Bild-Formate die Ollama Vision verarbeiten kann
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})

# Kategorie → Zielordner Mapping
CATEGORY_FOLDER_MAP: dict[str, str] = {
    "Vertrag": "Dokumente/Vertraege",
    "Rechnung": "Dokumente/Rechnungen",
    "Behoerden": "Dokumente/Behoerden",
    "Steuer": "Dokumente/Behoerden",
    "Haus": "Dokumente/Haus",
    "Manual": "Manuale",  # Unterordner wird vom LLM bestimmt
    "Projekt": "Projekte", # Projektname wird vom LLM bestimmt
    "Notiz": "Notizen",
    "Sonstiges": "Sonstiges",
}

# Erlaubte Kategorien (für Prompt + Validierung)
VALID_CATEGORIES = frozenset(CATEGORY_FOLDER_MAP.keys())

# Manual-Unterordner (für Prompt + Validierung)
MANUAL_SUBFOLDERS = frozenset({"3D-Druck", "Elektronik", "Netzwerk", "Smart-Home"})
```

DTO:

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
    manual_subfolder: str  # "" oder "Elektronik" (nur bei Manual)
```

Klasse DocumentClassifier:

```python
class DocumentClassifier:
    """Analysiert Dokumente und schlägt Dateinamen vor."""

    def __init__(
        self,
        ollama: OllamaClient,
        document_reader: DocumentReader,
        stirling_pdf: StirlingPDFClient | None = None,
    ) -> None:
        self._ollama = ollama
        self._reader = document_reader
        self._stirling = stirling_pdf
```

Methoden:

**`classify(self, file_path: Path) -> FilingSuggestion`**
1. `_extract_text(file_path)` → Text oder Beschreibung
2. `_build_prompt(text, file_path.name)` → System + User Prompt
3. `self._ollama.generate(prompt=user_prompt, system=system_prompt)`
4. `_parse_response(response, file_path)` → FilingSuggestion
5. Falls JSON-Parsing fehlschlägt → FilingSuggestion mit confidence="low"

**`classify_with_hint(self, file_path: Path, hint: str) -> FilingSuggestion`**
- Wenn hint ein vollständiger Name ist (enthält Kategorie aus VALID_CATEGORIES
  am Anfang, z.B. "Haus Angebot-Dach-RK-Bedachung"):
  → Direkt FilingSuggestion bauen ohne LLM
- Sonst: hint als zusätzlichen Kontext an Ollama geben
  ("Der Nutzer hat korrigiert: {hint}. Passe deinen Vorschlag an.")

**`_extract_text(self, file_path: Path) -> str`**
- PDF (.pdf):
  1. `self._reader.read_pdf(file_path)` → `DocumentResult`
  2. Wenn `.text` mit "[Kein Text erkannt" beginnt UND Stirling verfügbar:
     → `self._stirling.ocr(file_path, temp_ocr_path)` → erneut `read_pdf(temp_ocr_path)`
  3. Sonst: Text zurückgeben (max MAX_CLASSIFY_CHARS)
- Bild (.jpg/.png/.webp):
  1. Base64 kodieren
  2. `self._ollama.generate_with_image(prompt, base64)` → Beschreibung
- Sonstige: `""` (nur Dateiname als Kontext)

**`_build_prompt(self, text: str, filename: str) -> tuple[str, str]`**

System-Prompt:
```
Du bist ein Dokumenten-Klassifizierer. Analysiere den Text und bestimme:
1. datum — Datum aus dem Dokument (YYYY-MM-DD). Falls nicht erkennbar: heute.
2. kategorie — EXAKT eine aus: Vertrag, Rechnung, Behoerden, Steuer, Haus, Manual, Projekt, Notiz, Sonstiges
3. beschreibung — Firma und/oder Dokumenttyp. Regeln:
   - Bindestriche statt Leerzeichen
   - Keine Umlaute (ae/oe/ue statt ä/ö/ü)
   - Keine Unterstriche (die sind Block-Trenner)
   - Beispiele: RK-Bedachung-Angebot, Zahnarzt-Dr-Weber, Mietvertrag-Wohnung
4. manual_unterordner — NUR wenn kategorie=Manual: einer aus 3D-Druck, Elektronik, Netzwerk, Smart-Home. Sonst leer.
5. confidence — high (eindeutig), medium (unsicher bei Kategorie), low (geraten)

Antworte NUR mit JSON, kein anderer Text:
{"datum": "2026-04-02", "kategorie": "Haus", "beschreibung": "RK-Bedachung-Angebot", "manual_unterordner": "", "confidence": "high"}
```

User-Prompt:
```
Dateiname: {filename}

Dokumentinhalt:
{text[:MAX_CLASSIFY_CHARS]}
```

Falls text leer ist:
```
Dateiname: {filename}

Kein Textinhalt extrahierbar. Bitte anhand des Dateinamens klassifizieren.
```

**`_parse_response(self, response: str, file_path: Path) -> FilingSuggestion`**
1. ```json ... ``` Wrapper entfernen (falls vorhanden)
2. `json.loads(response)` → dict
3. Validierung:
   - `kategorie` in VALID_CATEGORIES → sonst "Sonstiges"
   - `datum` passt auf `\d{4}-\d{2}-\d{2}` → sonst `date.today().isoformat()`
   - `beschreibung` nicht leer → sonst Dateiname (stem, bereinigt)
   - `manual_unterordner` in MANUAL_SUBFOLDERS → sonst ""
4. `target_folder` aus CATEGORY_FOLDER_MAP bestimmen
   - Bei Manual + Unterordner: `f"Manuale/{unterordner}"`
   - Bei Projekt: `f"Projekte/{beschreibung.split('-')[0]}"` falls Projektname erkennbar,
     sonst `"Projekte"`
5. `filename` zusammenbauen: `f"{datum}_{kategorie}_{beschreibung}{file_path.suffix}"`
6. FilingSuggestion zurückgeben

Tests: `tests/test_document_classifier.py` (~20 Tests)

Mocke: OllamaClient.generate(), OllamaClient.generate_with_image(),
DocumentReader.read_pdf(), StirlingPDFClient.ocr()

- `test_classify_rechnung` — LLM gibt {"kategorie":"Rechnung",...} → korrekt
- `test_classify_vertrag` — Vertrag erkannt
- `test_classify_haus_angebot` — Haus-Kategorie
- `test_classify_manual_elektronik` — Manual + Unterordner "Elektronik"
- `test_classify_manual_unknown_sub` — Manual ohne Unterordner → "Manuale"
- `test_classify_projekt` — Projekt erkannt
- `test_classify_low_confidence` — LLM sagt confidence="low"
- `test_classify_no_text_scanned` — Kein Text → OCR Fallback → Text da
- `test_classify_no_text_no_stirling` — Kein Text, kein Stirling → nur Dateiname
- `test_classify_with_hint_category` — "Kategorie ist Haus" → neuer Vorschlag
- `test_classify_with_hint_full_name` — "Haus Angebot-Dach" → direkt gebaut
- `test_classify_date_from_doc` — Datum aus Dokumentinhalt
- `test_classify_date_fallback_today` — Kein Datum → heute
- `test_extract_pdf_with_text` — pymupdf liefert Text
- `test_extract_pdf_ocr_fallback` — pymupdf leer → Stirling OCR → Text
- `test_extract_image_vision` — Bild → generate_with_image → Beschreibung
- `test_extract_image_vision_fails` — Vision Error → leerer Text, kein Crash
- `test_extract_unknown_format` — .docx → leerer Text
- `test_parse_valid_json` — Saubere Antwort
- `test_parse_json_in_markdown` — ```json Wrapper
- `test_parse_invalid_json` — Kein JSON → FilingSuggestion mit low confidence
- `test_parse_invalid_category` — Unbekannte Kategorie → "Sonstiges"
- `test_description_umlaut_cleanup` — Ä→Ae, ö→oe etc. in Beschreibung

Führe aus: `.venv\Scripts\python.exe -m pytest tests/test_document_classifier.py -v`

---

### Schritt 4: `FilingCommandHandler` (neue Klasse)

Datei: `src/elder_berry/comms/commands/filing_commands.py`

```python
"""FilingCommandHandler – Dokumente im Eingang klassifizieren und ablegen.

Command: "cloud aufräumen" / "räum cloud auf" / "eingang aufräumen"
Flow: Eingang listen → pro Datei analysieren → Vorschlag → Bestätigung → MOVE
"""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.comms.pending_confirmation import PendingConfirmationStore
    from elder_berry.tools.document_classifier import DocumentClassifier
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient

logger = logging.getLogger(__name__)

INBOX_FOLDER = "Eingang"

FILING_PATTERN = re.compile(
    r"^(?:cloud\s+aufr[aä]umen|r[aä]um\s+cloud\s+auf|eingang\s+aufr[aä]umen)$",
    re.IGNORECASE,
)
```

DI:

```python
def __init__(
    self,
    nextcloud_files: NextcloudFilesClient | None = None,
    document_classifier: DocumentClassifier | None = None,
    pending_store: PendingConfirmationStore | None = None,
) -> None:
```

Methoden:

**`handles(self, text: str) -> bool`**
- `FILING_PATTERN.match(text.strip())` → True/False

**`execute(self, text: str, user_id: str = "") -> CommandResult`**
- Prüfe NC + Classifier verfügbar → Fehlermeldung wenn nicht
- `self._nc.list_dir(INBOX_FOLDER)` → Dateien (nur Dateien, keine Ordner)
- Leer → `CommandResult(success=True, text="📂 Eingang ist leer – nichts zu tun.")`
- Sonst → erste Datei verarbeiten via `_process_next_file(files, user_id)`

**`_process_next_file(self, files: list[NextcloudFile], user_id: str) -> CommandResult`**
1. `current = files[0]`, `remaining = files[1:]`
2. Download: `self._nc.download(f"{INBOX_FOLDER}/{current.name}", temp_dir)`
3. Classify: `self._classifier.classify(local_path)`
4. PendingAction setzen:
   ```python
   self._pending.set(user_id, PendingAction(
       action_type="filing",
       description=f"{current.name} → {suggestion.filename}",
       data={
           "source_path": f"{INBOX_FOLDER}/{current.name}",
           "local_temp": str(local_path),
           "suggestion": {
               "filename": suggestion.filename,
               "target_folder": suggestion.target_folder,
           },
           "remaining_files": [f.name for f in remaining],
           "confidence": suggestion.confidence,
       },
   ))
   ```
5. Vorschlag-Text zurückgeben:
   ```
   📄 {current.name}
   → {suggestion.filename}
   → Ziel: /{suggestion.target_folder}/
   {"⚠️ Unsicher – bitte prüfen." if confidence != "high" else ""}
   Passt das? (ja / korrigieren / überspringen)
   ```

**`handle_confirm(self, action: PendingAction, user_id: str) -> CommandResult`**
1. `source = action.data["source_path"]`
2. `target = action.data["suggestion"]["target_folder"]`
3. `filename = action.data["suggestion"]["filename"]`
4. `dest = f"{target}/{filename}"`
5. `self._nc.move(source, dest)` — bei Fehler: Fehlermeldung, Datei bleibt
6. Temp-Datei löschen (if exists)
7. Remaining files? → `_process_next_file()` für nächste
8. Sonst → "✅ Eingang ist leer. Alle Dateien abgelegt."

**`handle_correction(self, action: PendingAction, hint: str, user_id: str) -> CommandResult`**
1. `local_path = Path(action.data["local_temp"])`
2. Prüfe ob hint ein vollständiger Name ist (beginnt mit Kategorie):
   - `hint.split()[0]` in VALID_CATEGORIES → direkter Name
   - Sonst: `self._classifier.classify_with_hint(local_path, hint)`
3. PendingAction aktualisieren mit neuem Vorschlag
4. Neuen Vorschlag-Text zurückgeben

**`handle_skip(self, action: PendingAction, user_id: str) -> CommandResult`**
1. Temp-Datei löschen
2. Remaining files? → `_process_next_file()` für nächste
3. Sonst → "✅ Eingang abgearbeitet."

**`command_descriptions` Property:**
```python
@property
def command_descriptions(self) -> dict[str, str]:
    return {
        "cloud aufräumen": "Dateien im Eingang klassifizieren und ablegen",
    }
```

Tests: `tests/test_filing_commands.py` (~18 Tests)

Mocke: NextcloudFilesClient (list_dir, download, move),
DocumentClassifier (classify, classify_with_hint), PendingConfirmationStore

- `test_aufräumen_pattern` — "cloud aufräumen" → handles() True
- `test_räum_cloud_auf_pattern` — "räum cloud auf" → True
- `test_eingang_aufräumen_pattern` — "eingang aufräumen" → True
- `test_no_collision` — "cloud upload" / "cloud suche" → False
- `test_eingang_empty` — list_dir leer → "Eingang ist leer"
- `test_eingang_one_file` — 1 Datei → Vorschlag + PendingAction gesetzt
- `test_eingang_skips_directories` — Ordner im Eingang werden ignoriert
- `test_eingang_multiple_files` — 3 Dateien → erste vorgeschlagen, 2 remaining
- `test_confirm_moves_file` — "ja" → nc.move() aufgerufen mit korrekten Pfaden
- `test_confirm_next_file` — Nach MOVE → nächste Datei vorgeschlagen
- `test_confirm_last_file` — Letzte Datei → "Eingang ist leer"
- `test_skip_next_file` — "überspringen" → nächste ohne MOVE
- `test_correction_hint` — User-Hint → classify_with_hint aufgerufen
- `test_correction_direct_name` — "Haus Angebot-Dach" → direkt gebaut
- `test_move_error` — MOVE fehlgeschlagen → Fehlermeldung, Datei bleibt
- `test_no_nextcloud` — NC fehlt → "Nextcloud nicht konfiguriert"
- `test_no_classifier` — Classifier fehlt → "Dokument-Analyse nicht verfügbar"
- `test_help_text` — command_descriptions enthält "cloud aufräumen"

Führe aus: `.venv\Scripts\python.exe -m pytest tests/test_filing_commands.py -v`

---

### Schritt 5: Integration (remote_commands, message_handlers, start_saleria)

#### `src/elder_berry/comms/remote_commands.py`

1. Import: `from elder_berry.comms.commands.filing_commands import FilingCommandHandler`
2. TYPE_CHECKING: `from elder_berry.tools.document_classifier import DocumentClassifier`
3. `__init__`: Neuer Parameter `document_classifier: DocumentClassifier | None = None`
4. Handler instanziieren:
   ```python
   self._filing = FilingCommandHandler(
       nextcloud_files=nextcloud_files,
       document_classifier=document_classifier,
       pending_store=pending_store,  # muss ggf. durchgereicht werden
   )
   ```
5. In `self._handlers` Liste einfügen (nach Cloud-Handler)
6. KEYWORD_MAP ergänzen:
   ```python
   "aufräumen": "cloud aufräumen",
   "eingang": "cloud aufräumen",
   "eingang aufräumen": "cloud aufräumen",
   "räum cloud auf": "cloud aufräumen",
   "ablegen": "cloud aufräumen",
   ```
7. HELP_TEXT ergänzen:
   ```
   Dokument-Ablage:
     cloud aufräumen – Dateien im Eingang klassifizieren und ablegen
   ```

#### `src/elder_berry/comms/message_handlers.py`

PendingAction-Handling für `action_type="filing"` erweitern.
Lies die bestehende Logik für `mail_reply` als Referenz — gleich Muster:

1. In der Methode die PendingActions prüft (vermutlich `_check_pending`):
   ```python
   if action.action_type == "filing":
       # Bestätigungs-Wörter prüfen
       filing_confirm = {"ja", "yes", "passt", "ok", "ablegen"}
       filing_skip = {"überspringen", "skip", "weiter", "nächste"}
       lower = text.strip().lower()
       if lower in filing_confirm:
           return self._filing_handler.handle_confirm(action, user_id)
       if lower in filing_skip:
           return self._filing_handler.handle_skip(action, user_id)
       # Alles andere = Korrektur-Hint
       return self._filing_handler.handle_correction(action, text, user_id)
   ```
2. `_filing_handler` muss als Attribut verfügbar sein (via DI oder über
   RemoteCommandHandler._filing durchreichen)

**Wichtig:** Lies die bestehende message_handlers.py genau — das Pattern
für PendingAction-Handling ist dort bereits etabliert. Folge dem gleichen
Muster, füge keinen neuen Mechanismus ein.

#### `scripts/start_saleria.py`

DocumentClassifier instanziieren und durchreichen:

```python
from elder_berry.tools.document_classifier import DocumentClassifier

# Nach den bestehenden Client-Initialisierungen:
document_classifier = None
if ollama_client and ollama_client.is_available():
    document_classifier = DocumentClassifier(
        ollama=ollama_client,
        document_reader=document_reader,  # bereits vorhanden
        stirling_pdf=stirling_pdf_client,  # bereits vorhanden, kann None sein
    )
    logger.info("DocumentClassifier initialisiert (Ollama + DocumentReader)")
else:
    logger.warning("DocumentClassifier nicht verfügbar (Ollama fehlt)")
```

An RemoteCommandHandler durchreichen:
```python
remote_commands = RemoteCommandHandler(
    ...,
    document_classifier=document_classifier,
)
```

---

### Schritt 6: Gesamttest + Journal

1. Alle Tests ausführen:
   `.venv\Scripts\python.exe -m pytest -v`
2. Sicherstellen dass keine bestehenden Tests brechen
3. Journal-Eintrag in `docs/journal.txt` ergänzen:
   ```
   ## Abgeschlossen: Phase 42 – Dokument-Ablage (2026-XX-XX)
   - DocumentClassifier: Textextraktion (pymupdf → OCR → Vision) + Ollama-Analyse
   - FilingCommandHandler: "cloud aufräumen" mit Einzelbestätigung
   - NextcloudFilesClient.move(): WebDAV MOVE (Overwrite:F)
   - OllamaClient.generate_with_image(): Ollama Vision für Bilder
   - Integration: remote_commands, message_handlers, start_saleria
   - Tests: XX/XX grün (XX neue Tests)
   ```
4. Alle Änderungen committen:
   `git add -A && git commit -m "Phase 42: Dokument-Ablage (Cloud Aufräumen)"`

## Wichtige Constraints

### Dateistruktur
- Eine Klasse pro Datei, Dateiname = Klassenname (snake_case)
- Neue Dateien in maximal 400 Zeilen Chunks
- Absolute Pfade, pathlib wo möglich
- Dependency Injection über Konstruktor

### Tests
- Alle externen Aufrufe mocken (Ollama, Nextcloud, Stirling-PDF, pymupdf)
- pytest mit asyncio_mode=auto
- Tests vor dem Commit ausführen und Ergebnis berichten

### Was NICHT gemacht werden soll
- Kein neuer PendingAction-Mechanismus — bestehenden PendingConfirmationStore nutzen
- Keine neuen Dependencies — alles mit httpx, pymupdf, json (stdlib)
- Keine Änderung an der Dateinamenskonvention
- Keine automatische Verarbeitung (immer User-Bestätigung)
- Kein Zugriff auf /Archiv/, /Saleria/, /Deck/ (ausgeschlossen)

### Reihenfolge einhalten
1. move() + Tests → grün
2. generate_with_image() + Tests → grün
3. DocumentClassifier + Tests → grün
4. FilingCommandHandler + Tests → grün
5. Integration + Gesamttest → grün
6. Journal + Commit

Zwischen jedem Schritt: Tests ausführen, Ergebnis berichten,
Zwischenstand in journal.txt sichern.
