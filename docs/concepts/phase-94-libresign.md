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

### Server-Seite (Nextcloud, z. B. cloud.example.com)
- Nextcloud-App LibreSign installiert
- Dependencies: Java 11+, JSignPdf, CFSSL
- Konfiguration via occ (Plesk-PHP-Pfad beachten:
  /opt/plesk/php/8.3/bin/php -d memory_limit=512M occ libresign:...)

### Elder-Berry-Seite (optional, ab Stufe 2)
- LibreSignClient (analog NextcloudCookbookClient: sync httpx, SecretStore-Auth)
- LibreSignCommandHandler (CommandHandler ABC)
- Integration in bestehenden PendingConfirmationStore

## Architektur (Stufe 2+)

Grounding (verifizierte Patterns, an denen sich Stufe 2+ orientiert):

- Nextcloud-HTTP-Client: `src/elder_berry/tools/nextcloud_cookbook_client.py`
  (Phase 93) – synchron, `httpx`, Basic-Auth, Credentials aus SecretStore.
- CalDAV-Client: `src/elder_berry/tools/caldav_tasks.py` (Phase 56) – ebenfalls
  synchron, gleiche `nextcloud_*`-Secrets.
- Command-Handler-Vertrag: `src/elder_berry/comms/commands/base.py`
  (`CommandHandler.execute()` ist synchron, DI über `HandlerContext`).

Konsequenz: Der Client ist **synchron** (kein `async`), nutzt `httpx` und liest
seine Credentials aus dem `SecretStore` – nicht über Konstruktor-URLs.

src/elder_berry/tools/libresign_client.py
  class LibreSignClient:
    """LibreSign-API-Client (Nextcloud-App) – sync httpx, Basic-Auth.

    Liest nextcloud_url / nextcloud_user / nextcloud_app_password aus dem
    SecretStore (identisch mit Cookbook-/CalDAV-Client). LibreSign-API-Basis
    voraussichtlich index.php/apps/libresign/api/v1 – exakte Endpunkte in
    Stufe 1 verifizieren, bevor sie hier festgeschrieben werden.
    """
    def __init__(self, secret_store: SecretStore, timeout: float = 10.0)
    def is_available(self) -> bool
    def list_pending_signatures(self) -> list[SignatureRequest]
    def get_signature_status(self, file_id: str) -> SignatureStatus
    # erst Stufe 3:
    def request_signature(self, file_path, signers, fields) -> str
    def sign_document(self, request_id, signature_data) -> bytes

src/elder_berry/comms/commands/libresign_commands.py
  class LibreSignCommandHandler(CommandHandler):
    """Routet 'signatur-status', 'ausstehende verträge', (Stufe 3) 'signiere …'.

    execute(self, command: str, raw_text: str) -> CommandResult
    Fehlende Config → self.not_configured(command, "LibreSign").
    """

Dependency Injection: `LibreSignClient` wird im Bootstrap erzeugt und über den
`HandlerContext`-Service-Container an den Handler übergeben; der Handler wird in
`RemoteCommandHandler._handlers` registriert (Reihenfolge = Priorität). Keine
direkten Client-Imports im Handler-Body.

## Datentypen (frozen dataclass, colocated im Client-Modul)

Konvention im Repo: Domänen-Typen der Nextcloud-Clients sind
`@dataclass(frozen=True)` direkt im Client-Modul (vgl. `CookbookRecipeSummary`
in `nextcloud_cookbook_client.py`, `TaskItem` in `caldav_tasks.py`). Es gibt
kein zentrales `core/models.py`, und Pydantic wird nur in den FastAPI-Servern
(`robot/`, `agent/`) genutzt – nicht für Client-Domänentypen. Diese Typen
gehören also nach `libresign_client.py`, nicht in ein neues Modul.

@dataclass(frozen=True)
class Signer:
  email: str
  display_name: str
  signed_at: datetime | None

@dataclass(frozen=True)
class SignatureRequest:
  request_id: str
  file_name: str
  file_path: str  # WebDAV-Pfad relativ zu /remote.php/dav/files/{user}/
  created_at: datetime
  status: Literal["pending", "signed", "expired", "cancelled"]
  signers: list[Signer]

## Implementierungs-Stufen

### Stufe 1: Installation & Smoke-Test (kein Code)
Detailliertes Runbook: `docs/concepts/phase-94-stufe-1-runbook.md`
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
- Two-step confirmation über den eingebauten Mechanismus, NICHT manuell:
  Der Handler gibt `CommandResult(pending_confirmation=True, pending_data=...)`
  zurück; die Bridge legt daraus eine `PendingAction` im
  `PendingConfirmationStore` ab (Default-TTL 300 s, Bestätigung via
  "ja"/"ok"/"passt", Abbruch via "nein"/"abbrechen").
  1. "Bereite Vertrag X zur Signatur vor" → CommandResult mit
     pending_confirmation=True (Draft-Beschreibung im `description`).
  2. "ja"/"ok" → Bridge führt die hinterlegte Aktion aus.
- KEIN Auto-Signing ohne explizite Bestätigung.

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

Stufe 1: Manuell, dokumentiert im Bramble-Journal (project=elder-berry).
Stufe 2-3: pytest (Runner: `.\.venv\Scripts\python.exe -m pytest`).

- test_libresign_client.py: `unittest.mock` patcht
  `elder_berry.tools.libresign_client.httpx.Client` (analog
  `test_nextcloud_cookbook_client.py`). KEINE externe Mock-Lib
  (aiohttp/respx) – AGENTS.md verbietet das ohne Rückfrage.
- test_libresign_commands.py: Pattern-Match + Mock-Client; eigener Testfile
  pro neuer Klasse (AGENTS.md), nicht in bestehende Tests quetschen.
- Mindestens: Happy Path, Auth-/HTTP-Fehler (401/403/>=400), leere Liste.
- Integration-Test optional gegen lokale LibreSign-Instanz.

## Geklärte Fragen (Entscheidungen)

Die vier ursprünglich offenen Fragen sind anhand des bestehenden Codes
entschieden. Begründungen sind am Repo verifiziert, nicht angenommen.

1. **Authentifizierung → App-Password (Basic-Auth), keine OAuth.**
   Begründung: Cookbook-Client (Phase 93) und CalDAV-Client (Phase 56)
   nutzen bereits `nextcloud_url` / `nextcloud_user` / `nextcloud_app_password`
   aus dem `SecretStore` via `httpx`-Basic-Auth. LibreSign läuft auf derselben
   Nextcloud → dieselben Secrets wiederverwenden. KEINE neuen Auth-Keys, kein
   OAuth-Flow. (App-Password-Herkunft – NordPass o. Ä. – ist irrelevant.)
2. **WebDAV-Pfade → ja, relativ zu `/remote.php/dav/files/<user>/`.**
   Bestätigt durch `_webdav_base` im Cookbook-Client
   (`{url}/remote.php/dav/files/{user}/`). Hinweis: Die LibreSign-API selbst
   adressiert Dokumente i. d. R. über `fileId`, nicht über WebDAV-Pfade; der
   WebDAV-Pfad ist v. a. zum Hochlegen/Auffinden relevant.
3. **Signatur-Abschluss → Polling, kein Webhook (in Stufe 2/3).**
   Stufe 2 ist On-Demand-Statusabfrage ("was steht zur Signatur an?"); dafür
   genügt ein Poll beim `LibreSignClient`. Ein eingehender Webhook-Endpoint auf
   RPi5/Tower ist erst für die Automation in Stufe 4 nötig (YAGNI) und bleibt
   bis dahin out of scope.
4. **"Datei offen in LibreSign" beim Verschieben/Löschen → Guard in Stufe 3.**
   In Stufe 1/2 (read-only) nicht betroffen. Ab Stufe 3: vor move/delete einer
   Datei mit ausstehender Signatur den Status prüfen und warnen statt blind zu
   verschieben (würde sonst die offene Signatur-Anfrage verwaisen lassen).
   Konkrete Integration in `file_commands.py` erst dann entwerfen.

## Abhängigkeiten

- Phase 93 (Cookbook) abgeschlossen – `NextcloudCookbookClient` ist das
  nächste Vorbild (sync `httpx`, SecretStore-Auth, WebDAV).
- Nextcloud erreichbar (gegeben)
- Bestehender PendingConfirmationStore + `CommandResult.pending_confirmation`
  (gegeben)
- HTTP-Client-Pattern: CalDAVTaskClient (Phase 56, nutzt `caldav`-Lib) und
  NextcloudCookbookClient (Phase 93, nutzt `httpx`) – für LibreSign `httpx`.

## Definition of Done (gesamte Phase)

- [ ] LibreSign installiert und mit 3 Real-PDFs getestet
- [ ] LibreSignClient mit list + status implementiert
- [ ] LibreSignCommandHandler mit 2+ Patterns
- [ ] Tests grün
- [ ] Zwei-Schritt-Confirmation für sign_document
- [ ] Concept-Doc finalisiert, Bramble-Journal aktualisiert
      (project=elder-berry; `docs/journal.txt` ist nur historische
      Importquelle, dort KEINE neuen Einträge)
- [ ] PROJECT_ROADMAP.md aktualisiert
- [ ] Branch feature/phase-94-libresign-integration gemerged

## Plan B (falls Stufe 1 scheitert)

Wenn LibreSign installations- oder funktionsmäßig nicht
überzeugt:
- PDF24 Creator lokal auf Tower (kostenlos, Windows, kein Abo)
- PyMuPDF-basierter PdfCommandHandler in Elder-Berry für
  programmatische Aufgaben (Merge, Split, Watermark, simple
  Formularfelder ausfüllen via JSON-Mapping)
- Adobe Acrobat trotzdem deinstallieren
