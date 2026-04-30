"""Tests für WindowsActionController – alle Aktionen gemockt."""

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from elder_berry.actions.base import ActionController, WindowInfo


# ---------------------------------------------------------------------------
# ABC-Vertrag: ActionController kann nicht direkt instanziiert werden
# ---------------------------------------------------------------------------


class TestActionControllerABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            ActionController()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Windows-Plattformprüfung
# ---------------------------------------------------------------------------


class TestPlatformCheck:
    @patch("elder_berry.actions.windows_controller.platform")
    def test_raises_on_non_windows(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        from elder_berry.actions.windows_controller import WindowsActionController

        with pytest.raises(RuntimeError, match="Windows"):
            WindowsActionController()

    @patch("elder_berry.actions.windows_controller.platform")
    @patch("elder_berry.actions.windows_controller.pyautogui")
    @patch("elder_berry.actions.windows_controller.gw")
    def test_ok_on_windows(self, _gw, _pyauto, mock_platform):
        mock_platform.system.return_value = "Windows"
        from elder_berry.actions.windows_controller import WindowsActionController

        ctrl = WindowsActionController()
        assert isinstance(ctrl, ActionController)


# ---------------------------------------------------------------------------
# Hilfsfunktion: Controller mit gemockter Plattform erzeugen
# ---------------------------------------------------------------------------


@pytest.fixture
def controller():
    """Erzeugt einen WindowsActionController mit gemockter Plattformprüfung."""
    with patch("elder_berry.actions.windows_controller.platform") as mock_p:
        mock_p.system.return_value = "Windows"
        from elder_berry.actions.windows_controller import WindowsActionController

        ctrl = WindowsActionController()
    return ctrl


# ---------------------------------------------------------------------------
# Tastatur
# ---------------------------------------------------------------------------


class TestKeyboard:
    @patch("elder_berry.actions.windows_controller.pyautogui")
    def test_press_key(self, mock_pyauto, controller):
        controller.press_key("enter")
        mock_pyauto.press.assert_called_once_with("enter")

    @patch("elder_berry.actions.windows_controller.pyautogui")
    def test_type_text(self, mock_pyauto, controller):
        controller.type_text("hello", interval=0.05)
        mock_pyauto.typewrite.assert_called_once_with("hello", interval=0.05)

    @patch("elder_berry.actions.windows_controller.pyautogui")
    def test_hotkey(self, mock_pyauto, controller):
        controller.hotkey("ctrl", "c")
        mock_pyauto.hotkey.assert_called_once_with("ctrl", "c")


# ---------------------------------------------------------------------------
# Maus
# ---------------------------------------------------------------------------


class TestMouse:
    @patch("elder_berry.actions.windows_controller.pyautogui")
    def test_move_mouse(self, mock_pyauto, controller):
        controller.move_mouse(100, 200, duration=0.5)
        mock_pyauto.moveTo.assert_called_once_with(100, 200, duration=0.5)

    @patch("elder_berry.actions.windows_controller.pyautogui")
    def test_click_default(self, mock_pyauto, controller):
        controller.click(50, 60)
        mock_pyauto.click.assert_called_once_with(x=50, y=60, button="left")

    @patch("elder_berry.actions.windows_controller.pyautogui")
    def test_click_right(self, mock_pyauto, controller):
        controller.click(button="right")
        mock_pyauto.click.assert_called_once_with(x=None, y=None, button="right")


# ---------------------------------------------------------------------------
# Fenster
# ---------------------------------------------------------------------------


def _make_mock_window(
    title: str, hwnd: int = 12345, is_minimized: bool = False
) -> MagicMock:
    """Erzeugt ein Mock-Fensterobjekt kompatibel mit pygetwindow."""
    w = MagicMock()
    w.title = title
    w._hWnd = hwnd
    type(w).isMinimized = PropertyMock(return_value=is_minimized)
    return w


class TestWindows:
    @patch("elder_berry.actions.windows_controller.gw")
    def test_list_windows_filters_empty_titles(self, mock_gw, controller):
        mock_gw.getAllWindows.return_value = [
            _make_mock_window("Notepad", 1),
            _make_mock_window("", 2),
            _make_mock_window("  ", 3),
            _make_mock_window("Firefox", 4),
        ]
        result = controller.list_windows()
        assert len(result) == 2
        assert all(isinstance(w, WindowInfo) for w in result)
        titles = [w.title for w in result]
        assert "Notepad" in titles
        assert "Firefox" in titles

    @patch("elder_berry.actions.windows_controller.gw")
    def test_focus_window_found(self, mock_gw, controller):
        win = _make_mock_window("Notepad")
        mock_gw.getAllWindows.return_value = [win]
        assert controller.focus_window("notepad") is True
        win.activate.assert_called_once()

    @patch("elder_berry.actions.windows_controller.gw")
    def test_focus_window_restores_minimized(self, mock_gw, controller):
        win = _make_mock_window("Notepad", is_minimized=True)
        mock_gw.getAllWindows.return_value = [win]
        controller.focus_window("notepad")
        win.restore.assert_called_once()
        win.activate.assert_called_once()

    @patch("elder_berry.actions.windows_controller.gw")
    def test_focus_window_not_found(self, mock_gw, controller):
        mock_gw.getAllWindows.return_value = []
        assert controller.focus_window("nonexistent") is False

    @patch("elder_berry.actions.windows_controller.gw")
    def test_minimize_window(self, mock_gw, controller):
        win = _make_mock_window("Notepad")
        mock_gw.getAllWindows.return_value = [win]
        assert controller.minimize_window("notepad") is True
        win.minimize.assert_called_once()

    @patch("elder_berry.actions.windows_controller.gw")
    def test_maximize_window(self, mock_gw, controller):
        win = _make_mock_window("Notepad")
        mock_gw.getAllWindows.return_value = [win]
        assert controller.maximize_window("notepad") is True
        win.maximize.assert_called_once()

    @patch("elder_berry.actions.windows_controller.gw")
    def test_minimize_not_found(self, mock_gw, controller):
        mock_gw.getAllWindows.return_value = []
        assert controller.minimize_window("nope") is False


# ---------------------------------------------------------------------------
# Lautstärke
# ---------------------------------------------------------------------------


class TestVolume:
    def _mock_volume(self, controller):
        """Setzt ein Mock-Volume-Interface."""
        mock_vol = MagicMock()
        controller._volume_interface = mock_vol
        return mock_vol

    def test_get_volume(self, controller):
        mock_vol = self._mock_volume(controller)
        mock_vol.GetMasterVolumeLevelScalar.return_value = 0.75
        assert controller.get_volume() == 0.75

    def test_set_volume(self, controller):
        mock_vol = self._mock_volume(controller)
        controller.set_volume(0.5)
        mock_vol.SetMasterVolumeLevelScalar.assert_called_once_with(0.5, None)

    def test_set_volume_rejects_out_of_range(self, controller):
        self._mock_volume(controller)
        with pytest.raises(ValueError, match="0.0 und 1.0"):
            controller.set_volume(1.5)
        with pytest.raises(ValueError, match="0.0 und 1.0"):
            controller.set_volume(-0.1)

    def test_mute_on(self, controller):
        mock_vol = self._mock_volume(controller)
        controller.mute(True)
        mock_vol.SetMute.assert_called_once_with(1, None)

    def test_mute_off(self, controller):
        mock_vol = self._mock_volume(controller)
        controller.mute(False)
        mock_vol.SetMute.assert_called_once_with(0, None)
