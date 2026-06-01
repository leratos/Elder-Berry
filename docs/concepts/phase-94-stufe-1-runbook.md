# Phase 94 – Stufe 1: LibreSign Installation & Smoke-Test (Runbook)

**Dokument:** `docs/concepts/phase-94-stufe-1-runbook.md`
**Stand:** 2026-05-30
**Scope:** Server-seitige Installation von LibreSign auf der Nextcloud-Instanz
und manueller Smoke-Test mit 3 realen PDFs. **Kein Elder-Berry-Code.**
**Konzept:** `docs/concepts/phase-94-libresign.md`

---

## 1. Ziel & Abgrenzung

Stufe 1 ist ein **Go/No-Go-Gate**, kein Implementierungsschritt:

- **Erfolgskriterium:** 3 reale Use-Case-PDFs werden erfolgreich ausgefüllt
  und signiert (Details Abschnitt 4–6).
- **Wenn das Gate scheitert** (Installation fummelig oder UX unzureichend):
  Phase abbrechen → Plan B (PDF24 lokal + PyMuPDF-Handler, siehe Konzept-Doc).
  Dann ist kein Elder-Berry-Code verloren.
- **Out of Scope hier:** `LibreSignClient`, Command-Handler, Tests – das ist
  erst Stufe 2 und nur sinnvoll, wenn dieses Gate grün ist.

> Hinweis vorab: Exakte `occ libresign:*`-Subkommandos und Flags variieren je
> LibreSign-Version. Befehle unten, die als **[verifizieren]** markiert sind,
> vor Ausführung gegen `occ libresign:install --help` und die Admin-UI
> (Einstellungen → Verwaltung → LibreSign) abgleichen, statt sie blind zu
> übernehmen.

---

## 2. Voraussetzungen prüfen (vor der Installation)

| Punkt | Prüfung | Warum |
|-------|---------|-------|
| Nextcloud-Version | Admin → Übersicht | LibreSign-Kompatibilität ist versionsabhängig (App-Store-Eintrag prüfen). |
| Plesk-PHP-Pfad | `/opt/plesk/php/8.3/bin/php -v` | occ läuft nicht über System-PHP, sondern den Plesk-PHP-Binary. |
| Nextcloud-Webroot | Pfad des vHosts notieren | occ muss aus dem Webroot laufen (siehe 2.1). |
| Web-User | vHost-Systemuser in Plesk | occ als falscher User → Dateirechte-Chaos. |
| App Store erreichbar | Admin → Apps lädt Liste | Sonst App + Binaries manuell installieren. |
| Outbound-Internet | Server darf GitHub-Releases ziehen | `libresign:install` lädt Java/JSignPdf/CFSSL herunter. Plesk-Server haben teils Egress-Filter → ggf. manueller Download. |
| Freier Speicher | `df -h` | Java + JSignPdf + CFSSL = mehrere zehn MB im App-Data-Verzeichnis. |
| `memory_limit` | für occ via `-d memory_limit=512M` | Signier-/Form-Operationen sind speicherhungrig. |

### 2.1 occ-Aufruf-Konvention (Plesk)

occ immer (a) aus dem Nextcloud-Webroot, (b) mit Plesk-PHP, (c) als Web-User,
(d) mit erhöhtem `memory_limit` aufrufen. Schema:

```bash
cd /var/www/vhosts/example.com/cloud.example.com   # echten Webroot einsetzen
sudo -u <plesk-web-user> /opt/plesk/php/8.3/bin/php -d memory_limit=512M \
  occ <befehl>
```

Im Folgenden wird das zu `occ <befehl>` abgekürzt – der volle Wrapper ist immer
gemeint.

---

## 3. Installation

### 3.1 App installieren

Bevorzugt über die UI: **Admin → Apps → Suche „LibreSign" → Herunterladen und
aktivieren.** Alternativ per CLI:

```bash
occ app:install libresign
occ app:enable libresign
```

### 3.2 Binär-Abhängigkeiten ziehen **[verifizieren]**

LibreSign braucht Java, JSignPdf und (je nach Zertifikats-Engine) CFSSL. Die
Subkommandos zuerst auflisten:

```bash
occ libresign:install --help
```

Übliche Form (Flags gegen `--help` der installierten Version abgleichen):

```bash
occ libresign:install --java
occ libresign:install --jsignpdf
occ libresign:install --cfssl     # nur bei CFSSL-Engine, siehe 3.3
# oder gebündelt:
occ libresign:install --all
```

> Wenn Outbound-Downloads scheitern (Egress-Filter): Binaries manuell aus den
> jeweiligen GitHub-Releases laden und in das von LibreSign erwartete
> App-Data-Verzeichnis legen. Pfad und erwartete Version aus der Fehlermeldung
> bzw. der Admin-UI entnehmen.

### 3.3 Zertifikats-Engine / Root-CA konfigurieren **[verifizieren]**

LibreSign signiert mit einem selbst verwalteten Zertifikat. Für eine
Single-User-Selfhost-Instanz ist die **OpenSSL-Engine** der einfachere Weg
(kein zusätzlicher CFSSL-Daemon):

```bash
occ libresign:configure:openssl --help        # Optionen prüfen
occ libresign:configure:openssl --cn "Beispiel Name"   # Felder anpassen
```

CFSSL-Engine nur wählen, wenn bewusst gewünscht; dann `--cfssl` in 3.2 nötig
und die CFSSL-spezifische Konfiguration fahren.

> Entscheidung dokumentieren: OpenSSL vs CFSSL, und mit welchen
> Zertifikatsfeldern (CN/O/OU/C) – das landet später in Risiko #5 (FES, nicht
> QES).

### 3.4 Installation verifizieren

1. **Admin-UI:** Einstellungen → Verwaltung → LibreSign. Alle
   Abhängigkeiten müssen grün/„installiert" sein (Java, JSignPdf, Root-Cert).
2. **CLI-Gegencheck [verifizieren]:** ein Status-/Check-Kommando aus
   `occ libresign:` (z. B. `occ libresign:install --all` erneut → meldet
   „bereits installiert", oder ein dediziertes Check-Kommando der Version).
3. **Log prüfen:** `occ log:tail` bzw. `data/nextcloud.log` auf LibreSign-Fehler.

---

## 4. PDF-Testset (3 reale Use-Cases)

Das Testset deckt absichtlich die drei realistischen Schwierigkeitsgrade ab.
Echte Dokumente verwenden (ggf. mit Dummy-Daten), keine künstlichen Beispiele:

| # | Typ | Beispiel | Schwierigkeit |
|---|-----|----------|---------------|
| 1 | Gescanntes Behördenformular **ohne** AcroForm | Antrag/Formular vom Amt, eingescannt | Hoch – Felder müssen manuell als Eingabezonen gesetzt werden |
| 2 | Vertrag **mit** AcroForm-Feldern | PDF mit echten Formularfeldern | Mittel – Felder sollten erkannt werden |
| 3 | Einfaches Textdokument | Anschreiben/Brief, nur Unterschrift nötig | Niedrig – nur Signatur platzieren |

Dateien vor dem Test an einen definierten Nextcloud-Ort legen, z. B.
`/Dokumente/_libresign-test/` (über WebDAV oder Web-UI), damit der Smoke-Test
reproduzierbar ist.

---

## 5. Smoke-Test-Durchführung

Pro Test-PDF (1–3) im LibreSign-Web-UI durchführen und je Schritt
Pass/Fail festhalten:

1. **Öffnen/Hochladen:** PDF in LibreSign laden.
2. **Felder ausfüllen:** Text/Datum/Name setzen.
   - Bei #1 (ohne AcroForm): Eingabezonen manuell setzen – hier zeigt sich, ob
     der Aufwand tragbar ist (Risiko #2).
3. **Signatur platzieren:** Unterschrift/Signaturfeld setzen und signieren.
4. **Export/Download:** signiertes PDF herunterladen.
5. **Verifikation:** signiertes PDF öffnen (Browser/Reader) – Inhalt + sichtbare
   Signatur korrekt? Optional Signatur-Eigenschaften prüfen.

### 5.1 Ergebnis-Matrix (ausfüllen)

| Test-PDF | Ausfüllen | Signieren | Export | Verifikation | UX-Eindruck (1–5) |
|----------|-----------|-----------|--------|--------------|-------------------|
| 1 Behörde (Scan) | ☐ | ☐ | ☐ | ☐ |  |
| 2 Vertrag (AcroForm) | ☐ | ☐ | ☐ | ☐ |  |
| 3 Textdokument | ☐ | ☐ | ☐ | ☐ |  |

---

## 6. Bewertung & Gate-Entscheidung

**Go (→ Stufe 2 freigeben), wenn:**

- Alle 3 PDFs vollständig ausgefüllt **und** signiert (Matrix komplett ☑).
- Der manuelle Aufwand für #1 (Scan ohne AcroForm) ist im Alltag tragbar.
- Keine blockierenden Installations-/Stabilitätsprobleme offen.

**No-Go (→ Plan B), wenn:**

- Installation der Binär-Abhängigkeiten nicht robust hinzubekommen ist, **oder**
- die Form-Filling-UX (v. a. gescannte PDFs) zu mühsam für den realen Workflow.

Plan B (aus Konzept-Doc): PDF24 lokal auf Tower + PyMuPDF-basierter
`PdfCommandHandler` in Elder-Berry. Adobe Acrobat in **beiden** Fällen
deinstallieren.

---

## 7. Sicherheits- & Betriebshinweise

- **FES, nicht QES:** LibreSign liefert „fortgeschrittene" elektronische
  Signaturen, keine „qualifizierten" nach eIDAS. Für notarielle/qualifiziert
  formbedürftige Vorgänge nicht verwenden (Konzept-Doc Risiko #5).
- **Bestehende Apps nicht stören:** Installation auf einer produktiven
  Nextcloud – `occ` als korrekter Web-User, vor größeren Schritten Snapshot/
  Backup der NC-Daten + `config.php` erwägen.
- **Egress:** Wenn `libresign:install` ins offene Internet lädt, ist das ein
  bewusster Outbound-Vorgang auf dem Server – mit der Plesk-/Firewall-Policy
  abgleichen.
- **Root-CA-Material:** Das von LibreSign erzeugte Zertifikat/Schlüsselmaterial
  ist sensibel; nicht ins Repo, nicht in Logs.
- **Keine Secrets in Doc/Journal:** Hostnamen in committeten Docs sanitisiert
  halten (`cloud.example.com`), echte Werte nur in der Server-Umgebung.

---

## 8. Ergebnis dokumentieren

Nach Abschluss einen **Bramble-Journal**-Eintrag schreiben
(`project=elder-berry`) – **nicht** in `docs/journal.txt` (nur historische
Importquelle). Inhalt:

- Status: `abgeschlossen` (Gate grün) oder `notiz` (Gate-Entscheidung No-Go).
- LibreSign-Version + gewählte Engine (OpenSSL/CFSSL).
- Ergebnis-Matrix aus Abschnitt 5.1 (3 PDFs).
- Go/No-Go-Entscheidung + Begründung.
- Bei No-Go: Verweis auf Plan-B-Umsetzung.

---

## 9. Offene Verifikationspunkte (vor Ausführung klären)

- [ ] LibreSign-Version + Nextcloud-Kompatibilität (App-Store-Eintrag).
- [ ] Exakte `occ libresign:install`-Flags der Version (`--help`).
- [ ] Engine-Wahl: OpenSSL (empfohlen) vs CFSSL.
- [ ] Outbound-Download erlaubt? Sonst manueller Binary-Bezug.
- [ ] Korrekter Web-User + Webroot-Pfad für occ unter Plesk.
- [ ] Snapshot/Backup vor Installation auf produktiver NC.
