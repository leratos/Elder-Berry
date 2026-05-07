"""Tests: Assistant <plugin-candidate>-Extraktion + Block-Build (Phase 78 Etappe 2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from elder_berry.core.assistant import Assistant
from elder_berry.tools.proposal_store import ProposalStore


# ---------------------------------------------------------------------------
# _extract_plugin_candidate
# ---------------------------------------------------------------------------


class TestExtractPluginCandidate:
    def test_no_block_returns_text_unchanged(self) -> None:
        text = "Klar, ich mache das gleich."
        cleaned, candidate = Assistant._extract_plugin_candidate(text)
        assert cleaned == text
        assert candidate is None

    def test_valid_block_extracted_and_text_cleaned(self) -> None:
        text = (
            "Klar, ich spiele was von Hans Zimmer ab.\n\n"
            '<plugin-candidate>{"intent":"spotify_play_song",'
            '"title":"Spotify-Steuerung","description":"Spielt Tracks.",'
            '"category":"medien","confidence":0.85}</plugin-candidate>'
        )
        cleaned, candidate = Assistant._extract_plugin_candidate(text)
        assert "<plugin-candidate>" not in cleaned
        assert "Hans Zimmer" in cleaned
        assert candidate is not None
        assert candidate["intent"] == "spotify_play_song"
        assert candidate["title"] == "Spotify-Steuerung"
        assert candidate["confidence"] == 0.85
        assert candidate["category"] == "medien"

    def test_block_inside_text_cleaned(self) -> None:
        text = (
            'Vorne. <plugin-candidate>{"intent":"x","title":"X",'
            '"confidence":0.8}</plugin-candidate> Hinten.'
        )
        cleaned, candidate = Assistant._extract_plugin_candidate(text)
        # Cleaned hat Text vorne+hinten, ohne Block dazwischen
        assert "<plugin-candidate>" not in cleaned
        assert "Vorne." in cleaned
        assert "Hinten." in cleaned
        assert candidate is not None

    def test_invalid_json_returns_none(self) -> None:
        text = "Antwort. <plugin-candidate>{kaputtes json}</plugin-candidate>"
        cleaned, candidate = Assistant._extract_plugin_candidate(text)
        assert candidate is None
        # Block trotzdem entfernt
        assert "<plugin-candidate>" not in cleaned

    def test_missing_intent_field_returns_none(self) -> None:
        text = '<plugin-candidate>{"title":"X","confidence":0.8}</plugin-candidate>'
        _, candidate = Assistant._extract_plugin_candidate(text)
        assert candidate is None

    def test_missing_title_returns_none(self) -> None:
        text = '<plugin-candidate>{"intent":"x","confidence":0.8}</plugin-candidate>'
        _, candidate = Assistant._extract_plugin_candidate(text)
        assert candidate is None

    def test_missing_confidence_returns_none(self) -> None:
        text = '<plugin-candidate>{"intent":"x","title":"X"}</plugin-candidate>'
        _, candidate = Assistant._extract_plugin_candidate(text)
        assert candidate is None

    def test_non_numeric_confidence_returns_none(self) -> None:
        text = (
            '<plugin-candidate>{"intent":"x","title":"X","confidence":"hoch"}'
            "</plugin-candidate>"
        )
        _, candidate = Assistant._extract_plugin_candidate(text)
        assert candidate is None

    def test_empty_intent_returns_none(self) -> None:
        text = (
            '<plugin-candidate>{"intent":"","title":"X","confidence":0.8}'
            "</plugin-candidate>"
        )
        _, candidate = Assistant._extract_plugin_candidate(text)
        assert candidate is None

    def test_block_array_not_object_returns_none(self) -> None:
        text = "<plugin-candidate>[1,2,3]</plugin-candidate>"
        _, candidate = Assistant._extract_plugin_candidate(text)
        assert candidate is None

    def test_only_first_block_extracted_when_multiple(self) -> None:
        """Doppelter Block: erster wird gegriffen, zweiter bleibt drin
        (LLM-Output mit zwei Bloecken ist ein Fehler -- wir sind robust
        gegen Halluzinationen, aber raeumen nicht alles auf)."""
        text = (
            '<plugin-candidate>{"intent":"a","title":"A","confidence":0.8}'
            "</plugin-candidate>"
            '<plugin-candidate>{"intent":"b","title":"B","confidence":0.9}'
            "</plugin-candidate>"
        )
        _, candidate = Assistant._extract_plugin_candidate(text)
        assert candidate is not None
        assert candidate["intent"] == "a"


# ---------------------------------------------------------------------------
# _build_active_proposals_block
# ---------------------------------------------------------------------------


def _make_assistant_with_store(
    store: ProposalStore | None,
) -> Assistant:
    """Minimal-Assistant nur fuer Block-Build-Tests (kein process())."""
    llm = MagicMock()
    actions_db = MagicMock()
    actions_db.list_all.return_value = []
    controller = MagicMock()
    return Assistant(
        llm=llm,
        actions_db=actions_db,
        controller=controller,
        proposal_store=store,
    )


class TestActiveProposalsBlock:
    def test_no_store_returns_empty(self) -> None:
        assistant = _make_assistant_with_store(None)
        assert assistant._build_active_proposals_block() == ""

    def test_empty_store_returns_empty(self, tmp_path: Path) -> None:
        store = ProposalStore(db_path=tmp_path / "p.db")
        try:
            assistant = _make_assistant_with_store(store)
            assert assistant._build_active_proposals_block() == ""
        finally:
            store.close()

    def test_active_proposals_listed(self, tmp_path: Path) -> None:
        store = ProposalStore(db_path=tmp_path / "p.db")
        try:
            store.create_pending(
                intent="spotify_play_song",
                title="Spotify-Steuerung",
                description_md="kurz",
                sample_message="spiel",
                sender_hash="h",
                confidence=0.8,
            )
            assistant = _make_assistant_with_store(store)
            block = assistant._build_active_proposals_block()
            assert "Aktive Plugin-Vorschlaege" in block
            assert "spotify_play_song" in block
            assert "Spotify-Steuerung" in block
            assert "in_pruefung" in block
            assert block.endswith("]")
        finally:
            store.close()

    def test_only_active_statuses_included(self, tmp_path: Path) -> None:
        store = ProposalStore(db_path=tmp_path / "p.db")
        try:
            store.create_pending(
                intent="a",
                title="A",
                description_md="kurz",
                sample_message="s",
                sender_hash="h",
                confidence=0.8,
            )
            store.create_pending(
                intent="b",
                title="B",
                description_md="kurz",
                sample_message="s",
                sender_hash="h",
                confidence=0.8,
            )
            store.update_status("b", "abgelehnt", "lera")
            assistant = _make_assistant_with_store(store)
            block = assistant._build_active_proposals_block()
            assert "a:" in block
            assert "b:" not in block
        finally:
            store.close()

    def test_capped_at_max_lines(self, tmp_path: Path) -> None:
        store = ProposalStore(db_path=tmp_path / "p.db")
        try:
            for i in range(25):
                store.create_pending(
                    intent=f"intent_{i}",
                    title=f"T{i}",
                    description_md="kurz",
                    sample_message="s",
                    sender_hash="h",
                    confidence=0.8,
                )
            assistant = _make_assistant_with_store(store)
            block = assistant._build_active_proposals_block()
            line_count = block.count("\n- ")
            # Max 15 Zeilen
            assert line_count <= 15
        finally:
            store.close()

    def test_store_failure_does_not_kill_prompt(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        broken_store = MagicMock()
        broken_store.list_active.side_effect = RuntimeError("db down")
        assistant = _make_assistant_with_store(broken_store)
        with caplog.at_level("WARNING"):
            block = assistant._build_active_proposals_block()
        assert block == ""
        assert any("Active-Proposals-Block" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# _build_plugin_candidate_hint
# ---------------------------------------------------------------------------


class TestPluginCandidateHint:
    def test_contains_block_format(self) -> None:
        hint = Assistant._build_plugin_candidate_hint()
        assert "<plugin-candidate>" in hint
        assert "intent" in hint
        assert "title" in hint
        assert "confidence" in hint

    def test_warns_against_smalltalk(self) -> None:
        hint = Assistant._build_plugin_candidate_hint()
        # Negativliste-Hinweis
        assert "Smalltalk" in hint or "smalltalk" in hint.lower()


# ---------------------------------------------------------------------------
# AssistantResult-Feld
# ---------------------------------------------------------------------------


class TestAssistantResultField:
    def test_default_is_none(self) -> None:
        from elder_berry.core.assistant import AssistantResult

        result = AssistantResult(
            response="hi", action_executed=None, action_success=False
        )
        assert result.plugin_candidate is None

    def test_can_carry_dict(self) -> None:
        from elder_berry.core.assistant import AssistantResult

        result = AssistantResult(
            response="hi",
            action_executed=None,
            action_success=False,
            plugin_candidate={"intent": "x", "title": "X", "confidence": 0.8},
        )
        assert result.plugin_candidate is not None
        assert result.plugin_candidate["intent"] == "x"
