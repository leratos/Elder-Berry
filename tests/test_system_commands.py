"""Tests: SystemCommandHandler – System, Media, Volume, Avatar, Screenshot, Restart."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.system_commands import (
    AVATAR_EMOTION_PATTERN,
    MEDIA_KEYS,
    VOLUME_PATTERN,
    SystemCommandHandler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def monitor():
    m = MagicMock()
    info = MagicMock()
    info.cpu.usage_percent = 25.0
    info.cpu.core_count = 8
    info.cpu.thread_count = 16
    info.cpu.freq_mhz = 3600.0
    info.ram.used_mb = 8192.0
    info.ram.total_mb = 32768.0
    info.ram.usage_percent = 25.0
    info.gpus = []
    info.top_processes = []
    m.get_info.return_value = info
    return m


@pytest.fixture
def controller():
    return MagicMock()


@pytest.fixture
def avatar_renderer():
    return MagicMock()


@pytest.fixture
def handler(monitor, controller, avatar_renderer):
    return SystemCommandHandler(
        system_monitor=monitor,
        controller=controller,
        avatar_renderer=avatar_renderer,
    )


@pytest.fixture
def handler_minimal():
    return SystemCommandHandler()


# ---------------------------------------------------------------------------
# Pattern Tests
# ---------------------------------------------------------------------------

class TestVolumePattern:
    @pytest.mark.parametrize("text,level", [
        ("volume 50", "50"),
        ("vol 75", "75"),
        ("lautstärke 30", "30"),
        ("lautstarke 100", "100"),
    ])
    def test_valid(self, text, level):
        m = VOLUME_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == level

    def test_invalid(self):
        assert VOLUME_PATTERN.search("volume abc") is None


class TestAvatarEmotionPattern:
    @pytest.mark.parametrize("text,emotion", [
        ("avatar angry", "angry"),
        ("selfie cheerful", "cheerful"),
        ("avatar neutral", "neutral"),
    ])
    def test_valid(self, text, emotion):
        m = AVATAR_EMOTION_PATTERN.match(text)
        assert m is not None
        assert m.group(1) == emotion

    def test_no_emotion(self):
        assert AVATAR_EMOTION_PATTERN.match("avatar") is None


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class TestSystemInterface:
    def test_simple_commands(self, handler):
        cmds = handler.simple_commands
        assert "status" in cmds
        assert "screenshot" in cmds
        assert "restart" in cmds
        assert "pause" in cmds
        assert "play" in cmds
        assert "avatar" in cmds

    def test_patterns(self, handler):
        patterns = handler.patterns
        names = [p[1] for p in patterns]
        assert "volume" in names
        assert "avatar" in names

    def test_keywords(self, handler):
        kw = handler.keywords
        assert "screenshot" in kw
        assert "status" in kw
        assert "restart" in kw


# ---------------------------------------------------------------------------
# Status Command
# ---------------------------------------------------------------------------

class TestStatusCommand:
    def test_status_success(self, handler, monitor):
        result = handler.execute("status", "status")
        assert result.success is True
        assert "CPU" in result.text
        assert "RAM" in result.text

    def test_status_no_monitor(self, handler_minimal):
        result = handler_minimal.execute("status", "status")
        assert result.success is False
        assert "SystemMonitor" in result.text

    def test_status_exception(self, handler, monitor):
        monitor.get_info.side_effect = RuntimeError("fail")
        result = handler.execute("status", "status")
        assert result.success is False


# ---------------------------------------------------------------------------
# Media Commands
# ---------------------------------------------------------------------------

class TestMediaCommands:
    @pytest.mark.parametrize("cmd", ["pause", "play", "skip", "next", "prev", "previous"])
    def test_media_success(self, handler, controller, cmd):
        result = handler.execute(cmd, cmd)
        assert result.success is True
        controller.press_key.assert_called_once_with(MEDIA_KEYS[cmd])

    def test_media_no_controller(self, handler_minimal):
        result = handler_minimal.execute("pause", "pause")
        assert result.success is False
        assert "ActionController" in result.text

    def test_media_exception(self, handler, controller):
        controller.press_key.side_effect = RuntimeError("fail")
        result = handler.execute("pause", "pause")
        assert result.success is False


# ---------------------------------------------------------------------------
# Volume Command
# ---------------------------------------------------------------------------

class TestVolumeCommand:
    def test_volume_success(self, handler, controller):
        result = handler.execute("volume", "volume 50")
        assert result.success is True
        assert "50%" in result.text
        controller.set_volume.assert_called_once_with(0.5)

    def test_volume_over_100(self, handler):
        result = handler.execute("volume", "volume 150")
        assert result.success is False
        assert "0 und 100" in result.text

    def test_volume_no_controller(self, handler_minimal):
        result = handler_minimal.execute("volume", "volume 50")
        assert result.success is False

    def test_volume_invalid_format(self, handler):
        result = handler.execute("volume", "volume laut")
        assert result.success is False

    def test_volume_exception(self, handler, controller):
        controller.set_volume.side_effect = RuntimeError("fail")
        result = handler.execute("volume", "volume 50")
        assert result.success is False


# ---------------------------------------------------------------------------
# Screenshot Command
# ---------------------------------------------------------------------------

class TestScreenshotCommand:
    @patch("elder_berry.comms.commands.system_commands.SystemCommandHandler._wake_monitor")
    def test_screenshot_no_mss(self, mock_wake, handler):
        with patch.dict("sys.modules", {"mss": None}):
            import builtins
            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "mss":
                    raise ImportError("no mss")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = handler.execute("screenshot", "screenshot")
                assert result.success is False
                assert "weder mss noch TowerAgent" in result.text

    def test_screenshot_via_tower_agent(self):
        """Screenshot-Fallback über TowerAgent wenn kein lokales mss."""
        tower = MagicMock()
        tower.host = "127.0.0.1:12769"

        handler = SystemCommandHandler(tower_agent=tower)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"\x89PNG\r\n\x1a\nfake_png_data"

        # Lokales mss blockieren, httpx.get mocken
        with patch.object(handler, "_screenshot_local", return_value=None), \
             patch("httpx.get", return_value=mock_response):
            result = handler.execute("screenshot", "screenshot")
            assert result.success is True
            assert "Tower" in result.text
            assert result.image_path is not None
            # Cleanup
            if result.image_path and result.image_path.exists():
                result.image_path.unlink()

    def test_screenshot_local_preferred_over_tower(self, handler):
        """Lokaler Screenshot hat Vorrang vor TowerAgent."""
        from elder_berry.comms.commands.base import CommandResult
        local_result = CommandResult(
            command="screenshot",
            success=True,
            text="Screenshot aufgenommen.",
            image_path=Path("/tmp/fake.png"),
        )
        with patch.object(handler, "_screenshot_local", return_value=local_result):
            result = handler.execute("screenshot", "screenshot")
            assert result.success is True
            assert "Tower" not in result.text

    def test_screenshot_no_mss_no_tower(self):
        """Ohne mss und ohne TowerAgent → Fehlermeldung."""
        handler = SystemCommandHandler()
        with patch.object(handler, "_screenshot_local", return_value=None):
            result = handler.execute("screenshot", "screenshot")
            assert result.success is False
            assert "weder mss noch TowerAgent" in result.text


class TestIsBlack:
    """_is_black erkennt schwarze und nicht-schwarze Screenshots korrekt."""

    def test_empty_bytes_is_black(self):
        from elder_berry.comms.commands.system_commands import SystemCommandHandler
        assert SystemCommandHandler._is_black(b"") is True

    def test_all_zero_is_black(self):
        from elder_berry.comms.commands.system_commands import SystemCommandHandler
        assert SystemCommandHandler._is_black(bytes(3000)) is True

    def test_bright_pixels_not_black(self):
        from elder_berry.comms.commands.system_commands import SystemCommandHandler
        # Weißes Bild: alle Bytes = 255
        assert SystemCommandHandler._is_black(bytes([255] * 3000)) is False

    def test_dark_but_not_black_not_black(self):
        from elder_berry.comms.commands.system_commands import SystemCommandHandler
        # Dunkelgrau (30/255 ≈ 12% Helligkeit) → über Schwelle → kein Schwarz
        assert SystemCommandHandler._is_black(bytes([30] * 3000)) is False

    def test_nearly_black_is_black(self):
        from elder_berry.comms.commands.system_commands import SystemCommandHandler
        # Sehr dunkler Wert (5/255) → unter Schwelle → gilt als schwarz
        assert SystemCommandHandler._is_black(bytes([5] * 3000)) is True


class TestIsLocked:
    """_is_locked gibt auf Nicht-Windows-Plattformen False zurück.

    ctypes.windll existiert nur auf Windows. Statt patch.object auf dem
    echten ctypes.windll (AttributeError auf Linux) wird ctypes komplett
    via patch.dict(sys.modules) durch ein MagicMock ersetzt. Damit sieht
    ``import ctypes`` in _is_locked() nur das Stub-Objekt und der Test
    läuft auf jedem Betriebssystem.
    """

    def _fake_ctypes(self, open_desktop_retval: int) -> MagicMock:
        """Erzeugt einen ctypes-Stub mit konfiguriertem OpenInputDesktop."""
        stub = MagicMock()
        stub.windll.user32.OpenInputDesktop.return_value = open_desktop_retval
        return stub

    def test_non_windows_returns_false(self):
        from elder_berry.comms.commands.system_commands import SystemCommandHandler
        with patch("sys.platform", "linux"):
            assert SystemCommandHandler._is_locked() is False

    def test_windows_unlocked_returns_false(self):
        import sys
        from elder_berry.comms.commands.system_commands import SystemCommandHandler
        stub = self._fake_ctypes(open_desktop_retval=1)  # valider Handle → entsperrt
        with patch("sys.platform", "win32"), \
             patch.dict(sys.modules, {"ctypes": stub}):
            assert SystemCommandHandler._is_locked() is False
        stub.windll.user32.CloseDesktop.assert_called_once_with(1)

    def test_windows_locked_returns_true(self):
        import sys
        from elder_berry.comms.commands.system_commands import SystemCommandHandler
        stub = self._fake_ctypes(open_desktop_retval=0)  # NULL → gesperrt
        with patch("sys.platform", "win32"), \
             patch.dict(sys.modules, {"ctypes": stub}):
            assert SystemCommandHandler._is_locked() is True


class TestScreenshotLockStatus:
    """Screenshot-Text enthält den Sperrbildschirm-Hinweis wenn PC gesperrt.

    mss ist ein optionales Extra und muss nicht installiert sein.
    Beide Tests injizieren fake mss-Module via patch.dict(sys.modules)
    damit kein echter mss-Import stattfindet.
    """

    def _fake_mss_modules(self, brightness: int = 128):
        """Erzeugt gemockte mss/mss.tools ohne echtes mss zu importieren."""
        fake_rgb = bytes([brightness] * 3000)

        mock_shot = MagicMock()
        mock_shot.rgb = fake_rgb
        mock_shot.size = (100, 100)

        mock_sct = MagicMock()
        mock_sct.monitors = [None, {}]
        mock_sct.grab.return_value = mock_shot

        ctx_mgr = MagicMock()
        ctx_mgr.__enter__ = MagicMock(return_value=mock_sct)
        ctx_mgr.__exit__ = MagicMock(return_value=False)

        fake_mss = MagicMock()
        fake_mss.mss.return_value = ctx_mgr

        fake_tools = MagicMock()   # to_png ist ein No-op MagicMock
        # Wichtig: fake_mss.tools auf fake_tools setzen, damit
        # `mss.tools.to_png` im Produktionscode auf fake_tools zeigt.
        fake_mss.tools = fake_tools

        return fake_mss, fake_tools

    @patch("elder_berry.comms.commands.system_commands.SystemCommandHandler._wake_monitor")
    @patch("elder_berry.comms.commands.system_commands.SystemCommandHandler._is_locked",
           return_value=True)
    def test_locked_status_in_text(self, mock_locked, mock_wake):
        """Wenn PC gesperrt: Text enthält '(PC gesperrt)'."""
        import sys
        from elder_berry.comms.commands.system_commands import SystemCommandHandler

        handler = SystemCommandHandler()
        fake_mss, fake_tools = self._fake_mss_modules(brightness=128)

        with patch.dict(sys.modules, {"mss": fake_mss, "mss.tools": fake_tools}):
            result = handler._screenshot_local()

        assert result is not None
        assert result.success is True
        assert "gesperrt" in result.text

    @patch("elder_berry.comms.commands.system_commands.SystemCommandHandler._wake_monitor")
    @patch("elder_berry.comms.commands.system_commands.SystemCommandHandler._is_locked",
           return_value=False)
    def test_unlocked_no_lock_hint(self, mock_locked, mock_wake):
        """Wenn PC nicht gesperrt: kein Sperrhinweis im Text."""
        import sys
        from elder_berry.comms.commands.system_commands import SystemCommandHandler

        handler = SystemCommandHandler()
        fake_mss, fake_tools = self._fake_mss_modules(brightness=128)

        with patch.dict(sys.modules, {"mss": fake_mss, "mss.tools": fake_tools}):
            result = handler._screenshot_local()

        assert result is not None
        assert result.success is True
        assert "gesperrt" not in result.text

    @patch("elder_berry.comms.commands.system_commands.SystemCommandHandler._wake_monitor")
    @patch("elder_berry.comms.commands.system_commands.SystemCommandHandler._is_locked",
           return_value=False)
    def test_png_write_error_returns_none(self, mock_locked, mock_wake):
        """PNG-Schreibfehler → None (Tower-Fallback statt harter Ausnahme)."""
        import sys
        from elder_berry.comms.commands.system_commands import SystemCommandHandler

        handler = SystemCommandHandler()
        fake_mss, fake_tools = self._fake_mss_modules(brightness=128)
        fake_tools.to_png.side_effect = OSError("disk full")

        with patch.dict(sys.modules, {"mss": fake_mss, "mss.tools": fake_tools}):
            result = handler._screenshot_local()

        assert result is None


# ---------------------------------------------------------------------------
# Avatar Command
# ---------------------------------------------------------------------------

class TestAvatarCommand:
    def test_avatar_default_emotion(self, handler, avatar_renderer):
        result = handler.execute("avatar", "avatar")
        assert result.success is True
        assert result.image_path is not None
        avatar_renderer.render_to_file.assert_called_once()

    def test_avatar_with_emotion(self, handler, avatar_renderer):
        result = handler.execute("avatar", "avatar angry")
        assert result.success is True
        avatar_renderer.render_to_file.assert_called_once()

    def test_avatar_no_renderer_no_tower(self, handler_minimal):
        result = handler_minimal.execute("avatar", "avatar")
        assert result.success is False
        assert "weder lokal noch via Tower" in result.text

    def test_avatar_local_fails_no_tower(self, handler, avatar_renderer):
        avatar_renderer.render_to_file.side_effect = NotImplementedError()
        result = handler.execute("avatar", "avatar")
        assert result.success is False
        assert "weder lokal noch via Tower" in result.text

    def test_avatar_local_exception_no_tower(self, handler, avatar_renderer):
        avatar_renderer.render_to_file.side_effect = RuntimeError("render fail")
        result = handler.execute("avatar", "avatar")
        assert result.success is False

    def test_avatar_via_tower(self):
        """Avatar-Fallback via TowerAgent."""
        tower = MagicMock()
        tower.host = "127.0.0.1:12769"
        handler = SystemCommandHandler(tower_agent=tower)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"\x89PNG\r\nfake_avatar"

        with patch("httpx.get", return_value=mock_response):
            result = handler.execute("avatar", "avatar happy")
        assert result.success is True
        assert "Tower" in result.text
        assert result.image_path is not None
        if result.image_path and result.image_path.exists():
            result.image_path.unlink()


# ---------------------------------------------------------------------------
# Restart Command
# ---------------------------------------------------------------------------

class TestRestartCommand:
    def test_restart(self, handler):
        result = handler.execute("restart", "restart")
        assert result.success is True
        assert result.pending_confirmation is True
        assert result.pending_data["action_type"] == "restart"
        assert "Bestätige" in result.text

    def test_neustart(self, handler):
        result = handler.execute("neustart", "neustart")
        assert result.success is True
        assert result.pending_confirmation is True


# ---------------------------------------------------------------------------
# Unknown Command
# ---------------------------------------------------------------------------

class TestUnknownCommand:
    def test_unknown(self, handler):
        result = handler.execute("nonexistent", "nonexistent")
        assert result.success is False
        assert "Unbekannt" in result.text
