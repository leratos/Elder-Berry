"""Tests für EmotionResolver (Phase 83.1) und seine neuen Bausteine.

Deckt ab: seiteneffektfreies ``parse_emotion_tag`` (None != NEUTRAL),
``EmotionTracker.dominant_with_confidence``, das Scoring-Modell des Resolvers
inkl. Confidence-Skala, Trend-Dämpfung, Sensor-Stub, leere Antwort und die
B4-Aufzeichnungs-Semantik (record NACH dem Trend-Read, nur bei Tag).
"""

from datetime import datetime, timedelta

import pytest

from elder_berry.character.base import Emotion
from elder_berry.character.emotion_resolver import EmotionDecision, EmotionResolver
from elder_berry.character.emotion_tracker import EmotionTracker
from elder_berry.character.saleria import SaleriaEngine


# ---------------------------------------------------------------------------
# parse_emotion_tag – seiteneffektfrei, None != NEUTRAL
# ---------------------------------------------------------------------------


class TestParseEmotionTag:
    def test_valid_tag_returns_emotion(self):
        assert SaleriaEngine.parse_emotion_tag("[cheerful] Hi") is Emotion.CHEERFUL

    def test_case_insensitive(self):
        assert SaleriaEngine.parse_emotion_tag("[ANGRY] Grr") is Emotion.ANGRY

    def test_tag_in_middle(self):
        assert SaleriaEngine.parse_emotion_tag("Text [whisper] mehr") is Emotion.WHISPER

    def test_no_tag_returns_none_not_neutral(self):
        # Kernunterscheidung gegenüber extract_emotion: kein Tag != NEUTRAL.
        assert SaleriaEngine.parse_emotion_tag("Einfach nur Text.") is None

    def test_explicit_neutral_tag_returns_neutral(self):
        assert SaleriaEngine.parse_emotion_tag("[neutral] Ok") is Emotion.NEUTRAL

    def test_unknown_tag_returns_none(self):
        assert SaleriaEngine.parse_emotion_tag("[unknown] Text") is None

    def test_is_side_effect_free(self):
        engine = SaleriaEngine()
        engine.parse_emotion_tag("[angry] Grr")
        # Weder Mood noch Tracker dürfen sich geändert haben.
        assert engine.get_mood().current_emotion is Emotion.NEUTRAL
        assert engine.emotion_tracker.entry_count == 0

    def test_intensity_tag_emotion_still_parsed(self):
        # parse_emotion_tag (alt) ignoriert die Intensität, liefert die Emotion.
        assert SaleriaEngine.parse_emotion_tag("[cheerful:0.5] Hi") is Emotion.CHEERFUL


# ---------------------------------------------------------------------------
# parse_emotion_tag_with_intensity (Phase 109)
# ---------------------------------------------------------------------------


class TestParseEmotionTagWithIntensity:
    def test_no_tag_returns_none(self):
        assert SaleriaEngine.parse_emotion_tag_with_intensity("nur Text") is None

    def test_bare_tag_defaults_to_full_intensity(self):
        assert SaleriaEngine.parse_emotion_tag_with_intensity("[angry] x") == (
            Emotion.ANGRY,
            1.0,
        )

    def test_explicit_intensity(self):
        assert SaleriaEngine.parse_emotion_tag_with_intensity("[angry:0.4] x") == (
            Emotion.ANGRY,
            0.4,
        )

    def test_intensity_clamped_above_one(self):
        assert SaleriaEngine.parse_emotion_tag_with_intensity("[angry:2.0] x") == (
            Emotion.ANGRY,
            1.0,
        )

    def test_leading_dot_intensity(self):
        assert SaleriaEngine.parse_emotion_tag_with_intensity("[cheerful:.8] x") == (
            Emotion.CHEERFUL,
            0.8,
        )

    def test_clean_response_strips_intensity_tag(self):
        engine = SaleriaEngine()
        assert engine.clean_response("[cheerful:0.8] Na bitte") == "Na bitte"

    def test_side_effect_free(self):
        engine = SaleriaEngine()
        engine.parse_emotion_tag_with_intensity("[angry:0.9] Grr")
        assert engine.get_mood().current_emotion is Emotion.NEUTRAL
        assert engine.emotion_tracker.entry_count == 0

    def test_negative_intensity_clamped_to_zero(self):
        # Out-of-range (negativ) → Tag wird trotzdem erkannt + auf 0.0 geklemmt.
        assert SaleriaEngine.parse_emotion_tag_with_intensity("[angry:-0.2] x") == (
            Emotion.ANGRY,
            0.0,
        )

    def test_malformed_intensity_defaults_to_full(self):
        # Unparsbare Stärke → volle Intensität (kein Leck, Tag wird erkannt).
        assert SaleriaEngine.parse_emotion_tag_with_intensity("[angry:abc] x") == (
            Emotion.ANGRY,
            1.0,
        )

    def test_empty_intensity_defaults_to_full(self):
        assert SaleriaEngine.parse_emotion_tag_with_intensity("[angry:] x") == (
            Emotion.ANGRY,
            1.0,
        )

    def test_clean_response_strips_negative_intensity(self):
        engine = SaleriaEngine()
        assert engine.clean_response("[angry:-0.2] Grr") == "Grr"

    def test_clean_response_strips_malformed_intensity(self):
        engine = SaleriaEngine()
        assert engine.clean_response("[cheerful:abc] Hi") == "Hi"


# ---------------------------------------------------------------------------
# EmotionTracker.dominant_with_confidence
# ---------------------------------------------------------------------------


class TestDominantWithConfidence:
    def test_empty_returns_neutral_zero(self):
        tracker = EmotionTracker()
        assert tracker.dominant_with_confidence() == (Emotion.NEUTRAL, 0.0)

    def test_single_entry_full_ratio(self):
        tracker = EmotionTracker()
        now = datetime(2026, 3, 19, 12, 0)
        tracker.record(Emotion.ANGRY, now)
        dom, ratio = tracker.dominant_with_confidence(now)
        assert dom is Emotion.ANGRY
        assert ratio == 1.0

    def test_majority_ratio(self):
        tracker = EmotionTracker(max_entries=5)
        now = datetime(2026, 3, 19, 12, 0)
        for i, emotion in enumerate(
            [
                Emotion.CHEERFUL,
                Emotion.CHEERFUL,
                Emotion.CHEERFUL,
                Emotion.SAD,
                Emotion.ANGRY,
            ]
        ):
            tracker.record(emotion, now + timedelta(seconds=i))
        dom, ratio = tracker.dominant_with_confidence(now + timedelta(seconds=5))
        assert dom is Emotion.CHEERFUL
        assert ratio == pytest.approx(3 / 5)

    def test_decay_ignored(self):
        tracker = EmotionTracker(decay_minutes=30)
        now = datetime(2026, 3, 19, 12, 0)
        tracker.record(Emotion.ANGRY, now - timedelta(minutes=60))  # expired
        tracker.record(Emotion.CHEERFUL, now - timedelta(minutes=5))  # active
        dom, ratio = tracker.dominant_with_confidence(now)
        assert dom is Emotion.CHEERFUL
        assert ratio == 1.0


# ---------------------------------------------------------------------------
# EmotionDecision DTO
# ---------------------------------------------------------------------------


class TestEmotionDecision:
    def test_is_frozen(self):
        decision = EmotionDecision(Emotion.NEUTRAL, 0.0, "fallback", {})
        with pytest.raises(AttributeError):
            decision.emotion = Emotion.ANGRY


# ---------------------------------------------------------------------------
# Resolver – Confidence-Skala
# ---------------------------------------------------------------------------


def _resolver_with_seed(*seed: Emotion) -> tuple[EmotionResolver, SaleriaEngine]:
    """Baut Resolver + Engine mit geteiltem Tracker, vorbefüllt mit ``seed``."""
    engine = SaleriaEngine()
    tracker = engine.emotion_tracker
    for emotion in seed:
        tracker.record(emotion)
    resolver = EmotionResolver(character=engine, emotion_tracker=tracker)
    return resolver, engine


class TestResolveConfidenceScale:
    def test_tag_empty_tracker_is_0_7(self):
        resolver, _ = _resolver_with_seed()
        decision = resolver.resolve_from_llm("[cheerful] Hi")
        assert decision.emotion is Emotion.CHEERFUL
        assert decision.confidence == 0.7
        assert decision.source == "llm_tag"
        assert decision.raw_signals == {"llm_tag": 0.7}

    def test_tag_matches_tracker_up_to_0_9(self):
        resolver, _ = _resolver_with_seed(Emotion.CHEERFUL)
        decision = resolver.resolve_from_llm("[cheerful] Hi")
        assert decision.emotion is Emotion.CHEERFUL
        assert decision.confidence == 0.9
        assert decision.source == "llm_tag"
        assert decision.raw_signals == {"llm_tag": 0.7, "tracker_trend": 0.2}

    def test_tag_contradicts_tracker_stays_0_7(self):
        resolver, _ = _resolver_with_seed(Emotion.SAD)
        decision = resolver.resolve_from_llm("[cheerful] Hi")
        # Tag gewinnt die Identität, der widersprechende Trend hebt sie nicht.
        assert decision.emotion is Emotion.CHEERFUL
        assert decision.confidence == 0.7
        assert decision.source == "llm_tag"

    def test_tracker_only_up_to_0_2(self):
        resolver, _ = _resolver_with_seed(Emotion.SAD)
        decision = resolver.resolve_from_llm("Antwort ganz ohne Tag")
        assert decision.emotion is Emotion.SAD
        assert decision.confidence == 0.2
        assert decision.source == "tracker_trend"
        assert decision.raw_signals == {"tracker_trend": 0.2}

    def test_nothing_is_0_0_fallback(self):
        resolver, _ = _resolver_with_seed()
        decision = resolver.resolve_from_llm("Antwort ganz ohne Tag")
        assert decision.emotion is Emotion.NEUTRAL
        assert decision.confidence == 0.0
        assert decision.source == "fallback"
        assert decision.raw_signals == {}

    def test_empty_llm_response(self):
        resolver, _ = _resolver_with_seed()
        decision = resolver.resolve_from_llm("")
        assert decision.emotion is Emotion.NEUTRAL
        assert decision.confidence == 0.0
        assert decision.source == "fallback"


# ---------------------------------------------------------------------------
# Resolver – Intensität = Anzeige-Tiefe, Confidence intensitäts-unabhängig
# (Phase 110, Modell B)
# ---------------------------------------------------------------------------


class TestResolveIntensity:
    def test_bare_tag_full_confidence_and_intensity(self):
        # Bloßes [angry] = Intensität 1.0, volle tag_weight-Confidence.
        resolver, _ = _resolver_with_seed()
        decision = resolver.resolve_from_llm("[angry] Grr")
        assert decision.emotion is Emotion.ANGRY
        assert decision.confidence == 0.7
        assert decision.intensity == 1.0

    def test_weak_intensity_keeps_full_confidence(self):
        # Modell B: [angry:0.4] schaltet (confidence 0.7), intensity = 0.4.
        resolver, _ = _resolver_with_seed()
        decision = resolver.resolve_from_llm("[angry:0.4] etwas genervt")
        assert decision.emotion is Emotion.ANGRY
        assert decision.confidence == 0.7  # intensitäts-UNABHÄNGIG
        assert decision.intensity == 0.4
        assert decision.raw_signals == {"llm_tag": 0.7}

    def test_strong_intensity(self):
        resolver, _ = _resolver_with_seed()
        decision = resolver.resolve_from_llm("[angry:0.9] Schluss jetzt!")
        assert decision.confidence == 0.7
        assert decision.intensity == 0.9

    def test_intensity_independent_of_trend(self):
        # Tag + passender Trend → Confidence 0.9; Intensität bleibt der Tag-Wert.
        resolver, _ = _resolver_with_seed(Emotion.ANGRY)
        decision = resolver.resolve_from_llm("[angry:0.3] grummel")
        assert decision.confidence == 0.9
        assert decision.intensity == 0.3

    def test_intensity_recorded_in_mood(self):
        resolver, engine = _resolver_with_seed()
        resolver.resolve_from_llm("[cheerful:0.3] na gut")
        mood = engine.get_mood()
        assert mood.current_emotion is Emotion.CHEERFUL
        assert mood.intensity == 0.3

    def test_zero_intensity_is_no_signal(self):
        # [angry:0.0] = kein Signal → Fallback NEUTRAL, KEIN Mood/Tracker-Record.
        resolver, engine = _resolver_with_seed()
        decision = resolver.resolve_from_llm("[angry:0.0] kaum der Rede wert")
        assert decision.emotion is Emotion.NEUTRAL
        assert decision.confidence == 0.0
        assert decision.source == "fallback"
        assert decision.raw_signals == {}
        assert engine.get_mood().current_emotion is Emotion.NEUTRAL
        assert engine.emotion_tracker.entry_count == 0


# ---------------------------------------------------------------------------
# Resolver – Trend-Aggregation (wechselhaft-Dämpfung)
# ---------------------------------------------------------------------------


class TestResolveTrendAggregation:
    def test_wechselhaft_trend_is_damped(self):
        # CHEERFUL, SAD, CHEERFUL -> Trend "wechselhaft" -> damp 0.5.
        resolver, _ = _resolver_with_seed(
            Emotion.CHEERFUL, Emotion.SAD, Emotion.CHEERFUL
        )
        decision = resolver.resolve_from_llm("Antwort ohne Tag")
        # dom = CHEERFUL (2/3), contribution = 0.2 * 2/3 * 0.5 = 0.0667 -> 0.067
        assert decision.emotion is Emotion.CHEERFUL
        assert decision.confidence == 0.067
        assert decision.source == "tracker_trend"

    def test_stable_trend_not_damped(self):
        # Drei gleiche Einträge -> Trend "stabil" -> damp 1.0 -> volle 0.2.
        resolver, _ = _resolver_with_seed(
            Emotion.MOTIVATED, Emotion.MOTIVATED, Emotion.MOTIVATED
        )
        decision = resolver.resolve_from_llm("Antwort ohne Tag")
        assert decision.emotion is Emotion.MOTIVATED
        assert decision.confidence == 0.2


# ---------------------------------------------------------------------------
# Resolver – Sensor-Stub
# ---------------------------------------------------------------------------


class TestResolveSensorStub:
    def test_sensor_state_has_no_effect(self):
        resolver, _ = _resolver_with_seed()
        decision = resolver.resolve_from_llm("[cheerful] Hi", sensor_state=object())
        assert decision.emotion is Emotion.CHEERFUL
        assert decision.confidence == 0.7
        # Kein Sensor-Beitrag in den raw_signals.
        assert "sensor" not in decision.raw_signals


# ---------------------------------------------------------------------------
# Resolver – B4-Aufzeichnungs-Semantik
# ---------------------------------------------------------------------------


class TestResolveRecordSemantics:
    def test_tag_records_and_sets_mood(self):
        resolver, engine = _resolver_with_seed()
        resolver.resolve_from_llm("[angry] Grr")
        assert engine.get_mood().current_emotion is Emotion.ANGRY
        assert engine.emotion_tracker.entry_count == 1

    def test_no_tag_does_not_record_or_set_mood(self):
        resolver, engine = _resolver_with_seed()
        resolver.resolve_from_llm("Antwort ohne Tag")
        assert engine.get_mood().current_emotion is Emotion.NEUTRAL
        assert engine.emotion_tracker.entry_count == 0

    def test_record_happens_after_trend_read(self):
        # Seed SAD; Tag cheerful. Würde record VOR dem Trend-Read laufen, gäbe es
        # einen Gleichstand (SAD/CHEERFUL) und damit eine andere Confidence.
        resolver, engine = _resolver_with_seed(Emotion.SAD)
        decision = resolver.resolve_from_llm("[cheerful] Hi")
        assert decision.confidence == 0.7
        assert decision.raw_signals == {"llm_tag": 0.7, "tracker_trend": 0.2}
        # Nach dem Lauf ist CHEERFUL zusätzlich aufgezeichnet.
        assert engine.emotion_tracker.entry_count == 2


# ---------------------------------------------------------------------------
# Resolver – Wiring (geteilter Tracker)
# ---------------------------------------------------------------------------


class TestResolverWiring:
    def test_emotion_tracker_property_is_stable(self):
        engine = SaleriaEngine()
        # Wiederholter Zugriff liefert dieselbe Instanz (kein neuer Tracker je Call).
        first = engine.emotion_tracker
        second = engine.emotion_tracker
        assert first is second
        assert first is engine.emotion_tracker

    def test_records_feed_shared_mood_context(self):
        resolver, engine = _resolver_with_seed()
        resolver.resolve_from_llm("[cheerful] Hi")
        # Der Resolver schreibt in denselben Tracker, der den System-Prompt speist.
        context = engine.get_mood_context()
        assert context is not None
        assert "cheerful" in context
