# Phase 94: LibreSign Integration

## Motivation
Adobe Acrobat ablösen für den Workflow:
1. PDF-Formular erhalten (Mail, Download, Scan)
2. Felder ausfüllen (Text, Datum, Name)
3. Signieren
4. Zurücksenden oder ablegen

Ziele:
- Print/Scan-Schleifen vermeiden
- In bestehendem Nextcloud-Workspace bleiben
- Adobe Creative Suite Abo-Pressure entkommen
- Saleria kann Status/Workflow abfragen und triggern

## Komponenten-Übersicht

### Server-Seite (cloud.last-strawberry.com)
- Nextcloud-App LibreSign installiert
- Dependencies: Java 11+, JSignPdf, CFSSL
- Konfiguration via occ (Plesk-PHP-Pfad beachten:
  /opt/plesk/php/8.3/bin/php -d memory_limit=512M occ libresign:...)

### Elder-Berry-Seite (optional, ab Stufe 2)
- LibreSignClient (analog CalDAVTaskClient-Pattern)
- LibreSignCommandHandler (CommandHandler ABC)
- Integration in bestehenden PendingConfirmationStore

## Architektur (Stufe 2+)

src/elder_berry/tools/libresign_client.py
  class LibreSignClient:
    """OCS-API-Client für LibreSign auf Nextcloud."""
    def __init__(self, base_url, username, app_password, http_client)
    async def list_pending_signatures() -> list[SignatureRequest]
    async def get_signature_status(file_id) -> SignatureStatus
    async def request_signature(file_path, signers, fields) -> str
    async def sign_document(request_id, signature_data) -> bytes

src/elder_berry/comms/commands/libresign_handler.py
  class LibreSignCommandHandler(CommandHandler):
    """Routet 'signiere ...', 'signatur-status', 'ausstehende verträge'."""
    def __init__(self, libresign_client, confirmation_store, ...)

Dependency Injection: LibreSignClient wird im Bootstrap erzeugt
und in den Handler injiziert. Keine direkten Imports im Handler.

## Datentypen (Pydantic, in core/models.py)

class SignatureRequest(BaseModel):
  request_id: str
  file_name: str
  file_path: str  # WebDAV-Pfad
  created_at: datetime
  status: Literal["pending", "signed", "expired", "cancelled"]
  signers: list[Signer]

class Signer(BaseModel):
  email: str
  display_name: str
  signed_at: datetime | None

## Implementierungs-Stufen

### Stufe 1: Installation & Smoke-Test (kein Code)
Erfolgskriterium: 3 reale PDFs erfolgreich ausgefüllt + signiert
Aufwand: ~2-3h
- LibreSign via App Store installieren
- Dependencies via occ ziehen
- Manuell mit echten Use-Case-PDFs testen:
  - Behördenformular (gescannt, ohne AcroForm)
  - Vertrag mit AcroForm-Feldern
  - Einfaches Textdokument (Anschreiben + Unterschrift)
- Bewertung: Reicht die UX? Wenn nein → Phase abbrechen,
  Plan B: PDF24 lokal + PyMuPDF in Elder-Berry

### Stufe 2: Read-Only Client (Saleria kann fragen)
Erfolgskriterium: "Saleria, was steht zur Signatur an?" funktioniert
Aufwand: ~1 Tag
- LibreSignClient: list_pending_signatures, get_signature_status
- LibreSignCommandHandler mit Patterns:
  - "signatur(en)? (status|offen|ausstehend)"
  - "was muss ich noch signieren"
- Tests: pytest mit Mock-Client
- Kein Triggern von Signaturen, nur Anzeige

### Stufe 3: Signatur-Trigger via Saleria (mit Confirmation)
Erfolgskriterium: Zwei-Schritt-Bestätigung funktioniert sauber
Aufwand: ~1-2 Tage
- LibreSignClient: request_signature, sign_document
- Two-step confirmation via PendingConfirmationStore:
  1. "Bereite Vertrag X zur Signatur vor" → Draft
  2. "Bestätige" → Ausführung
- KEIN Auto-Signing ohne explizite Bestätigung

### Stufe 4 (optional, später): Workflow-Automation
NUR umsetzen wenn echter Bedarf entsteht (YAGNI)
- Mail-Anhang → Nextcloud-Ordner → Signatur-Queue
- Webhook-Empfang bei Signatur abgeschlossen → Mail zurück
- Nicht in dieser Phase planen

## Out of Scope (YAGNI)

- Multi-Party-Workflows (mehrere Unterzeichner) – Lera signiert solo
- Abstraktion ISignatureProvider – LibreSign ist einziger Kandidat,
  bei Bedarf später refactorn
- QES-Integration (D-Trust etc.) – nicht aktueller Bedarf
- DocuSign-/Documenso-Parallelbetrieb
- Mobile-App-Anbindung – Browser reicht
- Eigene Signatur-Visualisierung in PWA-Dashboard

## Bekannte Risiken

1. **Dependency-Installation fummelig**
   LibreSign braucht Java + JSignPdf + CFSSL, Web-Installer
   unvollständig. Plesk-PHP-Pfad-Eigenheit zusätzliches Risiko.
   Mitigation: Stufe 1 ist genau dieser Test. Wenn hier Stop,
   ist nicht viel Code verloren.

2. **Form-Filling-Limits bei gescannten PDFs**
   Behörden-PDFs ohne AcroForm-Felder erfordern manuelles
   Setzen von Eingabezonen. Kann tedious werden.
   Mitigation: Lokales Tool (PDF24) als Fallback behalten.

3. **API-Stabilität**
   LibreSign ist jünger als Core-Nextcloud-Apps, API-Breaking-
   Changes zwischen Versionen möglich.
   Mitigation: LibreSignClient als dünne Schicht, leicht
   anpassbar; Version pinnen.

4. **Saleria-Mehrwert begrenzt**
   Signieren ist inhärent interaktiv (PDF prüfen, Stellen
   wählen). Voice-/Chat-Trigger spart wenig.
   Mitigation: Stufe 2 (Status-Queries) zuerst – das ist der
   eigentliche Mehrwert. Stufe 3 nur wenn Stufe 2 sich bewährt.

5. **Rechtliche Verbindlichkeit**
   LibreSign-Signaturen sind "fortgeschrittene elektronische
   Signaturen" (FES), nicht "qualifizierte" (QES) nach eIDAS.
   Mitigation: Klar dokumentieren, für notarielle Sachen
   nicht verwenden.

## Test-Strategie

Stufe 1: Manuell, dokumentiert in journal.txt
Stufe 2-3: pytest mit asyncio_mode=auto
- test_libresign_client.py: HTTP-Mock mit aiohttp test utils
- test_libresign_handler.py: Pattern-Match + Mock-Client
- Integration-Test optional gegen lokale LibreSign-Instanz

## Offene Fragen

1. Authentifizierung: Reicht App-Password aus NordPass,
   oder OAuth nötig?
2. WebDAV-Pfade: relative zu /remote.php/dav/files/lera/?
3. Webhook-Endpoint für Signatur-Abschluss: Soll Saleria
   auf RPi5 Webhooks empfangen, oder Polling reichen?
4. Wie umgehen mit "Datei ist offen in LibreSign" während
   Saleria sie verschieben/löschen will?

## Abhängigkeiten

- Phase 93 (Cookbook) abgeschlossen
- Nextcloud erreichbar (gegeben)
- Bestehender PendingConfirmationStore (gegeben)
- HTTP-Client-Pattern aus CalDAVTaskClient (Phase 56)

## Definition of Done (gesamte Phase)

- [ ] LibreSign installiert und mit 3 Real-PDFs getestet
- [ ] LibreSignClient mit list + status implementiert
- [ ] LibreSignCommandHandler mit 2+ Patterns
- [ ] Tests grün
- [ ] Zwei-Schritt-Confirmation für sign_document
- [ ] Concept-Doc finalisiert, journal.txt aktualisiert
- [ ] PROJECT_ROADMAP.md aktualisiert
- [ ] Branch feature/phase-XX-libresign-integration gemerged

## Plan B (falls Stufe 1 scheitert)

Wenn LibreSign installations- oder funktionsmäßig nicht
überzeugt:
- PDF24 Creator lokal auf Tower (kostenlos, Windows, kein Abo)
- PyMuPDF-basierter PdfCommandHandler in Elder-Berry für
  programmatische Aufgaben (Merge, Split, Watermark, simple
  Formularfelder ausfüllen via JSON-Mapping)
- Adobe Acrobat trotzdem deinstallieren
