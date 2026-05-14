"""Tests für CharacterEngine (ABC) und SaleriaEngine."""

import pytest

from elder_berry.character.base import (
    CharacterEngine,
    Emotion,
    EmotionMapping,
    MoodState,
    Personality,
)
from elder_berry.character.saleria import SaleriaEngine


# ---------------------------------------------------------------------------
# DTO-Tests
# ---------------------------------------------------------------------------


class TestEmotion:
    """Tests für das Emotion Enum."""

    def test_all_emotions_have_string_values(self):
        for emotion in Emotion:
            assert isinstance(emotion.value, str)

    def test_emotion_count(self):
        assert len(Emotion) == 10

    def test_emotion_from_value(self):
        assert Emotion("neutral") is Emotion.NEUTRAL
        assert Emotion("angry") is Emotion.ANGRY

    def test_invalid_emotion_raises(self):
        with pytest.raises(ValueError):
            Emotion("nonexistent")


class TestPersonality:
    """Tests für das Personality DTO."""

    def test_personality_is_frozen(self):
        p = Personality(name="Test", title="T", core_trait="c", speaking_style="s")
        with pytest.raises(AttributeError):
            p.name = "Changed"

    def test_personality_defaults(self):
        p = Personality(name="Test", title="T", core_trait="c", speaking_style="s")
        assert p.boundaries == []

    def test_personality_with_boundaries(self):
        p = Personality(
            name="Test",
            title="T",
            core_trait="c",
            speaking_style="s",
            boundaries=["no violence"],
        )
        assert p.boundaries == ["no violence"]


class TestMoodState:
    """Tests für das MoodState DTO."""

    def test_default_mood(self):
        mood = MoodState()
        assert mood.current_emotion is Emotion.NEUTRAL
        assert mood.intensity == 0.5

    def test_custom_mood(self):
        mood = MoodState(current_emotion=Emotion.ANGRY, intensity=0.9)
        assert mood.current_emotion is Emotion.ANGRY
        assert mood.intensity == 0.9

    def test_intensity_too_low(self):
        with pytest.raises(ValueError):
            MoodState(intensity=-0.1)

    def test_intensity_too_high(self):
        with pytest.raises(ValueError):
            MoodState(intensity=1.1)

    def test_intensity_boundaries(self):
        MoodState(intensity=0.0)
        MoodState(intensity=1.0)


class TestEmotionMapping:
    """Tests für das EmotionMapping DTO."""

    def test_defaults_are_none(self):
        em = EmotionMapping(emotion=Emotion.NEUTRAL)
        assert em.voice_sample is None
        assert em.sprite_asset is None


# ---------------------------------------------------------------------------
# SaleriaEngine Tests
# ---------------------------------------------------------------------------


class TestSaleriaEngineInit:
    """Tests für SaleriaEngine Initialisierung."""

    def test_loads_default_config(self):
        engine = SaleriaEngine()
        assert isinstance(engine, CharacterEngine)

    def test_personality_name(self):
        engine = SaleriaEngine()
        p = engine.get_personality()
        assert p.name == "Saleria Berry"

    def test_personality_title(self):
        engine = SaleriaEngine()
        assert engine.get_personality().title == "Digitale Assistentin"

    def test_personality_has_boundaries(self):
        engine = SaleriaEngine()
        assert len(engine.get_personality().boundaries) > 0

    def test_default_mood_is_neutral(self):
        engine = SaleriaEngine()
        assert engine.get_mood().current_emotion is Emotion.NEUTRAL


class TestSaleriaEngineMood:
    """Tests für Mood-Verwaltung."""

    def test_set_mood(self):
        engine = SaleriaEngine()
        engine.set_mood(Emotion.CHEERFUL, 0.8)
        mood = engine.get_mood()
        assert mood.current_emotion is Emotion.CHEERFUL
        assert mood.intensity == 0.8

    def test_set_mood_default_intensity(self):
        engine = SaleriaEngine()
        engine.set_mood(Emotion.ANGRY)
        assert engine.get_mood().intensity == 0.5

    def test_set_mood_invalid_intensity(self):
        engine = SaleriaEngine()
        with pytest.raises(ValueError):
            engine.set_mood(Emotion.SAD, 1.5)


class TestSaleriaEnginePrompt:
    """Tests für System-Prompt Generierung."""

    def test_prompt_contains_name(self):
        engine = SaleriaEngine()
        prompt = engine.build_system_prompt()
        assert "Saleria Berry" in prompt

    def test_prompt_contains_emotion_tags(self):
        engine = SaleriaEngine()
        prompt = engine.build_system_prompt()
        assert "[neutral]" in prompt
        assert "[cheerful]" in prompt
        assert "[angry]" in prompt

    def test_prompt_contains_actions(self):
        engine = SaleriaEngine()
        prompt = engine.build_system_prompt(available_actions="- custom: test")
        assert "- custom: test" in prompt

    def test_prompt_contains_json_format(self):
        engine = SaleriaEngine()
        prompt = engine.build_system_prompt()
        assert '"action"' in prompt
        assert '"response"' in prompt

    def test_remote_command_prompt_contains_announce_rule(self):
        # Phase 90-B: response muss ANKUENDIGUNG sein, kein Vollzugs-Statement.
        engine = SaleriaEngine()
        prompt = engine.build_system_prompt()
        assert "ANKÜNDIGUNG" in prompt
        assert "Vollzugs" in prompt

    def test_remote_command_prompt_contains_fakt_example(self):
        # Phase 91-A: das fruehere mehrzeilige notiz:-Beispiel ist
        # auskommentiert (NoteStore-Refactor, Notiz-Backend in Umstellung).
        # Ersatz: ein Fakt-merk-Beispiel demonstriert weiterhin das
        # "Ankuendigung statt Vollzug"-Pattern.
        engine = SaleriaEngine()
        prompt = engine.build_system_prompt()
        assert "merk dir:" in prompt
        assert "Ich merke mir" in prompt


class TestSaleriaEngineEmotionExtraction:
    """Tests für Emotions-Tag Extraktion aus LLM-Antworten."""

    def test_extract_cheerful(self):
        engine = SaleriaEngine()
        text = "[cheerful] Na, das hab ich doch gern gemacht!"
        assert engine.extract_emotion(text) is Emotion.CHEERFUL

    def test_extract_angry(self):
        engine = SaleriaEngine()
        assert engine.extract_emotion("[angry] Das war nicht klug.") is Emotion.ANGRY

    def test_extract_case_insensitive(self):
        engine = SaleriaEngine()
        assert engine.extract_emotion("[CHEERFUL] Hallo!") is Emotion.CHEERFUL
        assert engine.extract_emotion("[Sarcastic] Ach ja?") is Emotion.SARCASTIC

    def test_extract_no_tag_returns_neutral(self):
        engine = SaleriaEngine()
        assert engine.extract_emotion("Einfach nur Text.") is Emotion.NEUTRAL

    def test_extract_unknown_tag_returns_neutral(self):
        engine = SaleriaEngine()
        assert engine.extract_emotion("[unknown] Text") is Emotion.NEUTRAL

    def test_extract_updates_mood(self):
        engine = SaleriaEngine()
        engine.extract_emotion("[sad] Das ist traurig.")
        assert engine.get_mood().current_emotion is Emotion.SAD

    def test_extract_tag_in_middle_of_text(self):
        engine = SaleriaEngine()
        text = "Hier kommt [whisper] ein Geheimnis."
        assert engine.extract_emotion(text) is Emotion.WHISPER


class TestSaleriaEngineCleanResponse:
    """Tests für das Entfernen von Emotions-Tags."""

    def test_clean_single_tag(self):
        engine = SaleriaEngine()
        assert engine.clean_response("[cheerful] Hallo!") == "Hallo!"

    def test_clean_multiple_tags(self):
        engine = SaleriaEngine()
        text = "[cheerful] Hallo [sad] und tschüss"
        assert engine.clean_response(text) == "Hallo  und tschüss"

    def test_clean_no_tags(self):
        engine = SaleriaEngine()
        assert engine.clean_response("Normaler Text.") == "Normaler Text."

    def test_clean_case_insensitive(self):
        engine = SaleriaEngine()
        assert engine.clean_response("[ANGRY] Grr!") == "Grr!"


class TestSaleriaEngineVoiceSamples:
    """Tests für Voice-Sample Zuordnung."""

    def test_neutral_sample_exists(self):
        engine = SaleriaEngine()
        path = engine.get_voice_sample(Emotion.NEUTRAL)
        assert path is not None
        assert path.exists()
        assert path.name == "saleria-neutral.wav"

    def test_all_samples_mapped(self):
        engine = SaleriaEngine()
        for emotion in Emotion:
            path = engine.get_voice_sample(emotion)
            assert path is not None, f"Kein Voice-Sample für {emotion.value}"
            assert path.exists(), f"Sample fehlt: {path}"

    def test_sprite_asset_none_without_dir(self):
        engine = SaleriaEngine()
        assert engine.get_sprite_asset(Emotion.NEUTRAL) is None
