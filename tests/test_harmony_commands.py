"""Tests fuer HarmonyCommandHandler -- Pattern-Matching + Execution."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.harmony_commands import (
    ACTIVITY_ON_PATTERN,
    ALL_OFF_PATTERN,
    CURRENT_PATTERN,
    LIST_ACTIVITIES_PATTERN,
    LIST_COMMANDS_PATTERN,
    LIST_DEVICES_PATTERN,
    MUTE_PATTERN,
    SCENE_LIST_PATTERN,
    SCENE_START_PATTERN,
    VOLUME_DOWN_PATTERN,
    VOLUME_UP_PATTERN,
    HarmonyCommandHandler,
)


# -- Fixtures -------------------------------------------------------------- #


@pytest.fixture
def mock_robot():
    robot = MagicMock()
    robot.harmony_start_activity = MagicMock(return_value=True)
    robot.harmony_power_off = MagicMock(return_value=True)
    robot.harmony_send_command = MagicMock(return_value=True)
    robot.harmony_status = MagicMock(
        return_value={
            "connected": True,
            "current_activity": "Fernsehen",
        }
    )
    robot.harmony_config = MagicMock(
        return_value={
            "activities": ["Fernsehen", "Musik"],
            "devices": ["Samsung TV", "Samsung TV"],
        }
    )
    robot.harmony_start_scene = MagicMock(
        return_value={
            "success": True,
            "steps_ok": 3,
            "steps_total": 3,
        }
    )
    robot.harmony_scenes = MagicMock(
        return_value=[
            {"name": "Gaming", "steps": []},
            {"name": "Musik", "steps": []},
        ]
    )
    return robot


@pytest.fixture
def handler(mock_robot) -> HarmonyCommandHandler:
    return HarmonyCommandHandler(robot_client=mock_robot)


@pytest.fixture
def handler_no_robot() -> HarmonyCommandHandler:
    return HarmonyCommandHandler(robot_client=None)


# -- Pattern-Tests --------------------------------------------------------- #


class TestPatterns:
    def test_activity_on_fernsehen(self):
        assert ACTIVITY_ON_PATTERN.match("fernsehen an")

    def test_activity_on_tv(self):
        assert ACTIVITY_ON_PATTERN.match("tv an")

    def test_activity_on_musik(self):
        assert ACTIVITY_ON_PATTERN.match("musik an")

    def test_activity_on_gaming(self):
        assert ACTIVITY_ON_PATTERN.match("gaming an")

    def test_activity_on_with_starte(self):
        assert ACTIVITY_ON_PATTERN.match("starte fernsehen an")

    def test_activity_on_case_insensitive(self):
        assert ACTIVITY_ON_PATTERN.match("Fernsehen An")

    def test_all_off_alles_aus(self):
        assert ALL_OFF_PATTERN.match("alles aus")

    def test_all_off_harmony_aus(self):
        assert ALL_OFF_PATTERN.match("harmony aus")

    def test_all_off_schalte_alles_aus(self):
        assert ALL_OFF_PATTERN.match("schalte alles aus")

    def test_volume_up_bare(self):
        assert VOLUME_UP_PATTERN.match("lauter")

    def test_volume_up_with_mach(self):
        assert VOLUME_UP_PATTERN.match("mach lauter")

    def test_volume_down_bare(self):
        assert VOLUME_DOWN_PATTERN.match("leiser")

    def test_volume_down_with_mach(self):
        assert VOLUME_DOWN_PATTERN.match("mach leiser")

    def test_mute_stumm(self):
        assert MUTE_PATTERN.match("stumm")

    def test_mute_stummschalten(self):
        assert MUTE_PATTERN.match("stummschalten")

    def test_current_was_laeuft(self):
        assert CURRENT_PATTERN.match("was läuft")

    def test_current_was_ist_an(self):
        assert CURRENT_PATTERN.match("was ist an")

    def test_current_harmony_status(self):
        assert CURRENT_PATTERN.match("harmony status")

    def test_list_activities(self):
        assert LIST_ACTIVITIES_PATTERN.match("harmony aktivitäten")

    def test_list_devices(self):
        assert LIST_DEVICES_PATTERN.match("harmony geräte")

    def test_list_commands_with_device(self):
        m = LIST_COMMANDS_PATTERN.match("harmony befehle Samsung TV")
        assert m
        assert m.group("device") == "Samsung TV"

    def test_no_false_positive_on_random_text(self):
        """Zufaelliger Text soll kein Pattern matchen."""
        assert not ACTIVITY_ON_PATTERN.match("erzähl mir was")
        assert not ALL_OFF_PATTERN.match("mach das licht aus")
        assert not VOLUME_UP_PATTERN.match("mach das lauter bitte")


# -- Handler-Execution-Tests ----------------------------------------------- #


class TestExecution:
    def test_start_activity_success(self, handler, mock_robot):
        result = handler.execute("harmony_activity_on", "fernsehen an")
        assert result.success
        mock_robot.harmony_start_activity.assert_called_once_with("Fernsehen")

    def test_start_activity_musik(self, handler, mock_robot):
        result = handler.execute("harmony_activity_on", "musik an")
        assert result.success
        mock_robot.harmony_start_activity.assert_called_once_with("Musik")

    def test_start_activity_not_found(self, handler, mock_robot):
        mock_robot.harmony_start_activity.return_value = False
        result = handler.execute("harmony_activity_on", "gaming an")
        assert not result.success

    def test_power_off(self, handler, mock_robot):
        result = handler.execute("harmony_all_off", "alles aus")
        assert result.success
        mock_robot.harmony_power_off.assert_called_once()

    def test_volume_up(self, handler, mock_robot):
        result = handler.execute("harmony_volume_up", "lauter")
        assert result.success
        mock_robot.harmony_send_command.assert_called_once_with(
            "Samsung TV",
            "VolumeUp",
        )

    def test_volume_down(self, handler, mock_robot):
        result = handler.execute("harmony_volume_down", "leiser")
        assert result.success
        mock_robot.harmony_send_command.assert_called_once_with(
            "Samsung TV",
            "VolumeDown",
        )

    def test_mute(self, handler, mock_robot):
        result = handler.execute("harmony_mute", "stumm")
        assert result.success
        mock_robot.harmony_send_command.assert_called_once_with(
            "Samsung TV",
            "Mute",
        )

    def test_current_activity_active(self, handler, mock_robot):
        result = handler.execute("harmony_current", "was läuft")
        assert result.success
        assert "Fernsehen" in result.text

    def test_current_activity_poweroff(self, handler, mock_robot):
        mock_robot.harmony_status.return_value = {
            "connected": True,
            "current_activity": None,
        }
        result = handler.execute("harmony_current", "was ist an")
        assert result.success
        assert "aus" in result.text.lower() or "keine" in result.text.lower()

    def test_list_activities(self, handler, mock_robot):
        result = handler.execute("harmony_list_activities", "harmony aktivitäten")
        assert result.success
        assert "Fernsehen" in result.text
        assert "Musik" in result.text

    def test_list_devices(self, handler, mock_robot):
        result = handler.execute("harmony_list_devices", "harmony geräte")
        assert result.success
        assert "Samsung TV" in result.text

    def test_list_commands_with_device(self, handler, mock_robot):
        result = handler.execute(
            "harmony_list_commands",
            "harmony befehle Samsung TV",
        )
        assert result.success

    def test_no_match_returns_failure(self, handler):
        result = handler.execute("harmony_unknown", "irgendwas")
        assert not result.success

    def test_no_robot_client(self, handler_no_robot):
        result = handler_no_robot.execute("harmony_all_off", "alles aus")
        assert not result.success
        assert "RobotClient" in result.text

    def test_robot_client_error_graceful(self, handler, mock_robot):
        mock_robot.harmony_power_off.side_effect = Exception("Connection lost")
        result = handler.execute("harmony_all_off", "alles aus")
        assert not result.success

    def test_current_hub_not_connected(self, handler, mock_robot):
        mock_robot.harmony_status.return_value = {
            "connected": False,
            "current_activity": None,
        }
        result = handler.execute("harmony_current", "harmony status")
        assert not result.success
        assert "nicht verbunden" in result.text.lower()


# -- Kollisions-Tests ------------------------------------------------------ #


class TestCollisions:
    def test_volume_no_collision_with_system_commands(self):
        """Lautstärke-Patterns kollidieren nicht mit system_commands
        (dort gibt es aktuell keine volume-patterns)."""
        # Dieser Test dokumentiert die Annahme aus dem Prompt
        assert VOLUME_UP_PATTERN.match("lauter")
        assert VOLUME_DOWN_PATTERN.match("leiser")
        # Kein Overlap mit "volume 50" (system_commands)
        assert not VOLUME_UP_PATTERN.match("volume 50")

    def test_activity_no_collision_with_reminder_patterns(self):
        """Aktivitäts-Patterns kollidieren nicht mit Erinnerungen."""
        # "erinnere mich" darf nicht als Aktivitaet erkannt werden
        assert not ACTIVITY_ON_PATTERN.match("erinnere mich an etwas")
        assert not ACTIVITY_ON_PATTERN.match("erinnere mich um 18:00")


# -- Szenen-Pattern-Tests -------------------------------------------------- #


class TestScenePatterns:
    def test_scene_start_basic(self):
        m = SCENE_START_PATTERN.match("szene Gaming")
        assert m
        assert m.group("scene") == "Gaming"

    def test_scene_start_with_starte(self):
        m = SCENE_START_PATTERN.match("starte szene Gaming")
        assert m
        assert m.group("scene") == "Gaming"

    def test_scene_start_case_insensitive(self):
        assert SCENE_START_PATTERN.match("Szene gaming")

    def test_scene_start_multi_word(self):
        m = SCENE_START_PATTERN.match("szene Musik hören")
        assert m
        assert m.group("scene") == "Musik hören"

    def test_scene_list_bare(self):
        assert SCENE_LIST_PATTERN.match("szenen")

    def test_scene_list_with_liste(self):
        assert SCENE_LIST_PATTERN.match("szenen liste")

    def test_scene_list_case_insensitive(self):
        assert SCENE_LIST_PATTERN.match("Szenen Liste")

    def test_scene_no_collision_with_activity(self):
        assert not ACTIVITY_ON_PATTERN.match("szene Gaming")
        assert not SCENE_START_PATTERN.match("fernsehen an")


# -- Szenen-Command-Tests ------------------------------------------------- #


class TestSceneCommands:
    def test_scene_start_success(self, handler, mock_robot):
        result = handler.execute("harmony_scene_start", "szene Gaming")
        assert result.success
        assert "Gaming" in result.text
        assert "3/3" in result.text
        mock_robot.harmony_start_scene.assert_called_once_with("Gaming")

    def test_scene_start_with_starte(self, handler, mock_robot):
        result = handler.execute("harmony_scene_start", "starte szene Gaming")
        assert result.success
        mock_robot.harmony_start_scene.assert_called_once_with("Gaming")

    def test_scene_start_failure(self, handler, mock_robot):
        mock_robot.harmony_start_scene.return_value = {
            "success": False,
            "error": "Szene 'Nope' nicht gefunden",
        }
        result = handler.execute("harmony_scene_start", "szene Nope")
        assert not result.success
        assert "nicht gefunden" in result.text

    def test_scene_start_no_match(self, handler):
        result = handler.execute("harmony_scene_start", "random text")
        assert not result.success

    def test_scene_list(self, handler, mock_robot):
        result = handler.execute("harmony_scene_list", "szenen")
        assert result.success
        assert "Gaming" in result.text
        assert "Musik" in result.text

    def test_scene_list_empty(self, handler, mock_robot):
        mock_robot.harmony_scenes.return_value = []
        result = handler.execute("harmony_scene_list", "szenen")
        assert result.success
        assert "Keine Szenen" in result.text

    def test_scene_commands_no_robot(self, handler_no_robot):
        result = handler_no_robot.execute(
            "harmony_scene_start",
            "szene Gaming",
        )
        assert not result.success
        assert "RobotClient" in result.text
