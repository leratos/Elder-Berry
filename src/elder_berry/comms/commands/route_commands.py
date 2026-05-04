"""RouteCommandHandler – Routenplanung via Google Maps Directions API.

Erkennt natürliche Spracheingaben wie:
- "plane meine fahrt zu Lisa"
- "fahrt von Mama zu Lisa, morgen um 16 uhr"
- "wie komme ich zu Lisa"
- "navigation zu Lisa"

Löst Kontaktnamen über ContactStore auf, berechnet Fahrtdauer via
RoutePlanner und liefert Abfahrtszeit + Google-Maps-Link.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandPlugin,
    CommandResult,
    HandlerContext,
    user_friendly_error,
)

if TYPE_CHECKING:
    from elder_berry.tools.contact_store import ContactStore
    from elder_berry.tools.route_planner import RoutePlanner

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# "fahrt von Mama zu Lisa, morgen 16 uhr"
ROUTE_FROM_TO_PATTERN = re.compile(
    r"(?:plane|berechne|navigation)?\s*"
    r"(?:meine\s+)?(?:fahrt|reise|route|weg)?\s*"
    r"von\s+(.+?)\s+(?:zu|nach|richtung)\s+(.+)",
    re.IGNORECASE,
)

# "plane (meine) fahrt/reise/route zu Lisa"
# "wie komme ich zu Lisa"
# "navigation zu Lisa"
ROUTE_PLAN_PATTERN = re.compile(
    r"(?:plane|planen|berechne|navigation|navigiere|"
    r"wie\s+(?:komme|fahre)\s+ich)\s+"
    r"(?:meine\s+)?(?:fahrt|reise|route|weg)?\s*"
    r"(?:zu|nach|richtung)\s+(.+)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Zeitparser
# ---------------------------------------------------------------------------

_TIME_PATTERN = re.compile(
    r"(?:um\s+)?(\d{1,2})(?::(\d{2}))?\s*(?:uhr)?",
    re.IGNORECASE,
)

_WEEKDAY_MAP: dict[str, int] = {
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,
    "samstag": 5,
    "sonntag": 6,
}


def parse_arrival_time(text: str) -> datetime | None:
    """Extrahiert Ankunftszeit aus Freitext.

    Unterstützt:
    - "morgen um 16 uhr" → morgen 16:00
    - "übermorgen 10 uhr" → übermorgen 10:00
    - "um 14:30" → heute 14:30
    - "freitag um 9" → nächster Freitag 09:00
    - Keine Zeitangabe → None

    Returns:
        datetime oder None wenn keine Zeitangabe erkannt.
    """
    # Uhrzeit extrahieren
    time_match = _TIME_PATTERN.search(text)
    if not time_match:
        return None

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    if hour > 23 or minute > 59:
        return None

    now = datetime.now()
    target_date = now.date()

    text_lower = text.lower()

    # Datum-Keywords prüfen
    if "übermorgen" in text_lower:
        target_date = now.date() + timedelta(days=2)
    elif "morgen" in text_lower:
        target_date = now.date() + timedelta(days=1)
    else:
        # Wochentag prüfen
        for day_name, day_num in _WEEKDAY_MAP.items():
            if day_name in text_lower:
                days_ahead = day_num - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                target_date = now.date() + timedelta(days=days_ahead)
                break

    return datetime(target_date.year, target_date.month, target_date.day, hour, minute)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class RouteCommandHandler(CommandHandler):
    """Routenplanung via Google Maps Directions API."""

    def __init__(
        self,
        route_planner: RoutePlanner,
        contact_store: ContactStore,
        default_user_id: str = "",
    ) -> None:
        self._planner = route_planner
        self._contacts = contact_store
        self._default_user_id = default_user_id

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            # "von X zu Y" muss vor "zu Y" stehen (spezifischer)
            (ROUTE_FROM_TO_PATTERN, "route_from_to", False, True),
            (ROUTE_PLAN_PATTERN, "route_plan", False, True),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "route_plan": [
                "plane fahrt",
                "plane reise",
                "plane route",
                "navigation zu",
                "navigiere zu",
                "wie komme ich",
                "wie fahre ich",
                "route zu",
                "fahrt zu",
            ],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "plane fahrt zu <Name>: Route von Zuhause zu Kontakt berechnen",
            "fahrt von <Name> zu <Name>: Route zwischen zwei Kontakten",
            "wie komme ich zu <Name>: Route von Zuhause berechnen",
            'Optional Ankunftszeit: "morgen um 16 uhr", "übermorgen 10 uhr"',
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "route_from_to":
            return self._cmd_route_from_to(raw_text)

        if command == "route_plan":
            return self._cmd_route_plan(raw_text)

        return CommandResult(command=command, success=False, fallthrough=True)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _cmd_route_from_to(self, raw_text: str) -> CommandResult:
        """Route von X nach Y (expliziter Start)."""
        m = ROUTE_FROM_TO_PATTERN.search(raw_text)
        if not m:
            return CommandResult(
                command="route_from_to",
                success=False,
                fallthrough=True,
            )
        origin_name = m.group(1).strip()
        dest_name = m.group(2).strip()
        # Zeitangabe aus dest_name entfernen
        dest_name = self._strip_time_suffix(dest_name)
        return self._plan_route(origin_name, dest_name, raw_text)

    def _cmd_route_plan(self, raw_text: str) -> CommandResult:
        """Route von Zuhause nach Y."""
        m = ROUTE_PLAN_PATTERN.search(raw_text)
        if not m:
            return CommandResult(
                command="route_plan",
                success=False,
                fallthrough=True,
            )
        dest_name = m.group(1).strip()
        dest_name = self._strip_time_suffix(dest_name)
        return self._plan_route(None, dest_name, raw_text)

    def _plan_route(
        self,
        origin_name: str | None,
        dest_name: str,
        raw_text: str,
    ) -> CommandResult:
        """Kernlogik: Adressen auflösen → API → Antwort formatieren."""
        command = "route_from_to" if origin_name else "route_plan"

        # 1. Adressen auflösen
        origin_addr = self._resolve_address(origin_name)
        dest_addr = self._resolve_address(dest_name)

        if not origin_addr:
            is_home = origin_name is None or origin_name.lower() in self._HOME_SYNONYMS
            if is_home:
                return CommandResult(
                    command=command,
                    success=True,
                    text="Bitte lege einen Kontakt mit Gruppe 'home' an, "
                    "damit ich deinen Startpunkt kenne.",
                )
            return CommandResult(
                command=command,
                success=True,
                text=f"Ich konnte keine Adresse für '{origin_name}' finden. "
                f"Ist eine Adresse im Kontakt hinterlegt?",
            )

        if not dest_addr:
            return CommandResult(
                command=command,
                success=True,
                text=f"Ich konnte keine Adresse für '{dest_name}' finden. "
                f"Verwende einen Kontaktnamen oder eine direkte Adresse "
                f"(z.B. Musterstr. 1, 12345 Berlin).",
            )

        # 2. Ankunftszeit parsen
        arrival = parse_arrival_time(raw_text)

        # 3. Route abfragen
        try:
            from elder_berry.tools.route_planner import RouteError

            result = self._planner.get_route(origin_addr, dest_addr)
        except RouteError as e:
            return CommandResult(
                command=command,
                success=True,
                text=user_friendly_error(e, "Route"),
            )
        except Exception as e:
            logger.error("Route-API Fehler: %s", e)
            return CommandResult(
                command=command,
                success=True,
                text=user_friendly_error(e, "Routenberechnung"),
            )

        # 4. Abfahrtszeit berechnen (wenn Ankunftszeit angegeben)
        departure_info = ""
        if arrival:
            departure = self._planner.calculate_departure(
                arrival,
                result.duration_seconds,
            )
            departure_info = (
                f"Du solltest spätestens um {departure.strftime('%H:%M')} "
                f"losfahren ({self._planner.buffer_minutes} Min Puffer).\n"
            )

        # 5. Google Maps Link
        link = self._planner.generate_maps_link(origin_addr, dest_addr)

        # 6. Antwort zusammenbauen
        response = (
            f"Route zu {dest_name}:\n"
            f"{result.end_address}\n"
            f"Fahrtdauer: {result.duration_text} ({result.distance_text})\n"
            f"{departure_info}"
            f"{link}"
        )
        return CommandResult(command=command, success=True, text=response)

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    # Synonyme für "von mir" / "von zuhause" → Home-Lookup
    _HOME_SYNONYMS = {"mir", "zuhause", "daheim", "home", "zu hause", "meiner"}

    # Heuristik: enthält Ziffern + mindestens ein Wort → wahrscheinlich
    # eine direkte Adresse, kein Kontaktname
    _ADDRESS_PATTERN = re.compile(
        r"\d+.*[a-zA-ZäöüÄÖÜß]|[a-zA-ZäöüÄÖÜß].*\d+",
    )

    def _resolve_address(self, name: str | None) -> str | None:
        """Kontaktname oder direkte Adresse auflösen.

        None oder Home-Synonym → Home-Kontakt (Gruppe 'home')
        Enthält Ziffern (Hausnummer/PLZ) → direkte Adresse
        'Lisa' → ContactStore fuzzy search → address-Feld
        """
        if name is None or name.lower() in self._HOME_SYNONYMS:
            homes = self._contacts.find_by_group(
                self._default_user_id,
                "home",
            )
            if homes:
                addr = homes[0].address
                return addr if addr else None
            return None

        # Anführungszeichen entfernen (User schreibt "Am Brendegraben 21")
        cleaned = name.strip().strip('"').strip("'").strip()

        # Direkte Adresse? (enthält Ziffern → Hausnummer oder PLZ)
        if self._ADDRESS_PATTERN.search(cleaned):
            return cleaned

        # Kontaktname → ContactStore
        results = self._contacts.search(self._default_user_id, name)
        if not results:
            return None
        contact = results[0]
        return contact.address if contact.address else None

    @staticmethod
    def _strip_time_suffix(name: str) -> str:
        """Entfernt Zeitangaben am Ende des Namens.

        'lisa, morgen um 16 uhr' → 'lisa'
        'lisa morgen 16 uhr' → 'lisa'
        """
        # Komma-Trennung: alles nach dem Komma ist vermutlich Zeitangabe
        if "," in name:
            name = name.split(",")[0].strip()
        # Zeitangabe ohne Komma: "lisa morgen um 16 uhr"
        for keyword in ("ankunft", "morgen", "übermorgen", "um ", "heute"):
            idx = name.lower().find(keyword)
            if idx > 0:
                name = name[:idx].strip()
                break
        # Wochentage
        for day in _WEEKDAY_MAP:
            idx = name.lower().find(day)
            if idx > 0:
                name = name[:idx].strip()
                break
        return name


# ---------------------------------------------------------------------------
# Phase 77: Plugin-Manifest
# ---------------------------------------------------------------------------

HELP_SECTION_ROUTE = """Routenplanung:
  plane fahrt zu <Name> -- Route von Zuhause zu Kontakt
  fahrt von <Name> zu <Name> -- Route zwischen zwei Kontakten
  wie komme ich zu <Name> -- Route von Zuhause
  Optional: "morgen um 16 uhr", "uebermorgen 10 uhr" -> Abfahrtszeit"""


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    if ctx.route_planner is None or ctx.contact_store is None:
        return None
    return RouteCommandHandler(
        route_planner=ctx.route_planner,
        contact_store=ctx.contact_store,
        default_user_id=ctx.default_user_id,
    )


PLUGIN = CommandPlugin(
    name="route",
    priority=76,
    category="web",
    help_section=HELP_SECTION_ROUTE,
    factory=_factory,
)
