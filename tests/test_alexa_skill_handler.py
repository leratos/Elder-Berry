"""Tests fuer AlexaSkillHandler -- Alexa Custom Skill auf RPi5."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from elder_berry.robot.alexa_skill_handler import (
    AlexaResult,
    AlexaSkillHandler,
)


def _run(coro):
    """Hilfsfunktion: fuehrt async Coroutine synchron aus."""
    return asyncio.run(coro)


# -- Fixtures -------------------------------------------------------------- #

@pytest.fixture()
def harmony():
    """Mock-HarmonyAdapter."""
    mock = AsyncMock()
    mock.start_activity = AsyncMock(return_value=True)
    mock.power_off = AsyncMock(return_value=True)
    mock.send_command = AsyncMock(return_value=True)
    mock.get_current_activity = AsyncMock(return_value="Fernsehen")
    return mock


@pytest.fixture()
def harmony_scenes():
    """Mock-HarmonySceneManager."""
    mock = AsyncMock()
    mock.start_scene = AsyncMock(return_value={"steps_ok": 3, "steps_total": 3})
    return mock


@pytest.fixture()
def handler(harmony, harmony_scenes):
    """AlexaSkillHandler mit Mock-Harmony."""
    return AlexaSkillHandler(harmony=harmony, harmony_scenes=harmony_scenes)


@pytest.fixture()
def handler_no_harmony():
    """AlexaSkillHandler ohne Harmony."""
    return AlexaSkillHandler(harmony=None, harmony_scenes=None)


def _intent_request(intent_name: str) -> dict:
    """Baut ein minimales Alexa IntentRequest."""
    return {
        "version": "1.0",
        "session": {},
        "request": {
            "type": "IntentRequest",
            "intent": {
                "name": intent_name,
                "slots": {},
            },
        },
    }


def _launch_request() -> dict:
    """Baut ein Alexa LaunchRequest."""
    return {
        "version": "1.0",
        "session": {},
        "request": {"type": "LaunchRequest"},
    }


def _session_ended_request() -> dict:
    """Baut ein Alexa SessionEndedRequest."""
    return {
        "version": "1.0",
        "session": {},
        "request": {"type": "SessionEndedRequest"},
    }


# -- Request Parsing ------------------------------------------------------- #

class TestAlexaRequestParsing:
    """Tests fuer parse_alexa_request()."""

    def test_intent_request_extracts_intent(self, handler):
        req = _intent_request("TVAnIntent")
        rtype, intent = handler.parse_alexa_request(req)
        assert rtype == "IntentRequest"
        assert intent == "TVAnIntent"

    def test_launch_request(self, handler):
        req = _launch_request()
        rtype, intent = handler.parse_alexa_request(req)
        assert rtype == "LaunchRequest"
        assert intent == ""

    def test_session_ended_request(self, handler):
        req = _session_ended_request()
        rtype, intent = handler.parse_alexa_request(req)
        assert rtype == "SessionEndedRequest"
        assert intent == ""

    def test_missing_intent_returns_empty(self, handler):
        req = {
            "version": "1.0",
            "session": {},
            "request": {
                "type": "IntentRequest",
                "intent": {},
            },
        }
        rtype, intent = handler.parse_alexa_request(req)
        assert rtype == "IntentRequest"
        assert intent == ""


# -- Response Building ----------------------------------------------------- #

class TestAlexaResponseBuilding:
    """Tests fuer build_alexa_response()."""

    def test_response_format(self, handler):
        result = AlexaResult(text="Hallo", success=True, end_session=True)
        resp = handler.build_alexa_response(result)
        assert resp["version"] == "1.0"
        assert resp["response"]["outputSpeech"]["type"] == "PlainText"
        assert resp["response"]["outputSpeech"]["text"] == "Hallo"
        assert resp["response"]["shouldEndSession"] is True

    def test_session_kept_open(self, handler):
        result = AlexaResult(text="Was?", end_session=False)
        resp = handler.build_alexa_response(result)
        assert resp["response"]["shouldEndSession"] is False


# -- LaunchRequest --------------------------------------------------------- #

class TestLaunchRequest:

    def test_launch_returns_greeting(self, handler):
        resp = _run(handler.handle_request(_launch_request()))
        text = resp["response"]["outputSpeech"]["text"]
        assert "hört" in text.lower() or "saleria" in text.lower()
        assert resp["response"]["shouldEndSession"] is False


# -- Activity Intents ------------------------------------------------------ #

class TestActivityIntents:

    def test_tv_an_intent(self, handler, harmony):
        resp = _run(handler.handle_request(_intent_request("TVAnIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "eingeschaltet" in text.lower() or "fernsehen" in text.lower()
        harmony.start_activity.assert_called_once_with("Fernsehen")

    def test_musik_an_intent(self, handler, harmony):
        _run(handler.handle_request(_intent_request("MusikAnIntent")))
        harmony.start_activity.assert_called_once_with("Musik")

    def test_gaming_an_intent(self, handler, harmony):
        _run(handler.handle_request(_intent_request("GamingAnIntent")))
        harmony.start_activity.assert_called_once_with("Gaming")

    def test_activity_failure(self, handler, harmony):
        harmony.start_activity = AsyncMock(return_value=False)
        resp = _run(handler.handle_request(_intent_request("TVAnIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht" in text.lower() or "fehl" in text.lower()

    def test_activity_exception(self, handler, harmony):
        harmony.start_activity = AsyncMock(side_effect=RuntimeError("Hub offline"))
        resp = _run(handler.handle_request(_intent_request("TVAnIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fehler" in text.lower()


# -- AllesAusIntent -------------------------------------------------------- #

class TestAllesAusIntent:

    def test_alles_aus(self, handler, harmony):
        resp = _run(handler.handle_request(_intent_request("AllesAusIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "ausgeschaltet" in text.lower() or "aus" in text.lower()
        harmony.power_off.assert_called_once()

    def test_all_off_failure(self, handler, harmony):
        harmony.power_off = AsyncMock(return_value=False)
        resp = _run(handler.handle_request(_intent_request("AllesAusIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fehlgeschlagen" in text.lower()


# -- Volume Intents -------------------------------------------------------- #

class TestVolumeIntents:

    def test_lauter(self, handler, harmony):
        resp = _run(handler.handle_request(_intent_request("LauterIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "lauter" in text.lower()
        harmony.send_command.assert_called_once_with(
            device="Samsung TV", command="VolumeUp",
        )

    def test_leiser(self, handler, harmony):
        _run(handler.handle_request(_intent_request("LeiserIntent")))
        harmony.send_command.assert_called_once_with(
            device="Samsung TV", command="VolumeDown",
        )

    def test_stumm(self, handler, harmony):
        _run(handler.handle_request(_intent_request("StummIntent")))
        harmony.send_command.assert_called_once_with(
            device="Samsung TV", command="Mute",
        )

    def test_volume_failure(self, handler, harmony):
        harmony.send_command = AsyncMock(return_value=False)
        resp = _run(handler.handle_request(_intent_request("LauterIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fehlgeschlagen" in text.lower()


# -- StatusIntent ---------------------------------------------------------- #

class TestStatusIntent:

    def test_was_laeuft(self, handler, harmony):
        resp = _run(handler.handle_request(_intent_request("StatusIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fernsehen" in text.lower()

    def test_nothing_active(self, handler, harmony):
        harmony.get_current_activity = AsyncMock(return_value=None)
        resp = _run(handler.handle_request(_intent_request("StatusIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "aus" in text.lower() or "nichts" in text.lower()


# -- Amazon Built-in Intents ----------------------------------------------- #

class TestBuiltinIntents:

    def test_cancel_intent(self, handler):
        resp = _run(handler.handle_request(_intent_request("AMAZON.CancelIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "tschüss" in text.lower()
        assert resp["response"]["shouldEndSession"] is True

    def test_stop_intent(self, handler):
        resp = _run(handler.handle_request(_intent_request("AMAZON.StopIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "tschüss" in text.lower()

    def test_help_intent(self, handler):
        resp = _run(handler.handle_request(_intent_request("AMAZON.HelpIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fernsehen" in text.lower()
        assert resp["response"]["shouldEndSession"] is False

    def test_fallback_intent(self, handler):
        resp = _run(handler.handle_request(_intent_request("AMAZON.FallbackIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht verstanden" in text.lower()
        assert resp["response"]["shouldEndSession"] is False


# -- No Harmony ------------------------------------------------------------ #

class TestNoHarmony:

    def test_activity_without_harmony(self, handler_no_harmony):
        resp = _run(handler_no_harmony.handle_request(
            _intent_request("TVAnIntent"),
        ))
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht verfügbar" in text.lower()

    def test_off_without_harmony(self, handler_no_harmony):
        resp = _run(handler_no_harmony.handle_request(
            _intent_request("AllesAusIntent"),
        ))
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht verfügbar" in text.lower()

    def test_volume_without_harmony(self, handler_no_harmony):
        resp = _run(handler_no_harmony.handle_request(
            _intent_request("LauterIntent"),
        ))
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht verfügbar" in text.lower()


# -- Unknown Intent -------------------------------------------------------- #

class TestUnknownIntent:

    def test_unknown_intent(self, handler):
        resp = _run(handler.handle_request(
            _intent_request("PizzaBestellenIntent"),
        ))
        text = resp["response"]["outputSpeech"]["text"]
        assert "kenne ich" in text.lower() or "nicht" in text.lower()


# -- Session End ----------------------------------------------------------- #

class TestSessionEnd:

    def test_session_ended(self, handler):
        resp = _run(handler.handle_request(_session_ended_request()))
        assert resp["response"]["shouldEndSession"] is True

    def test_all_responses_end_session(self, handler):
        """Befehle beenden die Session (kein Follow-up noetig)."""
        resp = _run(handler.handle_request(_intent_request("TVAnIntent")))
        assert resp["response"]["shouldEndSession"] is True
