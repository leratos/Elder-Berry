# Stirling-PDF Integration – StirlingPDFClient + PDF-Commands

## Kontext

Stirling-PDF läuft als Docker-Container auf dem Rootserver unter
`pdf.example.com`. Saleria soll über Matrix-Commands PDFs
verarbeiten können: zusammenfügen, aufteilen, komprimieren, OCR,
konvertieren. Die PDFs liegen in Nextcloud.

**Bewusst NICHT über API:** Visuelles Unterschreiben — das geht nur
im Browser (Stirling-PDF Frontend-Only Feature). Saleria hat keine
Berechtigung, Dokumente zu signieren.

**Workflow:** Saleria holt PDF aus Nextcloud → verarbeitet via
Stirling-PDF API → lädt Ergebnis zurück nach Nextcloud.

## Vorbereitung

1. Lies `docs/journal.txt` (letzte 80 Zeilen) für den aktuellen Stand
2. Lies `src/elder_berry/tools/nextcloud_files.py` (für NC-Integration)
3. Lies `src/elder_berry/comms/commands/cloud_commands.py` (Pattern-Referenz)
4. Lies `CLAUDE.md` für Projektkonventionen
5. Erstelle Branch: `feature/stirling-pdf-integration`

## Stirling-PDF API Details

**Base-URL:** `https://pdf.example.com/api/v1/`
**Auth:** Header `X-API-Key: <key>` (aus SecretStore: `stirling_pdf_api_key`)
**Format:** Alle Endpoints: `POST`, `Content-Type: multipart/form-data`
**Response:** Verarbeitete PDF als Binary (application/pdf)

**Relevante Endpoints:**

| Endpoint | Funktion | Parameter |
|---|---|---|
| `/api/v1/general/merge-pdfs` | PDFs zusammenfügen | `fileInput` (multiple files) |
| `/api/v1/general/split-pdf-by-pages` | PDF aufteilen | `fileInput`, `pages` (z.B. "1-3,5") |
| `/api/v1/misc/compress-pdf` | PDF komprimieren | `fileInput`, `optimizeLevel` (1-9) |
| `/api/v1/misc/ocr-pdf` | OCR (Text erkennen) | `fileInput`, `ocrType` ("force-ocr"), `languages` ("deu+eng") |
| `/api/v1/convert/pdf-to-word` | PDF → DOCX | `fileInput`, `outputFormat` ("docx") |
| `/api/v1/convert/file-to-pdf` | DOCX/Bild → PDF | `fileInput` |
| `/api/v1/security/add-password` | PDF verschlüsseln | `fileInput`, `password` |
| `/api/v1/security/remove-password` | PDF entschlüsseln | `fileInput`, `password` |
| `/api/v1/misc/extract-images` | Bilder extrahieren | `fileInput` |

**Beispiel-Request (curl):**
```bash
curl -X POST "https://pdf.example.com/api/v1/misc/compress-pdf" \
  -H "X-API-Key: <key>" \
  -F "fileInput=@dokument.pdf" \
  -F "optimizeLevel=5" \
  -o komprimiert.pdf
```

## Neue Dateien

### 1. `src/elder_berry/tools/stirling_pdf.py`

Klasse `StirlingPDFClient` — REST-Client für Stirling-PDF.

**Credentials aus SecretStore:**
- `stirling_pdf_url` → `https://pdf.example.com`
- `stirling_pdf_api_key` → API-Key aus Stirling-PDF Settings

**Klasse:**
```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class PDFResult:
    """Ergebnis einer PDF-Operation."""
    success: bool
    output_path: Path | None = None  # Lokaler Pfad zur verarbeiteten PDF
    message: str = ""
    original_name: str = ""

class StirlingPDFClient:
    def __init__(self, secret_store: SecretStore) -> None: ...
    def is_available(self) -> bool: ...
        # Credentials vorhanden + Server erreichbar (GET /api/v1/info/status)

    def merge(self, pdf_paths: list[Path], output_path: Path) -> PDFResult: ...
        # POST /api/v1/general/merge-pdfs
        # fileInput: mehrere Dateien

    def split(self, pdf_path: Path, pages: str, output_dir: Path) -> PDFResult: ...
        # POST /api/v1/general/split-pdf-by-pages
        # pages: "1-3" oder "1,3,5"
        # Response: ZIP mit einzelnen Seiten → entpacken in output_dir

    def compress(self, pdf_path: Path, output_path: Path, level: int = 5) -> PDFResult: ...
        # POST /api/v1/misc/compress-pdf
        # optimizeLevel: 1 (wenig) bis 9 (stark)

    def ocr(self, pdf_path: Path, output_path: Path, languages: str = "deu+eng") -> PDFResult: ...
        # POST /api/v1/misc/ocr-pdf
        # ocrType: "force-ocr", languages: "deu+eng"

    def to_word(self, pdf_path: Path, output_path: Path) -> PDFResult: ...
        # POST /api/v1/convert/pdf-to-word
        # outputFormat: "docx"

    def to_pdf(self, file_path: Path, output_path: Path) -> PDFResult: ...
        # POST /api/v1/convert/file-to-pdf
        # Konvertiert DOCX, Bilder etc. → PDF

    def extract_images(self, pdf_path: Path, output_dir: Path) -> PDFResult: ...
        # POST /api/v1/misc/extract-images
        # Response: ZIP → entpacken in output_dir
```

**Implementierungshinweise:**

- HTTP-Client: `httpx` (bereits in dependencies)
- Auth: `X-API-Key` Header bei jedem Request
- Upload: `httpx` multipart mit `files={"fileInput": (filename, file_bytes, "application/pdf")}`
- Für merge: mehrere Dateien als Liste: `files=[("fileInput", (name1, bytes1, mime)), ("fileInput", (name2, bytes2, mime))]`
- Download: Response-Body als Bytes → in output_path schreiben
- ZIP-Responses (split, extract_images): `zipfile.ZipFile` zum Entpacken
- Timeout: 60s (OCR und Konvertierung können dauern)
- Temp-Verzeichnis: `tempfile.mkdtemp()` für Zwischendateien, am Ende aufräumen
- Fehlerklassen: `StirlingPDFError`, `StirlingPDFConnectionError`

**_call_api() Helfer-Methode:**
```python
def _call_api(
    self, endpoint: str, files: list[tuple], data: dict | None = None,
    output_path: Path | None = None,
) -> bytes:
    """Sendet Request an Stirling-PDF API, gibt Response-Bytes zurück."""
    url = f"{self._base_url}/api/v1/{endpoint}"
    headers = {"X-API-Key": self._api_key}
    response = httpx.post(
        url, headers=headers, files=files, data=data or {},
        timeout=60.0,
    )
    response.raise_for_status()
    if output_path:
        output_path.write_bytes(response.content)
    return response.content
```

### 2. `src/elder_berry/comms/commands/pdf_commands.py`

Klasse `PDFCommandHandler(CommandHandler)` — PDF-Verarbeitungs-Commands.

**DI:**
- `stirling_pdf: StirlingPDFClient | None = None`
- `nextcloud_files: NextcloudFilesClient | None = None`

**Patterns:**
```python
# pdf zusammenfügen <datei1> <datei2> [datei3...]
PDF_MERGE_PATTERN = re.compile(
    r"^pdf\s+(?:zusammenfügen|merge|verbinden)\s+(.+)$",
    re.IGNORECASE,
)

# pdf aufteilen <datei> seiten 1-3,5
PDF_SPLIT_PATTERN = re.compile(
    r"^pdf\s+(?:aufteilen|split|teilen)\s+(.+?)\s+(?:seiten?|pages?)\s+(.+)$",
    re.IGNORECASE,
)

# pdf komprimieren <datei> [stufe 1-9]
PDF_COMPRESS_PATTERN = re.compile(
    r"^pdf\s+(?:komprimieren|compress|verkleinern)\s+(.+?)(?:\s+(?:stufe|level)\s+(\d))?$",
    re.IGNORECASE,
)

# pdf ocr <datei>
PDF_OCR_PATTERN = re.compile(
    r"^pdf\s+ocr\s+(.+)$",
    re.IGNORECASE,
)

# pdf zu word <datei> / pdf to word <datei>
PDF_TO_WORD_PATTERN = re.compile(
    r"^pdf\s+(?:zu|to|nach)\s+word\s+(.+)$",
    re.IGNORECASE,
)

# pdf konvertiere <datei> / zu pdf <datei>
PDF_FROM_FILE_PATTERN = re.compile(
    r"^(?:zu\s+pdf|to\s+pdf|pdf\s+(?:konvertiere?|convert))\s+(.+)$",
    re.IGNORECASE,
)

# pdf bilder <datei> / pdf extract images <datei>
PDF_EXTRACT_IMAGES_PATTERN = re.compile(
    r"^pdf\s+(?:bilder|images?|bilder\s+extrahieren)\s+(.+)$",
    re.IGNORECASE,
)
```

**Workflow je Command (Nextcloud-Integration):**

Jeder Command folgt demselben Muster:
1. Dateiname(n) aus dem Command extrahieren
2. `cloud suche <dateiname>` → NextcloudFilesClient.search(name)
3. Wenn genau 1 Treffer: download in temp-Verzeichnis
4. Wenn 0 Treffer: Fehlermeldung "Datei nicht gefunden in Nextcloud"
5. Wenn >1 Treffer: Liste anzeigen, Nutzer soll präziser sein
6. Stirling-PDF API aufrufen
7. Ergebnis-PDF nach Nextcloud hochladen (gleicher Ordner, Suffix im Namen)
8. Temp-Dateien aufräumen
9. CommandResult mit Erfolgsmeldung + Nextcloud-Pfad

**Namenskonvention für Ergebnisse:**
- Komprimieren: `original_compressed.pdf`
- OCR: `original_ocr.pdf`
- Merge: `merged_<timestamp>.pdf`
- Split: `original_seite_1.pdf`, `original_seite_2.pdf`
- Konvertierung: `original.docx` oder `original.pdf`

**Helfer-Methode `_resolve_nc_file()`:**
```python
def _resolve_nc_file(self, name: str) -> tuple[Path | None, str]:
    """Sucht Datei in Nextcloud, lädt sie herunter.

    Returns:
        (local_path, remote_path) oder (None, error_message)
    """
    results = self._nc.search(name)
    pdfs = [f for f in results if f.name.lower().endswith('.pdf')]
    if len(pdfs) == 0:
        return None, f"Keine PDF '{name}' in Nextcloud gefunden."
    if len(pdfs) > 1:
        listing = "\n".join(f"  📄 {f.path}" for f in pdfs[:5])
        return None, f"Mehrere Treffer:\n{listing}\nBitte genauer angeben."
    remote_path = pdfs[0].path
    local_path = self._nc.download(remote_path)
    return local_path, remote_path
```

**Ohne Nextcloud-Fallback:**

Wenn `nextcloud_files` nicht konfiguriert ist, können die Commands trotzdem
mit lokalen Pfaden arbeiten (z.B. `pdf komprimieren C:\Docs\vertrag.pdf`).
Pattern erkennt lokale Pfade am `\` oder `/` am Anfang.

### 3. `tests/test_stirling_pdf.py`

Tests für `StirlingPDFClient`. HTTP komplett gemockt.

**Test-Kategorien (~20 Tests):**

Credentials & Verfügbarkeit:
- `test_is_available_success`
- `test_is_available_no_credentials`
- `test_is_available_server_unreachable`

Merge:
- `test_merge_two_pdfs` — Zwei Dateien → merged PDF
- `test_merge_server_error` — 500 → StirlingPDFError

Split:
- `test_split_pages` — Seiten "1-3" → ZIP → entpackt
- `test_split_single_page` — Seite "2" → eine PDF

Compress:
- `test_compress_default_level` — Level 5
- `test_compress_custom_level` — Level 9
- `test_compress_file_smaller` — Output kleiner als Input

OCR:
- `test_ocr_default_languages` — deu+eng
- `test_ocr_success` — PDF mit Text zurück

Convert:
- `test_to_word_success` — PDF → DOCX
- `test_to_pdf_from_docx` — DOCX → PDF
- `test_to_pdf_from_image` — PNG → PDF

Extract:
- `test_extract_images_success` — ZIP → Bilder entpackt
- `test_extract_images_no_images` — Leere ZIP

Error:
- `test_api_timeout` — 60s Timeout
- `test_api_auth_error` — 401 → Fehler
- `test_invalid_pdf` — 400 → Fehlermeldung

### 4. `tests/test_pdf_commands.py`

Tests für `PDFCommandHandler`. Client + Nextcloud gemockt.

**Test-Kategorien (~18 Tests):**

Pattern-Matching:
- `test_merge_pattern` — "pdf zusammenfügen A.pdf B.pdf"
- `test_split_pattern` — "pdf aufteilen Vertrag.pdf seiten 1-3"
- `test_compress_pattern` — "pdf komprimieren Vertrag.pdf"
- `test_compress_pattern_with_level` — "pdf komprimieren Vertrag.pdf stufe 9"
- `test_ocr_pattern` — "pdf ocr Scan.pdf"
- `test_to_word_pattern` — "pdf zu word Bericht.pdf"
- `test_to_pdf_pattern` — "zu pdf Brief.docx"
- `test_extract_images_pattern` — "pdf bilder Katalog.pdf"
- `test_no_collision_with_existing` — Kein Overlap mit cloud/file Commands

Execution (Nextcloud-Workflow):
- `test_compress_nc_workflow` — Suche → Download → Compress → Upload
- `test_merge_nc_workflow` — Zwei Dateien aus NC → Merge → Upload
- `test_ocr_nc_workflow` — NC Download → OCR → Upload
- `test_file_not_found_in_nc` — Keine Treffer → Fehlermeldung
- `test_multiple_matches_in_nc` — Mehrere Treffer → Liste
- `test_no_stirling` — Client fehlt → "PDF-Verarbeitung nicht konfiguriert"
- `test_no_nextcloud` — NC fehlt, lokaler Pfad funktioniert
- `test_commands_in_help` — command_descriptions vorhanden
- `test_local_path_fallback` — "pdf komprimieren C:\Docs\x.pdf" ohne NC

## Zu ändernde Dateien

### 5. `src/elder_berry/comms/remote_commands.py`

- Import: `from elder_berry.comms.commands.pdf_commands import PDFCommandHandler`
- TYPE_CHECKING: `from elder_berry.tools.stirling_pdf import StirlingPDFClient`
- `__init__`: Neuer Parameter `stirling_pdf: StirlingPDFClient | None = None`
- Handler instanziieren:
  ```python
  PDFCommandHandler(
      stirling_pdf=stirling_pdf,
      nextcloud_files=nextcloud_files,  # bereits vorhanden
  )
  ```
- In `self._handlers` Liste einfügen (nach _cloud, vor _process)
- HELP_TEXT ergänzen:
  ```
  PDF-Verarbeitung (Stirling-PDF):
    pdf zusammenfügen <a.pdf> <b.pdf> – PDFs zusammenfügen
    pdf aufteilen <datei> seiten 1-3 – Seiten extrahieren
    pdf komprimieren <datei> [stufe 1-9] – Dateigröße reduzieren
    pdf ocr <datei> – Text erkennen (Deutsch+Englisch)
    pdf zu word <datei> – PDF → Word konvertieren
    zu pdf <datei> – Word/Bild → PDF konvertieren
    pdf bilder <datei> – Bilder aus PDF extrahieren
  ```

### 6. `scripts/start_saleria.py`

In `_init_productivity_services()`:
```python
# Stirling-PDF
if secrets.get_or_none("stirling_pdf_url"):
    try:
        from elder_berry.tools.stirling_pdf import StirlingPDFClient
        spdf = StirlingPDFClient(secret_store=secrets)
        if spdf.is_available():
            svc["stirling_pdf"] = spdf
            logger.info("Stirling-PDF: aktiv (%s)", secrets.get("stirling_pdf_url"))
        else:
            logger.warning("Stirling-PDF: nicht erreichbar")
    except Exception as e:
        logger.warning("Stirling-PDF nicht verfügbar: %s", e)
```

Im `RemoteCommandHandler(...)` Aufruf:
```python
stirling_pdf=svc.get("stirling_pdf"),
```

### 7. `pyproject.toml`

Keine Änderung nötig — `httpx` und `zipfile` (stdlib) reichen aus.

## Architektur-Hinweise

- `StirlingPDFClient` ist eigenständig in `tools/` — wie alle anderen Clients
- `PDFCommandHandler` ist eigenständig in `comms/commands/`
- Nextcloud-Integration: `PDFCommandHandler` bekommt `NextcloudFilesClient` per DI
  und nutzt es für Download/Upload. Kein direkter Import zwischen den Clients.
- Temp-Dateien: `tempfile.mkdtemp()` → nach Operation `shutil.rmtree(temp_dir)`
- ZIP-Handling: `zipfile.ZipFile` (stdlib) für Split und Extract-Images Responses
- Alle Patterns starten mit `pdf ` → keine Kollision mit `cloud ` oder anderen Commands
- Fehler: Graceful degradation wenn Stirling-PDF nicht erreichbar

## Sicherheits-Entscheidungen

- **Keine Signatur-Funktion:** Bewusste Entscheidung — Saleria darf nicht unterschreiben
- **Keine Passwort-Funktion über Matrix:** `add-password`/`remove-password` Endpoints
  werden NICHT exponiert. Passwörter für PDFs gehören nicht in Chat-Nachrichten.
- **Kein Löschen:** Saleria verarbeitet PDFs, löscht aber nie das Original in Nextcloud
- **Ergebnisse immer als neue Datei:** `_compressed.pdf`, `_ocr.pdf` etc.

## SecretStore Setup

```python
from elder_berry.core.secret_store import SecretStore
s = SecretStore()
s.set("stirling_pdf_url", "https://pdf.example.com")
s.set("stirling_pdf_api_key", "<dein-api-key>")
```

## Reihenfolge

1. `StirlingPDFClient` implementieren (stirling_pdf.py)
2. Tests schreiben (test_stirling_pdf.py) — ~20 Tests, HTTP gemockt
3. `PDFCommandHandler` implementieren (pdf_commands.py) inkl. NC-Workflow
4. Tests schreiben (test_pdf_commands.py) — ~18 Tests
5. `remote_commands.py` anpassen (Import + DI + HELP_TEXT)
6. `start_saleria.py` anpassen (Init + DI)
7. Alle Tests ausführen, 0 Fehler
8. Journal-Eintrag abschließen
9. Commit auf Branch
