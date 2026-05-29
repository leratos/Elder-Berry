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
    r"\b(vorher|danach|und\s+dann|auf dem weg|unterwegs|"
    r"über|ueber|via|"
    r"abholen|einkaufen|tanken|holen|"
    r"einkauf|tankstelle|supermarkt|apotheke)\b",
    re.IGNORECASE,
)

# Mindest-Trigger: irgendein Routing-Verb oder "nach <Ort>".
ROUTE_INTRO = re.compile(
    r"\b(fahrt|fahren|fahre|fahr|route|navig\w+|"
    r"muss\s+nach|"
    r"muss\s+zu|"
    r"muss\s+von\b.*?\bzu\s+|"
    r"will\s+nach|"
    r"will\s+zu|"
    r"will\s+von\b.*?\bzu\s+|"
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
    " Wichtig: Bei Formulierungen wie 'von zuhause zu Nadine und dann zu Lisa'"
    " ist 'Lisa' das destination-Ziel und 'Nadine' ein waypoint."
    " 'unterwegs moechte ich noch zu Hornbach' ist ein POI-Waypoint und"
    " nicht Teil des destination-Strings."
)


_CHAINED_DESTINATION_RE = re.compile(
    r"\bzu\s+(?P<first>[^,.!?]+?)\s+und\s+dann\s+zu\s+(?P<second>[^,.!?]+)",
    re.IGNORECASE,
)
_ALONG_ROUTE_POI_RE = re.compile(
    r"\bunterwegs(?:\s+moechte\s+ich)?(?:\s+noch)?\s+zu\s+"
    r"(?P<poi>[^,.!?]+)",
    re.IGNORECASE,
)
_HEURISTIC_ARRIVAL_RE = re.compile(
    r"\b(?:"
    r"uebermorgen|übermorgen|morgen|heute|"
    r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag"
    r")\b[^,.!?]*?\b(?:um\s+)?\d{1,2}(?::\d{2})?(?:\s*uhr)?\b"
    r"|\b(?:um\s+)?\d{1,2}(?::\d{2})?(?:\s*uhr)?\b",
    re.IGNORECASE,
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

    def __init__(self, anthropic_client: AnthropicClient | None) -> None:
        self._client = anthropic_client

    def parse(self, text: str) -> RouteIntent:
        """Wandelt Freitext in eine validierte ``RouteIntent``.

        Raises:
            RouteIntentExtractionError: Bei Schema-Verstoss oder leerer
                Antwort.
        """
        if self._client is None or not self._client.is_available():
            return self._heuristic_parse(text)

        raw = self._client.tool_call(
            prompt=text,
            tool=ROUTE_EXTRACT_TOOL,
            system=_SYSTEM_PROMPT,
            max_tokens=1024,
        )
        intent = self._raw_to_intent(raw)
        return self._repair_common_chained_route_phrasing(text, intent)

    @staticmethod
    def _heuristic_parse(text: str) -> RouteIntent:
        """Lokaler Fallback fuer haeufige Multi-Stop-Satzmuster ohne Sonnet.

        Deckt bewusst nur die ueblichen Phase-92-Formulierungen ab:
        - ``zu X und dann zu Y``
        - ``vorher X abholen`` / ``vorher X und Y abholen``
        - ``unterwegs ... zu/bei X`` fuer Marken/POIs
        """
        normalized = text.strip()
        if not normalized:
            raise RouteIntentExtractionError("leere Routenanfrage")

        origin = IntentStop(type="home", value="")
        if re.search(
            r"\bvon\s+zuhause\b|\bvon\s+zu\s+hause\b", normalized, re.IGNORECASE
        ):
            origin = IntentStop(type="home", value="")

        chain_match = _CHAINED_DESTINATION_RE.search(normalized)
        if chain_match is not None:
            destination = IntentStop(
                type="contact",
                value=chain_match.group("second").strip(),
            )
            waypoints = [
                IntentStop(
                    type="contact",
                    value=chain_match.group("first").strip(),
                    constraint="before_destination",
                )
            ]
        else:
            destination = RouteIntentParser._heuristic_destination(normalized)
            waypoints = RouteIntentParser._heuristic_contact_waypoints(normalized)

        poi = RouteIntentParser._heuristic_poi_waypoint(normalized)
        if poi is not None:
            waypoints.append(poi)

        if not destination.value:
            raise RouteIntentExtractionError("destination fehlt im Heuristik-Fallback")

        arrival_time_text = RouteIntentParser._heuristic_arrival_time_text(normalized)

        return RouteIntent(
            origin=origin,
            destination=destination,
            waypoints=tuple(waypoints),
            arrival_time_text=arrival_time_text,
        )

    @staticmethod
    def _heuristic_destination(text: str) -> IntentStop:
        patterns = [
            re.compile(r"\bnach\s+(?P<dest>[^,.!?]+)", re.IGNORECASE),
            re.compile(r"\bzu\s+(?P<dest>[^,.!?]+)", re.IGNORECASE),
        ]
        for pattern in patterns:
            match = pattern.search(text)
            if match is None:
                continue
            destination = match.group("dest").strip()
            destination = re.split(
                r"\s+(?:vorher|danach|unterwegs|auf\s+dem\s+weg|und\s+dann)\b",
                destination,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip()
            if destination:
                return IntentStop(type="contact", value=destination)
        return IntentStop(type="contact", value="")

    @staticmethod
    def _heuristic_contact_waypoints(text: str) -> list[IntentStop]:
        previous_match = re.search(
            r"\bvorher\s+(?P<names>[^,.!?]+?)\s+abholen\b",
            text,
            re.IGNORECASE,
        )
        if previous_match is None:
            return []
        names_raw = previous_match.group("names").strip()
        names = [
            part.strip() for part in re.split(r"\s+und\s+", names_raw) if part.strip()
        ]
        return [
            IntentStop(type="contact", value=name, constraint="before_destination")
            for name in names
        ]

    @staticmethod
    def _heuristic_poi_waypoint(text: str) -> IntentStop | None:
        poi_match = re.search(
            r"\b(?:unterwegs|auf\s+dem\s+weg)(?:\s+moechte\s+ich)?(?:\s+noch)?\s+(?:zu|bei)\s+(?P<poi>[^,.!?]+)",
            text,
            re.IGNORECASE,
        )
        if poi_match is None:
            return None
        poi_value = poi_match.group("poi").strip()
        if not poi_value:
            return None
        return IntentStop(
            type="poi",
            value=poi_value,
            constraint="along_route",
        )

    @staticmethod
    def _heuristic_arrival_time_text(text: str) -> str:
        """Extrahiert eine woertliche Zeitphrase fuer parse_arrival_time()."""
        match = _HEURISTIC_ARRIVAL_RE.search(text)
        if match is None:
            return ""
        return match.group(0).strip()

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

    @staticmethod
    def _repair_common_chained_route_phrasing(
        text: str,
        intent: RouteIntent,
    ) -> RouteIntent:
        """Repariert haeufige LLM-Fehlsegmentierungen bei Ketten wie
        'zu Nadine und dann zu Lisa, unterwegs zu Hornbach'.

        Live-Befund 2026-05-28: Sonnet kann in solchen Formulierungen den
        kompletten Restsatz in ``destination.value`` kippen. Wir greifen nur
        ein, wenn der destination-String genau solche Kettenmarker enthaelt;
        ansonsten bleibt das LLM-Ergebnis unveraendert.
        """
        destination_value = intent.destination.value.strip()
        lowered_destination = destination_value.lower()
        if "und dann zu" not in lowered_destination:
            return intent

        match = _CHAINED_DESTINATION_RE.search(destination_value)
        if match is None:
            match = _CHAINED_DESTINATION_RE.search(text)
        if match is None:
            return intent

        first = match.group("first").strip()
        second = match.group("second").strip()
        if not first or not second:
            return intent

        repaired_waypoints = list(intent.waypoints)
        repaired_waypoints.insert(
            0,
            IntentStop(
                type="contact",
                value=first,
                constraint="before_destination",
            ),
        )

        poi_match = _ALONG_ROUTE_POI_RE.search(text)
        if poi_match is not None:
            poi_value = poi_match.group("poi").strip()
            if poi_value and all(
                w.value.lower() != poi_value.lower() for w in repaired_waypoints
            ):
                repaired_waypoints.append(
                    IntentStop(
                        type="poi",
                        value=poi_value,
                        constraint="along_route",
                    ),
                )

        return RouteIntent(
            origin=intent.origin,
            destination=IntentStop(
                type=intent.destination.type,
                value=second,
                poi_category=intent.destination.poi_category,
                constraint=intent.destination.constraint,
            ),
            waypoints=tuple(repaired_waypoints),
            arrival_time_text=intent.arrival_time_text,
        )
