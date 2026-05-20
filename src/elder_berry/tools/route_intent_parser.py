"""RouteIntentParser -- NLU-Schicht fuer Multi-Stop-Routenanfragen.

Phase 92 (E2). Zweistufige Pipeline:

1. Pattern-Vorfilter (Regex) -- schnell, billig, deterministisch.
   Erkennt: gibt es ueberhaupt einen Multi-Stop-Hinweis? Trigger sind
   Indikatoren wie "vorher", "auf dem weg", "unterwegs", "abholen",
   mehrere Personen, "ueber X", "via X".
2. Claude Sonnet Tool-Call -- strukturierte Extraktion mit JSON-Schema.
   Nur wenn Pattern-Vorfilter Multi-Stop-Verdacht hat.

Erlaubt dem Handler, Single-Stop-Faelle (Phase 43) ohne LLM-Round-
Trip durchzulassen.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from elder_berry.llm.anthropic_client import AnthropicClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pattern-Vorfilter
# ---------------------------------------------------------------------------

# Multi-Stop-Indikatoren (Disjunktion). "ueber" und "via" sind
# Reise-Stops; "abholen", "einkaufen", "tanken", "holen" sind
# typische Aktivitaeten-Hinweise.
MULTI_STOP_HINTS = re.compile(
    r"\b(vorher|danach|auf dem weg|unterwegs|"
    r"über|ueber|via|"
    r"abholen|einkaufen|tanken|holen|"
    r"einkauf|tankstelle|supermarkt|apotheke)\b",
    re.IGNORECASE,
)

# Mindest-Trigger: irgendein Routing-Verb oder "nach <Ort>".
ROUTE_INTRO = re.compile(
    r"\b(fahrt|fahren|fahre|fahr|route|navig\w+|"
    r"muss\s+nach|"
    r"will\s+nach|"
    r"zu\s+fahren|"
    r"nach\s+)",
    re.IGNORECASE,
)


def is_multi_stop_candidate(text: str) -> bool:
    """Pattern-Vorfilter: macht der Text einen Multi-Stop-Eindruck?

    Beide Trigger muessen feuern -- der Hint allein (z.B. "einkaufen
    gehen") ist kein Routing-Intent, und ROUTE_INTRO allein
    (z.B. "fahr zu Lisa") ist Single-Stop.
    """
    return bool(ROUTE_INTRO.search(text) and MULTI_STOP_HINTS.search(text))


# ---------------------------------------------------------------------------
# Datacontracts
# ---------------------------------------------------------------------------


StopType = Literal["home", "contact", "address", "poi"]
Constraint = Literal["before_destination", "along_route"]


@dataclass(frozen=True)
class IntentStop:
    """Ein Stop, wie ihn der Parser aus dem Freitext extrahiert hat.

    Noch nicht aufgeloest -- ``value`` ist Kontaktname / Adresse /
    POI-Kategorie. Der Handler reicht ``contact``/``address``-Stops
    an den ContactAddressResolver, ``poi``-Stops an den Google-
    Places-Pfad.
    """

    type: StopType
    value: str
    poi_category: str = ""
    """Nur fuer ``type=poi`` relevant: ``supermarket``, ``fuel``,
    ``pharmacy``, ``restaurant``, ``atm``, ``other``."""
    constraint: Constraint = "before_destination"


@dataclass(frozen=True)
class RouteIntent:
    """Strukturierte Multi-Stop-Anfrage."""

    origin: IntentStop
    destination: IntentStop
    waypoints: tuple[IntentStop, ...] = field(default_factory=tuple)
    arrival_time_text: str = ""
    """Woertlich extrahierte Zeitangabe (``"morgen um 16 uhr"``). Wird
    an die existierende ``parse_arrival_time()`` aus route_commands.py
    durchgereicht -- deterministisches Datumsrechnen statt Sonnet das
    machen zu lassen."""


# ---------------------------------------------------------------------------
# Sonnet-Tool-Schema
# ---------------------------------------------------------------------------


ROUTE_EXTRACT_TOOL: dict[str, Any] = {
    "name": "extract_multi_stop_route",
    "description": (
        "Extrahiert strukturiert die Stops einer Multi-Stop-"
        "Routenanfrage. Reihenfolge bewahren wie im Text genannt;"
        " type='poi' nur wenn der User klar nach einer Kategorie/"
        "Marke sucht (z.B. Kaufland, Tankstelle, Supermarkt), nicht"
        " bei konkreten Adressen oder Kontaktnamen."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "origin": {
                "type": "object",
                "properties": {
                    "type": {"enum": ["home", "contact", "address"]},
                    "value": {"type": "string"},
                },
                "required": ["type"],
            },
            "destination": {
                "type": "object",
                "properties": {
                    "type": {"enum": ["contact", "address"]},
                    "value": {"type": "string"},
                },
                "required": ["type", "value"],
            },
            "waypoints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"enum": ["contact", "address", "poi"]},
                        "value": {"type": "string"},
                        "poi_category": {
                            "type": "string",
                            "description": (
                                "Nur wenn type=poi. Werte: supermarket,"
                                " fuel, pharmacy, restaurant, atm, other."
                            ),
                        },
                        "constraint": {
                            "enum": ["before_destination", "along_route"],
                            "description": (
                                "before_destination = vorher abholen;"
                                " along_route = irgendwo unterwegs (POIs)."
                            ),
                        },
                    },
                    "required": ["type", "value"],
                },
            },
            "arrival_time_text": {
                "type": "string",
                "description": (
                    "Woertliche Zeitangabe falls vorhanden, z.B."
                    " 'morgen um 16 uhr'. Sonst leerer String."
                ),
            },
        },
        "required": ["destination", "waypoints"],
    },
}


_SYSTEM_PROMPT = (
    "Du extrahierst strukturierte Routen-Stops aus deutscher Alltagssprache."
    " Antworte ausschliesslich ueber den extract_multi_stop_route-Tool-Call;"
    " kein Freitext. Bewahre die Reihenfolge, wie der User die Stops nennt."
    " Wenn der User 'von <X>' nicht erwaehnt, ist origin.type='home'."
    " 'auf dem weg', 'unterwegs', 'einkaufen' deutet auf type='poi'"
    " mit constraint='along_route'. 'vorher <Name> abholen' ist"
    " type='contact' mit constraint='before_destination'."
)


class RouteIntentExtractionError(Exception):
    """Sonnet hat das Schema verfehlt (z.B. fehlende destination)."""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class RouteIntentParser:
    """Extrahiert eine ``RouteIntent`` aus deutscher Alltagssprache.

    Nutzt den AnthropicClient.tool_call()-Pfad fuer schema-strikte
    Extraktion. Pattern-Vorfilter (`is_multi_stop_candidate`) sollte
    vor dem Aufruf der Parse-Methode laufen -- der Handler entscheidet,
    ob er ueberhaupt zum LLM geht.
    """

    def __init__(self, anthropic_client: AnthropicClient) -> None:
        self._client = anthropic_client

    def parse(self, text: str) -> RouteIntent:
        """Wandelt Freitext in eine validierte ``RouteIntent``.

        Raises:
            RouteIntentExtractionError: Bei Schema-Verstoss oder leerer
                Antwort.
        """
        raw = self._client.tool_call(
            prompt=text,
            tool=ROUTE_EXTRACT_TOOL,
            system=_SYSTEM_PROMPT,
            max_tokens=1024,
        )
        return self._raw_to_intent(raw)

    # ------------------------------------------------------------------
    # Schema-Validierung + DTO-Bau
    # ------------------------------------------------------------------

    @staticmethod
    def _raw_to_intent(raw: dict[str, Any]) -> RouteIntent:
        """Wandelt das Tool-Use-Input-Dict in ein RouteIntent-DTO um.

        Bewusst defensiv: Sonnet kann das Schema in Edge-Cases
        verfehlen (fehlende waypoints-Liste, leerer destination-value).
        Statt zu crashen wandeln wir das in eine
        ``RouteIntentExtractionError`` mit klarem Grund -- der Handler
        antwortet dem User dann mit "ich hab das nicht verstanden,
        formulier es bitte anders".
        """
        destination_raw = raw.get("destination")
        if not isinstance(destination_raw, dict):
            raise RouteIntentExtractionError("destination fehlt im Schema")
        destination = RouteIntentParser._stop_from_raw(
            destination_raw,
            allow_home=False,
            require_value=True,
        )

        origin_raw = raw.get("origin") or {"type": "home", "value": ""}
        if not isinstance(origin_raw, dict):
            origin_raw = {"type": "home", "value": ""}
        origin = RouteIntentParser._stop_from_raw(
            origin_raw,
            allow_home=True,
            require_value=False,
        )

        waypoints_raw = raw.get("waypoints", [])
        if not isinstance(waypoints_raw, list):
            raise RouteIntentExtractionError("waypoints ist keine Liste")
        waypoints: list[IntentStop] = []
        for idx, wp in enumerate(waypoints_raw):
            if not isinstance(wp, dict):
                raise RouteIntentExtractionError(
                    f"waypoints[{idx}] ist kein Dict",
                )
            waypoints.append(
                RouteIntentParser._stop_from_raw(
                    wp,
                    allow_home=False,
                    require_value=True,
                ),
            )

        arrival = str(raw.get("arrival_time_text", "") or "")
        return RouteIntent(
            origin=origin,
            destination=destination,
            waypoints=tuple(waypoints),
            arrival_time_text=arrival,
        )

    @staticmethod
    def _stop_from_raw(
        raw: dict[str, Any],
        *,
        allow_home: bool,
        require_value: bool,
    ) -> IntentStop:
        """Schmaler Validator fuer ein einzelnes Stop-Dict."""
        stop_type_raw = raw.get("type")
        allowed_types = {"contact", "address", "poi"}
        if allow_home:
            allowed_types = allowed_types | {"home"}
        if stop_type_raw not in allowed_types:
            raise RouteIntentExtractionError(
                f"Unbekannter stop type: {stop_type_raw!r}",
            )

        value = str(raw.get("value", "") or "").strip()
        if require_value and not value:
            raise RouteIntentExtractionError(
                f"Stop ({stop_type_raw}) hat leeren value",
            )

        category = str(raw.get("poi_category", "") or "").strip()
        constraint: Constraint
        if raw.get("constraint") == "along_route":
            constraint = "along_route"
        elif raw.get("constraint") == "before_destination":
            constraint = "before_destination"
        else:
            # POI ohne expliziten Constraint -> along_route ist
            # die sinnvollere Default-Annahme (Einkauf irgendwo
            # zwischendurch). Kontakte default before_destination.
            constraint = (
                "along_route" if stop_type_raw == "poi" else "before_destination"
            )

        stop_type: StopType = stop_type_raw  # validiert via allowed_types oben
        return IntentStop(
            type=stop_type,
            value=value,
            poi_category=category,
            constraint=constraint,
        )
