"""Tests fuer TurntableCommandHandler (Patterns, Keywords, Execute)."""
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.turntable_commands import (
    DEFAULT_ROTATION_DEGREES,
    LOOK_DIRECTION_PATTERN,
    ROTATE_BY_PATTERN,
    ROTATE_DIRECTION_PATTERN,
    ROTATE_TO_PATTERN,
    TurntableCommandHandler,
)
from elder_berry.robot.protocol import ApiResponse


def _make_handler(robot=None):
    if robot is None:
        robot = MagicMock()
    return TurntableCommandHandler(robot_client=robot)


class TestSimpleCommands:

    def test_simple_commands_registered(self):
        h = _make_handler()
        assert "drehteller home" in h.simple_commands
        assert "drehteller stopp" in h.simple_commands
        assert "drehteller status" in h.simple_commands


class TestPatterns:

    def test_rotate_by_90(self):
        m = ROTATE_BY_PATTERN.match("dreh dich um 90 grad")
        assert m is not None
        assert m.group(1) == "90"

    def test_rotate_by_45_links(self):
        m = ROTATE_BY_PATTERN.match("dreh dich um 45 grad nach links")
        assert m is not None
        assert m.group(1) == "45"
        assert m.group(2) == "links"

    def test_rotate_to_120(self):
        m = ROTATE_TO_PATTERN.match("dreh dich auf 120 grad")
        assert m is not None
        assert m.group(1) == "120"

    def test_rotate_to_negative(self):
        m = ROTATE_TO_PATTERN.match("dreh dich auf -90 grad")
        assert m is not None
        assert m.group(1) == "-90"

    def test_direction_links(self):
        m = ROTATE_DIRECTION_PATTERN.match("dreh dich nach links")
        assert m is not None
        assert m.group(1) == "links"

    def test_direction_rechts(self):
        m = ROTATE_DIRECTION_PATTERN.match("dreh dich nach rechts")
        assert m is not None
        assert m.group(1) == "rechts"

    def test_look_links(self):
        m = LOOK_DIRECTION_PATTERN.match("schau nach links")
        assert m is not None
        assert m.group(1) == "links"

    def test_look_rechts(self):
        m = LOOK_DIRECTION_PATTERN.match("schau nach rechts")
        assert m is not None
        assert m.group(1) == "rechts"


class TestKeywords:

    def test_keyword_dreh_dich(self):
        h = _make_handler()
        all_keywords = {}
        for cmd, kws in h.keywords.items():
            for kw in kws:
                all_keywords[kw] = cmd
        assert "dreh dich" in all_keywords

    def test_keyword_schau_nach_links(self):
        h = _make_handler()
        all_keywords = {}
        for cmd, kws in h.keywords.items():
            for kw in kws:
                all_keywords[kw] = cmd
        assert "schau nach links" in all_keywords

    def test_keyword_wo_schaust_du(self):
        h = _make_handler()
        all_keywords = {}
        for cmd, kws in h.keywords.items():
            for kw in kws:
                all_keywords[kw] = cmd
        assert "wo schaust du hin" in all_keywords


class TestExecution:

    def test_no_robot_client(self):
        h = TurntableCommandHandler(robot_client=None)
        result = h.execute("drehteller home", "drehteller home")
        assert result.success is False
        assert "nicht verfügbar" in result.text.lower() or "nicht verbunden" in result.text.lower()

    def test_home_execute(self):
        robot = MagicMock()
        robot.home_turntable.return_value = ApiResponse(success=True, message="Homing gestartet")
        h = _make_handler(robot)
        result = h.execute("drehteller home", "drehteller home")
        assert result.success is True
        robot.home_turntable.assert_called_once()

    def test_status_execute(self):
        robot = MagicMock()
        robot.turntable_status.return_value = {
            "available": True,
            "is_homed": True,
            "is_moving": False,
            "position_degrees": 45.0,
        }
        h = _make_handler(robot)
        result = h.execute("drehteller status", "drehteller status")
        assert result.success is True
        assert "45.0" in result.text

    def test_rotate_dir_links(self):
        robot = MagicMock()
        robot.rotate_turntable.return_value = ApiResponse(
            success=True, message="Rotation um -90 Grad gestartet",
        )
        h = _make_handler(robot)
        result = h.execute("turntable_rotate_dir", "dreh dich nach links")
        assert result.success is True
        robot.rotate_turntable.assert_called_once_with(
            relative_degrees=-DEFAULT_ROTATION_DEGREES,
        )

    def test_rotate_dir_rechts(self):
        robot = MagicMock()
        robot.rotate_turntable.return_value = ApiResponse(
            success=True, message="Rotation um 90 Grad gestartet",
        )
        h = _make_handler(robot)
        result = h.execute("turntable_rotate_dir", "dreh dich nach rechts")
        assert result.success is True
        robot.rotate_turntable.assert_called_once_with(
            relative_degrees=DEFAULT_ROTATION_DEGREES,
        )

    def test_stop_execute(self):
        robot = MagicMock()
        robot.stop_turntable.return_value = ApiResponse(
            success=True, message="Rotation gestoppt",
        )
        h = _make_handler(robot)
        result = h.execute("drehteller stopp", "drehteller stopp")
        assert result.success is True


class TestCollisionCheck:

    def test_no_collision_schau_mal(self):
        """'schau mal was' darf NICHT vom Turntable-Pattern gematcht werden."""
        assert LOOK_DIRECTION_PATTERN.match("schau mal was") is None
        assert ROTATE_DIRECTION_PATTERN.match("schau mal was") is None

    def test_no_collision_schau_mal_ob(self):
        """'schau mal ob' darf NICHT vom Turntable-Pattern gematcht werden."""
        assert LOOK_DIRECTION_PATTERN.match("schau mal ob") is None
        assert ROTATE_DIRECTION_PATTERN.match("schau mal ob") is None


class TestCommandDescriptions:

    def test_descriptions_not_empty(self):
        h = _make_handler()
        assert len(h.command_descriptions) > 0
