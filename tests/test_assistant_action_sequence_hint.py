"""Tests: Assistant action_sequence-System-Prompt-Hint (Phase 82 Etappe 2).

Pflicht aus Konzept docs/concepts/phase-82-multi-action-sequencing.md §5.2:
- Hint enthaelt mindestens ein Few-Shot mit ``on_failure: stop`` und
  logischer Step-Abhaengigkeit (sonst lernt Saleria die ``stop``-
  Strategie nie).
- Hint enthaelt Few-Shot mit ``on_failure: continue`` (heterogen).
- Hint warnt aktiv vor 5x-derselbe-Command -- dafuer reicht ein
  remote_command mit Newline-separiertem command-String (Quick-Fix).
- Hint erscheint im finalen System-Prompt -- in BEIDEN Pfaden
  (Saleria-CharacterEngine + Fallback-Template).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from elder_berry.core.assistant import Assistant


# ---------------------------------------------------------------------------
# Hint-Inhalt (Pflicht aus Konzept §5.2)
# ---------------------------------------------------------------------------


class TestActionSequenceHintContent:
    def test_contains_action_sequence_keyword(self) -> None:
        hint = Assistant._build_action_sequence_hint()
        assert "action_sequence" in hint

    def test_contains_steps_and_on_failure_keys(self) -> None:
        hint = Assistant._build_action_sequence_hint()
        assert '"steps"' in hint
        assert "on_failure" in hint

    def test_documents_continue_strategy(self) -> None:
        hint = Assistant._build_action_sequence_hint()
        assert "'continue'" in hint or '"continue"' in hint
        # Default-Markierung darf nicht verschwinden -- LLM soll wissen,
        # was greift wenn er on_failure weglaesst.
        assert "Default" in hint or "default" in hint

    def test_documents_stop_strategy(self) -> None:
        hint = Assistant._build_action_sequence_hint()
        assert "'stop'" in hint or '"stop"' in hint

    def test_few_shot_continue_example_present(self) -> None:
        """Heterogenes continue-Beispiel: Notiz + Reminder + Todo."""
        hint = Assistant._build_action_sequence_hint()
        # Mindestens ein on_failure: continue im Beispiel-JSON
        assert '"on_failure": "continue"' in hint
        # Heterogen: drei verschiedene Command-Typen sind drin
        assert "notiz:" in hint
        assert "erinnere mich" in hint
        assert "todo:" in hint

    def test_few_shot_stop_example_with_logical_dependency(self) -> None:
        """Pflicht aus §5.2: stop-Few-Shot mit logischer Abhaengigkeit.

        Ohne dieses Beispiel lernt Saleria die stop-Strategie nie und der
        on_failure=stop-Pfad bleibt totes Code.
        """
        hint = Assistant._build_action_sequence_hint()
        assert '"on_failure": "stop"' in hint
        # Logische Abhaengigkeit: Termin + Reminder, beides clear
        # Pending-Confirm-frei (R3 aus §3.2 -- mail-antworte ginge
        # nicht, weil pending_confirmation in der Sequenz FAILURE wird).
        assert "termin:" in hint
        # Reminder muss den Termin-Inhalt referenzieren -- sonst keine
        # echte Step-Abhaengigkeit, sondern zwei unabhaengige Aktionen.
        assert "Zahnarzt" in hint

    def test_warns_against_homogeneous_batch(self) -> None:
        """Konzept-Vorrang-Regel: 5x derselbe Command -> Multi-Line-Quick-Fix,
        nicht action_sequence. Sonst doppelte Wege fuer denselben Use-Case."""
        hint = Assistant._build_action_sequence_hint()
        # Negativ-Hinweis ist drin (egal in welcher exakten Formulierung,
        # solange "NICHT" + "Newline" auftauchen).
        assert "NICHT" in hint
        assert "Newline" in hint or "newline" in hint.lower()

    def test_response_field_in_examples_signals_user_intent(self) -> None:
        """Beispiele zeigen 'response'-Feld -- LLM soll mitkommunizieren,
        was er gerade tut, nicht stillschweigend Steps abarbeiten."""
        hint = Assistant._build_action_sequence_hint()
        assert '"response"' in hint

    def test_phase_82_1_multi_line_in_step_clarification(self) -> None:
        """Phase 82.1: Hint muss klarstellen, dass gleichartige Items
        innerhalb einer heterogenen Sequenz wahlweise als einzelne
        Steps ODER als ein Multi-Line-Step emittiert werden koennen.

        Trigger: Smoketest-Befund -- Saleria packte 3 Todos in 1 Step
        und parse_command warf FAILURE 'kein bekannter command', weil
        ��3.2 die Splittung nicht erlaubte. ��3.2 wurde umgekehrt;
        der Hint dokumentiert die neue Wahlfreiheit + zeigt ein
        Multi-Line-Few-Shot.
        """
        hint = Assistant._build_action_sequence_hint()
        # Klarstellung-Marker (Wording darf sich aendern, Marker bleiben)
        assert "Phase 82.1" in hint
        assert "EINZELNE Steps" in hint or "einzelne Steps" in hint.lower()
        # Few-Shot zeigt einen Multi-Line-command (\\n im JSON-String)
        assert "\\n" in hint
        # Few-Shot ist ein Pizza-Beispiel mit 3 Todos + Notiz + Reminder
        assert "Pizza" in hint


# ---------------------------------------------------------------------------
# Wiring: Hint erscheint im finalen System-Prompt
# ---------------------------------------------------------------------------


def _make_assistant_no_character() -> Assistant:
    """Minimal-Assistant ohne CharacterEngine -> Fallback-Template-Pfad."""
    llm = MagicMock()
    actions_db = MagicMock()
    actions_db.list_all.return_value = []
    controller = MagicMock()
    return Assistant(
        llm=llm,
        actions_db=actions_db,
        controller=controller,
    )


def _make_assistant_with_character() -> Assistant:
    """Minimal-Assistant mit MagicMock-CharacterEngine -> Saleria-Pfad."""
    llm = MagicMock()
    actions_db = MagicMock()
    actions_db.list_all.return_value = []
    controller = MagicMock()
    character = MagicMock()
    character.build_system_prompt.return_value = "SALERIA-CHAR-PROMPT-BODY"
    character.get_mood_context.return_value = ""
    return Assistant(
        llm=llm,
        actions_db=actions_db,
        controller=controller,
        character=character,
    )


class TestActionSequenceHintWiredIntoPrompt:
    def test_hint_present_in_fallback_path(self) -> None:
        assistant = _make_assistant_no_character()
        prompt = assistant._build_system_prompt()
        # Hint ist drin (charakteristische Marker, nicht volltext --
        # spaetere Wording-Refines sollen die Tests nicht killen).
        assert "action_sequence" in prompt
        assert '"on_failure": "stop"' in prompt
        assert '"on_failure": "continue"' in prompt

    def test_hint_present_in_character_path(self) -> None:
        assistant = _make_assistant_with_character()
        prompt = assistant._build_system_prompt()
        # Charakter-Body wurde aufgenommen ...
        assert "SALERIA-CHAR-PROMPT-BODY" in prompt
        # ... UND der Hint wurde angehaengt.
        assert "action_sequence" in prompt
        assert '"on_failure": "stop"' in prompt
        assert '"on_failure": "continue"' in prompt

    def test_hint_does_not_replace_plugin_candidate_hint(self) -> None:
        """Beide Hints muessen koexistieren -- nicht versehentlich der
        candidate_hint beim Wiring rausgeflogen sein."""
        assistant = _make_assistant_no_character()
        prompt = assistant._build_system_prompt()
        assert "action_sequence" in prompt
        assert "<plugin-candidate>" in prompt
