# Benutzung

Saleria wird primär über **Element** (Matrix-Client) bedient. Einfach eine Nachricht
in den konfigurierten Raum tippen. Direkte Commands werden sofort ausgeführt,
alles andere geht ans LLM (Saleria antwortet mit Persönlichkeit).

Tipp: `hilfe` zeigt alle verfügbaren Commands direkt in Element an.

## Basis-Commands

| Command | Beschreibung |
|---|---|
| `status` / `systemstatus` | CPU, RAM, GPU, Disk, Top-Prozesse |
| `screenshot` / `screen` | Screenshot als Bild senden |
| `hilfe` / `help` | Alle Commands anzeigen |

## Medien-Steuerung

| Command | Beschreibung |
|---|---|
| `pause` / `play` | Musik pausieren/fortsetzen |
| `skip` / `next` | Nächster Track |
| `prev` / `previous` | Vorheriger Track |
| `volume <0-100>` | Lautstärke setzen |

## Avatar

| Command | Beschreibung |
|---|---|
| `selfie` / `avatar` | Bild von Saleria senden |
| `selfie <emotion>` | Mit Emotion (angry, cheerful, sad, ...) |

## Kalender (Nextcloud CalDAV / Google Calendar Fallback)

| Command | Beschreibung |
|---|---|
| `termine` | Termine heute |
| `termine morgen` | Termine morgen |
| `termine woche` | Nächste 7 Tage |
| `termine monat` | Bis Monatsende |
| `termin suche <Begriff>` | Termin suchen (nächste 90 Tage) |
| `termin: Titel morgen 14:00` | Termin erstellen |
| `erstelle termin Zahnarzt 30.03 10:00` | Natürliche Sprache |
| `lösche termin <Titel/ID>` | Termin löschen |
| `lösche den 2. termin` | Per Index aus letztem Ergebnis |
| `lösche alle termine` | Alle aus letztem Ergebnis |

## E-Mail (IMAP/SMTP)

| Command | Beschreibung |
|---|---|
| `mails` | Ungelesene E-Mails |
| `mails 5` | Letzte 5 Tage |
| `mail suche <Begriff>` | Nach Betreff/Absender suchen |
| `mail <ID>` / `mail #<ID>` | Mail anzeigen |
| `mail anhang <ID>` | Anhänge senden |
| `mail zusammenfassung` | LLM-Zusammenfassung ungelesener Mails |
| `antworte auf #<ID> <Anweisung>` | Antwort-Entwurf generieren |
| `lösche mail #<ID>` | Mail löschen |
| `lösche die mail` | Zuletzt abgerufene Mail löschen |

### E-Mail-Antwort-Workflow (Phase 28)

1. `antworte auf #4523 positiv, bedanke dich` — Saleria zeigt einen Entwurf
2. `ja` — Saleria sendet die Antwort
3. `nein, förmlicher` — Saleria überarbeitet den Entwurf (zurück zu Schritt 1)

Wenn ein Kontakt zum Absender existiert (Phase 29), wird dessen Kontext
(Name, Rolle, bevorzugte Anrede) automatisch im Entwurf berücksichtigt.

## Kontaktbuch (Phase 29 + 38)

| Command | Beschreibung |
|---|---|
| `kontakt: Name, Rolle, Email, Anrede` | Kontakt anlegen |
| `wer ist <Name>?` | Kontakt abrufen (kein Treffer → LLM beantwortet) |
| `kontakte` | Alle Kontakte anzeigen |
| `kontakte suche <Begriff>` | Volltextsuche |
| `kontakt ändern #<ID>: feld=wert` | Kontakt bearbeiten |
| `kontakt löschen #<ID>` | Kontakt löschen |
| `kontakte sync` | Nextcloud CardDAV Sync (bidirektional) |
| `kontakte sync pull` | Nur Nextcloud → lokal |
| `kontakte sync push` | Nur lokal → Nextcloud |
| `kontakte sync reset` | Alles löschen + frischer Pull |
| `wann hat <Name> Geburtstag?` | Geburtstag abfragen |
| `was ist die Adresse von <Name>?` | Adresse abfragen |
| `wie ist die Nummer von <Name>?` | Telefonnummer abfragen |
| `wo arbeitet <Name>?` | Arbeitgeber abfragen |
| `kontakte gruppe <Name>` | Kontakte einer Gruppe anzeigen |

Beispiel: `kontakt: Herr Müller, Vermieter, info@mueller.de, förmlich`

Felder werden automatisch erkannt: `@` → E-Mail, Ziffern → Telefon,
"förmlich"/"locker" → Anrede, erstes unbekanntes Feld → Rolle, weitere → Notizen.

Alle Nextcloud-vCard-Felder werden gesynct: Name, mehrere Emails/Telefonnummern,
Adresse, Organisation, Titel, Gruppen (CATEGORIES), Spitzname, Geburtstag, Jahrestag, Website.
Geburtstage und Jahrestage erscheinen automatisch im täglichen Briefing.

## Aufgabenliste (Phase 30)

| Command | Beschreibung |
|---|---|
| `todo: <text>` | Aufgabe anlegen |
| `todo: <text>, hoch, Arbeit` | Mit Priorität + Kategorie |
| `todos` / `aufgaben` | Offene Aufgaben anzeigen |
| `todos hoch` | Nach Priorität filtern (hoch/mittel/niedrig) |
| `todos Arbeit` | Nach Kategorie filtern |
| `todo erledigt #<ID>` | Aufgabe abhaken |
| `todo wieder öffnen #<ID>` | Aufgabe wieder öffnen |
| `todo priorität #<ID> hoch` | Priorität ändern |
| `todo löschen #<ID>` | Aufgabe löschen |
| `todos erledigt` | Erledigte anzeigen |
| `todos aufräumen` | Alle erledigten löschen |

Offene Todos erscheinen automatisch im täglichen Briefing.

## Notizen & Wissensdatenbank (Phase 16)

| Command | Beschreibung |
|---|---|
| `merk dir: <schlüssel> ist <wert>` | Fakt speichern |
| `notiz: <text>` | Freitext-Notiz |
| `was ist <schlüssel>?` | Fakt abrufen |
| `notizen suche <Begriff>` | Volltextsuche |
| `notizen` | Alle Notizen (max 20) |
| `notiz löschen #<ID>` | Notiz löschen |
| `vergiss <schlüssel>` | KV-Fakt vergessen |

## Wetter (Open-Meteo)

| Command | Beschreibung |
|---|---|
| `wetter` | Aktuelles Wetter |
| `wetter morgen` | Prognose morgen |
| `wetter woche` | 7-Tage-Prognose |
| `wetter 3` | Prognose für 3 Tage |

## Timer & Erinnerungen

| Command | Beschreibung |
|---|---|
| `timer 20 min` | Timer auf 20 Minuten |
| `timer 1 stunde` | Timer auf 1 Stunde |
| `erinnere mich um 18:00: Wäsche` | Erinnerung zu Uhrzeit |
| `erinnere mich in 2 stunden: Kuchen` | Erinnerung nach Zeitspanne |
| `erinnerungen` | Offene Erinnerungen anzeigen |
| `lösche erinnerung 3` | Erinnerung #3 löschen |

### Wiederkehrende Erinnerungen (Phase 19)

| Command | Beschreibung |
|---|---|
| `erinnere mich jeden montag um 9:00: Wochenbericht` | Wöchentlich |
| `erinnere mich täglich um 8:00: Standup` | Täglich |
| `erinnere mich werktags um 7:30: Aufstehen` | Mo–Fr |
| `erinnere mich jeden 1. um 10:00: Miete` | Monatlich |

## Briefing

| Command | Beschreibung |
|---|---|
| `briefing` | Tagesübersicht (Wetter + Termine + Erinnerungen + Todos) |

Wird auch automatisch um 07:30 gesendet. Keywords wie "guten morgen" lösen es ebenfalls aus.

Enthält: Wetter, Termine, Geburtstage (heute/morgen/diese Woche), Jahrestage,
Erinnerungen, offene Todos, ungelesene E-Mails, "Vor einem Jahr"-Notizen.
Kontakte werden vor jedem Briefing automatisch von Nextcloud gesynct.

## Fitness (Berry-Gym)

| Command | Beschreibung |
|---|---|
| `training` | Zusammenfassung (letztes Training, Woche, Gewicht) |
| `training details` | Letztes Training mit allen Sätzen |
| `training woche` | Trainings der letzten 7 Tage |
| `prs` | Personal Records (letzte 30 Tage) |

## Web-Suche & Web-Zusammenfassung (Brave Search)

| Command | Beschreibung |
|---|---|
| `suche <Begriff>` | Im Internet suchen |
| `such mal <Begriff>` | Alias |
| `google <Begriff>` | Alias |
| `fasse <URL> zusammen` | Webseite zusammenfassen (LLM-aufbereitet) |
| `zusammenfassung von <URL>` | Alias |

## Dateien & Clipboard

| Command | Beschreibung |
|---|---|
| `clipboard` | Zwischenablage lesen |
| `clip: <text>` | Text in Zwischenablage schreiben |
| `schick mir <pfad>` | Datei senden (max 50 MB) |
| `download <url>` | Datei herunterladen |
| `zusammenfassung <pfad>` | PDF/TXT via LLM zusammenfassen |

Dateien werden automatisch auf Nextcloud hochgeladen und als Share-Link geteilt
(Fallback: direkter Matrix-Upload wenn NC nicht verfügbar).

## Nextcloud Cloud (Phase 36 + 39)

| Command | Beschreibung |
|---|---|
| `cloud upload <pfad> [ziel]` | Datei zu Nextcloud hochladen |
| `cloud download <pfad>` | Datei aus Nextcloud herunterladen |
| `cloud dateien [ordner]` | Nextcloud-Verzeichnis auflisten |
| `cloud suche <query>` | Dateien suchen (Dateiname) |
| `cloud inhalt <query>` | Dateiinhalte durchsuchen (Volltextsuche) |
| `cloud link <pfad>` | Öffentlichen Share-Link erstellen |
| `richte nextcloud ein` | Standard-Dateien löschen + Ordnerstruktur anlegen |

Varianten für Setup: "nextcloud setup", "nextcloud-setup", "cloud einrichten".
Der Befehl zeigt erst eine Vorschau (was gelöscht/erstellt wird) und wartet auf
Bestätigung ("ja"/"nein") bevor Änderungen vorgenommen werden.

### Dokument-Ablage

| Command | Beschreibung |
|---|---|
| `cloud aufräumen` | Dateien im Eingang klassifizieren und ablegen |
| `anhang ablegen #<ID>` | PDF-Anhänge aus Mail klassifizieren und ablegen |

### PDF-Verarbeitung (Stirling-PDF)

| Command | Beschreibung |
|---|---|
| `pdf zusammenfügen <a.pdf> <b.pdf>` | PDFs zusammenfügen |
| `pdf aufteilen <datei> seiten 1-3` | Seiten extrahieren |
| `pdf komprimieren <datei> [stufe 1-9]` | Dateigröße reduzieren |
| `pdf ocr <datei>` | Text erkennen (Deutsch + Englisch) |
| `pdf zu word <datei>` | PDF → Word konvertieren |
| `zu pdf <datei>` | Word/Bild → PDF konvertieren |
| `pdf bilder <datei>` | Bilder aus PDF extrahieren |

## Prozesse & System

| Command | Beschreibung |
|---|---|
| `starte <programm>` | Programm starten (Whitelist) |
| `kill <prozess>` | Prozess beenden (Whitelist) |
| `wol` | Wake-on-LAN (Tower aufwecken) |
| `restart` | Bot neu starten |
| `git status` / `git pull` / `git log` | Git-Commands |
| `docker ps` / `docker restart <name>` | Docker-Commands |

## Self-Update (Phase 15)

| Command | Beschreibung |
|---|---|
| `update` / `update dich` | Git Pull + Dependencies + Neustart (Tower) |
| `update tower` | Tower-PC aktualisieren |
| `update rpi` | RPi5 aktualisieren |
| `update alles` | Server + Tower + RPi5 nacheinander |
| `rollback` | Auf Stand vor letztem Update zurücksetzen |

## Routenplanung (Phase 43)

| Command | Beschreibung |
|---|---|
| `plane fahrt zu <Name>` | Route von Zuhause zu Kontakt |
| `fahrt von <Name> zu <Name>` | Route zwischen zwei Kontakten |
| `wie komme ich zu <Name>` | Route von Zuhause |

Optional: `"morgen um 16 uhr"`, `"übermorgen 10 uhr"` → Abfahrtszeit berechnen

## Computer Use (Phase 13)

| Command | Beschreibung |
|---|---|
| `klick auf <Element>` | Vision-basierter Klick auf Bildschirmelement |
| `tippe <Text>` | Text tippen |
| `scroll runter/hoch` | Scrollen |
| `drück <Taste>` | Taste/Kombination drücken (z.B. `drück Strg+S`) |

## Kamera (Phase 26)

| Command | Beschreibung |
|---|---|
| `foto` / `kamera` | Foto aufnehmen und senden |
| `was siehst du [kontext]` | Kamerabild + KI-Beschreibung |

## Smart Home – Harmony Hub (Phase 37)

| Command | Beschreibung |
|---|---|
| `<aktivität> an` | Aktivität starten (z.B. `fernsehen an`, `musik an`) |
| `alles aus` / `harmony aus` | Alle Geräte ausschalten |
| `lauter` / `mach lauter` | Lautstärke erhöhen (Receiver) |
| `leiser` / `mach leiser` | Lautstärke senken (Receiver) |
| `stummschalten` / `stumm` | Receiver stummschalten |
| `was läuft` / `harmony status` | Aktuelle Aktivität anzeigen |
| `harmony aktivitäten` | Alle konfigurierten Aktivitäten auflisten |
| `harmony geräte` | Alle Geräte im Hub auflisten |
| `harmony befehle <gerät>` | Verfügbare Befehle für ein Gerät |
| `starte szene <name>` / `szene <name>` | Harmony-Szene starten |
| `szenen` / `szenen liste` | Alle Szenen auflisten |

## Drehteller (Phase 27)

| Command | Beschreibung |
|---|---|
| `drehteller home` | Home-Position anfahren |
| `dreh dich um <grad>` | Relativ drehen |
| `dreh dich nach links/rechts` | 90° in Richtung |
| `dreh dich auf <grad>` | Absolute Position anfahren |
| `schau nach links/rechts` | Drehteller in Richtung |
| `drehteller stopp` | Rotation abbrechen |
| `drehteller status` | Aktuelle Position |

## Audio-Routing

| Command | Beschreibung |
|---|---|
| `audio` | Audio-Modus anzeigen |
| `audio lokal an` | Lokale Wiedergabe aktivieren (Matrix + PC) |
| `audio lokal aus` | Nur Matrix (Standard) |

## Log-Zugriff / Remote-Debugging (Phase 61)

| Command | Beschreibung |
|---|---|
| `log` / `log <n>` | Letzte N Einträge aus `elder_berry.log` (default 10, max 50) |
| `log errors [n]` | Nur ERROR/CRITICAL-Einträge |
| `log warnings [n]` | Nur WARNING und höher |
| `log security [n]` | Aus `security.log` (Login-Versuche, Rate-Limits) |

Beispiele: `log 30` · `log errors` · `log errors 20`

## Spezial

| Command | Beschreibung |
|---|---|
| `claude "<Auftrag>"` | Komplexe Anfrage an Claude API |
| `selfcheck` / `systemcheck` | Gesundheitsprüfung aller Komponenten |
| 🎤 Sprachnachricht | Whisper STT → Command/LLM → Text + Sprachantwort |

## Natürliche Sprache

Neben den direkten Commands versteht Saleria auch natürliche Sprache. Beispiele:

- "Schick mir ein Screenshot" → `screenshot`
- "Nächster Song" → `skip`
- "Wie wird das Wetter morgen?" → `wetter morgen`
- "Was muss ich noch erledigen?" → `todos`
- "Wer ist Herr Müller?" → `kontakt` (oder LLM wenn kein Kontakt)
- "Wie geht's dir?" → LLM-Antwort mit Saleria-Persönlichkeit

## Sprachsteuerung via Alexa (Phase 40.1)

Saleria kann über einen Amazon Echo per Sprache gesteuert werden.

| Sprachbefehl | Aktion |
|---|---|
| "Alexa, frag meine Saleria fernsehen an" | TV einschalten (Harmony Hub) |
| "Alexa, frag meine Saleria musik an" | Musik-Aktivität starten |
| "Alexa, frag meine Saleria gaming an" | Gaming-Aktivität starten |
| "Alexa, frag meine Saleria alles aus" | Alle Geräte ausschalten |
| "Alexa, frag meine Saleria lauter" | Lautstärke erhöhen |
| "Alexa, frag meine Saleria leiser" | Lautstärke senken |
| "Alexa, frag meine Saleria stumm" | Stummschalten |
| "Alexa, frag meine Saleria was läuft" | Aktuelle Aktivität abfragen |

Alternativ im Zwei-Schritt-Modus:

1. "Alexa, öffne meine Saleria" → "Saleria hört. Was soll ich tun?"
2. "Fernsehen an" → "Fernsehen wurde eingeschaltet."

Kette: Echo → Amazon Cloud → Rootserver (HTTPS) → SSH-Tunnel → RPi5 → Harmony Hub → IR

## Web-Dashboard

Unter `http://localhost:8090` läuft ein Web-Interface (FastAPI) mit:

- **Audio-Routing** Toggle (Matrix only / Matrix + lokal)
- **Monitor-Auswahl** für Computer Use
- **Secret-Verwaltung** (API-Keys, Zugangsdaten verschlüsselt)
- **LLM-Konfiguration** (Primär-Modell, Ollama-Host)
- **Setup-Wizard** (Ersteinrichtung, `/setup`)
- **Dashboard-Login** (Passwort-Schutz, `scripts/set_dashboard_password.py`)

## Eigene Plugins schreiben

Saleria's Command-System ist Plugin-basiert (Phase 77). Jeder Befehl
gehört zu einem Plugin – Builtin im Repo oder eigene Erweiterung im
Home-Verzeichnis. Eine neue Capability = eine neue Datei.

### Plugin-Quellen

Die Registry lädt beim Start aus drei Quellen, in dieser Priorität:

1. **Builtin** – `src/elder_berry/comms/commands/<name>_commands.py`
   im Repo. Standard-Set (23 Plugins).
2. **User-Verzeichnis** – `~/.elder-berry/plugins/<name>.py`. Eigene
   Plugins, die nur lokal benötigt werden. Werden automatisch geladen,
   sobald Saleria neu startet.
3. **Entry-Points** – `pip install`-Pakete mit Group
   `elder_berry.commands`. Für distributable Drittanbieter-Plugins.

Bei Namens-Kollision gewinnt das User-Plugin vor Entry-Point vor Builtin.
Heißt: ein User-Plugin `name="weather"` ersetzt das Builtin komplett.

### Wizard

Schnellster Weg zum Skelett:

```
python scripts/generate_plugin.py
```

Der Wizard fragt Plugin-Name (snake_case), Kurzbeschreibung, Kategorie
und Priority und erzeugt die Datei in `~/.elder-berry/plugins/`. Mit
`--builtin` schreibt er stattdessen ins Repo (für PRs). Mit
`--name <name>` lässt sich der erste Prompt überspringen.

### Manifest-Format

Jedes Plugin-Modul exportiert genau ein `PLUGIN`-Objekt vom Typ
`CommandPlugin` (siehe [base.py](../src/elder_berry/comms/commands/base.py)).
Pflichtfelder: `name`, `priority`, `category`, `help_section`, `factory`.

Empfohlene Priority-Bereiche:

| Bereich | Zweck |
|---|---|
| 0–9 | Kritische Pre-Filter (selten) |
| 10–49 | Domänen-Commands mit Pattern-Konflikten |
| 50–89 | Normale Commands |
| 90–99 | Catch-All / LLM-Fallback |

### Pattern-Konflikte

Wenn dein Plugin-Pattern denselben Text trifft wie ein anderes Plugin,
gewinnt das mit der niedrigeren Priority. Damit das in Code-Review nicht
übersehen wird, gibt es `tests/test_plugin_pattern_conflicts.py` als
CI-Gate. Bei einer Kollision musst du entweder:

- die Priority anpassen (sodass dein Plugin sicher davor läuft),
- das Pattern enger fassen, oder
- den anderen Plugin-Namen in `conflicts=("anderer_name",)` deklarieren –
  dann ist die Kollision dokumentiert und der Test akzeptiert sie.

### Sicherheits-Hinweis

Plugins laufen mit den vollen Rechten von Saleria – kein Sandboxing.
Entry-Point-Plugins (per `pip install`) sind eine Vertrauensfrage:
fremder Code wird ausgeführt. Lokale User-Plugins sind sicherer, weil
sie nur dein eigener Code sind.

### Konzept-Doku

Die vollständige Architektur steht in
[docs/concepts/phase-77-commands-plugin-registry.md](concepts/phase-77-commands-plugin-registry.md)
– inklusive Backwards-Compat-Strategie und Folge-Phasen (Hot-Reload,
Marketplace).
