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

import difflib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult
from elder_berry.comms.commands.help_sections import (
    CATEGORY_LABELS,
    build_full_help,
    build_overview,
    get_section,
)
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
from elder_berry.comms.commands.log_commands import LogCommandHandler
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
    from elder_berry.tools.caldav_tasks import CalDAVTaskClient
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
__all__ = [
    "RemoteCommandHandler",
    "CommandResult",
    "HELP_TEXT",
    "HELP_OVERVIEW",
    "KEYWORD_MAP",
]

# Phase 51.1: Hilfe ist in thematische Sektionen aufgeteilt (help_sections.py).
# HELP_OVERVIEW – kurze Kategorien-Übersicht (Default bei "hilfe")
# HELP_TEXT      – Volltext aller Sektionen (bei "hilfe alles", Tests, Validierung)
HELP_OVERVIEW = build_overview()
HELP_TEXT = build_full_help()

# Phase 51.3: Füllwörter am Satzanfang, die vor Command-Erkennung entfernt werden.
# Konservativ gehalten (nur neutrale Höflichkeits- und Aufforderungs-Floskeln),
# damit keine Kollisionen mit bestehenden Keywords entstehen.
_FILLER_PREFIXES: tuple[str, ...] = (
    "kannst du mir mal",
    "kannst du mir bitte",
    "kannst du mir",
    "kannst du mal",
    "kannst du bitte",
    "kannst du",
    "könntest du mir",
    "könntest du",
    "würdest du",
    "zeig mir mal",
    "zeig mir bitte",
    "zeig mir",
    "zeige mir",
    "sag mir mal",
    "sag mir bitte",
    "sag mir",
    "sage mir",
    "gib mir mal",
    "gib mir",
    "check mir mal",
    "check mir",
    "check mal",
    "schau mal",
    "bitte",
    "mal",
)

# Trailing Füllwörter (neutrale Hilfsverben, die nach einem Command folgen
# können, ohne seine Bedeutung zu verändern). Konservativ gehalten.
_FILLER_SUFFIXES: tuple[str, ...] = (
    "bitte",
    "mal",
    "zeigen",
    "anzeigen",
    "ausgeben",
    "checken",
)

# Vorkompilierter Regex: entfernt einen Füllwort-Prefix inkl. optionalem Komma.
_FILLER_PREFIX_RE = re.compile(
    r"^(?:" + "|".join(re.escape(p) for p in _FILLER_PREFIXES) + r")\b[,\s]*",
    re.IGNORECASE,
)

_FILLER_SUFFIX_RE = re.compile(
    r"[,\s]*\b(?:" + "|".join(re.escape(s) for s in _FILLER_SUFFIXES) + r")$",
    re.IGNORECASE,
)


def _strip_fillers(text: str) -> str:
    """Entfernt bekannte Füllwort-Prefixe und -Suffixe iterativ.

    "Kannst du mir mal den Status zeigen" → "den Status"
    "bitte zeig mir status bitte" → "status"
    """
    prev = None
    current = text.strip()
    while prev != current:
        prev = current
        current = _FILLER_PREFIX_RE.sub("", current).strip()
        current = _FILLER_SUFFIX_RE.sub("", current).strip()
    return current or text.strip()


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
        task_client: CalDAVTaskClient | None = None,
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
            tower_agent=tower_agent,
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
                "task_client": task_client,
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
        self._log = LogCommandHandler(
            log_dir=(project_root / "logs") if project_root else None,
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

        # TodoCommandHandler: nur wenn CalDAVTaskClient vorhanden
        self._todos: TodoCommandHandler | None = None
        if task_client is not None:
            self._todos = TodoCommandHandler(
                task_client=task_client,
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
            self._log,
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
        0. Füllwort-Stripping am Satzanfang ("kannst du mir mal ..." → "...")
        1. Hilfe (inkl. ``hilfe <kategorie>`` und ``hilfe alles``)
        2. Exakter Match gegen Simple-Commands aller Handler
        3. Pattern-Match gegen alle Handler-Patterns (in Handler-Reihenfolge)
        4. Keyword-Suche in natürlicher Sprache

        Args:
            text: Nachrichtentext vom Nutzer.

        Returns:
            Normalisierter Command-Name oder None wenn kein Command erkannt.
            Für Hilfe-Unterkategorien wird ``"hilfe:<kategorie>"`` zurückgegeben.
        """
        # Phase 51.3: gestrippte Variante für exakte/Pattern-Matches,
        # originaler Text für Keyword-Suche (Keywords enthalten bewusst
        # natürlichsprachige Floskeln wie "zeig mir den bildschirm").
        original_normalized = text.strip().lower()
        stripped = _strip_fillers(text)
        normalized = stripped.lower()

        # Stufe 1: Hilfe (bleibt im Orchestrator)
        if normalized in ("hilfe", "help"):
            return "hilfe"
        if normalized in ("hilfe alles", "help alles", "hilfe all", "help all"):
            return "hilfe:alles"
        if normalized.startswith(("hilfe ", "help ")):
            category = normalized.split(None, 1)[1].strip()
            if category in CATEGORY_LABELS:
                return f"hilfe:{category}"
            # Unbekannte Kategorie – als Hilfe-Overview + Hinweis behandeln
            return f"hilfe:?{category}"

        # Stufe 2: Exakter Match gegen Simple-Commands
        if normalized in self._simple_commands:
            return normalized

        # Stufe 2a: Pattern-Match am Textanfang (match, höhere Konfidenz)
        for handler in self._handlers:
            for pattern, command, use_original, *rest in handler.patterns:
                use_search = rest[0] if rest else False
                if use_search:
                    continue  # search-Patterns in Stufe 2b
                check_text = text.strip() if use_original else normalized
                if pattern.match(check_text):
                    return command

        # Stufe 2b: Pattern-Suche im Text (search, niedrigere Konfidenz)
        for handler in self._handlers:
            for pattern, command, use_original, *rest in handler.patterns:
                use_search = rest[0] if rest else False
                if not use_search:
                    continue  # Bereits in Stufe 2a geprüft
                check_text = text.strip() if use_original else normalized
                if pattern.search(check_text):
                    return command

        # Stufe 3: Keyword-Suche in natürlicher Sprache.
        # Hier auf dem *originalen* Text (nicht stripped), damit Keywords
        # wie "zeig mir den bildschirm" oder "schau mal im netz" weiter greifen.
        for handler in self._handlers:
            for command, keywords in handler.keywords.items():
                for keyword in keywords:
                    if keyword in original_normalized:
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
        # Hilfe bleibt im Orchestrator (Phase 51.1)
        if command in ("hilfe", "help"):
            return CommandResult(command="hilfe", success=True, text=HELP_OVERVIEW)
        if command == "hilfe:alles":
            return CommandResult(command="hilfe", success=True, text=HELP_TEXT)
        if command.startswith("hilfe:?"):
            unknown = command[len("hilfe:?"):]
            text = (
                f"Unbekannte Hilfe-Kategorie: '{unknown}'.\n\n" + HELP_OVERVIEW
            )
            return CommandResult(command="hilfe", success=True, text=text)
        if command.startswith("hilfe:"):
            category = command.split(":", 1)[1]
            section = get_section(category)
            if section:
                return CommandResult(command="hilfe", success=True, text=section)
            return CommandResult(command="hilfe", success=True, text=HELP_OVERVIEW)

        # Handler-Lookup (alle Commands bei Init registriert)
        handler = self._command_handler_map.get(command)
        if handler:
            return handler.execute(command, raw_text)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Command: {command}",
        )

    def suggest_command(self, text: str) -> str | None:
        """Did-you-mean Vorschlag wenn parse_command fehlgeschlagen ist.

        Nutzt ``difflib.get_close_matches`` auf den ersten Token der Eingabe
        gegen die aggregierten Simple-Commands aller Handler. Rückgabe ist
        ein fertig formatierter Hinweistext oder ``None`` wenn kein hinreichend
        ähnlicher Command gefunden wurde (cutoff 0.75).

        Phase 51.2.
        """
        stripped = _strip_fillers(text).lower()
        if not stripped:
            return None
        tokens = stripped.split()
        # Nur bei sehr kurzen Eingaben (max. 2 Tokens) vorschlagen –
        # sonst würden ganze Sätze, die ans LLM gehen sollen, abgefangen.
        if len(tokens) > 2:
            return None
        first_token = tokens[0]
        if len(first_token) < 4:
            return None
        # Keine Vorschläge wenn das erste Token bereits ein echter Command ist.
        if first_token in self._simple_commands:
            return None
        candidates = sorted(self._simple_commands)
        matches = difflib.get_close_matches(
            first_token, candidates, n=1, cutoff=0.75,
        )
        if not matches:
            return None
        return f"Meintest du '{matches[0]}'? Tippe 'hilfe' für alle Commands."
