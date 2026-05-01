"""Tests für ComputerUseController – Vision-gesteuerte PC-Bedienung."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.llm.anthropic_client import ComputerUseAction
from elder_berry.actions.computer_use import (
    ComputerUseController,
    ComputerUseResult,
    MAX_SCREENSHOT_WIDTH,
    VERIFICATION_DELAY,
)

_mss_installed = importlib.util.find_spec("mss") is not None
requires_mss = pytest.mark.skipif(not _mss_installed, reason="mss nicht installiert")

_pil_installed = importlib.util.find_spec("PIL") is not None
requires_pil = pytest.mark.skipif(not _pil_installed, reason="Pillow nicht installiert")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_controller() -> MagicMock:
    """Erstellt einen Mock-ActionController."""
    from elder_berry.actions.base import ActionController

    mock = MagicMock(spec=ActionController)
    return mock


def _make_anthropic_client(action: ComputerUseAction | None = None) -> MagicMock:
    """Erstellt einen Mock-AnthropicClient."""
    from elder_berry.llm.anthropic_client import AnthropicClient

    mock = MagicMock(spec=AnthropicClient)
    mock.is_available.return_value = True
    if action:
        mock.computer_use.return_value = action
    return mock


def _make_monitor_data():
    """Erstellt Mock-Monitor-Daten für mss."""
    return [
        {"left": 0, "top": 0, "width": 3840, "height": 2160},  # 0: virtual
        {"left": 0, "top": 0, "width": 1920, "height": 1080},  # 1: primary
        {"left": 1920, "top": 0, "width": 2560, "height": 1440},  # 2: secondary
    ]


# ---------------------------------------------------------------------------
# ComputerUseResult DTO
# ---------------------------------------------------------------------------


class TestComputerUseResult:
    def test_success_result(self):
        action = ComputerUseAction(action="left_click", coordinate=(100, 200))
        result = ComputerUseResult(action=action, success=True, message="OK")
        assert result.success is True
        assert result.verification_image_path is None
        assert result.error is None

    def test_error_result(self):
        action = ComputerUseAction(action="none")
        result = ComputerUseResult(
            action=action, success=False, message="Fehler", error="api_error"
        )
        assert result.success is False
        assert result.error == "api_error"

    def test_with_verification_path(self, tmp_path):
        img = tmp_path / "verify.png"
        img.touch()
        action = ComputerUseAction(action="left_click", coordinate=(50, 50))
        result = ComputerUseResult(
            action=action,
            success=True,
            message="OK",
            verification_image_path=img,
        )
        assert result.verification_image_path == img


# ---------------------------------------------------------------------------
# ComputerUseController – Init + Monitor
# ---------------------------------------------------------------------------


class TestControllerInit:
    def test_default_monitor_index(self):
        ctrl = ComputerUseController(_make_anthropic_client(), _make_controller())
        assert ctrl.monitor_index == 1

    def test_custom_monitor_index(self):
        ctrl = ComputerUseController(
            _make_anthropic_client(), _make_controller(), monitor_index=2
        )
        assert ctrl.monitor_index == 2

    def test_monitor_index_setter(self):
        ctrl = ComputerUseController(_make_anthropic_client(), _make_controller())
        ctrl.monitor_index = 3
        assert ctrl.monitor_index == 3

    @requires_mss
    def test_get_available_monitors(self):
        ctrl = ComputerUseController(_make_anthropic_client(), _make_controller())
        monitors = ctrl.get_available_monitors()
        assert isinstance(monitors, list)
        # Mindestens 1 Monitor
        assert len(monitors) >= 1
        assert "width" in monitors[0]
        assert "height" in monitors[0]
        assert monitors[0]["index"] >= 1


# ---------------------------------------------------------------------------
# ComputerUseController – execute_instruction
# ---------------------------------------------------------------------------


class TestExecuteInstruction:
    def test_mss_missing(self):
        ctrl = ComputerUseController(_make_anthropic_client(), _make_controller())
        with patch("elder_berry.actions.computer_use._MSS_AVAILABLE", False):
            result = ctrl.execute_instruction("klick auf OK")
        assert result.success is False
        assert result.error == "mss_missing"

    @requires_mss
    def test_screenshot_failed(self):
        ctrl = ComputerUseController(_make_anthropic_client(), _make_controller())
        with patch.object(
            ctrl, "_capture_screenshot", side_effect=RuntimeError("fail")
        ):
            result = ctrl.execute_instruction("klick auf OK")
        assert result.success is False
        assert result.error == "screenshot_failed"

    @requires_mss
    def test_api_error(self):
        anthropic = _make_anthropic_client()
        anthropic.computer_use.side_effect = RuntimeError("API down")
        ctrl = ComputerUseController(anthropic, _make_controller())

        with patch.object(ctrl, "_capture_screenshot", return_value=("b64", 1280, 720)):
            result = ctrl.execute_instruction("klick auf OK")
        assert result.success is False
        assert result.error == "api_error"

    @requires_mss
    def test_successful_click(self):
        click_action = ComputerUseAction(
            action="left_click", coordinate=(640, 360), tool_use_id="t1"
        )
        anthropic = _make_anthropic_client(click_action)
        controller = _make_controller()
        ctrl = ComputerUseController(anthropic, controller)

        with (
            patch.object(ctrl, "_capture_screenshot", return_value=("b64", 1280, 720)),
            patch.object(
                ctrl, "_get_monitor_geometry", return_value=(1920, 1080, 0, 0)
            ),
            patch.object(ctrl, "_take_verification_screenshot", return_value=None),
            patch("elder_berry.actions.computer_use.time") as mock_time,
        ):
            result = ctrl.execute_instruction("klick auf den Button")

        assert result.success is True
        assert result.action.action == "left_click"
        # Koordinaten: 640 * (1920/1280) = 960, 360 * (1080/720) = 540
        controller.click.assert_called_once_with(960, 540, button="left")
        mock_time.sleep.assert_called_once_with(VERIFICATION_DELAY)


# ---------------------------------------------------------------------------
# _execute_action – Einzelne Aktionen
# ---------------------------------------------------------------------------


class TestExecuteAction:
    def _make_ctrl(self):
        return ComputerUseController(
            _make_anthropic_client(), _make_controller(), monitor_index=1
        )

    def _run(self, ctrl, action, display_w=1280, display_h=720):
        with patch.object(
            ctrl, "_get_monitor_geometry", return_value=(1920, 1080, 0, 0)
        ):
            ctrl._execute_action(action, display_w, display_h)

    def test_left_click(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="left_click", coordinate=(100, 200))
        self._run(ctrl, action)
        # 100*(1920/1280)=150, 200*(1080/720)=300
        ctrl._controller.click.assert_called_once_with(150, 300, button="left")

    def test_right_click(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="right_click", coordinate=(100, 200))
        self._run(ctrl, action)
        ctrl._controller.click.assert_called_once_with(150, 300, button="right")

    def test_middle_click(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="middle_click", coordinate=(100, 200))
        self._run(ctrl, action)
        ctrl._controller.click.assert_called_once_with(150, 300, button="middle")

    def test_double_click(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="double_click", coordinate=(100, 200))
        self._run(ctrl, action)
        assert ctrl._controller.click.call_count == 2

    def test_type_text(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="type", text="Hallo Welt")
        self._run(ctrl, action)
        ctrl._controller.type_text.assert_called_once_with("Hallo Welt")

    def test_type_no_text_raises(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="type", text=None)
        with pytest.raises(ValueError, match="benötigt Text"):
            self._run(ctrl, action)

    def test_key_single(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="key", text="enter")
        self._run(ctrl, action)
        ctrl._controller.press_key.assert_called_once_with("enter")

    def test_key_combo(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="key", text="ctrl+s")
        self._run(ctrl, action)
        ctrl._controller.hotkey.assert_called_once_with("ctrl", "s")

    def test_key_no_text_raises(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="key", text=None)
        with pytest.raises(ValueError, match="benötigt einen Tasten-String"):
            self._run(ctrl, action)

    def test_scroll_down(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(
            action="scroll",
            coordinate=(640, 360),
            scroll_direction="down",
            scroll_amount=3,
        )
        mock_pag = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pag}):
            self._run(ctrl, action)
        ctrl._controller.move_mouse.assert_called_once()
        mock_pag.scroll.assert_called_once_with(-3)  # down = negativ

    def test_scroll_up(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(
            action="scroll",
            coordinate=(640, 360),
            scroll_direction="up",
            scroll_amount=5,
        )
        mock_pag = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pag}):
            self._run(ctrl, action)
        mock_pag.scroll.assert_called_once_with(5)  # up = positiv

    def test_mouse_move(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="mouse_move", coordinate=(640, 360))
        self._run(ctrl, action)
        ctrl._controller.move_mouse.assert_called_once_with(960, 540)

    def test_screenshot_action_noop(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="screenshot")
        self._run(ctrl, action)
        # Keine Controller-Methode aufgerufen
        ctrl._controller.click.assert_not_called()
        ctrl._controller.type_text.assert_not_called()

    def test_click_no_coordinate_raises(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="left_click", coordinate=None)
        with pytest.raises(ValueError, match="benötigt Koordinaten"):
            self._run(ctrl, action)

    def test_multi_monitor_offset(self):
        ctrl = self._make_ctrl()
        action = ComputerUseAction(action="left_click", coordinate=(640, 360))
        # Monitor 2: offset 1920, 0
        with patch.object(
            ctrl, "_get_monitor_geometry", return_value=(2560, 1440, 1920, 0)
        ):
            ctrl._execute_action(action, 1280, 720)
        # 640*(2560/1280)+1920 = 1280+1920=3200, 360*(1440/720)+0=720
        ctrl._controller.click.assert_called_once_with(3200, 720, button="left")


# ---------------------------------------------------------------------------
# _describe_action
# ---------------------------------------------------------------------------


class TestDescribeAction:
    def test_click(self):
        action = ComputerUseAction(action="left_click", coordinate=(100, 200))
        desc = ComputerUseController._describe_action(action)
        assert "left_click" in desc
        assert "100" in desc

    def test_type(self):
        action = ComputerUseAction(action="type", text="Hello")
        desc = ComputerUseController._describe_action(action)
        assert "Hello" in desc

    def test_type_long_text_truncated(self):
        action = ComputerUseAction(action="type", text="A" * 50)
        desc = ComputerUseController._describe_action(action)
        assert "..." in desc

    def test_key(self):
        action = ComputerUseAction(action="key", text="ctrl+c")
        desc = ComputerUseController._describe_action(action)
        assert "ctrl+c" in desc

    def test_scroll(self):
        action = ComputerUseAction(
            action="scroll", scroll_direction="down", scroll_amount=3
        )
        desc = ComputerUseController._describe_action(action)
        assert "down" in desc

    def test_unknown(self):
        action = ComputerUseAction(action="wait")
        desc = ComputerUseController._describe_action(action)
        assert desc == "wait"


# ---------------------------------------------------------------------------
# _capture_screenshot (mit Resize)
# ---------------------------------------------------------------------------


class TestCaptureScreenshot:
    @requires_mss
    @requires_pil
    def test_screenshot_resized_if_too_wide(self):
        ctrl = ComputerUseController(_make_anthropic_client(), _make_controller())
        # Mock mss um konsistente Daten zu liefern
        mock_screenshot = MagicMock()
        mock_screenshot.width = 1920
        mock_screenshot.height = 1080
        mock_screenshot.rgb = b"\x00" * (1920 * 1080 * 3)
        mock_screenshot.size = (1920, 1080)

        mock_sct = MagicMock()
        mock_sct.monitors = [
            {"left": 0, "top": 0, "width": 3840, "height": 2160},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]
        mock_sct.grab.return_value = mock_screenshot
        mock_sct.__enter__ = MagicMock(return_value=mock_sct)
        mock_sct.__exit__ = MagicMock(return_value=False)

        with patch("elder_berry.actions.computer_use.mss.mss", return_value=mock_sct):
            b64, w, h = ctrl._capture_screenshot()

        assert w == MAX_SCREENSHOT_WIDTH
        assert h == int(1080 * (MAX_SCREENSHOT_WIDTH / 1920))
        assert isinstance(b64, str)
