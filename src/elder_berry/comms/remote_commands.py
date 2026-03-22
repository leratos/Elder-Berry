"""RemoteCommandHandler – Orchestrator für direkte Befehle via Matrix.

Delegiert an domänenspezifische Handler in comms/commands/:
- SystemCommandHandler: Status, Screenshot, Media, Volume, Avatar, Restart
- CalendarCommandHandler: Termine CRUD + Suche
- MailCommandHandler: Mails, Suche, Anhänge, per ID
- FileCommandHandler: Clipboard, Send-File, Download
- ProcessCommandHandler: Start/Kill, Git, Docker, WoL, Self-Update
- WeatherCommandHandler: Wetter, Timer, Erinnerungen, Briefing, Training
- NoteCommandHandler: Notizen & Wissensdatenbank (optional, benötigt NoteStore)
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
from elder_berry.comms.commands.weather_commands import WeatherCommandHandler
from elder_berry.comms.commands.advanced_commands import AdvancedCommandHandler
from elder_berry.comms.commands.camera_commands import CameraCommandHandler
from elder_berry.comms.commands.note_commands import NoteCommandHandler

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
    from elder_berry.tools.reminder_store import ReminderStore
    from elder_berry.tools.weather_client import WeatherClient

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

Web-Suche:
  suche <Begriff> – Im Internet suchen (z.B. suche Dachdecker Plattenburg)
  such mal <Begriff> – Alias für suche
  google <Begriff> – Alias für suche

Computer Use (Vision-gesteuert):
  klick auf <Element> – Klickt auf ein Bildschirmelement (z.B. klick auf den Discord-Button)
  tippe <Text> – Tippt Text an der aktuellen Position
  scroll runter/hoch – Scrollt auf dem Bildschirm
  drück <Taste> – Drückt eine Taste/Kombination (z.B. drück Strg+S)

Claude-Agent:
  claude "<Auftrag>" – Komplexe Anfrage an Claude API

Sprachnachrichten:
  🎤 OGG/Opus Sprachnachricht → Whisper STT → Saleria antwortet (Text + Sprache)

🔄 Self-Update:
  update / update dich – Git Pull + Dependencies + Neustart
  rollback / update zurücksetzen – Auf Stand vor letztem Update zurücksetzen

🩺 Systemcheck:
  selfcheck / systemcheck / prüf dich – Gesundheitsprüfung aller Komponenten
  alles ok? – Kurzform für Systemcheck"""

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
        note_store: NoteStore | None = None,
        robot_client: RobotClient | None = None,
        anthropic_client: AnthropicClient | None = None,
        default_user_id: str = "",
    ) -> None:
        # Domain-Handler erstellen
        self._system = SystemCommandHandler(
            system_monitor=system_monitor,
            controller=controller,
            avatar_renderer=avatar_renderer,
        )
        self._calendar = CalendarCommandHandler(calendar=calendar)
        self._mail = MailCommandHandler(email_client=email_client)
        self._file = FileCommandHandler(
            download_dir=download_dir,
            send_file_allowed_roots=send_file_allowed_roots,
        )
        self._process = ProcessCommandHandler(
            secret_store=secret_store,
            project_root=project_root,
        )
        self._weather = WeatherCommandHandler(
            weather=weather,
            reminder_store=reminder_store,
            briefing_scheduler=briefing_scheduler,
            gym_client=gym_client,
        )
        self._camera = CameraCommandHandler(
            robot_client=robot_client,
            anthropic_client=anthropic_client,
        )
        self._advanced = AdvancedCommandHandler(
            computer_use=computer_use,
            search_client=search_client,
            document_reader=document_reader,
            audio_router=audio_router,
        )
        # NoteCommandHandler: nur wenn NoteStore vorhanden
        self._notes: NoteCommandHandler | None = None
        if note_store is not None:
            self._notes = NoteCommandHandler(
                note_store=note_store,
                default_user_id=default_user_id,
            )

        # Handler-Liste (Reihenfolge bestimmt Priorität bei Pattern/Keyword-Match)
        # WICHTIG: _weather VOR _calendar, weil REMINDER_DELETE vor TERMIN_DELETE
        # matchen muss ("lösche erinnerung" vs "lösche termin")
        self._handlers: list[CommandHandler] = [
            self._system,
            self._weather,
            self._calendar,
            self._mail,
            self._file,
            self._process,
            self._camera,
        ]
        if self._notes is not None:
            self._handlers.append(self._notes)
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

        # Aggregierte Keyword-Map (global verfügbar für Bridge)
        global KEYWORD_MAP
        KEYWORD_MAP.clear()
        KEYWORD_MAP.update(_build_keyword_map(self._handlers))

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
                    self._command_handler_map[command] = handler
                    return command

        # Stufe 3: Keyword-Suche in natürlicher Sprache
        for handler in self._handlers:
            for command, keywords in handler.keywords.items():
                for keyword in keywords:
                    if keyword in normalized:
                        self._command_handler_map[command] = handler
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
