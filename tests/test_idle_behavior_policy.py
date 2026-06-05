"""Tests für IdleBehaviorPolicy (Phase 83.6).

Determinismus ohne Flake: Die Intervalle werden mit ``min == max`` konstruiert
(``random.uniform(x, x) == x``) und die Action-Pools sind ein-elementig
(``random.choice([a]) == a``). Damit reicht eine echte ``random.Random`` – kein
Seed-Raten, keine zeitabhängigen Flakes (§ Klärpunkt 4).
"""

from __future__ import annotations

import pytest

from elder_berry.avatar.attention import AttentionProvider, AttentionState
from elder_berry.avatar.briefing_mode import BriefingModeProvider
from elder_berry.avatar.idle_policy import (
    BLINK_EYES,
    IdleAction,
    IdleBehaviorPolicy,
)
from elder_berry.character.base import Emotion

# Idle-Aktionen wie in der realen Config (avatar_config.yaml).
_GLANCE = IdleAction("glance_left", "eye_left_side_open", "eye_right_side_open", None)
_SMILE = IdleAction("smile", None, None, "mouth_halfopen")
_SOFT_CLOSE = IdleAction("soft_close", "eye_left_close", "eye_right_close", None)
_SURPRISE = IdleAction(
    "surprise", "eye_left_surprise_open", "eye_right_surprise_open", "mouth_open"
)


class _FixedAttention(AttentionProvider):
    def __init__(self, state: AttentionState) -> None:
        self._state = state

    def current(self) -> AttentionState:
        return self._state


class _FixedBriefing(BriefingModeProvider):
    def __init__(self, formal: bool) -> None:
        self._formal = formal

    def is_formal(self) -> bool:
        return self._formal


def _policy(
    *,
    idle_actions=(_GLANCE,),
    can_blink=None,
    attention=AttentionState.UNKNOWN,
    formal=False,
    available=None,
    blink_interval=3.0,
    blink_duration=0.5,
    idle_interval=5.0,
    idle_duration=2.0,
) -> IdleBehaviorPolicy:
    return IdleBehaviorPolicy(
        idle_actions=list(idle_actions),
        can_blink=can_blink if can_blink is not None else {Emotion.NEUTRAL: True},
        attention_provider=_FixedAttention(attention),
        briefing_provider=_FixedBriefing(formal),
        available_components=available,
        blink_min=blink_interval,
        blink_max=blink_interval,
        blink_duration=blink_duration,
        idle_min=idle_interval,
        idle_max=idle_interval,
        idle_duration=idle_duration,
    )


# ---------------------------------------------------------------------------
# Blink – mood-unabhängig (B2/§0.4), can_blink:false blinzelt nie
# ---------------------------------------------------------------------------


class TestBlinkInterval:
    def test_interval_is_mood_independent(self):
        """blink_interval() liefert für jede Emotion dasselbe (mood-unabhängig)."""
        policy = _policy(blink_interval=4.0)
        intervals = {policy.blink_interval(e) for e in Emotion}
        assert intervals == {4.0}

    def test_interval_within_global_range(self):
        policy = IdleBehaviorPolicy(
            idle_actions=[_GLANCE],
            can_blink={Emotion.NEUTRAL: True},
            attention_provider=_FixedAttention(AttentionState.UNKNOWN),
        )
        for _ in range(50):
            assert 2.0 <= policy.blink_interval(Emotion.NEUTRAL) <= 6.0


class TestCanBlink:
    def test_can_blink_false_never_blinks(self):
        """can_blink=false → nie geschlossene Augen, egal wie viel Zeit vergeht."""
        policy = _policy(can_blink={Emotion.ANGRY: False}, blink_interval=0.5)
        for now in range(0, 100):
            assert policy.update_blink(float(now), Emotion.ANGRY) is None

    def test_unmapped_mood_never_blinks(self):
        """Unbekannte Emotion (nicht in can_blink) → kein Blink (Fallback False)."""
        policy = _policy(can_blink={}, blink_interval=0.5)
        for now in range(0, 20):
            assert policy.update_blink(float(now), Emotion.NEUTRAL) is None

    def test_can_blink_true_blinks_on_global_schedule(self):
        """can_blink=true: Blink nach Intervall, schließt nach Dauer, plant neu."""
        policy = _policy(
            can_blink={Emotion.NEUTRAL: True}, blink_interval=3.0, blink_duration=0.5
        )
        m = Emotion.NEUTRAL
        assert policy.update_blink(0.0, m) is None  # lazy: plant next_blink @3.0
        assert policy.update_blink(2.9, m) is None  # noch nicht fällig
        assert policy.update_blink(3.0, m) == BLINK_EYES  # Blink startet
        assert policy.update_blink(3.4, m) == BLINK_EYES  # noch geschlossen
        assert policy.update_blink(3.5, m) is None  # Dauer vorbei → offen + neu
        assert policy.update_blink(6.5, m) == BLINK_EYES  # nächster Blink @ 3.5+3.0


# ---------------------------------------------------------------------------
# Idle – Trigger-Timing, Sprech-Gate, Attention-Gate
# ---------------------------------------------------------------------------


class TestIdleTrigger:
    def test_idle_triggers_after_interval_and_ends_after_duration(self):
        policy = _policy(idle_actions=(_GLANCE,), idle_interval=5.0, idle_duration=2.0)
        m = Emotion.NEUTRAL
        assert policy.next_action(0.0, m) is None  # lazy: plant next_idle @5.0
        assert policy.next_action(4.9, m) is None  # noch nicht fällig
        assert policy.next_action(5.0, m) is _GLANCE  # Idle startet
        assert policy.next_action(6.0, m) is _GLANCE  # noch aktiv (Ende @7.0)
        assert policy.next_action(7.0, m) is None  # Dauer vorbei → neu geplant

    def test_frame_overrides_suppresses_idle_while_speaking(self):
        """Beim Sprechen werden Idle-Overrides nicht gezeigt (saubere Unterdrückung)."""
        policy = _policy(idle_actions=(_GLANCE,), idle_interval=5.0)
        m = Emotion.NEUTRAL
        policy.frame_overrides(0.0, m, is_speaking=False)  # plant Idle @5.0

        speaking = policy.frame_overrides(10.0, m, is_speaking=True)
        assert speaking.idle_eyes is None
        assert speaking.idle_mouth is None

        # Nach dem Sprechen läuft Idle wieder (Timer war eingefroren).
        resumed = policy.frame_overrides(10.0, m, is_speaking=False)
        assert resumed.idle_eyes == ("eye_left_side_open", "eye_right_side_open")


class TestAttentionGate:
    @pytest.mark.parametrize(
        "state", [AttentionState.UNKNOWN, AttentionState.AWAY]
    )
    def test_unknown_and_away_allow_idle(self, state):
        """UNKNOWN/AWAY = kein aktives Engagement → Idle erlaubt (Bestand)."""
        policy = _policy(attention=state, idle_interval=5.0)
        m = Emotion.NEUTRAL
        policy.next_action(0.0, m)
        assert policy.next_action(5.0, m) is _GLANCE

    @pytest.mark.parametrize(
        "state", [AttentionState.PRESENT, AttentionState.FOCUSED]
    )
    def test_present_and_focused_suppress_idle(self, state):
        """PRESENT/FOCUSED = aktives Engagement → kein ambient-Idle."""
        policy = _policy(attention=state, idle_interval=5.0)
        m = Emotion.NEUTRAL
        policy.next_action(0.0, m)
        assert policy.next_action(5.0, m) is None
        assert policy.next_action(100.0, m) is None


# ---------------------------------------------------------------------------
# Briefing-Modus (formell): nur soft_close, Frequenz −50 %
# ---------------------------------------------------------------------------


class TestFormalBriefingMode:
    def test_formal_only_allows_soft_close(self):
        """Formell: surprise/smile/glance ausgeblendet, nur soft_close wählbar."""
        policy = _policy(
            idle_actions=(_GLANCE, _SMILE, _SURPRISE, _SOFT_CLOSE),
            formal=True,
            idle_interval=5.0,
        )
        m = Emotion.NEUTRAL
        policy.next_action(0.0, m)  # plant Idle: formell → 5.0 * 2 = 10.0
        action = policy.next_action(10.0, m)
        assert action is _SOFT_CLOSE

    def test_formal_halves_idle_frequency(self):
        """Formell halbiert die Idle-Frequenz (Intervall × 2)."""
        casual = _policy(idle_actions=(_SOFT_CLOSE,), formal=False, idle_interval=5.0)
        formal = _policy(idle_actions=(_SOFT_CLOSE,), formal=True, idle_interval=5.0)
        m = Emotion.NEUTRAL
        casual.next_action(0.0, m)
        formal.next_action(0.0, m)
        # casual feuert nach 5 s, formell erst nach 10 s.
        assert casual.next_action(5.0, m) is _SOFT_CLOSE
        assert formal.next_action(5.0, m) is None
        assert formal.next_action(10.0, m) is _SOFT_CLOSE

    def test_formal_without_soft_close_stays_idle_free(self):
        """Formell + kein soft_close in der Config → leerer Pool → kein Idle."""
        policy = _policy(idle_actions=(_GLANCE, _SMILE), formal=True, idle_interval=5.0)
        m = Emotion.NEUTRAL
        policy.next_action(0.0, m)
        assert policy.next_action(10.0, m) is None
        assert policy.next_action(100.0, m) is None


# ---------------------------------------------------------------------------
# Komponenten-Existenz-Guard (§0.6, wie Bestand _start_idle_action)
# ---------------------------------------------------------------------------


class TestComponentGuard:
    def test_missing_component_skips_action(self):
        """Fehlt eine benötigte Komponente, wird die Aktion übersprungen."""
        # surprise braucht mouth_open + surprise-Augen; mouth_open fehlt.
        available = {"eye_left_surprise_open", "eye_right_surprise_open"}
        policy = _policy(
            idle_actions=(_SURPRISE,), available=available, idle_interval=5.0
        )
        m = Emotion.NEUTRAL
        policy.next_action(0.0, m)
        assert policy.next_action(5.0, m) is None  # mouth_open fehlt → übersprungen
        assert policy.next_action(10.0, m) is None  # neu geplant, weiterhin fehlend

    def test_present_components_allow_action(self):
        available = {
            "eye_left_surprise_open",
            "eye_right_surprise_open",
            "mouth_open",
        }
        policy = _policy(
            idle_actions=(_SURPRISE,), available=available, idle_interval=5.0
        )
        m = Emotion.NEUTRAL
        policy.next_action(0.0, m)
        assert policy.next_action(5.0, m) is _SURPRISE

    def test_no_guard_when_available_none(self):
        """available_components=None → kein Guard (Aktion läuft auch ohne Assets)."""
        policy = _policy(idle_actions=(_SURPRISE,), available=None, idle_interval=5.0)
        m = Emotion.NEUTRAL
        policy.next_action(0.0, m)
        assert policy.next_action(5.0, m) is _SURPRISE


# ---------------------------------------------------------------------------
# frame_overrides – Komposition Blink + Idle
# ---------------------------------------------------------------------------


class TestFrameOverrides:
    def test_blink_and_idle_both_present(self):
        """Blink (eigene Augen) und Idle (eigene Augen/Mund) parallel im DTO.

        Der Renderer entscheidet danach via RenderPlan.compose die Priorität
        (Blink > Idle); die Policy liefert beide Roh-Overrides.
        """
        policy = _policy(
            idle_actions=(_GLANCE,),
            can_blink={Emotion.NEUTRAL: True},
            blink_interval=3.0,
            blink_duration=0.5,
            idle_interval=3.0,
            idle_duration=2.0,
        )
        m = Emotion.NEUTRAL
        policy.frame_overrides(0.0, m, is_speaking=False)  # plant beides @3.0
        ov = policy.frame_overrides(3.0, m, is_speaking=False)
        assert ov.blink_eyes == BLINK_EYES
        assert ov.idle_eyes == ("eye_left_side_open", "eye_right_side_open")
        assert ov.idle_mouth is None  # glance hat keinen Mund-Override

    def test_idle_mouth_only_action(self):
        """Eine reine Mund-Idle (smile) setzt idle_mouth, aber keine idle_eyes."""
        policy = _policy(idle_actions=(_SMILE,), idle_interval=5.0)
        m = Emotion.NEUTRAL
        policy.frame_overrides(0.0, m, is_speaking=False)
        ov = policy.frame_overrides(5.0, m, is_speaking=False)
        assert ov.idle_eyes is None
        assert ov.idle_mouth == "mouth_halfopen"

    def test_blink_independent_of_speaking(self):
        """Blink läuft auch beim Sprechen (wie Bestand)."""
        policy = _policy(
            can_blink={Emotion.NEUTRAL: True}, blink_interval=3.0, blink_duration=0.5
        )
        m = Emotion.NEUTRAL
        policy.frame_overrides(0.0, m, is_speaking=True)  # plant Blink @3.0
        ov = policy.frame_overrides(3.0, m, is_speaking=True)
        assert ov.blink_eyes == BLINK_EYES
        assert ov.idle_eyes is None  # Idle beim Sprechen unterdrückt
