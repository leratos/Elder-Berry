# Phase 94: LibreSign Integration

## Status & Scope (Stand 2026-06-01)

- **Scope: reine serverseitige Installation + manuelle Nutzung** über die
  Nextcloud-Weboberfläche. **Kein Elder-Berry-Code, keine Saleria-Anbindung.**
- LibreSign ist serverseitig installiert und konfiguriert (OpenSSL-Root-Cert,
  Signatur-Engine JSignPdf). Installationsdetails + Stolpersteine:
  `docs/concepts/phase-94-stufe-1-runbook.md`.
- **Gate grün (2026-06-01):** manuelles, sichtbares Signieren eines frischen
  PDFs funktioniert end-to-end (Signaturfeld + QR-Validierungslink). LibreSign
  ist für den manuellen Browser-Workflow nutzbar.
- Rest: `notifications`-App bleibt deaktiviert (Workaround, siehe „Offene
  Punkte"); Rest-Admin (Roadmap, Merge) bei Lera.

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

## Komponenten-Übersicht

### Server-Seite (Nextcloud, z. B. cloud.example.com)

- Nextcloud-App LibreSign installiert
- Dependencies: Java, JSignPdf, PDFtk (+ Poppler für Signatur-Validierung)
- Zertifikats-Engine: OpenSSL (selbst verwaltete Root-CA)
- Konfiguration via occ (Plesk-PHP-Pfad beachten:
  `/opt/plesk/php/8.3/bin/php -d memory_limit=512M occ libresign:...`)

### Elder-Berry-Seite

Keine. Bewusste Entscheidung – siehe nächster Abschnitt.

## Sicherheitsentscheidung: keine Saleria-/Elder-Berry-Anbindung

Lera-Entscheidung 2026-06-01: **Es wird kein Elder-Berry-Code für LibreSign
gebaut** – weder Signatur-Trigger noch Read-Only-Status-Abfrage.

Begründung (sicherheitskritisch):

- Signieren ist unwiderruflich und rechtlich bindend (auch als FES). Es über
  einen Chat-/Voice-Agenten exponierbar zu machen, ist ein schlechtes
  Risiko/Nutzen-Verhältnis.
- Die ursprünglich geplante „Zwei-Schritt-Bestätigung" liefe über **denselben
  Matrix-Kanal**, über den Saleria gesteuert wird. Wer Saleria kompromittiert,
  kontrolliert auch die Bestätigung – **kein echter zweiter Faktor**.
- Der praktische Mehrwert einer Sprach-/Chat-gesteuerten Signatur ist gering;
  Signieren ist inhärent interaktiv (PDF prüfen, Stelle wählen).

Konsequenz: LibreSign wird ausschließlich **manuell** im Browser benutzt. Damit
entfallen `LibreSignClient`, Command-Handler, Pydantic/Dataclass-Domänentypen
und die zugehörigen Tests vollständig.

## Installation & manuelle Nutzung

Vollständige Anleitung inkl. occ-Befehlen, PDF-Testset, Bewertungs-Gate und den
heute aufgetretenen Stolpersteinen: **`docs/concepts/phase-94-stufe-1-runbook.md`**.

Kurz-Workflow (manuell im Browser):

1. PDF in Nextcloud ablegen.
2. Über Dateien → LibreSign die Datei öffnen, sich selbst als Unterzeichner
   hinzufügen.
3. **Sichtbares Signaturfeld platzieren** (sonst nur unsichtbare,
   kryptografische Signatur), bei AcroForm-PDFs direkt das vorhandene
   Unterschriftsfeld anklicken.
4. Signieren → Zertifikats-Passwort → signiertes PDF (mit QR-Validierungslink)
   herunterladen.

Signatur-Methode: **Text** oder **hochgeladenes Bild (PNG)** sind am
robustesten; gezeichnete Signaturen funktionieren nur mit dem
ImageMagick-SVG-Decoder (siehe Runbook, Gotcha „SVG").

## Bekannte Risiken

1. **Dependency-Installation fummelig.**
   LibreSign braucht Java + JSignPdf + PDFtk; der Web-Installer ist
   unvollständig, occ-Weg ist robuster. Bestätigt: mehrere Server-Stolpersteine
   nötig (UTF-8-Locale, ImageMagick-SVG-Decoder, notifications-App-Bug). Alle
   im Runbook dokumentiert.

2. **Form-Filling-Limits bei gescannten PDFs.**
   Behörden-PDFs ohne AcroForm-Felder erfordern manuelles Setzen von
   Eingabezonen; LibreSign neigt dort dazu, die ganze Seite zu markieren.
   Mitigation: Lokales Tool (PDF24) als Fallback behalten.

3. **API-/App-Stabilität.**
   LibreSign ist jünger als Core-Nextcloud-Apps. Auf NC 33 + LibreSign 13.2.4
   traten mehrere Laufzeitfehler auf (Notification-Push, Timestamp-Decode bei
   re-signierten Dateien). Da keine Elder-Berry-Anbindung existiert, ist die
   Blast-Radius klein; manuelle Nutzung bleibt möglich.

4. **Rechtliche Verbindlichkeit.**
   LibreSign-Signaturen sind „fortgeschrittene elektronische Signaturen" (FES),
   nicht „qualifizierte" (QES) nach eIDAS. In den Signatur-Einstellungen unter
   „Rechtliche Informationen" entsprechend kennzeichnen; für notarielle Sachen
   nicht verwenden.

## Out of Scope

- **Jegliche Saleria-/Elder-Berry-Anbindung** (Signieren UND Status-Abfrage) –
  bewusst gestrichen, siehe Sicherheitsentscheidung.
- Multi-Party-Workflows (mehrere Unterzeichner) – solo-Nutzung.
- Workflow-Automation (Mail-Anhang → Queue, Webhook-Empfang).
- QES-Integration (D-Trust etc.).
- DocuSign-/Documenso-Parallelbetrieb.
- Mobile-App-Anbindung – Browser reicht.

## Definition of Done (gesamte Phase)

- [x] LibreSign serverseitig installiert (Java, JSignPdf, PDFtk, Poppler,
      OpenSSL-Root-Cert) – Konfigurations-Prüfung grün.
- [x] Sicherheitsentscheidung dokumentiert: keine Saleria-Anbindung.
- [x] Mind. 1 reales PDF manuell **sichtbar** signiert (Gate-Bestätigung,
      2026-06-01).
- [x] Stufe-1-Runbook mit realen Befehlen + Gotchas finalisiert.
- [x] Bramble-Journal aktualisiert (project=elder-berry; `docs/journal.txt` ist
      nur historische Importquelle, dort KEINE neuen Einträge).
- [ ] PROJECT_ROADMAP.md aktualisiert.
- [ ] Branch feature/phase-94-libresign-integration gemerged.

## Offene Punkte (operativ, server-seitig)

- **`notifications`-App deaktiviert** als Workaround für einen NC-33-Bug
  (`getAppValueString() on null` im Push-Pfad). Folge: keine Nextcloud-
  Benachrichtigungs-Glocke. Wieder aktivieren, sobald ein Upstream-Fix vorliegt.
- ~~Mailserver-Zertifikat abgelaufen~~ **erledigt (2026-06-01):** in Plesk dem
  Mail-/Webmail-Dienst das gültige Domain-Zertifikat zugewiesen. **Learning:**
  Eine Zert-Aktualisierung auf Haupt-Domain-Ebene kaskadiert **nicht**
  automatisch auf die Mail-/Webmail-Ebene — die muss separat ausgewählt werden.

## Plan B (falls die manuelle UX nicht überzeugt)

Wenn LibreSign funktionsmäßig nicht trägt:

- PDF24 Creator lokal auf Tower (kostenlos, Windows, kein Abo).
- PyMuPDF-basierter `PdfCommandHandler` in Elder-Berry für programmatische
  Aufgaben (Merge, Split, Watermark, simple Formularfelder ausfüllen via
  JSON-Mapping).
- Adobe Acrobat in beiden Fällen deinstallieren.
