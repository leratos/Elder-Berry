"""Tests fuer AlexaSkillHandler -- Alexa Custom Skill auf RPi5."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from elder_berry.robot.alexa_skill_handler import (
    AlexaResult,
    AlexaSkillHandler,
)


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


def _intent_request(command_text: str) -> dict:
    """Baut ein minimales Alexa IntentRequest."""
    return {
        "version": "1.0",
        "session": {},
        "request": {
            "type": "IntentRequest",
            "intent": {
                "name": "SaleriaCommand",
                "slots": {
                    "CommandText": {"value": command_text},
                },
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

    def test_intent_request_extracts_text(self, handler):
        req = _intent_request("fernsehen an")
        rtype, text = handler.parse_alexa_request(req)
        assert rtype == "IntentRequest"
        assert text == "fernsehen an"

    def test_launch_request(self, handler):
        req = _launch_request()
        rtype, text = handler.parse_alexa_request(req)
        assert rtype == "LaunchRequest"
        assert text == ""

    def test_session_ended_request(self, handler):
        req = _session_ended_request()
        rtype, text = handler.parse_alexa_request(req)
        assert rtype == "SessionEndedRequest"
        assert text == ""

    def test_missing_slot_returns_empty(self, handler):
        req = {
            "version": "1.0",
            "session": {},
            "request": {
                "type": "IntentRequest",
                "intent": {"name": "SaleriaCommand", "slots": {}},
            },
        }
        rtype, text = handler.parse_alexa_request(req)
        assert rtype == "IntentRequest"
        assert text == ""

    def test_empty_slot_value(self, handler):
        req = {
            "version": "1.0",
            "session": {},
            "request": {
                "type": "IntentRequest",
                "intent": {
                    "name": "SaleriaCommand",
                    "slots": {"CommandText": {"value": "  "}},
                },
            },
        }
        rtype, text = handler.parse_alexa_request(req)
        assert text == ""


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

    async def test_launch_returns_greeting(self, handler):
        resp = await handler.handle_request(_launch_request())
        text = resp["response"]["outputSpeech"]["text"]
        assert "hört" in text.lower() or "saleria" in text.lower()
        assert resp["response"]["shouldEndSession"] is False


# -- Activity Commands ----------------------------------------------------- #

class TestActivityCommands:

    async def test_fernsehen_an(self, handler, harmony):
        resp = await handler.handle_request(_intent_request("fernsehen an"))
        text = resp["response"]["outputSpeech"]["text"]
        assert "eingeschaltet" in text.lower() or "fernsehen" in text.lower()
        harmony.start_activity.assert_called_once_with("Fernsehen")

    async def test_tv_an(self, handler, harmony):
        resp = await handler.handle_request(_intent_request("tv an"))
        harmony.start_activity.assert_called_once_with("Fernsehen")

    async def test_musik_an(self, handler, harmony):
        resp = await handler.handle_request(_intent_request("musik an"))
        harmony.start_activity.assert_called_once_with("Musik")

    async def test_gaming_an(self, handler, harmony):
        resp = await handler.handle_request(_intent_request("gaming an"))
        harmony.start_activity.assert_called_once_with("Gaming")

    async def test_fernseher_an(self, handler, harmony):
        resp = await handler.handle_request(_intent_request("fernseher an"))
        harmony.start_activity.assert_called_once_with("Fernsehen")

    async def test_activity_failure(self, handler, harmony):
        harmony.start_activity = AsyncMock(return_value=False)
        resp = await handler.handle_request(_intent_request("fernsehen an"))
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht" in text.lower() or "fehl" in text.lower()

    async def test_activity_exception(self, handler, harmony):
        harmony.start_activity = AsyncMock(side_effect=RuntimeError("Hub offline"))
        resp = await handler.handle_request(_intent_request("fernsehen an"))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fehler" in text.lower()


# -- All Off --------------------------------------------------------------- #

class TestAllOff:

    async def test_alles_aus(self, handler, harmony):
        resp = await handler.handle_request(_intent_request("alles aus"))
        text = resp["response"]["outputSpeech"]["text"]
        assert "ausgeschaltet" in text.lower() or "aus" in text.lower()
        harmony.power_off.assert_called_once()

    async def test_harmony_aus(self, handler, harmony):
        await handler.handle_request(_intent_request("harmony aus"))
        harmony.power_off.assert_called_once()

    async def test_aus(self, handler, harmony):
        await handler.handle_request(_intent_request("aus"))
        harmony.power_off.assert_called_once()

    async def test_all_off_failure(self, handler, harmony):
        harmony.power_off = AsyncMock(return_value=False)
        resp = await handler.handle_request(_intent_request("alles aus"))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fehlgeschlagen" in text.lower()


# -- Volume ---------------------------------------------------------------- #

class TestVolume:

    async def test_lauter(self, handler, harmony):
        resp = await handler.handle_request(_intent_request("lauter"))
        text = resp["response"]["outputSpeech"]["text"]
        assert "lauter" in text.lower()
        harmony.send_command.assert_called_once_with(
            device="Samsung TV", command="VolumeUp",
        )

    async def test_mach_lauter(self, handler, harmony):
        await handler.handle_request(_intent_request("mach lauter"))
        harmony.send_command.assert_called_once_with(
            device="Samsung TV", command="VolumeUp",
        )

    async def test_leiser(self, handler, harmony):
        await handler.handle_request(_intent_request("leiser"))
        harmony.send_command.assert_called_once_with(
            device="Samsung TV", command="VolumeDown",
        )

    async def test_stumm(self, handler, harmony):
        await handler.handle_request(_intent_request("stumm"))
        harmony.send_command.assert_called_once_with(
            device="Samsung TV", command="Mute",
        )

    async def test_volume_failure(self, handler, harmony):
        harmony.send_command = AsyncMock(return_value=False)
        resp = await handler.handle_request(_intent_request("lauter"))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fehlgeschlagen" in text.lower()


# -- Status ---------------------------------------------------------------- #

class TestStatus:

    async def test_was_laeuft(self, handler, harmony):
        resp = await handler.handle_request(_intent_request("was läuft"))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fernsehen" in text.lower()

    async def test_was_ist_an(self, handler, harmony):
        resp = await handler.handle_request(_intent_request("was ist an"))
        harmony.get_current_activity.assert_called_once()

    async def test_nothing_active(self, handler, harmony):
        harmony.get_current_activity = AsyncMock(return_value=None)
        resp = await handler.handle_request(_intent_request("was läuft"))
        text = resp["response"]["outputSpeech"]["text"]
        assert "aus" in text.lower() or "nichts" in text.lower()


# -- Scenes ---------------------------------------------------------------- #

class TestScenes:

    async def test_scene_start(self, handler, harmony_scenes):
        resp = await handler.handle_request(_intent_request("starte szene Gaming"))
        text = resp["response"]["outputSpeech"]["text"]
        assert "gaming" in text.lower()
        harmony_scenes.start_scene.assert_called_once_with("Gaming")

    async def test_scene_failure(self, handler, harmony_scenes):
        harmony_scenes.start_scene = AsyncMock(
            side_effect=RuntimeError("not found"),
        )
        resp = await handler.handle_request(_intent_request("szene Test"))
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht" in text.lower()


# -- No Harmony ------------------------------------------------------------ #

class TestNoHarmony:

    async def test_activity_without_harmony(self, handler_no_harmony):
        resp = await handler_no_harmony.handle_request(
            _intent_request("fernsehen an"),
        )
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht verfügbar" in text.lower()

    async def test_off_without_harmony(self, handler_no_harmony):
        resp = await handler_no_harmony.handle_request(
            _intent_request("alles aus"),
        )
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht verfügbar" in text.lower()

    async def test_volume_without_harmony(self, handler_no_harmony):
        resp = await handler_no_harmony.handle_request(
            _intent_request("lauter"),
        )
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht verfügbar" in text.lower()


# -- Unknown Command ------------------------------------------------------- #

class TestUnknownCommand:

    async def test_unknown_command(self, handler):
        resp = await handler.handle_request(
            _intent_request("bestell mir eine Pizza"),
        )
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht erkannt" in text.lower()

    async def test_empty_command(self, handler):
        resp = await handler.handle_request(_intent_request(""))
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht verstanden" in text.lower() or "beispiel" in text.lower()


# -- Session End ----------------------------------------------------------- #

class TestSessionEnd:

    async def test_session_ended(self, handler):
        resp = await handler.handle_request(_session_ended_request())
        assert resp["response"]["shouldEndSession"] is True

    async def test_all_responses_end_session(self, handler):
        """Befehle beenden die Session (kein Follow-up noetig)."""
        resp = await handler.handle_request(_intent_request("fernsehen an"))
        assert resp["response"]["shouldEndSession"] is True
