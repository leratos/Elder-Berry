"""RemoteCommandHandler – Orchestrator für direkte Befehle via Matrix.

Delegiert an domänenspezifische Handler in comms/commands/:
- SystemCommandHandler: Status, Screenshot, Media, Volume, Avatar, Restart
- CalendarCommandHandler: Termine CRUD + Suche
- MailCommandHandler: Mails, Suche, Anhänge, per ID
- FileCommandHandler: Clipboard, Send-File, Download
- CloudCommandHandler: Nextcloud Upload/Download/List/Search/Share
- PDFCommandHandler: PDF-Verarbeitung via Stirling-PDF
- FilingCommandHandler: Dokument-Ablage (Eingang aufräumen)
- ProcessCommandHandler: Prozess Start/Kill
- GitCommandHandler: Git-Befehle (status, pull, log, diff)
- DockerCommandHandler: Docker-Befehle (ps, restart, logs)
- WolCommandHandler: Wake-on-LAN
- UpdateCommandHandler: Self-Update, Rollback, Backup
- SelfcheckCommandHandler: Systemgesundheitsprüfung
- WeatherCommandHandler: Wetter, Timer, Erinnerungen, Briefing, Training
- NoteCommandHandler: Notizen & Wissensdatenbank (optional, benötigt NoteStore)
- RouteCommandHandler: Routenplanung via Google Maps Directions API
- AdvancedCommandHandler: Computer Use, Web-Suche, Dokumente, Audio

Verwendung:
    handler = RemoteCommandHandler(
        system_monitor=monitor,
        controller=action_ctrl,
        secret_store=store,
        project_root=Path("C:/Dev/Elder-Berry"),
    )
    cmd = handler.parse_command("status")
    if cmd:
        result = handler.execute(cmd, "status")
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult
from elder_berry.comms.commands.system_commands import SystemCommandHandler
from elder_berry.comms.commands.calendar_commands import CalendarCommandHandler
from elder_berry.comms.commands.mail_commands import MailCommandHandler
from elder_berry.comms.commands.file_commands import FileCommandHandler
from elder_berry.comms.commands.process_commands import ProcessCommandHandler
from elder_berry.comms.commands.git_commands import GitCommandHandler
from elder_berry.comms.commands.docker_commands import DockerCommandHandler
from elder_berry.comms.commands.wol_commands import WolCommandHandler
from elder_berry.comms.commands.update_commands import UpdateCommandHandler
from elder_berry.comms.commands.selfcheck_commands import SelfcheckCommandHandler
from elder_berry.comms.commands.weather_commands import WeatherCommandHandler
from elder_berry.comms.commands.advanced_commands import AdvancedCommandHandler
from elder_berry.comms.commands.camera_commands import CameraCommandHandler
from elder_berry.comms.commands.turntable_commands import TurntableCommandHandler
from elder_berry.comms.commands.note_commands import NoteCommandHandler
from elder_berry.comms.commands.contact_commands import ContactCommandHandler
from elder_berry.comms.commands.todo_commands import TodoCommandHandler
from elder_berry.comms.commands.cloud_commands import CloudCommandHandler
from elder_berry.comms.commands.pdf_commands import PDFCommandHandler
from elder_berry.comms.commands.filing_commands import FilingCommandHandler
from elder_berry.comms.commands.harmony_commands import HarmonyCommandHandler
from elder_berry.comms.commands.route_commands import RouteCommandHandler

if TYPE_CHECKING:
    from elder_berry.actions.base import ActionController
    from elder_berry.actions.computer_use import ComputerUseController
    from elder_berry.avatar.base import AvatarRenderer
    from elder_berry.core.audio_router import AudioRouter
    from elder_berry.core.secret_store import SecretStore
    from elder_berry.llm.anthropic_client import AnthropicClient
    from elder_berry.robot.client import RobotClient
    from elder_berry.system.info import SystemMonitor
    from elder_berry.tools.brave_search_client import BraveSearchClient
    from elder_berry.tools.document_reader import DocumentReader
    from elder_berry.tools.email_client import IMAPEmailClient
    from elder_berry.tools.google_calendar import GoogleCalendarClient
    from elder_berry.tools.gym_data import GymDataClient
    from elder_berry.comms.briefing_scheduler import BriefingScheduler
    from elder_berry.tools.note_store import NoteStore
    from elder_berry.tools.contact_store import ContactStore
    from elder_berry.tools.todo_store import TodoStore
    from elder_berry.tools.reminder_store import ReminderStore
    from elder_berry.tools.weather_client import WeatherClient
    from elder_berry.tools.carddav_sync import CardDAVSyncClient
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient
    from elder_berry.comms.pending_confirmation import PendingConfirmationStore
    from elder_berry.tools.document_classifier import DocumentClassifier
    from elder_berry.tools.stirling_pdf import StirlingPDFClient
    from elder_berry.core.tower_agent import TowerAgent
    from elder_berry.tools.route_planner import RoutePlanner
    from elder_berry.tools.web_fetcher import WebFetcher

logger = logging.getLogger(__name__)

# Re-export für Rückwärtskompatibilität (Bridge, Tests etc. importieren von hier)
__all__ = ["RemoteCommandHandler", "CommandResult", "HELP_TEXT", "KEYWORD_MAP"]

# Hilfe-Text: ALLE Commands hier auflisten!
# (siehe CLAUDE.md – bei neuen Features nachtragen)
HELP_TEXT = """Verfügbare Commands:

Basis:
  status / systemstatus – CPU, RAM, GPU, Disk, Top-Prozesse
  screenshot / screen – Screenshot als Bild
  hilfe / help – Diese Hilfe anzeigen

Medien:
  pause / play – Musik pausieren/fortsetzen
  skip / next – Nächster Track
  prev / previous – Vorheriger Track
  volume <0-100> – Lautstärke setzen

Avatar:
  selfie / avatar – Bild von Saleria senden
  selfie <emotion> – Mit Emotion (angry, cheerful, sad, ...)

Clipboard:
  clipboard – Zwischenablage lesen
  clip: <text> – Text in Zwischenablage schreiben

Dateien:
  schick mir <pfad> – Datei senden (max 50 MB, nur erlaubte Verzeichnisse)
  download <url> – Datei herunterladen

Cloud (Nextcloud):
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
  pdf bilder <datei> – Bilder aus PDF extrahieren

Prozesse:
  starte <programm> – Programm starten (Whitelist)
  kill <prozess> – Prozess beenden (Whitelist)

System:
  wol – Wake-on-LAN (Tower aufwecken)
  restart / neustart – Bot neu starten (z.B. nach git pull)
  git status / git pull / git log / git diff
  docker ps / docker restart <name> / docker logs <name>

Kalender:
  termine – Termine heute
  termine morgen – Termine morgen
  termine woche – Termine nächste 7 Tage
  termine monat – Termine bis Monatsende
  termin suche <Begriff> – Termin suchen (nächste 90 Tage)
  termin: Titel morgen 14:00 – Termin erstellen (morgen/übermorgen/DD.MM/YYYY-MM-DD)
  erstelle termin Titel 30.03 10:00 – Termin erstellen (natürliche Sprache)
  lösche termin <Titel/ID> – Termin löschen
  lösche den 2. termin – Per Index aus letztem Ergebnis
  lösche alle termine – Alle aus letztem Ergebnis löschen

E-Mail:
  mails – Ungelesene E-Mails
  mails 5 – Letzte 5 Tage
  mail suche <Begriff> – Mails nach Betreff/Absender durchsuchen
  mail <ID> / mail #<ID> – Mail anzeigen (z.B. mail 99, fasse mail #99 zusammen)
  mail anhang <ID> – Anhänge einer Mail senden (ID aus Suchergebnis)
  mail zusammenfassung – LLM-Zusammenfassung ungelesener Mails
  antworte auf #<ID> <Anweisung> – Email-Antwort generieren
    Beispiele: antworte auf #4523 positiv, bedanke dich
    → Saleria zeigt Entwurf, du bestätigst mit 'ja'
  lösche mail #<ID> – Mail löschen (z.B. lösche mail #4523)
  lösche die mail – Letzte abgerufene Mail löschen

Fitness (Berry-Gym):
  training – Zusammenfassung (letztes Training, Woche, Gewicht)
  training details – Letztes Training mit allen Sätzen
  training woche – Trainings der letzten 7 Tage
  prs – Personal Records (letzte 30 Tage)

Wetter:
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
  briefing – Tagesübersicht (Wetter + Termine + Erinnerungen)

📝 Notizen & Wissen:
  merk dir: <schlüssel> ist <wert>  – Fakt speichern (z.B. merk dir: WLAN Büro ist xyz123)
  notiz: <text>                      – Freitext-Notiz speichern
  was ist <schlüssel>?               – Fakt abrufen
  notizen suche <Begriff>            – Notizen durchsuchen
  notizen                            – Alle Notizen anzeigen (max 20)
  notiz löschen #<id>                – Notiz per ID löschen
  vergiss <schlüssel>                – KV-Fakt vergessen

📇 Kontakte:
  kontakt: Name, Rolle, Email, Anrede – Kontakt anlegen
    Beispiel: kontakt: Herr Müller, Vermieter, info@mueller.de, förmlich
  wer ist <Name>? – Kontakt abrufen
  kontakte – Alle Kontakte anzeigen
  kontakte suche <Begriff> – Kontakt suchen
  kontakt löschen #<ID> – Kontakt löschen
  kontakte sync – Kontakte mit Nextcloud synchronisieren
  kontakte sync push – Nur lokal → Nextcloud
  kontakte sync pull – Nur Nextcloud → lokal

✅ Aufgaben (To-Do):
  todo: <text> – Aufgabe anlegen (optional: , hoch/mittel, Kategorie)
  todos / aufgaben – Offene Aufgaben anzeigen
  todos hoch / todos Arbeit – Gefiltert nach Priorität/Kategorie
  todo erledigt #<ID> – Aufgabe abhaken
  todo wieder öffnen #<ID> – Aufgabe wieder öffnen
  todo priorität #<ID> hoch – Priorität ändern (hoch/mittel/niedrig)
  todo löschen #<ID> – Aufgabe löschen
  todos erledigt – Erledigte Aufgaben anzeigen
  todos aufräumen – Alle erledigten löschen

Kamera:
  foto / kamera – Foto aufnehmen und senden
  was siehst du [kontext] – Kamerabild + KI-Beschreibung

Audio:
  audio – Audio-Modus anzeigen (matrix_only / matrix_and_local)
  audio lokal an – Lokale Wiedergabe aktivieren (Matrix + PC)
  audio lokal aus – Nur Matrix (Standard)

Dokumente:
  zusammenfassung <Pfad> – PDF/TXT zusammenfassen (z.B. zusammenfassung C:\\Docs\\report.pdf)
  fasse zusammen <Pfad> – Alias für zusammenfassung

Web-Zusammenfassung:
  fasse <URL> zusammen – Webseite zusammenfassen (z.B. fasse https://example.com zusammen)
  zusammenfassung von <URL> – Alias für fasse zusammen
  fasse die seite <URL> zusammen – Alias für fasse zusammen

Web-Suche:
  suche <Begriff> – Im Internet suchen (z.B. suche Dachdecker Plattenburg)
  such mal <Begriff> – Alias für suche
  google <Begriff> – Alias für suche

Harmony Hub (Smart Home):
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
  drehteller status – Aktuelle Position anzeigen

Computer Use (Vision-gesteuert):
  klick auf <Element> – Klickt auf ein Bildschirmelement (z.B. klick auf den Discord-Button)
  tippe <Text> – Tippt Text an der aktuellen Position
  scroll runter/hoch – Scrollt auf dem Bildschirm
  drück <Taste> – Drückt eine Taste/Kombination (z.B. drück Strg+S)

Claude-Agent:
  claude "<Auftrag>" – Komplexe Anfrage an Claude API

Sprachnachrichten:
  🎤 OGG/Opus Sprachnachricht → Whisper STT → Saleria antwortet (Text + Sprache)

🗺️ Routenplanung:
  plane fahrt zu <Name> – Route von Zuhause zu Kontakt
  fahrt von <Name> zu <Name> – Route zwischen zwei Kontakten
  wie komme ich zu <Name> – Route von Zuhause
  Optional: "morgen um 16 uhr", "übermorgen 10 uhr" → Abfahrtszeit

🔄 Self-Update:
  update / update dich – Git Pull + Dependencies + Neustart (Tower)
  update rpi – RPi5 aktualisieren (git pull + pip + systemctl restart)
  update alles – Tower + RPi5 nacheinander aktualisieren
  rollback / update zurücksetzen – Auf Stand vor letztem Update zurücksetzen

🩺 Systemcheck:
  selfcheck / systemcheck / prüf dich – Infrastruktur + Fähigkeiten-Check
  alles ok? – Kurzform für Systemcheck
  Prüft: Git, Python, Disk, RAM, Ollama, SecretStore, Imports, Dependencies
  + Fähigkeiten: LLM, Kalender, Mail, Nextcloud, Wetter, TTS, STT, Memory, ..."""

# Aggregierte Keyword-Map (aus allen Handlern zusammengeführt).
# Wird von der Bridge für Keyword-Routing genutzt.
KEYWORD_MAP: dict[str, list[str]] = {}


def _build_keyword_map(handlers: list[CommandHandler]) -> dict[str, list[str]]:
    """Baut die aggregierte KEYWORD_MAP aus allen Handler-Keywords."""
    result: dict[str, list[str]] = {}
    for handler in handlers:
        for command, keywords in handler.keywords.items():
            result[command] = keywords
    return result


class RemoteCommandHandler:
    """Orchestrator für direkte Befehle über Matrix (kein LLM nötig).

    Delegiert an domänenspezifische CommandHandler-Instanzen.
    Alle Dependencies sind optional – fehlende Dependencies führen zu
    graceful Degradation (Fehlertext statt Crash).
    """

    def __init__(
        self,
        system_monitor: SystemMonitor | None = None,
        controller: ActionController | None = None,
        secret_store: SecretStore | None = None,
        project_root: Path | None = None,
        download_dir: Path | None = None,
        avatar_renderer: AvatarRenderer | None = None,
        send_file_allowed_roots: tuple[Path, ...] | None = None,
        calendar: GoogleCalendarClient | None = None,
        email_client: IMAPEmailClient | None = None,
        gym_client: GymDataClient | None = None,
        weather: WeatherClient | None = None,
        reminder_store: ReminderStore | None = None,
        briefing_scheduler: BriefingScheduler | None = None,
        document_reader: DocumentReader | None = None,
        audio_router: AudioRouter | None = None,
        computer_use: ComputerUseController | None = None,
        search_client: BraveSearchClient | None = None,
        web_fetcher: WebFetcher | None = None,
        note_store: NoteStore | None = None,
        contact_store: ContactStore | None = None,
        todo_store: TodoStore | None = None,
        robot_client: RobotClient | None = None,
        anthropic_client: AnthropicClient | None = None,
        nextcloud_files: NextcloudFilesClient | None = None,
        stirling_pdf: StirlingPDFClient | None = None,
        document_classifier: DocumentClassifier | None = None,
        carddav_sync: CardDAVSyncClient | None = None,
        route_planner: RoutePlanner | None = None,
        pending_store: PendingConfirmationStore | None = None,
        default_user_id: str = "",
        tower_agent: TowerAgent | None = None,
    ) -> None:
        # Domain-Handler erstellen
        self._system = SystemCommandHandler(
            system_monitor=system_monitor,
            controller=controller,
            avatar_renderer=avatar_renderer,
            tower_agent=tower_agent,
        )
        self._calendar = CalendarCommandHandler(calendar=calendar)
        self._mail = MailCommandHandler(
            email_client=email_client,
            anthropic_client=anthropic_client,
            contact_store=contact_store,
            default_user_id=default_user_id,
        )
        self._file = FileCommandHandler(
            download_dir=download_dir,
            send_file_allowed_roots=send_file_allowed_roots,
        )
        self._process = ProcessCommandHandler()
        self._git = GitCommandHandler(project_root=project_root)
        self._docker = DockerCommandHandler()
        self._wol = WolCommandHandler(secret_store=secret_store)
        self._update = UpdateCommandHandler(
            project_root=project_root,
            robot_client=robot_client,
        )
        self._selfcheck = SelfcheckCommandHandler(
            project_root=project_root,
            secret_store=secret_store,
            services={
                "anthropic_client": anthropic_client,
                "calendar": calendar,
                "email_client": email_client,
                "nextcloud_files": nextcloud_files,
                "stirling_pdf": stirling_pdf,
                "carddav_sync": carddav_sync,
                "weather": weather,
                "search_client": search_client,
                "robot_client": robot_client,
                "note_store": note_store,
                "contact_store": contact_store,
                "todo_store": todo_store,
                "reminder_store": reminder_store,
                "gym_client": gym_client,
                "computer_use": computer_use,
                "document_reader": document_reader,
                "web_fetcher": web_fetcher,
                "audio_router": audio_router,
                "tower_agent": tower_agent,
            },
        )
        self._weather = WeatherCommandHandler(
            weather=weather,
            reminder_store=reminder_store,
            briefing_scheduler=briefing_scheduler,
            gym_client=gym_client,
        )
        self._turntable = TurntableCommandHandler(
            robot_client=robot_client,
        )
        self._camera = CameraCommandHandler(
            robot_client=robot_client,
            anthropic_client=anthropic_client,
        )
        self._cloud = CloudCommandHandler(
            nextcloud_files=nextcloud_files,
        )
        self._pdf = PDFCommandHandler(
            stirling_pdf=stirling_pdf,
            nextcloud_files=nextcloud_files,
        )
        self._filing = FilingCommandHandler(
            nextcloud_files=nextcloud_files,
            document_classifier=document_classifier,
            pending_store=pending_store,
            email_client=email_client,
        )
        self._harmony = HarmonyCommandHandler(
            robot_client=robot_client,
        )
        self._advanced = AdvancedCommandHandler(
            computer_use=computer_use,
            search_client=search_client,
            document_reader=document_reader,
            audio_router=audio_router,
            web_fetcher=web_fetcher,
            nextcloud_files=nextcloud_files,
        )
        # NoteCommandHandler: nur wenn NoteStore vorhanden
        self._notes: NoteCommandHandler | None = None
        if note_store is not None:
            self._notes = NoteCommandHandler(
                note_store=note_store,
                default_user_id=default_user_id,
            )

        # ContactCommandHandler: nur wenn ContactStore vorhanden
        self._contacts: ContactCommandHandler | None = None
        if contact_store is not None:
            self._contacts = ContactCommandHandler(
                contact_store=contact_store,
                default_user_id=default_user_id,
                carddav_sync=carddav_sync,
            )

        # TodoCommandHandler: nur wenn TodoStore vorhanden
        self._todos: TodoCommandHandler | None = None
        if todo_store is not None:
            self._todos = TodoCommandHandler(
                todo_store=todo_store,
                default_user_id=default_user_id,
            )

        # RouteCommandHandler: nur wenn RoutePlanner + ContactStore vorhanden
        self._route: RouteCommandHandler | None = None
        if route_planner is not None and contact_store is not None:
            self._route = RouteCommandHandler(
                route_planner=route_planner,
                contact_store=contact_store,
                default_user_id=default_user_id,
            )

        # Handler-Liste (Reihenfolge bestimmt Priorität bei Pattern/Keyword-Match)
        # WICHTIG: _weather VOR _calendar, weil REMINDER_DELETE vor TERMIN_DELETE
        # matchen muss ("lösche erinnerung" vs "lösche termin")
        # WICHTIG: _mail VOR _calendar, weil MAIL_DELETE vor TERMIN_DELETE
        # matchen muss ("lösche die mail" vs "lösche termin")
        # WICHTIG: _turntable VOR _camera wegen "schau nach" Pattern-Prioritaet
        self._handlers: list[CommandHandler] = [
            self._system,
            self._weather,
            self._mail,
            self._calendar,
            self._file,
            self._cloud,
            self._pdf,
            self._filing,
            self._process,
            self._git,
            self._docker,
            self._wol,
            self._update,
            self._selfcheck,
            self._turntable,
            self._harmony,
            self._camera,
        ]
        if self._notes is not None:
            self._handlers.append(self._notes)
        if self._contacts is not None:
            self._handlers.append(self._contacts)
        if self._todos is not None:
            self._handlers.append(self._todos)
        if self._route is not None:
            self._handlers.append(self._route)
        self._handlers.append(self._advanced)

        # Aggregierte Simple-Commands und Command→Handler Lookup
        self._simple_commands: set[str] = set()
        self._command_handler_map: dict[str, CommandHandler] = {}

        for handler in self._handlers:
            for cmd in handler.simple_commands:
                self._simple_commands.add(cmd)
                self._command_handler_map[cmd] = handler
            # Pattern-Commands ebenfalls registrieren
            for _pattern, cmd, _use_orig, *_rest in handler.patterns:
                self._command_handler_map[cmd] = handler
            # Keyword-Commands ebenfalls registrieren
            for cmd in handler.keywords:
                self._command_handler_map[cmd] = handler

        # Aggregierte Keyword-Map (instance attribute ist primary source)
        self.keyword_map = _build_keyword_map(self._handlers)
        # Update global for backwards compat (deprecated, use instance.keyword_map instead)
        global KEYWORD_MAP
        KEYWORD_MAP.clear()
        KEYWORD_MAP.update(self.keyword_map)

    def validate_help_text(self) -> list[str]:
        """Prüft ob HELP_TEXT und Handler-Registrierung synchron sind.

        Returns:
            Liste von Warnungen (leer wenn alles konsistent).
        """
        warnings: list[str] = []
        help_lower = HELP_TEXT.lower()
        for handler in self._handlers:
            for desc in handler.command_descriptions:
                # Ersten Command-Namen extrahieren (vor dem ':')
                cmd_name = desc.split(":")[0].strip().split()[0]
                if cmd_name and cmd_name not in help_lower:
                    warnings.append(
                        f"Command '{cmd_name}' aus {type(handler).__name__}"
                        f" fehlt in HELP_TEXT"
                    )
        if warnings:
            for w in warnings:
                logger.warning("HELP_TEXT Sync: %s", w)
        return warnings

    def get_command_summary(self) -> str:
        """Generiert eine kompakte Übersicht aller verfügbaren Remote-Commands.

        Wird für den dynamischen Command-Block im System-Prompt genutzt.
        Single Source of Truth: Handler definieren ihre Commands,
        der Prompt wird daraus generiert.

        Returns:
            Mehrzeiliger String mit allen Command-Beschreibungen.
        """
        lines: list[str] = []
        for handler in self._handlers:
            descriptions = handler.command_descriptions
            if descriptions:
                for desc in descriptions:
                    lines.append(f"    - {desc}")
        # Hilfe-Command (lebt im Orchestrator)
        lines.append("    - hilfe: Alle verfügbaren Commands anzeigen")
        return "\n".join(lines)

    def parse_command(self, text: str) -> str | None:
        """Prüft ob der Text ein direkter Command ist.

        Erkennung in mehreren Stufen:
        1. Exakter Match gegen Simple-Commands aller Handler
        2. Pattern-Match gegen alle Handler-Patterns (in Handler-Reihenfolge)
        3. Keyword-Suche in natürlicher Sprache

        Args:
            text: Nachrichtentext vom Nutzer.

        Returns:
            Normalisierter Command-Name oder None wenn kein Command erkannt.
        """
        normalized = text.strip().lower()

        # Stufe 1: Hilfe (bleibt im Orchestrator)
        if normalized in ("hilfe", "help"):
            return normalized

        # Stufe 2: Exakter Match gegen Simple-Commands
        if normalized in self._simple_commands:
            return normalized

        # Stufe 2: Pattern-Match (Handler-Reihenfolge bestimmt Priorität)
        for handler in self._handlers:
            for pattern, command, use_original, *rest in handler.patterns:
                use_search = rest[0] if rest else False
                check_text = text.strip() if use_original else normalized
                match = pattern.search(check_text) if use_search else pattern.match(check_text)
                if match:
                    return command

        # Stufe 3: Keyword-Suche in natürlicher Sprache
        for handler in self._handlers:
            for command, keywords in handler.keywords.items():
                for keyword in keywords:
                    if keyword in normalized:
                        return command

        return None

    def execute(self, command: str, raw_text: str) -> CommandResult:
        """Führt einen erkannten Command aus.

        Args:
            command: Normalisierter Command-Name (von parse_command).
            raw_text: Originaler Nachrichtentext (für Parameter-Extraktion).

        Returns:
            CommandResult mit Ergebnis.
        """
        # Hilfe bleibt im Orchestrator
        if command in ("hilfe", "help"):
            return CommandResult(command="hilfe", success=True, text=HELP_TEXT)

        # Handler-Lookup (alle Commands bei Init registriert)
        handler = self._command_handler_map.get(command)
        if handler:
            return handler.execute(command, raw_text)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Command: {command}",
        )
