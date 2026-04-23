"""Kategorisierte Hilfe-Texte für Matrix (Phase 51.1).

Statt eines ~190 Zeilen langen HELP_TEXT-Blocks wird die Hilfe in
thematische Sektionen aufgeteilt. Der Nutzer tippt ``hilfe`` für die
Übersicht und ``hilfe <kategorie>`` für die Details einer Sektion.
``hilfe alles`` zeigt weiterhin den Volltext.
"""
from __future__ import annotations

CATEGORY_LABELS: dict[str, str] = {
    "basis": "Status, Screenshot, Hilfe",
    "medien": "Audio, Musik, Lautstärke",
    "avatar": "Avatar, Kamera, Selfie",
    "dateien": "Clipboard, Senden, Download",
    "cloud": "Nextcloud, Ablage, PDF",
    "kalender": "Termine, Suche, Erstellen",
    "mail": "Mails, Suche, Antworten",
    "fitness": "Berry-Gym, Training, PRs",
    "wetter": "Wetter, Timer, Erinnerungen, Briefing",
    "notizen": "Notizen & Wissensdatenbank",
    "kontakte": "Kontaktbuch + Sync",
    "todos": "Aufgabenliste",
    "smart-home": "Harmony Hub, Drehteller",
    "web": "Web-Suche, Dokumente, Computer Use, Routen",
    "system": "Prozesse, Git, Docker, Update, Selfcheck",
    "diagnose": "Log-Zugriff für Remote-Debugging",
}

HELP_SECTIONS: dict[str, str] = {
    "basis": """Basis:
  status / systemstatus – CPU, RAM, GPU, Disk, Top-Prozesse
  screenshot / screen – Screenshot als Bild
  hilfe / help – Kategorien-Übersicht
  hilfe <kategorie> – Details einer Kategorie
  hilfe alles – Vollständige Hilfe (alle Commands)""",

    "medien": """Medien:
  pause / play – Musik pausieren/fortsetzen
  skip / next – Nächster Track
  prev / previous – Vorheriger Track
  volume <0-100> – Lautstärke setzen

Audio:
  audio – Audio-Modus anzeigen (matrix_only / matrix_and_local)
  audio lokal an – Lokale Wiedergabe aktivieren (Matrix + PC)
  audio lokal aus – Nur Matrix (Standard)

Sprachnachrichten:
  🎤 OGG/Opus → Whisper STT → Saleria antwortet (Text + Sprache)""",

    "avatar": """Avatar:
  selfie / avatar – Bild von Saleria senden
  selfie <emotion> – Mit Emotion (angry, cheerful, sad, ...)

Kamera:
  foto / kamera – Foto aufnehmen und senden
  was siehst du [kontext] – Kamerabild + KI-Beschreibung""",

    "dateien": """Clipboard:
  clipboard – Zwischenablage lesen
  clip: <text> – Text in Zwischenablage schreiben

Dateien:
  schick mir <pfad> – Datei senden (max 50 MB, nur erlaubte Verzeichnisse)
  download <url> – Datei herunterladen""",

    "cloud": """Cloud (Nextcloud):
  cloud upload <pfad> [ziel] – Datei zu Nextcloud hochladen
  cloud download <pfad> – Datei aus Nextcloud herunterladen
  cloud dateien [ordner] – Verzeichnis auflisten
  cloud suche <query> – Dateien suchen
  cloud link <pfad> – Öffentlichen Share-Link erstellen
  richte nextcloud ein – Standard-Dateien löschen + Ordnerstruktur anlegen

Dokument-Ablage:
  cloud aufräumen – Dateien im Eingang klassifizieren und ablegen
  anhang ablegen #<ID> – PDF-Anhänge aus Mail klassifizieren und ablegen

PDF-Verarbeitung (Stirling-PDF):
  pdf zusammenfügen <a.pdf> <b.pdf> – PDFs zusammenfügen
  pdf aufteilen <datei> seiten 1-3 – Seiten extrahieren
  pdf komprimieren <datei> [stufe 1-9] – Dateigröße reduzieren
  pdf ocr <datei> – Text erkennen (Deutsch+Englisch)
  pdf zu word <datei> – PDF → Word konvertieren
  zu pdf <datei> – Word/Bild → PDF konvertieren
  pdf bilder <datei> – Bilder aus PDF extrahieren""",

    "kalender": """Kalender:
  termine – Termine heute
  termine morgen – Termine morgen
  termine woche – Termine nächste 7 Tage
  termine monat – Termine bis Monatsende
  termin suche <Begriff> – Termin suchen (nächste 90 Tage)
  termin: Titel morgen 14:00 – Termin erstellen
  erstelle termin Titel 30.03 10:00 – Termin erstellen (natürliche Sprache)
  lösche termin <Titel/ID> – Termin löschen
  lösche den 2. termin – Per Index aus letztem Ergebnis
  lösche alle termine – Alle aus letztem Ergebnis löschen""",

    "mail": """E-Mail:
  mails – Ungelesene E-Mails
  mails 5 – Letzte 5 Tage
  mail suche <Begriff> – Mails nach Betreff/Absender durchsuchen
  mail <ID> / mail #<ID> – Mail anzeigen
  mail anhang <ID> – Anhänge einer Mail senden
  mail zusammenfassung – LLM-Zusammenfassung ungelesener Mails
  antworte auf #<ID> <Anweisung> – Email-Antwort generieren
    Beispiele: antworte auf #4523 positiv, bedanke dich
    → Saleria zeigt Entwurf, du bestätigst mit 'ja'
  lösche mail #<ID> – Mail löschen
  lösche die mail – Letzte abgerufene Mail löschen""",

    "fitness": """Fitness (Berry-Gym):
  training – Zusammenfassung (letztes Training, Woche, Gewicht)
  training details – Letztes Training mit allen Sätzen
  training woche – Trainings der letzten 7 Tage
  prs – Personal Records (letzte 30 Tage)""",

    "wetter": """Wetter:
  wetter – Aktuelles Wetter
  wetter morgen – Wetterprognose morgen
  wetter woche – 7-Tage-Prognose
  wetter 3 – Prognose für 3 Tage

Timer & Erinnerungen:
  timer 20 min – Timer auf 20 Minuten
  timer 1 stunde – Timer auf 1 Stunde
  erinnere mich um 18:00: Wäsche – Erinnerung zu bestimmter Uhrzeit
  erinnere mich in 2 stunden: Kuchen – Erinnerung nach Zeitspanne
  erinnerungen – Offene Erinnerungen anzeigen
  lösche erinnerung 3 – Erinnerung #3 löschen
  lösche alle erinnerungen – Alle löschen

🔁 Wiederkehrende Erinnerungen:
  erinnere mich jeden montag um 9:00: Wochenbericht – Wöchentlich
  erinnere mich täglich um 8:00: Standup – Täglich
  erinnere mich werktags um 7:30: Aufstehen – Mo–Fr
  erinnere mich jeden 1. um 10:00: Miete – Monatlich

Briefing:
  briefing – Tagesübersicht (Wetter + Termine + Erinnerungen)""",

    "notizen": """📝 Notizen & Wissen:
  merk dir: <schlüssel> ist <wert>  – Fakt speichern (z.B. merk dir: WLAN Büro ist xyz123)
  notiz: <text>                      – Freitext-Notiz speichern
  was ist <schlüssel>?               – Fakt abrufen
  notizen suche <Begriff>            – Notizen durchsuchen
  notizen                            – Alle Notizen anzeigen (max 20)
  notiz löschen #<id>                – Notiz per ID löschen
  vergiss <schlüssel>                – KV-Fakt vergessen""",

    "kontakte": """📇 Kontakte:
  kontakt: Name, Rolle, Email, Anrede – Kontakt anlegen
    Beispiel: kontakt: Herr Müller, Vermieter, info@mueller.de, förmlich
  wer ist <Name>? – Kontakt abrufen
  kontakte – Alle Kontakte anzeigen
  kontakte suche <Begriff> – Kontakt suchen
  kontakt löschen #<ID> – Kontakt löschen
  kontakte sync – Kontakte mit Nextcloud synchronisieren
  kontakte sync push – Nur lokal → Nextcloud
  kontakte sync pull – Nur Nextcloud → lokal""",

    "todos": """✅ Aufgaben (To-Do):
  todo: <text> – Aufgabe anlegen (optional: , hoch/mittel, Kategorie)
  todos / aufgaben – Offene Aufgaben anzeigen
  todos hoch / todos Arbeit – Gefiltert nach Priorität/Kategorie
  todo erledigt #<ID> – Aufgabe abhaken
  todo wieder öffnen #<ID> – Aufgabe wieder öffnen
  todo priorität #<ID> hoch – Priorität ändern (hoch/mittel/niedrig)
  todo löschen #<ID> – Aufgabe löschen
  todos erledigt – Erledigte Aufgaben anzeigen
  todos aufräumen – Alle erledigten löschen""",

    "smart-home": """Harmony Hub (Smart Home):
  <aktivität> an – Aktivität starten (z.B. fernsehen an, musik an)
  alles aus / harmony aus – Alle Geräte ausschalten
  lauter / mach lauter – Lautstärke erhöhen (Receiver)
  leiser / mach leiser – Lautstärke senken (Receiver)
  stummschalten / stumm – Receiver stummschalten
  was läuft / harmony status – Aktuelle Aktivität anzeigen
  harmony aktivitäten – Alle Aktivitäten auflisten
  harmony geräte – Alle Geräte auflisten
  harmony befehle <gerät> – Verfügbare Befehle für ein Gerät
  starte szene <name> / szene <name> – Harmony-Szene starten
  szenen / szenen liste – Alle Szenen auflisten

Drehteller:
  drehteller home – Home-Position anfahren
  dreh dich um <grad> [nach links/rechts] – Relativ drehen
  dreh dich nach links/rechts – 90 Grad in Richtung drehen
  dreh dich auf <grad> – Auf absolute Position fahren
  schau nach links/rechts – Drehteller in Richtung drehen
  drehteller stopp – Rotation sofort abbrechen
  drehteller status – Aktuelle Position anzeigen""",

    "web": """Web-Suche:
  suche <Begriff> – Im Internet suchen
  such mal <Begriff> – Alias für suche
  google <Begriff> – Alias für suche

Web-Zusammenfassung:
  fasse <URL> zusammen – Webseite zusammenfassen
  zusammenfassung von <URL> – Alias
  fasse die seite <URL> zusammen – Alias

Dokumente:
  zusammenfassung <Pfad> – PDF/TXT zusammenfassen
  fasse zusammen <Pfad> – Alias für zusammenfassung

Computer Use (Vision-gesteuert):
  klick auf <Element> – Klickt auf ein Bildschirmelement
  tippe <Text> – Tippt Text an der aktuellen Position
  scroll runter/hoch – Scrollt auf dem Bildschirm
  drück <Taste> – Drückt eine Taste/Kombination (z.B. drück Strg+S)

Claude-Agent:
  claude "<Auftrag>" – Komplexe Anfrage an Claude API

🗺️ Routenplanung:
  plane fahrt zu <Name> – Route von Zuhause zu Kontakt
  fahrt von <Name> zu <Name> – Route zwischen zwei Kontakten
  wie komme ich zu <Name> – Route von Zuhause
  Optional: "morgen um 16 uhr", "übermorgen 10 uhr" → Abfahrtszeit""",

    "system": """Prozesse:
  starte <programm> – Programm starten (Whitelist)
  kill <prozess> – Prozess beenden (Whitelist)

System:
  wol – Wake-on-LAN (Tower aufwecken)
  restart / neustart – Bot neu starten (z.B. nach git pull)
  git status / git pull / git log / git diff
  docker ps / docker restart <name> / docker logs <name>

🔄 Self-Update:
  update / update dich – Git Pull + Dependencies + Neustart (Server)
  update tower – Tower-PC aktualisieren (git pull + pip + restart)
  update rpi – RPi5 aktualisieren (git pull + pip + systemctl restart)
  update alles – Server + Tower + RPi5 nacheinander aktualisieren
  rollback / update zurücksetzen – Auf Stand vor letztem Update zurücksetzen

🩺 Systemcheck:
  selfcheck / systemcheck / prüf dich – Infrastruktur + Fähigkeiten-Check
  alles ok? – Kurzform für Systemcheck
  Prüft: Git, Python, Disk, RAM, Ollama, SecretStore, Imports, Dependencies
  + Fähigkeiten: LLM, Kalender, Mail, Nextcloud, Wetter, TTS, STT, Memory, ...""",

    "diagnose": """📋 Log-Zugriff (Remote-Debugging):
  log [n] – Letzte N Einträge aus elder_berry.log (default 10, max 50)
  log errors [n] – Nur ERROR/CRITICAL-Einträge
  log warnings [n] – Nur WARNING und höher
  log security [n] – Aus security.log (Login-Versuche, Rate-Limits)

  Beispiele:
    log – Letzte 10 Zeilen
    log 30 – Letzte 30 Zeilen
    log errors – Letzte 10 Fehler
    log errors 20 – Letzte 20 Fehler""",
}


def build_overview() -> str:
    """Baut die kurze Kategorien-Übersicht für ``hilfe`` ohne Argument."""
    lines = ["Verfügbare Hilfe-Kategorien:"]
    for key, label in CATEGORY_LABELS.items():
        lines.append(f"  hilfe {key} – {label}")
    lines.append("  hilfe alles – Vollständige Hilfe (alle Commands)")
    lines.append("")
    lines.append("Tippe 'hilfe <kategorie>' für Details.")
    return "\n".join(lines)


def build_full_help() -> str:
    """Baut den kompletten Hilfetext (alle Sektionen aneinandergereiht)."""
    blocks = ["Verfügbare Commands:", ""]
    for key in CATEGORY_LABELS:
        section = HELP_SECTIONS.get(key)
        if section:
            blocks.append(section)
            blocks.append("")
    return "\n".join(blocks).rstrip()


def get_section(category: str) -> str | None:
    """Liefert den Hilfetext einer Kategorie oder None wenn unbekannt."""
    return HELP_SECTIONS.get(category.strip().lower())
