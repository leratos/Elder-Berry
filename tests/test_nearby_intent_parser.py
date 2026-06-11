"""Tests fuer nearby_intent_parser -- Vorfilter + Sonnet-Extraktion (Phase 97).

Phase 97 (E2). KEIN echter LLM-Call -- der AnthropicClient ist gemockt.
Schwerpunkte (Konzept §6): Vorfilter true (Shisha/Rockerbar) / false
(Routen-Text MUSS false, Negativtest "mit Lisa"); Schema -> NearbyQueryDraft;
fehlender Ort/Modus -> to_query() None; Heuristik-Fallback ohne Anthropic.
"""

from __future__ import annotations

from typing import Any

import pytest

from elder_berry.tools.nearby_intent_parser import (
    NEARBY_EXTRACT_TOOL,
    NearbyIntentParser,
    is_nearby_candidate,
)
from elder_berry.tools.nearby_place_search import NearbyQueryDraft
from elder_berry.tools.place_types import normalize_travel_mode


class _FakeAnthropic:
    """Minimaler AnthropicClient-Stub (is_available + tool_call)."""

    def __init__(
        self,
        *,
        available: bool = True,
        tool_result: dict[str, Any] | None = None,
    ) -> None:
        self._available = available
        self._tool_result = tool_result or {}
        self.calls: list[dict[str, Any]] = []

    def is_available(self) -> bool:
        return self._available

    def tool_call(
        self,
        prompt: str,
        tool: dict[str, Any],
        system: str = "",
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        self.calls.append({"prompt": prompt, "tool": tool, "system": system})
        return self._tool_result


# ---------------------------------------------------------------------------
# Vorfilter
# ---------------------------------------------------------------------------


class TestIsNearbyCandidate:
    @pytest.mark.parametrize(
        "text",
        [
            (
                "ich bin Karl-Liebknecht-Str 12 in Leipzig und brauche einen "
                "Shisha-Kopf — wo kaufe ich den hier?"
            ),
            (
                "ich bin mit Lisa in der Suedvorstadt, kannst du mir eine "
                "Rockerbar nennen?"
            ),
            "wo gibt es hier einen Baumarkt?",
            "nenne mir eine Apotheke in der Naehe",
            "ich brauche eine Apotheke",
            "wo kann ich Tomatensauce kaufen?",
            "kennst du einen guten Laden in der Naehe?",
        ],
    )
    def test_positive(self, text: str) -> None:
        assert is_nearby_candidate(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "fahr mich nach Leipzig Hbf, vorher Lisa abholen",
            "navigier mich zu Lisa",
            "ich fahre mit Lisa nach Berlin",
            "fahr mich zu der Bar",  # Navigation zu bekannter Bar -> Route
            "lies meine mails und trag den termin ein",
            "wie spaet ist es?",
            "ich brauche eine Pause",  # Kauf-Verb ohne Standort-Kontext
            "ich bin zuhause und brauche eine Route nach Berlin",  # Route gewinnt
        ],
    )
    def test_negative(self, text: str) -> None:
        assert is_nearby_candidate(text) is False

    @pytest.mark.parametrize(
        "text",
        [
            # Codex-Review PR #302: Item-Kauf ohne Venue-Nomen, aber mit
            # Standort-/Modus-Kontext (Kern-Flow §0.1/§9 "Tomatensauce").
            "ich bin in Connewitz und brauche eine Tomatensauce, zu Fuss",
            "ich bin Hauptstr 3 und brauche eine Tomatensauce — wo zu Fuß?",
        ],
    )
    def test_positive_item_buy_with_context(self, text: str) -> None:
        assert is_nearby_candidate(text) is True


# ---------------------------------------------------------------------------
# parse() via gemockten Sonnet-Tool-Call
# ---------------------------------------------------------------------------


class TestParseWithLLM:
    def test_full_schema_builds_draft(self) -> None:
        client = _FakeAnthropic(
            tool_result={
                "subject": "Rockerbar",
                "search_query": "Rockerbar",
                "included_type": "bar",
                "exclude_types": ["restaurant"],
                "location_text": "Suedvorstadt Leipzig",
                "travel_mode": "driving",
                "open_now": True,
            },
        )
        parser = NearbyIntentParser(client)
        draft = parser.parse("kannst du mir eine Rockerbar nennen?")

        assert isinstance(draft, NearbyQueryDraft)
        assert draft.subject == "Rockerbar"
        assert draft.search_query == "Rockerbar"
        assert draft.included_type == "bar"
        assert draft.exclude_types == ("restaurant",)
        assert draft.location_text == "Suedvorstadt Leipzig"
        assert draft.travel_mode == "driving"
        # genau ein Tool-Call, mit dem richtigen Tool.
        assert len(client.calls) == 1
        assert client.calls[0]["tool"]["name"] == NEARBY_EXTRACT_TOOL["name"]

    def test_lisa_is_not_taken_as_location(self) -> None:
        # Schema-Response setzt location auf den Ort, nicht den Kontaktnamen.
        client = _FakeAnthropic(
            tool_result={
                "subject": "Rockerbar",
                "search_query": "Rockerbar",
                "location_text": "Suedvorstadt",
            },
        )
        parser = NearbyIntentParser(client)
        draft = parser.parse("ich bin mit Lisa in der Suedvorstadt, eine Rockerbar?")
        assert draft is not None
        assert draft.location_text == "Suedvorstadt"
        assert "lisa" not in (draft.location_text or "").lower()

    def test_missing_location_and_mode_yield_draft_without_query(self) -> None:
        client = _FakeAnthropic(
            tool_result={
                "subject": "Shisha-Kopf",
                "search_query": "Shisha-Kopf kaufen",
                # kein location_text, kein travel_mode
            },
        )
        parser = NearbyIntentParser(client)
        draft = parser.parse("wo kaufe ich einen Shisha-Kopf?")
        assert draft is not None
        assert draft.location_text is None
        assert draft.travel_mode is None
        # Draft erhalten, aber noch keine vollstaendige Query (Codex #4).
        assert draft.to_query() is None

    def test_invalid_included_type_kept_in_draft_dropped_in_query(self) -> None:
        # Der Parser validiert NICHT -- to_query() (place_types) tut es (R2-C1).
        client = _FakeAnthropic(
            tool_result={
                "subject": "Shisha-Zubehoer",
                "search_query": "Shisha-Zubehoer",
                "included_type": "shisha_shop",
                "exclude_types": ["bar"],
                "location_text": "Leipzig",
                "travel_mode": "zu fuss",
            },
        )
        parser = NearbyIntentParser(client)
        draft = parser.parse("wo kaufe ich Shisha-Zubehoer zu Fuss?")
        assert draft is not None
        assert draft.included_type == "shisha_shop"  # roh erhalten
        query = draft.to_query()
        assert query is not None
        assert query.included_type is None          # R2-C1: validiert raus
        assert query.travel_mode == "walking"        # R2-C2: Synonym normiert
        assert query.exclude_types == ("bar",)

    def test_empty_subject_and_query_returns_none(self) -> None:
        client = _FakeAnthropic(tool_result={"subject": "", "search_query": ""})
        parser = NearbyIntentParser(client)
        assert parser.parse("irgendwas") is None

    def test_search_query_falls_back_to_subject(self) -> None:
        client = _FakeAnthropic(
            tool_result={"subject": "Apotheke", "search_query": ""},
        )
        parser = NearbyIntentParser(client)
        draft = parser.parse("ich brauche eine Apotheke")
        assert draft is not None
        assert draft.search_query == "Apotheke"


# ---------------------------------------------------------------------------
# Heuristik-Fallback (kein/unavailable Anthropic)
# ---------------------------------------------------------------------------


class TestHeuristicFallback:
    def test_none_client_uses_heuristic(self) -> None:
        parser = NearbyIntentParser(None)
        draft = parser.parse("ich brauche eine Apotheke")
        assert draft is not None
        assert draft.subject == "Apotheke"
        assert draft.search_query == "Apotheke"
        assert draft.included_type is None  # Fallback: kein Typ

    def test_unavailable_client_uses_heuristic(self) -> None:
        client = _FakeAnthropic(available=False)
        parser = NearbyIntentParser(client)
        parser.parse("ich brauche eine Apotheke")
        assert client.calls == []  # KEIN Tool-Call bei unavailable

    def test_heuristic_extracts_location_and_mode(self) -> None:
        parser = NearbyIntentParser(None)
        draft = parser.parse(
            "ich brauche eine Apotheke in der Naehe von Connewitz, zu Fuss"
        )
        assert draft is not None
        assert draft.subject == "Apotheke"
        assert draft.location_text == "Connewitz"
        # roher Modus -> ueber to_query() normiert.
        query = draft.to_query()
        assert query is not None
        assert query.travel_mode == "walking"

    def test_heuristic_handles_wo_kann_ich_kaufen(self) -> None:
        # Codex-Review PR #302: der Vorfilter akzeptiert "wo kann ich ...
        # kaufen", also muss der Ollama-Fallback es auch parsen (nicht None).
        parser = NearbyIntentParser(None)
        draft = parser.parse("wo kann ich Tomatensauce kaufen?")
        assert draft is not None
        assert "tomatensauce" in draft.subject.lower()

    def test_heuristic_mode_eszett(self) -> None:
        parser = NearbyIntentParser(None)
        draft = parser.parse(
            "ich brauche eine Apotheke in der Naehe von Connewitz, zu Fuß"
        )
        assert draft is not None
        query = draft.to_query()
        assert query is not None
        assert query.travel_mode == "walking"

    def test_heuristic_without_subject_returns_none(self) -> None:
        parser = NearbyIntentParser(None)
        assert parser.parse("hallo wie geht es dir?") is None

    def test_heuristic_empty_text_returns_none(self) -> None:
        parser = NearbyIntentParser(None)
        assert parser.parse("   ") is None

    def test_heuristic_location_from_ich_bin(self) -> None:
        parser = NearbyIntentParser(None)
        draft = parser.parse("ich bin Hauptstr 3 Leipzig und brauche eine Apotheke")
        assert draft is not None
        assert draft.location_text is not None
        assert "Hauptstr" in draft.location_text

    @pytest.mark.parametrize(
        ("text", "expected_mode"),
        [
            ("ich brauche eine Apotheke hier mit dem Fahrrad", "bicycling"),
            ("ich brauche eine Apotheke hier mit dem Auto", "driving"),
            ("ich brauche eine Apotheke hier, oepnv", "transit"),
        ],
    )
    def test_heuristic_mode_variants(self, text: str, expected_mode: str) -> None:
        parser = NearbyIntentParser(None)
        draft = parser.parse(text)
        assert draft is not None
        assert normalize_travel_mode(draft.travel_mode) == expected_mode


class TestRawToDraftEdges:
    def test_subject_empty_uses_search_query(self) -> None:
        client = _FakeAnthropic(
            tool_result={"subject": "", "search_query": "Brot"},
        )
        draft = NearbyIntentParser(client).parse("wo gibt es Brot?")
        assert draft is not None
        assert draft.subject == "Brot"

    def test_blank_location_text_becomes_none(self) -> None:
        # Whitespace-Ort -> None (nicht leerer String) -> Rueckfrage.
        client = _FakeAnthropic(
            tool_result={
                "subject": "Bar", "search_query": "Bar", "location_text": "   ",
            },
        )
        draft = NearbyIntentParser(client).parse("nenne mir eine Bar")
        assert draft is not None
        assert draft.location_text is None
