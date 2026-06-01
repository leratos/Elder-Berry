# Phase 94 – Stufe 1: LibreSign Installation & Smoke-Test (Runbook)

**Dokument:** `docs/concepts/phase-94-stufe-1-runbook.md`
**Stand:** 2026-06-01 (Befehle real bestätigt: NC 33.0.4 + LibreSign 13.2.4,
Ubuntu/Plesk, PHP 8.3, OpenSSL-Engine).
**Scope:** Server-seitige Installation von LibreSign auf der Nextcloud-Instanz
und manueller Smoke-Test. **Kein Elder-Berry-Code, keine Saleria-Anbindung**
(Sicherheitsentscheidung, siehe Konzept-Doc).
**Konzept:** `docs/concepts/phase-94-libresign.md`

---

## 1. Ziel & Abgrenzung

Stufe 1 ist ein **Go/No-Go-Gate**, kein Implementierungsschritt:

- **Erfolgskriterium:** 3 reale Use-Case-PDFs werden erfolgreich ausgefüllt
  und signiert (Details Abschnitt 4–6).
- **Wenn das Gate scheitert** (Installation fummelig oder UX unzureichend):
  Phase abbrechen → Plan B (PDF24 lokal + PyMuPDF-Handler, siehe Konzept-Doc).
  Dann ist kein Elder-Berry-Code verloren.
- **Out of Scope (endgültig):** `LibreSignClient`, Command-Handler, Tests und
  jede Saleria-Anbindung. Bewusst gestrichen (Sicherheitsentscheidung im
  Konzept-Doc). LibreSign wird nur manuell im Browser genutzt.

> Die Befehle unten sind am 2026-06-01 auf NC 33.0.4 + LibreSign 13.2.4 real
> ausgeführt worden. Bei anderen Versionen vorher mit
> `occ libresign:install --help` und der Admin-UI (Einstellungen → Verwaltung →
> LibreSign) abgleichen.

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

### 3.2 Binär-Abhängigkeiten ziehen (real bestätigt)

Bei OpenSSL-Engine werden Java, JSignPdf und PDFtk gebraucht (kein CFSSL). Die
Admin-UI „Prüfung der Konfiguration" zeigt für jede fehlende Abhängigkeit den
passenden occ-Befehl als Tipp:

```bash
occ libresign:install --java
occ libresign:install --jsignpdf
occ libresign:install --pdftk
```

Jeder Befehl lädt sein Binary herunter und meldet „Finished with success."
(Java ist mit Abstand der größte Download.)

Optional, aber empfohlen (Signatur-Validierung + Seitenmaße – behebt die zwei
`info`-Punkte pdfsig/pdfinfo). System-Paket, **nicht** occ, als root:

```bash
apt-get install -y poppler-utils
```

> Wenn Outbound-Downloads scheitern (Egress-Filter): Binaries manuell aus den
> jeweiligen GitHub-Releases laden und in das von LibreSign erwartete
> App-Data-Verzeichnis legen. Pfad und erwartete Version aus der Fehlermeldung
> bzw. der Admin-UI entnehmen.

### 3.3 Zertifikats-Engine / Root-CA konfigurieren (real bestätigt)

**OpenSSL-Engine** gewählt (einfachster Weg, kein CFSSL-Daemon). Optionen:
`--cn`, `--o`, `--c`, `--st`, `--l`, `--ou`. Real ausgeführt (privates Solo-
Setup, CN = Klarname, O = Klarname, Land DE):

```bash
occ libresign:configure:openssl --cn "Vorname Nachname" --o "Vorname Nachname" --c "DE"
```

> Die Zertifikatsfelder (CN/O/C) erscheinen als Aussteller-Identität auf den
> signierten PDFs. Es ist eine FES, keine QES (Risiko #4 im Konzept-Doc).

### 3.4 Installation verifizieren

1. **Admin-UI:** Einstellungen → Verwaltung → LibreSign → „Prüfung der
   Konfiguration". Alle Punkte müssen `success` zeigen: Java, JSignPdf, PDFtk,
   pdfsig/pdfinfo, „Root certificate setup is working fine."
2. **Java-UTF-8-Hinweis beachten** – falls ein `info` „Non-UTF-8 encoding"
   erscheint, siehe Gotcha (3.5).
3. **Log prüfen:** beim Signieren auftretende Fehler über die `reqId` im
   `<datadir>/nextcloud.log` per `grep -F "<reqId>"` ziehen.

### 3.5 Real aufgetretene Stolpersteine & Workarounds (2026-06-01)

Diese Punkte traten bei der echten Installation auf NC 33.0.4 + LibreSign
13.2.4 auf. Alle sind lösbar, kosten aber Zeit (Risiko #1 „fummelig").

1. **Java meldet ASCII statt UTF-8** (Admin-UI `info`: „Non-UTF-8 encoding
   detected: ANSI_X3.4-1968"). Folge: Umlaute in PDFs/Stempel können
   verstümmeln. Fix = Locale für den **PHP-FPM-Pool** der Domain setzen. In
   Plesk → Domain → PHP-Einstellungen → „Zusätzliche Konfigurationsdirektiven";
   **`env[]` sind FPM-Pool-Direktiven** und brauchen die Trennlinie, sonst
   schlägt der Config-Test fehl (`unexpected ']'`):

   ```ini
   [php-fpm-pool-settings]
   env[LANG] = C.UTF-8
   env[LC_ALL] = C.UTF-8
   ```

2. **Gezeichnete Signatur scheitert:** `no decode delegate for image format
   'SVG'`. LibreSign speichert Draw-Signaturen als SVG; die ImageMagick der
   PHP-`imagick`-Extension hat keinen SVG-Coder. `librsvg2-bin` reicht **nicht**
   (nur CLI). Nötig ist das `-extra`-Paket der Library, danach FPM-Restart:

   ```bash
   apt-get install -y libmagickcore-6.q16-6-extra   # ggf. q16hdri-Variante
   systemctl restart plesk-php83-fpm_<domain>_<id>.service
   /opt/plesk/php/8.3/bin/php -r 'var_dump((new Imagick())->queryFormats("SVG"));'
   ```

   Alternativ ohne Fix: **Text-** oder **Upload-(PNG)-Signatur** statt Draw.

3. **`getAppValueString() on null` beim Signieren** – Bug der `notifications`-
   App (Push-Pfad) auf NC 33, nicht von LibreSign. Signatur wird trotzdem
   erzeugt, aber die UI zeigt 500. Workaround: `occ app:disable notifications`
   (reversibel; Preis: keine Benachrichtigungs-Glocke).

4. **`extractTimestampData(): null given`** beim Signieren – tritt bei
   **bereits/teilsignierten** PDFs auf (LibreSign liest die vorhandene Signatur
   und stolpert). Immer mit einer **frischen, nie signierten Kopie** arbeiten.

5. **Mailserver-Zertifikat abgelaufen** (separat entdeckt): Nextcloud konnte
   keine Mails senden (`certificate verify failed`). Ursache war ein
   abgelaufenes Mail-Zert; in Plesk dem Mail-Dienst das gültige Domain-Zert
   zuweisen. Betrifft die gesamte Mail, nicht nur LibreSign.

6. **`open_basedir`-Warnungen** auf einen Zertifikats-DN
   (`file_exists(/C=DE/O=…)`) in `OrderCertificatesTrait.php` – **harmloses
   Rauschen** (LibreSign prüft einen DN-String wie einen Pfad), kein Fehler.

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

**Go (→ LibreSign manuell produktiv nutzen), wenn:**

- Mind. die realistischen PDF-Typen lassen sich vollständig ausfüllen **und**
  sichtbar signieren (Matrix möglichst komplett ☑).
- Der manuelle Aufwand für gescannte PDFs (ohne AcroForm) ist im Alltag
  tragbar.
- Keine blockierenden Installations-/Stabilitätsprobleme offen (Stolpersteine
  aus 3.5 sind gefixt/umschifft).

**No-Go (→ Plan B), wenn:**

- Installation/Stabilität nicht robust hinzubekommen ist, **oder**
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

## 9. Stand der Verifikationspunkte

Erledigt (2026-06-01):

- [x] Version/Kompatibilität: NC 33.0.4 + LibreSign 13.2.4.
- [x] occ-Flags real bestätigt (`--java`, `--jsignpdf`, `--pdftk`,
      `configure:openssl`).
- [x] Engine: OpenSSL gewählt.
- [x] Outbound-Download funktionierte.
- [x] occ-Wrapper: Webroot + Web-User (lokaler vHost-User) bestätigt.

Noch offen:

- [ ] Finale Gate-Bestätigung: mind. 1 reales PDF manuell **sichtbar** signiert
      (frische Kopie, kein re-sign).
- [ ] Stolperstein 5 (Mail-Zert) im Plesk gefixt.
- [ ] Entscheidung, ob `notifications` (Stolperstein 3) dauerhaft aus bleibt.
