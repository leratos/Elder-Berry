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
- NoteCommandHandler: Wissensdatenbank/Fakten (optional, benötigt FactStore).
  Notiz-Commands liefern in Phase 91-A einen Stub bis Phase 91-B/C
  NextcloudNotesClient ausrollt.
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

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandResult,
    HandlerContext,
)
from elder_berry.comms.commands.help_sections import (
    CATEGORY_LABELS,
    build_full_help,
    build_overview,
    get_section,
)
from elder_berry.comms.commands.registry import load_plugins

# Phase 77 Etappe 2: Alle 23 Handler werden ueber die Plugin-Registry geladen
# (registry.py importiert sie via importlib). Direkt-Imports hier nicht mehr noetig.

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
    from elder_berry.tools.fact_store import FactStore
    from elder_berry.tools.contact_store import ContactStore
    from elder_berry.tools.caldav_tasks import CalDAVTaskClient
    from elder_berry.tools.reminder_store import ReminderStore
    from elder_berry.tools.weather_client import WeatherClient
    from elder_berry.tools.carddav_sync import CardDAVSyncClient
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient
    from elder_berry.tools.nextcloud_notes_client import NextcloudNotesClient
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

    ACHTUNG: Diese Funktion entfernt AUCH Suffix-Filler ("bitte", "mal",
    "zeigen" etc. am Wortende). Das ist OK fuer den ``parse_command``-
    Pfad, der den Text bewusst zur Routing-Erkennung normalisiert und
    den Inhalt nicht durchschleift. Fuer den ``execute()``-Pfad, der
    User-Content an die Sub-Handler reicht (clip:, notiz:, mail-reply
    etc.), wuerde Suffix-Strip Daten verstuemmeln -- nimm dort
    ``_strip_filler_prefix`` (siehe unten).
    """
    prev = None
    current = text.strip()
    while prev != current:
        prev = current
        current = _FILLER_PREFIX_RE.sub("", current).strip()
        current = _FILLER_SUFFIX_RE.sub("", current).strip()
    return current or text.strip()


def _strip_filler_prefix(text: str) -> str:
    """Entfernt NUR Prefix-Filler -- nicht den Suffix.

    Phase Filler-Strip-in-execute (2026-05-12, Option X4a):
    der ``execute()``-Pfad in ``RemoteCommandHandler`` reicht den Text
    an Sub-Handler weiter, die ihn als Command + User-Content
    re-parsen. Wenn der User-Content auf einem Filler-Token endet
    (z.B. ``clip: hallo bitte`` -- Clipboard soll wirklich ``hallo
    bitte`` enthalten), wuerde der volle ``_strip_fillers`` den
    Inhalt verstuemmeln. Deshalb gibt es diesen Prefix-only-Helper.

    Asymmetrie zu ``_strip_fillers`` ist gewollt:

    - ``parse_command``  -> ``_strip_fillers``      (Prefix + Suffix)
      ... bewusste Normalisierung fuer Routing, Inhalt wird nicht
      durchgereicht.
    - ``execute()``      -> ``_strip_filler_prefix`` (nur Prefix)
      ... User-Content darf am Ende erhalten bleiben.

    Codex-Reviewer P2 (2026-05-11) hat diesen Bug-Mechanismus
    aufgedeckt -- siehe ``docs/concepts/filler-strip-in-execute.md``.
    Bitte NIEMALS ``_strip_fillers`` im execute()-Pfad verwenden,
    sonst kehrt der Suffix-Verlust-Bug zurueck.

    Beispiele:

    - "kannst du mir mal clip: hallo bitte"
      -> "clip: hallo bitte" (Prefix weg, Suffix bleibt -- richtig)
    - "bitte notiz: meld dich mal"
      -> "notiz: meld dich mal" (Suffix-"mal" bleibt erhalten)
    - "zeig mir mal status"
      -> "status" (Prefix weg, kein Suffix vorhanden)
    """
    prev = None
    current = text.strip()
    while prev != current:
        prev = current
        current = _FILLER_PREFIX_RE.sub("", current).strip()
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

    # Phase 82 Hotfix B (2026-05-10): Cap fuer die Keyword-Suche-Stufe
    # in parse_command. Ueber dieser Schwelle (gemessen am gestrippten
    # Text, also nach Filler-Removal) wird Stufe 3 uebersprungen und der
    # Bridge faellt auf den LLM-Pfad zurueck. Verhindert, dass Multi-
    # Action-Anfragen wie "erstell 3 todos UND schreib notiz UND ..."
    # an einer Substring-Erkennung ("todos" -> Listenanzeige) haengen
    # bleiben, bevor Saleria action_sequence emittieren kann.
    # 8 ist grosszuegig: bestehende keyword-Tests liegen alle bei <= 6
    # Wortern (nach Filler-Strip).
    _MAX_KEYWORD_PHRASE_WORDS: int = 8

    def __init__(
        self,
        ctx: HandlerContext | None = None,
        *,
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
        fact_store: FactStore | None = None,
        contact_store: ContactStore | None = None,
        task_client: CalDAVTaskClient | None = None,
        robot_client: RobotClient | None = None,
        anthropic_client: AnthropicClient | None = None,
        nextcloud_files: NextcloudFilesClient | None = None,
        nextcloud_notes: NextcloudNotesClient | None = None,
        stirling_pdf: StirlingPDFClient | None = None,
        document_classifier: DocumentClassifier | None = None,
        carddav_sync: CardDAVSyncClient | None = None,
        route_planner: RoutePlanner | None = None,
        pending_store: PendingConfirmationStore | None = None,
        default_user_id: str = "",
        tower_agent: TowerAgent | None = None,
    ) -> None:
        # Phase 77 Etappe 2: HandlerContext aus Kwargs aufbauen, falls nicht
        # explizit uebergeben (Backwards-Compat-Shim laut Konzept §8). Aufrufer
        # sollten zu ctx=HandlerContext(...) migrieren -- die Kwarg-Liste wird
        # 6 Monate nach Phase 77 entfernt.
        if ctx is None:
            ctx = HandlerContext(
                project_root=project_root,
                secret_store=secret_store,
                default_user_id=default_user_id,
                system_monitor=system_monitor,
                controller=controller,
                download_dir=download_dir,
                avatar_renderer=avatar_renderer,
                send_file_allowed_roots=send_file_allowed_roots,
                audio_router=audio_router,
                computer_use=computer_use,
                robot_client=robot_client,
                tower_agent=tower_agent,
                anthropic_client=anthropic_client,
                weather=weather,
                reminder_store=reminder_store,
                briefing_scheduler=briefing_scheduler,
                email_client=email_client,
                calendar=calendar,
                fact_store=fact_store,
                contact_store=contact_store,
                task_client=task_client,
                pending_store=pending_store,
                nextcloud_files=nextcloud_files,
                nextcloud_notes=nextcloud_notes,
                document_classifier=document_classifier,
                stirling_pdf=stirling_pdf,
                route_planner=route_planner,
                web_fetcher=web_fetcher,
                search_client=search_client,
                document_reader=document_reader,
                gym_client=gym_client,
                carddav_sync=carddav_sync,
            )
        self._ctx = ctx

        # Phase 77 Etappe 2: Konzept §3.5 -- Handler-Liste wird komplett aus
        # der Plugin-Registry gefuellt. Reihenfolge ergibt sich aus priority
        # (siehe einzelne PLUGIN-Manifeste). Frueher kritische Constraints
        # (weather VOR calendar, mail VOR calendar, turntable VOR camera) sind
        # jetzt durch die priority-Werte kodifiziert, nicht durch implizite
        # Listen-Position.
        self._handlers: list[CommandHandler] = []
        for plugin in load_plugins():
            handler = plugin.factory(ctx)
            if handler is None:
                continue
            self._handlers.append(handler)
            # Backwards-Compat: bestehende Tests greifen direkt auf
            # self._<plugin_name> zu (z.B. self._calendar._last_events).
            # Wird in 6 Monaten zusammen mit den Legacy-Kwargs entfernt.
            setattr(self, f"_{plugin.name}", handler)

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
        #
        # Phase 82 Hotfix B (2026-05-10): zwei Schutzschichten gegen False-
        # Positives, die action_sequence aushebeln (Multi-Action-Anfragen
        # wie "erstell 3 todos UND schreib notiz UND ..." landeten frueher
        # auf "todos"-Listen-Anzeige, weil "todos" als Substring matchte).
        #
        # 1) Length-Cap auf den GESTRIPPTEN Text: ueber 8 Wortern ist die
        #    Anfrage typischerweise eine Beschreibung mehrerer Aktionen
        #    oder eine komplexe Frage -- der LLM soll entscheiden, nicht
        #    der Keyword-Matcher. Filler werden vorher abgeschnitten,
        #    damit hoefliche Variants ("kannst du mir mal die offenen
        #    todos zeigen") weiterhin durchkommen.
        # 2) Wort-Boundary statt Substring-Check: verhindert, dass z.B.
        #    "todoslisten" das keyword "todos" matcht.
        if len(stripped.split()) <= self._MAX_KEYWORD_PHRASE_WORDS:
            for handler in self._handlers:
                for command, keywords in handler.keywords.items():
                    for keyword in keywords:
                        kw_pattern = rf"(?<!\w){re.escape(keyword)}(?!\w)"
                        if re.search(kw_pattern, original_normalized):
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
        # Phase Filler-Strip-in-execute (2026-05-12, Option X4a):
        # parse_command strippt Filler vor dem Pattern-Match, aber Bridge
        # reicht den ORIGINALEN msg.body an execute() durch. Die _cmd_*-
        # Methoden re-parsen den Text mit demselben Pattern -- ohne
        # Filler-Strip wuerde z.B. "bitte notiz löschen #1" zwar das
        # Routing passieren, im Re-Parse aber an "bitte" haengen.
        #
        # WICHTIG: hier nur ``_strip_filler_prefix`` (Prefix-only), NICHT
        # ``_strip_fillers``. Letzteres strippt auch Suffix-Filler und
        # wuerde User-Content verstuemmeln (clip: hallo bitte -> clip:
        # hallo). Codex-Reviewer P2 (2026-05-11) hat den Bug-Mechanismus
        # aufgedeckt -- siehe docs/concepts/filler-strip-in-execute.md.
        text = _strip_filler_prefix(raw_text)

        # Hilfe bleibt im Orchestrator (Phase 51.1)
        if command in ("hilfe", "help"):
            return CommandResult(command="hilfe", success=True, text=HELP_OVERVIEW)
        if command == "hilfe:alles":
            return CommandResult(command="hilfe", success=True, text=HELP_TEXT)
        if command.startswith("hilfe:?"):
            unknown = command[len("hilfe:?") :]
            text_out = f"Unbekannte Hilfe-Kategorie: '{unknown}'.\n\n" + HELP_OVERVIEW
            return CommandResult(command="hilfe", success=True, text=text_out)
        if command.startswith("hilfe:"):
            category = command.split(":", 1)[1]
            section = get_section(category)
            if section:
                return CommandResult(command="hilfe", success=True, text=section)
            return CommandResult(command="hilfe", success=True, text=HELP_OVERVIEW)

        # Handler-Lookup (alle Commands bei Init registriert)
        handler = self._command_handler_map.get(command)
        if handler:
            return handler.execute(command, text)

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
            first_token,
            candidates,
            n=1,
            cutoff=0.75,
        )
        if not matches:
            return None
        return f"Meintest du '{matches[0]}'? Tippe 'hilfe' für alle Commands."
