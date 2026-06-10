"""NearbyIntentParser -- NLU-Schicht fuer Umkreis-/Ortssuchanfragen (Phase 97).

Zweistufig wie ``RouteIntentParser`` (Phase 92):

1. ``is_nearby_candidate(text)`` -- billiger Regex-Vorfilter. Erkennt
   "ich suche/brauche Y in der Naehe / wo kaufe ich Y / nenne mir eine X".
   MUSS Routen-Text false geben (sonst stiehlt die Umkreissuche dem
   Route-Handler die Anfrage -- §7-Risiko + Negativtest "mit Lisa").
2. ``NearbyIntentParser.parse(text)`` -- Claude-Sonnet-Tool-Call
   (``extract_nearby_search``) fuer schema-strikte Extraktion. Liefert
   einen ``NearbyQueryDraft`` (Codex #4): fehlt ``location_text``/
   ``travel_mode``, bleibt das schon Geparste erhalten und der Handler
   stellt EINE Rueckfrage. Nur wenn gar kein Ortssuch-Intent erkennbar
   ist -> ``None``.

Arbeitsteilung (Konzept §1): der LLM URTEILT (Item->Kategorie, optionaler
``included_type``, Ausschlussliste, Reisemodus); der Code ERZWINGT spaeter
(``place_types``-Validierung in ``NearbyQueryDraft.to_query()``,
Radius-Cap/Filter in ``NearbyPlaceSearch``). Hier wird NICHT validiert --
nur extrahiert.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from elder_berry.tools.nearby_place_search import NearbyQueryDraft

if TYPE_CHECKING:
    from elder_berry.llm.anthropic_client import AnthropicClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pattern-Vorfilter
# ---------------------------------------------------------------------------

# Ortsnomen, die einen Venue-/Laden-Wunsch plausibel machen (Disjunktion).
_PLACE_NOUN = (
    r"bar|kneipe|club|disco|laden|gesch(?:ä|ae)ft|shop|markt|supermarkt|"
    r"baumarkt|apotheke|tankstelle|kiosk|caf[eé]|restaurant|imbiss|"
    r"b(?:ä|ae)cker|metzger|drogerie|friseur|werkstatt|store|pizzeria"
)

# Ortsnomen auch als Kompositum-Suffix matchen ("Rockerbar", "Buchladen",
# "Baumarkt"): deutsche Komposita haben keine Wortgrenze vor dem Grundwort.
_PLACE_NOUN_GROUP = r"\w*(?:" + _PLACE_NOUN + r")"
_HAS_PLACE_NOUN = re.compile(r"\b" + _PLACE_NOUN_GROUP + r"\b", re.IGNORECASE)

# Nearby-Intent-Signale. Bewusst ortssuchspezifisch, damit reiner Routen-
# Text ("fahr nach X", "von A zu B") NICHT feuert.
_NEARBY_INTENT = re.compile(
    # "wo kaufe ich / wo gibt es / wo finde ich / wo bekomme ich ..."
    r"\bwo\s+(?:kann\s+ich|kaufe?\s+ich|gibt\s+es|bekomme?\s+ich|"
    r"finde\s+ich|krieg\w*\s+ich|besorge?\s+ich)\b"
    # "... wo kaufen?"
    r"|\bwo\s+.*\bkaufen\b"
    # "in der Naehe" / "in meiner Naehe" / "hier in der Naehe"
    r"|\bin\s+(?:der\s+|meiner\s+)?n(?:ä|ae)he\b"
    # Empfehl-/Nenn-Verb + Ortsnomen ("nenne mir eine Rockerbar",
    # "kennst du einen guten Laden", "kannst du mir eine Bar empfehlen")
    r"|\b(?:nenn\w*|empfiehl\w*|empfehle\w*|kennst\s+du|kannst\s+du|"
    r"zeig\s+mir|finde\s+mir|such\w*\s+mir|gibt\s+es|hast\s+du)\b"
    r"[^.?!]*\b" + _PLACE_NOUN_GROUP + r"\b"
    # "brauche einen <Ortsnomen>" / "suche eine <Ortsnomen>"
    r"|\b(?:brauche?|such\w*)\b[^.?!]*\b" + _PLACE_NOUN_GROUP + r"\b",
    re.IGNORECASE,
)

# Harte Routen-Signale: wenn der Text klar eine Navigation IST (und kein
# Nearby-Nomen traegt), bleibt der Vorfilter aus -- der Route-Handler
# besitzt den Fall. "mit <Name>" ist KEIN Adress-/Ortssignal (Phase 92).
_ROUTE_ONLY = re.compile(
    r"\b(?:navigier\w*|route\s+(?:nach|zu)|fahr(?:e|t|en)?\s+(?:mich\s+)?(?:nach|zu|zum|zur)|"
    r"bring\s+mich\s+(?:nach|zu)|wie\s+komme?\s+ich\s+(?:nach|zu))\b",
    re.IGNORECASE,
)


def is_nearby_candidate(text: str) -> bool:
    """Vorfilter: macht der Text einen Umkreis-/Ortssuch-Eindruck?

    ``True`` wenn ein Nearby-Signal feuert. Ein reiner Navigations-Satz
    ohne Ortsnomen (``"fahr mich nach Leipzig"``) -> ``False``: der
    Route-Handler besitzt den. Steht aber ein Nearby-Signal MIT Ortsnomen
    drin, gewinnt Nearby (der Handler-Priority-Konflikt wird in E4/B4
    final gegen die Registry verifiziert).
    """
    if not _NEARBY_INTENT.search(text):
        return False
    # Nearby-Signal vorhanden. Nur unterdruecken, wenn es ein klarer
    # Routen-Satz OHNE Ortsnomen ist (z.B. "navigier mich zu Lisa").
    if _ROUTE_ONLY.search(text) and not _HAS_PLACE_NOUN.search(text):
        return False
    return True


# ---------------------------------------------------------------------------
# Sonnet-Tool-Schema
# ---------------------------------------------------------------------------

NEARBY_EXTRACT_TOOL: dict[str, Any] = {
    "name": "extract_nearby_search",
    "description": (
        "Extrahiert eine Umkreis-/Ortssuche aus deutscher Alltagssprache."
        " Der Nutzer steht an einem Ort und sucht etwas in der Naehe (zum"
        " Kaufen oder als Venue). Item->Kategorie selbst beurteilen"
        " (Weltwissen): z.B. 'Shisha-Kopf'->Tabak/Zubehoer (kein sauberer"
        " Google-Typ -> included_type=null), 'Tomatensauce'->Supermarkt"
        " (included_type='supermarket'), 'Rockerbar'->Bar"
        " (search_query='Rockerbar', included_type='bar')."
        " Kontaktnamen ('mit Lisa') sind KEIN Standort."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": (
                    "Worum es geht, kurz (fuer das Echo 'Ich suche X')."
                ),
            },
            "search_query": {
                "type": "string",
                "description": (
                    "Freitext-Suchbegriff fuer Google (traegt die Nuance,"
                    " z.B. 'Rockerbar', 'Shisha-Kopf kaufen')."
                ),
            },
            "included_type": {
                "type": "string",
                "description": (
                    "Optionaler Google-Place-Typ NUR wenn ein sauberer"
                    " existiert (z.B. bar, restaurant, supermarket,"
                    " pharmacy, hardware_store). Im Zweifel weglassen/null."
                ),
            },
            "exclude_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Google-Typen, die NICHT gemeint sind (z.B. bei"
                    " 'Shisha-Zubehoer' -> ['bar'] um Shisha-Bars"
                    " auszuschliessen)."
                ),
            },
            "location_text": {
                "type": "string",
                "description": (
                    "Standort des Nutzers als Freitext (Strasse + Stadt"
                    " o.ae.). Null, wenn nicht genannt -- KEIN Kontaktname."
                ),
            },
            "travel_mode": {
                "type": "string",
                "enum": ["driving", "walking", "bicycling", "transit"],
                "description": (
                    "Reisemodus, falls genannt ('zu Fuss'->walking,"
                    " 'mit Auto'->driving). Null, wenn nicht genannt."
                ),
            },
            "open_now": {
                "type": "boolean",
                "description": "Ob nur aktuell geoeffnete Orte zaehlen.",
            },
        },
        "required": ["subject", "search_query"],
    },
}

_SYSTEM_PROMPT = (
    "Du extrahierst strukturierte Umkreis-/Ortssuchen aus deutscher"
    " Alltagssprache. Antworte ausschliesslich ueber den"
    " extract_nearby_search-Tool-Call; kein Freitext. Beurteile selbst,"
    " welche Kategorie das gesuchte Item hat (Weltwissen). Setze"
    " included_type nur, wenn ein sauberer Google-Typ existiert; sonst"
    " null und nutze ggf. exclude_types. location_text ist der STANDORT"
    " des Nutzers -- ein Kontaktname wie 'Lisa' ist KEIN Standort."
    " Felder, die der Nutzer nicht nennt (location_text, travel_mode),"
    " weglassen oder null."
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class NearbyIntentParser:
    """Extrahiert einen ``NearbyQueryDraft`` aus deutscher Alltagssprache."""

    def __init__(self, anthropic_client: AnthropicClient | None) -> None:
        self._client = anthropic_client

    def parse(self, text: str) -> NearbyQueryDraft | None:
        """Wandelt Freitext in einen ``NearbyQueryDraft`` oder ``None``.

        ``None`` nur, wenn gar kein Ortssuch-Intent erkennbar ist (kein
        ``subject``/``search_query``). Fehlt nur ``location_text``/
        ``travel_mode``, kommt der Draft mit ``None`` in diesen Feldern
        zurueck -- der Handler stellt dann EINE Rueckfrage (Codex #4).
        """
        if self._client is None or not self._client.is_available():
            return self._heuristic_parse(text)

        raw = self._client.tool_call(
            prompt=text,
            tool=NEARBY_EXTRACT_TOOL,
            system=_SYSTEM_PROMPT,
            max_tokens=1024,
        )
        return self._raw_to_draft(raw)

    # ------------------------------------------------------------------
    # Schema -> DTO
    # ------------------------------------------------------------------

    @staticmethod
    def _raw_to_draft(raw: dict[str, Any]) -> NearbyQueryDraft | None:
        """Baut den Draft aus dem Tool-Input-Dict (defensiv).

        Bewusst KEINE Validierung von ``included_type``/``travel_mode``
        hier -- das macht ``NearbyQueryDraft.to_query()`` ueber
        ``place_types`` (eine Garantie-Stelle, auch fuer den
        Heuristik-/Ollama-Fallback).
        """
        subject = str(raw.get("subject", "") or "").strip()
        search_query = str(raw.get("search_query", "") or "").strip()
        # Kein brauchbarer Intent -> None (False-Positive des Vorfilters).
        if not subject and not search_query:
            return None
        # search_query traegt die Suche; faellt auf subject zurueck.
        if not search_query:
            search_query = subject
        if not subject:
            subject = search_query

        included = raw.get("included_type")
        included_type = str(included).strip() if included else None

        exclude_raw = raw.get("exclude_types")
        exclude_types = (
            tuple(str(t).strip() for t in exclude_raw if str(t).strip())
            if isinstance(exclude_raw, list)
            else ()
        )

        location = raw.get("location_text")
        location_text = str(location).strip() if location else None
        if location_text == "":
            location_text = None

        mode = raw.get("travel_mode")
        travel_mode = str(mode).strip() if mode else None

        open_now_raw = raw.get("open_now", True)
        open_now = bool(open_now_raw) if isinstance(open_now_raw, bool) else True

        return NearbyQueryDraft(
            subject=subject,
            search_query=search_query,
            included_type=included_type,
            exclude_types=exclude_types,
            location_text=location_text,
            travel_mode=travel_mode,
            open_now=open_now,
        )

    # ------------------------------------------------------------------
    # Heuristik-Fallback (Ollama/kein Anthropic) -- akzeptierte Degradierung
    # ------------------------------------------------------------------

    @staticmethod
    def _heuristic_parse(text: str) -> NearbyQueryDraft | None:
        """Best-effort ohne LLM: Freitext-Query (+ ggf. Ort/Modus).

        Bewusst lossy (Konzept §"Fallback Ollama"): included_type bleibt
        null, exclude_types leer; der Freitext-Query traegt die Suche.
        Kein extrahierbares Subjekt -> ``None``.
        """
        normalized = " ".join(text.split())
        if not normalized:
            return None

        subject = NearbyIntentParser._heuristic_subject(normalized)
        if not subject:
            return None

        return NearbyQueryDraft(
            subject=subject,
            search_query=subject,
            included_type=None,
            exclude_types=(),
            location_text=NearbyIntentParser._heuristic_location(normalized),
            travel_mode=NearbyIntentParser._heuristic_mode(normalized),
            open_now=True,
        )

    # Beendet eine grobe Subjekt-/Ortsextraktion am naechsten Trenner
    # (Komma, Satzzeichen, typisches Folgewort oder Textende).
    _STOP = r"(?=[,.?!]|\s+(?:hier|wo|in|zu|mit|und)\b|$)"

    @staticmethod
    def _heuristic_subject(text: str) -> str:
        """Grobes Subjekt nach typischen Triggern."""
        stop = NearbyIntentParser._STOP
        patterns = [
            r"\bkaufe?\s+ich\s+(?:den|die|das|einen|eine|ein)?\s*(?P<s>[\wäöüß\- ]+?)" + stop,
            r"\bbrauche?\s+(?:noch\s+)?(?:einen|eine|ein|nen|ne)?\s*(?P<s>[\wäöüß\- ]+?)" + stop,
            r"\b(?:nenn\w*|empfiehl\w*|finde\s+mir|such\w*\s+mir)\s+(?:mir\s+)?"
            r"(?:einen|eine|ein)?\s*(?P<s>[\wäöüß\- ]+?)" + stop,
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match is not None:
                subject = match.group("s").strip()
                if len(subject) > 1:
                    return subject
        return ""

    @staticmethod
    def _heuristic_location(text: str) -> str | None:
        """Standort nach 'in der Naehe von X' oder 'ich bin <X> und'."""
        near = re.search(
            r"\bin\s+der\s+n(?:ä|ae)he\s+von\s+(?P<loc>[\wäöüß\-. ]+?)(?=[,.?!]|$)",
            text,
            re.IGNORECASE,
        )
        if near is not None:
            loc = near.group("loc").strip()
            if loc:
                return loc
        # "ich bin <Strasse/Stadt> und ..." -- nimm den Teil dazwischen.
        in_city = re.search(
            r"\bich\s+bin\s+(?P<loc>[\wäöüß\-.,/ ]+?)\s+und\b",
            text,
            re.IGNORECASE,
        )
        if in_city is not None:
            loc = in_city.group("loc").strip()
            if loc:
                return loc
        return None

    @staticmethod
    def _heuristic_mode(text: str) -> str | None:
        """Reisemodus-Phrase im Text (roh, ohne place_types-Normalisierung)."""
        lowered = text.lower()
        if re.search(r"\bzu\s+fuss\b|\bzu\s+fu(?:ß|ss)\b|\bzu\s+fuss\b", lowered):
            return "zu fuss"
        if re.search(r"\bmit\s+dem\s+rad\b|\bfahrrad\b|\bmit\s+dem\s+fahrrad\b", lowered):
            return "fahrrad"
        if re.search(r"\b(?:ö|oe)pnv\b|\bbahn\b|\bbus\b|\bmit\s+dem\s+bus\b", lowered):
            return "oepnv"
        if re.search(r"\bmit\s+dem\s+auto\b|\bauto\b|\bmit\s+dem\s+wagen\b", lowered):
            return "auto"
        return None
