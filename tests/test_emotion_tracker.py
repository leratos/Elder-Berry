"""Tests für EmotionTracker – Emotionales Kurzzeitgedächtnis."""
from datetime import datetime, timedelta

import pytest

from elder_berry.character.base import Emotion
from elder_berry.character.emotion_tracker import EmotionTracker, EmotionEntry


# ---------------------------------------------------------------------------
# EmotionEntry DTO
# ---------------------------------------------------------------------------

class TestEmotionEntry:

    def test_fields(self):
        ts = datetime(2026, 3, 19, 12, 0)
        entry = EmotionEntry(emotion=Emotion.CHEERFUL, timestamp=ts)
        assert entry.emotion is Emotion.CHEERFUL
        assert entry.timestamp == ts


# ---------------------------------------------------------------------------
# EmotionTracker – record & Ringbuffer
# ---------------------------------------------------------------------------

class TestRecord:

    def test_record_single(self):
        tracker = EmotionTracker()
        tracker.record(Emotion.CHEERFUL)
        assert tracker.entry_count == 1

    def test_record_multiple(self):
        tracker = EmotionTracker()
        for emotion in [Emotion.CHEERFUL, Emotion.SAD, Emotion.ANGRY]:
            tracker.record(emotion)
        assert tracker.entry_count == 3

    def test_ringbuffer_overflow(self):
        tracker = EmotionTracker(max_entries=3)
        for emotion in [Emotion.CHEERFUL, Emotion.SAD, Emotion.ANGRY, Emotion.NEUTRAL]:
            tracker.record(emotion)
        assert tracker.entry_count == 3

    def test_ringbuffer_evicts_oldest(self):
        tracker = EmotionTracker(max_entries=2)
        ts_base = datetime(2026, 3, 19, 12, 0)
        tracker.record(Emotion.CHEERFUL, ts_base)
        tracker.record(Emotion.SAD, ts_base + timedelta(minutes=1))
        tracker.record(Emotion.ANGRY, ts_base + timedelta(minutes=2))
        # CHEERFUL sollte rausgeflogen sein
        assert tracker.dominant_emotion(ts_base + timedelta(minutes=2)) is not Emotion.CHEERFUL

    def test_record_with_custom_timestamp(self):
        tracker = EmotionTracker()
        ts = datetime(2026, 1, 1, 0, 0)
        tracker.record(Emotion.SHY, ts)
        assert tracker.entry_count == 1

    def test_clear(self):
        tracker = EmotionTracker()
        tracker.record(Emotion.ANGRY)
        tracker.record(Emotion.SAD)
        tracker.clear()
        assert tracker.entry_count == 0


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------

class TestDecay:

    def test_active_entries_within_decay(self):
        tracker = EmotionTracker(decay_minutes=30)
        now = datetime(2026, 3, 19, 12, 0)
        tracker.record(Emotion.CHEERFUL, now - timedelta(minutes=10))
        tracker.record(Emotion.SAD, now - timedelta(minutes=5))
        # Beide innerhalb von 30 Min
        assert tracker.dominant_emotion(now) is not Emotion.NEUTRAL

    def test_expired_entries_ignored(self):
        tracker = EmotionTracker(decay_minutes=30)
        now = datetime(2026, 3, 19, 12, 0)
        tracker.record(Emotion.ANGRY, now - timedelta(minutes=60))
        # Eintrag ist 60 Min alt, Decay ist 30 → sollte ignoriert werden
        assert tracker.dominant_emotion(now) is Emotion.NEUTRAL

    def test_mixed_active_and_expired(self):
        tracker = EmotionTracker(decay_minutes=30)
        now = datetime(2026, 3, 19, 12, 0)
        tracker.record(Emotion.ANGRY, now - timedelta(minutes=60))  # expired
        tracker.record(Emotion.CHEERFUL, now - timedelta(minutes=5))  # active
        assert tracker.dominant_emotion(now) is Emotion.CHEERFUL

    def test_all_expired_returns_neutral(self):
        tracker = EmotionTracker(decay_minutes=10)
        now = datetime(2026, 3, 19, 12, 0)
        tracker.record(Emotion.ANGRY, now - timedelta(minutes=20))
        tracker.record(Emotion.SAD, now - timedelta(minutes=15))
        assert tracker.dominant_emotion(now) is Emotion.NEUTRAL

    def test_summary_none_when_all_expired(self):
        tracker = EmotionTracker(decay_minutes=10)
        now = datetime(2026, 3, 19, 12, 0)
        tracker.record(Emotion.SAD, now - timedelta(minutes=20))
        assert tracker.get_mood_summary(now) is None


# ---------------------------------------------------------------------------
# dominant_emotion
# ---------------------------------------------------------------------------

class TestDominantEmotion:

    def test_empty_tracker_returns_neutral(self):
        tracker = EmotionTracker()
        assert tracker.dominant_emotion() is Emotion.NEUTRAL

    def test_single_entry(self):
        tracker = EmotionTracker()
        now = datetime(2026, 3, 19, 12, 0)
        tracker.record(Emotion.ANGRY, now)
        assert tracker.dominant_emotion(now) is Emotion.ANGRY

    def test_majority_wins(self):
        tracker = EmotionTracker(max_entries=5)
        now = datetime(2026, 3, 19, 12, 0)
        for i, emotion in enumerate([
            Emotion.CHEERFUL, Emotion.CHEERFUL, Emotion.CHEERFUL,
            Emotion.SAD, Emotion.ANGRY,
        ]):
            tracker.record(emotion, now + timedelta(seconds=i))
        assert tracker.dominant_emotion(now + timedelta(seconds=5)) is Emotion.CHEERFUL

    def test_tie_returns_one_of_tied(self):
        tracker = EmotionTracker(max_entries=4)
        now = datetime(2026, 3, 19, 12, 0)
        for i, emotion in enumerate([
            Emotion.SAD, Emotion.SAD, Emotion.ANGRY, Emotion.ANGRY
        ]):
            tracker.record(emotion, now + timedelta(seconds=i))
        result = tracker.dominant_emotion(now + timedelta(seconds=5))
        assert result in (Emotion.SAD, Emotion.ANGRY)


# ---------------------------------------------------------------------------
# get_trend
# ---------------------------------------------------------------------------

class TestGetTrend:

    def test_no_entries_returns_none(self):
        tracker = EmotionTracker()
        assert tracker.get_trend() is None

    def test_single_entry_returns_none(self):
        tracker = EmotionTracker()
        now = datetime(2026, 3, 19, 12, 0)
        tracker.record(Emotion.SAD, now)
        assert tracker.get_trend(now) is None

    def test_aufhellend(self):
        tracker = EmotionTracker()
        now = datetime(2026, 3, 19, 12, 0)
        for i, emotion in enumerate([Emotion.SAD, Emotion.NEUTRAL, Emotion.CHEERFUL]):
            tracker.record(emotion, now + timedelta(seconds=i))
        assert tracker.get_trend(now + timedelta(seconds=3)) == "aufhellend"

    def test_abkuehlend(self):
        tracker = EmotionTracker()
        now = datetime(2026, 3, 19, 12, 0)
        for i, emotion in enumerate([Emotion.CHEERFUL, Emotion.NEUTRAL, Emotion.SAD]):
            tracker.record(emotion, now + timedelta(seconds=i))
        assert tracker.get_trend(now + timedelta(seconds=3)) == "abkühlend"

    def test_stabil(self):
        tracker = EmotionTracker()
        now = datetime(2026, 3, 19, 12, 0)
        for i in range(3):
            tracker.record(Emotion.NEUTRAL, now + timedelta(seconds=i))
        assert tracker.get_trend(now + timedelta(seconds=3)) == "stabil"

    def test_wechselhaft(self):
        tracker = EmotionTracker()
        now = datetime(2026, 3, 19, 12, 0)
        for i, emotion in enumerate([Emotion.CHEERFUL, Emotion.SAD, Emotion.CHEERFUL]):
            tracker.record(emotion, now + timedelta(seconds=i))
        assert tracker.get_trend(now + timedelta(seconds=3)) == "wechselhaft"


# ---------------------------------------------------------------------------
# get_mood_summary
# ---------------------------------------------------------------------------

class TestGetMoodSummary:

    def test_empty_returns_none(self):
        tracker = EmotionTracker()
        assert tracker.get_mood_summary() is None

    def test_single_entry_format(self):
        tracker = EmotionTracker()
        now = datetime(2026, 3, 19, 12, 0)
        tracker.record(Emotion.ANGRY, now)
        summary = tracker.get_mood_summary(now)
        assert summary is not None
        assert "angry" in summary
        assert "Dominante Stimmung: angry" in summary

    def test_multi_entry_contains_chain(self):
        tracker = EmotionTracker()
        now = datetime(2026, 3, 19, 12, 0)
        for i, emotion in enumerate([Emotion.SAD, Emotion.NEUTRAL, Emotion.CHEERFUL]):
            tracker.record(emotion, now + timedelta(seconds=i))
        summary = tracker.get_mood_summary(now + timedelta(seconds=3))
        assert "sad → neutral → cheerful" in summary

    def test_summary_contains_trend(self):
        tracker = EmotionTracker()
        now = datetime(2026, 3, 19, 12, 0)
        for i, emotion in enumerate([Emotion.SAD, Emotion.NEUTRAL, Emotion.CHEERFUL]):
            tracker.record(emotion, now + timedelta(seconds=i))
        summary = tracker.get_mood_summary(now + timedelta(seconds=3))
        assert "Tendenz:" in summary

    def test_summary_no_trend_with_single_entry(self):
        tracker = EmotionTracker()
        now = datetime(2026, 3, 19, 12, 0)
        tracker.record(Emotion.CHEERFUL, now)
        summary = tracker.get_mood_summary(now)
        assert "Tendenz:" not in summary


# ---------------------------------------------------------------------------
# SaleriaEngine Integration
# ---------------------------------------------------------------------------

class TestSaleriaIntegration:

    def test_extract_emotion_feeds_tracker(self):
        from elder_berry.character.saleria import SaleriaEngine
        engine = SaleriaEngine()
        engine.extract_emotion("[cheerful] Hallo!")
        engine.extract_emotion("[angry] Grr!")
        context = engine.get_mood_context()
        assert context is not None
        assert "cheerful" in context
        assert "angry" in context

    def test_get_mood_context_none_initially(self):
        from elder_berry.character.saleria import SaleriaEngine
        engine = SaleriaEngine()
        assert engine.get_mood_context() is None

    def test_get_mood_context_after_single_emotion(self):
        from elder_berry.character.saleria import SaleriaEngine
        engine = SaleriaEngine()
        engine.extract_emotion("[sad] Das ist traurig.")
        context = engine.get_mood_context()
        assert context is not None
        assert "sad" in context

    def test_neutral_fallback_not_tracked(self):
        """Wenn kein Tag gefunden → NEUTRAL returned, aber NICHT im Tracker."""
        from elder_berry.character.saleria import SaleriaEngine
        engine = SaleriaEngine()
        result = engine.extract_emotion("Kein Tag hier.")
        assert result is Emotion.NEUTRAL
        # Tracker sollte leer sein
        assert engine.get_mood_context() is None


# ---------------------------------------------------------------------------
# Assistant Integration
# ---------------------------------------------------------------------------

class TestAssistantIntegration:

    def test_mood_context_in_system_prompt(self):
        """Prüft dass mood_context im generierten System-Prompt auftaucht."""
        from unittest.mock import MagicMock, patch
        from elder_berry.character.saleria import SaleriaEngine
        from elder_berry.core.assistant import Assistant

        engine = SaleriaEngine()
        # Emotionen aufbauen
        engine.extract_emotion("[angry] Grr!")
        engine.extract_emotion("[angry] Nochmal!")

        llm = MagicMock()
        llm.generate.return_value = '{"action": null, "params": {}, "response": "[neutral] Ok."}'
        actions_db = MagicMock()
        actions_db.list_all.return_value = []
        controller = MagicMock()

        assistant = Assistant(
            llm=llm, actions_db=actions_db, controller=controller,
            character=engine,
        )
        assistant.process("Hallo")

        # Prüfe dass der System-Prompt mood_context enthält
        call_args = llm.generate.call_args
        system_prompt = call_args.kwargs.get("system") or call_args[1].get("system", "")
        assert "angry" in system_prompt
        assert "Dominante Stimmung" in system_prompt
