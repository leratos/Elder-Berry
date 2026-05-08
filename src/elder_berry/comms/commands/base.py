"""CommandHandler ABC – Basisklasse für domänenspezifische Command-Handler.

Jeder Handler registriert seine Patterns und Keywords und kann
Commands parsen und ausführen.

Phase 77: Plugin-Registry-Format (CommandPlugin) und Service-Container
(HandlerContext) leben hier, damit jeder Handler sie ohne Zirkular-Import
nutzen kann.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from elder_berry.actions.base import ActionController
    from elder_berry.actions.computer_use import ComputerUseController
    from elder_berry.avatar.base import AvatarRenderer
    from elder_berry.comms.briefing_scheduler import BriefingScheduler
    from elder_berry.comms.pending_confirmation import PendingConfirmationStore
    from elder_berry.core.audio_router import AudioRouter
    from elder_berry.core.secret_store import SecretStore
    from elder_berry.core.tower_agent import TowerAgent
    from elder_berry.llm.anthropic_client import AnthropicClient
    from elder_berry.robot.client import RobotClient
    from elder_berry.system.info import SystemMonitor
    from elder_berry.tools.brave_search_client import BraveSearchClient
    from elder_berry.tools.caldav_tasks import CalDAVTaskClient
    from elder_berry.tools.carddav_sync import CardDAVSyncClient
    from elder_berry.tools.contact_store import ContactStore
    from elder_berry.tools.document_classifier import DocumentClassifier
    from elder_berry.tools.document_reader import DocumentReader
    from elder_berry.tools.email_client import IMAPEmailClient
    from elder_berry.tools.google_calendar import GoogleCalendarClient
    from elder_berry.tools.gym_data import GymDataClient
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient
    from elder_berry.tools.note_store import NoteStore
    from elder_berry.tools.reminder_store import ReminderStore
    from elder_berry.tools.route_planner import RoutePlanner
    from elder_berry.tools.stirling_pdf import StirlingPDFClient
    from elder_berry.tools.weather_client import WeatherClient
    from elder_berry.tools.web_fetcher import WebFetcher

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Ergebnis eines ausgeführten Remote-Commands."""

    command: str
    """Name des erkannten Commands (z.B. 'status', 'screenshot')."""

    success: bool
    """True wenn der Command erfolgreich ausgeführt wurde."""

    text: str | None = None
    """Text-Antwort für den Nutzer (z.B. Systemstatus)."""

    history_text: str | None = None
    """Alternativer Text für die Chat-History (z.B. Mail-Body für LLM-Kontext).
    Wenn gesetzt, wird dieser statt `text` in der History gespeichert."""

    image_path: Path | None = None
    """Pfad zum generierten Bild (z.B. Screenshot-PNG)."""

    file_path: Path | None = None
    """Pfad zur Datei die gesendet werden soll (z.B. PDF)."""

    file_paths: list[Path] = field(default_factory=list)
    """Mehrere Dateien zum Senden (z.B. Mail-Anhänge)."""

    restart: bool = False
    """True wenn der Bot nach diesem Command neu starten soll."""

    pending_confirmation: bool = False
    """True wenn diese Aktion eine Nutzer-Bestätigung erfordert.
    Die Bridge erstellt dann eine PendingAction aus pending_data."""

    pending_data: dict[str, Any] | None = None
    """Daten für die PendingAction (z.B. Draft-Text, Empfänger).
    Nur relevant wenn pending_confirmation=True."""

    fallthrough: bool = False
    """True wenn der Command nichts gefunden hat und die Bridge
    zum LLM-Fallback weiterleiten soll."""

    list_items: list[dict[str, Any]] | None = None
    """Phase 80: Strukturierte Mehrfachergebnisse, die der Bridge in den
    ConversationListStore registriert (zusammen mit ``list_type``).
    Reihenfolge entspricht der User-sichtbaren Nummerierung in ``text``
    (1-basiert). None wenn der Command keine Liste liefert."""

    list_type: str | None = None
    """Phase 80: Listen-Typ fuer den ConversationListStore-Key
    (z.B. ``"search"``, ``"mail_inbox"``, ``"note_search"``). None wenn
    ``list_items`` ungesetzt ist."""


@dataclass
class PatternMatch:
    """Ergebnis eines Pattern-Checks."""

    command: str
    """Normalisierter Command-Name."""

    use_original_text: bool = False
    """True wenn parse_command den Originaltext (case-sensitiv) statt
    normalisierten Text verwenden soll (z.B. bei Pfad-Erkennung)."""


class CommandHandler(ABC):
    """Basisklasse für domänenspezifische Command-Handler.

    Jeder Handler definiert:
    - simple_commands: Set von Commands ohne Parameter (exakter Match)
    - patterns: Liste von (Pattern, command_name, use_original) Tuples
    - keywords: Dict von command_name → Keyword-Liste
    - execute(): Führt einen erkannten Command aus
    """

    @property
    def simple_commands(self) -> set[str]:
        """Commands ohne Parameter (exakter Match auf normalized text)."""
        return set()

    @property
    def patterns(self) -> list[tuple[re.Pattern[str], str, bool, bool]]:
        """Regex-Patterns für parametrierte Commands.

        Returns:
            Liste von (compiled_pattern, command_name, use_original_text, use_search).
            use_original_text=True wenn der Pattern auf den Originaltext
            (nicht normalisierten) geprüft werden soll.
            use_search=True für pattern.search() statt pattern.match().
        """
        return []

    @property
    def keywords(self) -> dict[str, list[str]]:
        """Keyword-Map für natürliche Sprache.

        Returns:
            Dict von command_name → Liste von Keywords.
        """
        return {}

    @property
    def command_descriptions(self) -> list[str]:
        """Kompakte Beschreibungen aller Commands dieses Handlers.

        Wird von RemoteCommandHandler.get_command_summary() genutzt um
        den dynamischen Command-Block im System-Prompt zu generieren.

        Returns:
            Liste von Beschreibungs-Strings, z.B.
            ["mails: Ungelesene E-Mails anzeigen",
             "mail suche <begriff>: E-Mails durchsuchen"]
        """
        return []

    @staticmethod
    def not_configured(
        command: str,
        service: str,
        setup_step: int | None = None,
    ) -> CommandResult:
        """Einheitliche Antwort wenn ein Dienst nicht konfiguriert ist.

        Args:
            command: Command-Name für das CommandResult.
            service: Anzeigename des Dienstes (z.B. "E-Mail", "Nextcloud").
            setup_step: Optionale Schritt-Nummer im Setup-Wizard.
        """
        hint = "Einrichten unter http://localhost:8090/setup"
        if setup_step is not None:
            hint += f" (Schritt {setup_step})"
        return CommandResult(
            command=command,
            success=False,
            text=f"⚠ {service} nicht konfiguriert. {hint}",
        )

    @abstractmethod
    def execute(self, command: str, raw_text: str) -> CommandResult:
        """Führt einen erkannten Command aus.

        Args:
            command: Normalisierter Command-Name.
            raw_text: Originaler Nachrichtentext (für Parameter-Extraktion).

        Returns:
            CommandResult mit Ergebnis.
        """


# ---- Setup-Step-Mapping für not_configured()-Hinweise ----
SETUP_STEPS: dict[str, int] = {
    "llm": 2,
    "anthropic": 2,
    "ollama": 2,
    "matrix": 3,
    "nextcloud": 4,
    "caldav": 4,
    "carddav": 4,
    "cloud": 4,
    "email": 5,
    "imap": 5,
    "smtp": 5,
    "standort": 6,
    "wetter": 6,
    "brave": 7,
    "elevenlabs": 7,
    "groq": 7,
    "google_maps": 7,
    "rpi": 7,
    "gym": 7,
    "harmony": 7,
}


def user_friendly_error(exc: Exception, context: str = "") -> str:
    """Wandelt eine Exception in eine nutzerfreundliche Fehlermeldung um.

    Args:
        exc: Die aufgetretene Exception.
        context: Optionaler Kontext (z.B. "E-Mail-Abfrage", "Kalender").

    Returns:
        Nutzerfreundlicher Fehlertext mit Handlungsempfehlung.
    """
    prefix = f"{context}: " if context else ""
    exc_type = type(exc).__name__
    exc_str = str(exc)

    # --- Netzwerk / Verbindung ---
    if isinstance(exc, ConnectionError) or "ConnectionRefused" in exc_type:
        return (
            f"❌ {prefix}Server nicht erreichbar. "
            "Prüfe ob der Dienst läuft und die Adresse stimmt."
        )

    if isinstance(exc, TimeoutError) or "Timeout" in exc_type:
        return (
            f"❌ {prefix}Zeitüberschreitung. "
            "Der Server antwortet nicht. Versuch es gleich nochmal."
        )

    if "ConnectError" in exc_type or "ConnectionError" in exc_type:
        return (
            f"❌ {prefix}Verbindung fehlgeschlagen. "
            "Prüfe Netzwerk und Server-Erreichbarkeit."
        )

    # --- Auth / API ---
    if "401" in exc_str or "Unauthorized" in exc_str:
        return (
            f"❌ {prefix}Zugangsdaten ungültig oder abgelaufen. "
            "Neu konfigurieren unter http://localhost:8090/setup"
        )

    if "403" in exc_str or "Forbidden" in exc_str:
        return (
            f"❌ {prefix}Zugriff verweigert. Prüfe ob die Berechtigungen korrekt sind."
        )

    if "404" in exc_str or "Not Found" in exc_str:
        return f"❌ {prefix}Nicht gefunden. Prüfe ob die Adresse/Ressource existiert."

    if "429" in exc_str or "RateLimit" in exc_type or "rate" in exc_str.lower():
        return f"❌ {prefix}Zu viele Anfragen. Warte kurz und versuch es dann nochmal."

    if "5" == exc_str[:1] and len(exc_str) >= 3 and exc_str[1:3].isdigit():
        return (
            f"❌ {prefix}Serverfehler ({exc_str[:3]}). "
            "Der Dienst hat ein Problem. Versuch es später nochmal."
        )

    # --- Dateisystem ---
    if isinstance(exc, FileNotFoundError):
        return f"❌ {prefix}Datei nicht gefunden: {exc}"

    if isinstance(exc, PermissionError):
        return f"❌ {prefix}Keine Berechtigung für diese Datei/diesen Ordner."

    if isinstance(exc, OSError) and "disk" in exc_str.lower():
        return f"❌ {prefix}Speicherplatz-Problem. Prüfe den verfügbaren Platz."

    # --- Daten / Parsing ---
    if isinstance(exc, (ValueError, KeyError)):
        return f"❌ {prefix}Ungültige Daten: {exc}"

    # --- Fallback: kurze Beschreibung ohne Stacktrace ---
    short = exc_str if len(exc_str) <= 120 else exc_str[:117] + "..."
    logger.debug("user_friendly_error fallback für %s: %s", exc_type, exc_str)
    return f"❌ {prefix}Fehler: {short}"


# ---------------------------------------------------------------------------
# Phase 77: Plugin-Registry
# ---------------------------------------------------------------------------


@dataclass
class HandlerContext:
    """Service-Container für Plugin-Factories (Phase 77).

    Ersetzt die alte Kwargs-Liste in ``RemoteCommandHandler.__init__``.
    Jede Factory liest, was sie braucht; optionale Felder sind ``None``,
    wenn der Service nicht konfiguriert ist. Field-Namen und -Typen
    spiegeln die bisherigen Konstruktor-Parameter 1:1, damit Migration
    in Etappe 2 mechanisch bleibt.
    """

    # --- Pflicht-/Quasi-Pflicht-Felder (in der Praxis fast immer gesetzt) ---
    project_root: Path | None = None
    secret_store: SecretStore | None = None
    default_user_id: str = ""

    # --- Aktionen / System ---
    system_monitor: SystemMonitor | None = None
    controller: ActionController | None = None
    download_dir: Path | None = None
    avatar_renderer: AvatarRenderer | None = None
    send_file_allowed_roots: tuple[Path, ...] | None = None
    audio_router: AudioRouter | None = None
    computer_use: ComputerUseController | None = None
    robot_client: RobotClient | None = None
    tower_agent: TowerAgent | None = None
    anthropic_client: AnthropicClient | None = None

    # --- Tools ---
    weather: WeatherClient | None = None
    reminder_store: ReminderStore | None = None
    briefing_scheduler: BriefingScheduler | None = None
    email_client: IMAPEmailClient | None = None
    calendar: GoogleCalendarClient | None = None
    note_store: NoteStore | None = None
    contact_store: ContactStore | None = None
    task_client: CalDAVTaskClient | None = None
    pending_store: PendingConfirmationStore | None = None
    nextcloud_files: NextcloudFilesClient | None = None
    document_classifier: DocumentClassifier | None = None
    stirling_pdf: StirlingPDFClient | None = None
    route_planner: RoutePlanner | None = None
    web_fetcher: WebFetcher | None = None
    search_client: BraveSearchClient | None = None
    document_reader: DocumentReader | None = None
    gym_client: GymDataClient | None = None
    carddav_sync: CardDAVSyncClient | None = None


@dataclass(frozen=True)
class CommandPlugin:
    """Selbstbeschreibung eines Command-Handlers (Phase 77).

    Jedes Plugin-Modul exportiert genau ein PLUGIN-Objekt auf Modul-Ebene.
    Die Registry erkennt das automatisch (siehe registry.py).
    """

    name: str
    """Eindeutiger, snake_case Name. Wird als Key für Lookup, Help-Sektion
    und Logging genutzt."""

    priority: int
    """Niedrigere Zahl = früher geprüft. Empfohlene Werte:
    0–9     – kritische Pre-Filter (selten)
    10–49   – domänenspezifische Commands mit Pattern-Konflikten
    50–89   – normale Commands
    90–99   – Catch-All (z.B. AdvancedCommands für LLM-Fallback)"""

    category: str
    """Hilfe-Kategorie (siehe help_sections.CATEGORY_LABELS).
    Neue Kategorien müssen dort registriert werden."""

    help_section: str
    """Help-Text dieser Domäne. Wird in build_full_help() aggregiert
    (Etappe 2: aktuell parallel zur statischen HELP_SECTIONS-Map)."""

    factory: Callable[[HandlerContext], "CommandHandler | None"]
    """Konstruktor-Funktion. Liest aus HandlerContext, was sie braucht.
    Darf None zurückgeben, wenn benötigte Services fehlen
    (z.B. NoteStore=None → kein NoteHandler)."""

    requires: tuple[str, ...] = field(default_factory=tuple)
    """Plugin-Namen, deren Handler vor diesem laufen müssen.
    Liefert Konflikt-Constraint für die Sortierung (Etappe 3)."""

    conflicts: tuple[str, ...] = field(default_factory=tuple)
    """Plugin-Namen, mit denen Patterns kollidieren könnten.
    Triggert Pattern-Konflikt-Test in CI (Etappe 3)."""

    version: str = "1.0.0"
    """Plugin-Version. Macht später Migrations möglich."""
