"""Tests: RemoteCommandHandler – Direkte Befehle via Matrix."""
import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.remote_commands import (
    MEDIA_KEYS,
    VOLUME_PATTERN,
    CommandResult,
    RemoteCommandHandler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_monitor_mock():
    """Erstellt einen Mock-SystemMonitor mit realistischen Daten."""
    from elder_berry.system.info import CpuInfo, GpuInfo, RamInfo, SystemInfo

    monitor = MagicMock()
    monitor.get_info.return_value = SystemInfo(
        platform="Windows",
        cpu=CpuInfo(
            usage_percent=25.0,
            per_core_percent=[20.0, 30.0, 25.0, 25.0],
            freq_mhz=3200.0,
            core_count=4,
            thread_count=8,
        ),
        ram=RamInfo(
            total_mb=16384.0,
            used_mb=8192.0,
            available_mb=8192.0,
            usage_percent=50.0,
        ),
        gpus=[
            GpuInfo(
                name="RTX 4070 Ti Super",
                vram_total_mb=16384.0,
                vram_used_mb=4096.0,
                vram_free_mb=12288.0,
                gpu_util_percent=15.0,
                temperature_c=45.0,
            ),
        ],
        top_processes=[
            {"pid": 1, "name": "python", "cpu_percent": 12.0, "memory_percent": 3.5},
            {"pid": 2, "name": "chrome", "cpu_percent": 8.0, "memory_percent": 5.2},
        ],
    )
    return monitor


def _make_controller_mock():
    """Erstellt einen Mock-ActionController."""
    controller = MagicMock()
    return controller


# ---------------------------------------------------------------------------
# CommandResult DTO
# ---------------------------------------------------------------------------

class TestCommandResult:
    def test_creation_text_only(self):
        result = CommandResult(command="status", success=True, text="OK")
        assert result.command == "status"
        assert result.success is True
        assert result.text == "OK"
        assert result.image_path is None

    def test_creation_with_image(self):
        result = CommandResult(
            command="screenshot", success=True,
            text="Screenshot aufgenommen.", image_path=Path("/tmp/screen.png"),
        )
        assert result.image_path == Path("/tmp/screen.png")

    def test_defaults(self):
        result = CommandResult(command="x", success=False)
        assert result.text is None
        assert result.image_path is None


# ---------------------------------------------------------------------------
# parse_command
# ---------------------------------------------------------------------------

class TestParseCommand:
    def test_status(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("status") == "status"
        assert handler.parse_command("Status") == "status"
        assert handler.parse_command("STATUS") == "status"
        assert handler.parse_command("  status  ") == "status"

    def test_systemstatus(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("systemstatus") == "systemstatus"

    def test_screenshot(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("screenshot") == "screenshot"
        assert handler.parse_command("screen") == "screen"

    def test_media_commands(self):
        handler = RemoteCommandHandler()
        for cmd in ("pause", "play", "skip", "next", "prev", "previous"):
            assert handler.parse_command(cmd) == cmd

    def test_volume(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("volume 50") == "volume"
        assert handler.parse_command("vol 75") == "volume"
        assert handler.parse_command("Volume 0") == "volume"
        assert handler.parse_command("lautstärke 100") == "volume"

    def test_not_a_command(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("was ist los?") is None
        assert handler.parse_command("erzähl mir einen witz") is None
        assert handler.parse_command("") is None
        assert handler.parse_command("   ") is None

    def test_volume_invalid_format(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("volume") is None
        assert handler.parse_command("volume abc") is None

    def test_keyword_screenshot_in_sentence(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("schick mir ein screenshot") == "screenshot"
        assert handler.parse_command("Schick mir bitte ein Screenshot vom pc") == "screenshot"
        assert handler.parse_command("mach mal ein Bildschirmfoto") == "screenshot"

    def test_keyword_status_in_sentence(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("wie ist der systemstatus?") == "status"
        assert handler.parse_command("zeig mir den PC Status") == "status"

    def test_keyword_media_in_sentence(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("musik aus bitte") == "pause"
        assert handler.parse_command("nächster song") == "skip"

    def test_volume_in_sentence(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("setz lautstärke 50") == "volume"
        assert handler.parse_command("bitte volume 30 setzen") == "volume"


# ---------------------------------------------------------------------------
# execute: status
# ---------------------------------------------------------------------------

class TestCmdStatus:
    def test_status_success(self):
        monitor = _make_monitor_mock()
        handler = RemoteCommandHandler(system_monitor=monitor)
        result = handler.execute("status", "status")

        assert result.command == "status"
        assert result.success is True
        assert "CPU: 25.0%" in result.text
        assert "RAM:" in result.text
        assert "RTX 4070 Ti Super" in result.text
        assert "python" in result.text

    def test_status_no_monitor(self):
        handler = RemoteCommandHandler()
        result = handler.execute("status", "status")

        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_status_monitor_error(self):
        monitor = MagicMock()
        monitor.get_info.side_effect = RuntimeError("psutil kaputt")
        handler = RemoteCommandHandler(system_monitor=monitor)
        result = handler.execute("status", "status")

        assert result.success is False
        assert "Fehler" in result.text

    def test_systemstatus_alias(self):
        monitor = _make_monitor_mock()
        handler = RemoteCommandHandler(system_monitor=monitor)
        result = handler.execute("systemstatus", "systemstatus")

        assert result.success is True
        assert "CPU:" in result.text


# ---------------------------------------------------------------------------
# execute: screenshot
# ---------------------------------------------------------------------------

class TestCmdScreenshot:
    def test_screenshot_result_shape(self):
        """Screenshot liefert immer ein gültiges CommandResult (Erfolg oder Fehler)."""
        handler = RemoteCommandHandler()
        result = handler._cmd_screenshot()

        assert result.command == "screenshot"
        # Entweder Erfolg (mss installiert) oder graceful Fehler
        if result.success:
            assert result.image_path is not None
            assert result.image_path.exists()
            result.image_path.unlink(missing_ok=True)
        else:
            assert result.text is not None

    def test_screenshot_via_execute(self):
        """execute('screenshot', ...) ruft _cmd_screenshot auf."""
        handler = RemoteCommandHandler()
        result = handler.execute("screenshot", "screenshot")

        assert result.command == "screenshot"
        if result.success:
            assert result.image_path is not None
            result.image_path.unlink(missing_ok=True)

    def test_screenshot_no_mss(self):
        """Screenshot wenn mss nicht importierbar ist."""
        handler = RemoteCommandHandler()

        # Simuliere fehlenden mss-Import
        with patch.dict("sys.modules", {"mss": None, "mss.tools": None}):
            import builtins
            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "mss":
                    raise ImportError("No module named 'mss'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = handler._cmd_screenshot()

        assert result.success is False
        assert "mss" in result.text


# ---------------------------------------------------------------------------
# execute: media
# ---------------------------------------------------------------------------

class TestCmdMedia:
    def test_pause(self):
        ctrl = _make_controller_mock()
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("pause", "pause")

        assert result.success is True
        assert result.text == "Media: pause"
        ctrl.press_key.assert_called_once_with("playpause")

    def test_play(self):
        ctrl = _make_controller_mock()
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("play", "play")

        assert result.success is True
        ctrl.press_key.assert_called_once_with("playpause")

    def test_skip(self):
        ctrl = _make_controller_mock()
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("skip", "skip")

        assert result.success is True
        ctrl.press_key.assert_called_once_with("nexttrack")

    def test_next(self):
        ctrl = _make_controller_mock()
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("next", "next")

        assert result.success is True
        ctrl.press_key.assert_called_once_with("nexttrack")

    def test_prev(self):
        ctrl = _make_controller_mock()
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("prev", "prev")

        assert result.success is True
        ctrl.press_key.assert_called_once_with("prevtrack")

    def test_previous(self):
        ctrl = _make_controller_mock()
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("previous", "previous")

        assert result.success is True
        ctrl.press_key.assert_called_once_with("prevtrack")

    def test_no_controller(self):
        handler = RemoteCommandHandler()
        result = handler.execute("pause", "pause")

        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_controller_error(self):
        ctrl = _make_controller_mock()
        ctrl.press_key.side_effect = RuntimeError("pyautogui kaputt")
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("pause", "pause")

        assert result.success is False
        assert "fehlgeschlagen" in result.text


# ---------------------------------------------------------------------------
# execute: volume
# ---------------------------------------------------------------------------

class TestCmdVolume:
    def test_volume_50(self):
        ctrl = _make_controller_mock()
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("volume", "volume 50")

        assert result.success is True
        assert "50%" in result.text
        ctrl.set_volume.assert_called_once_with(0.5)

    def test_volume_0(self):
        ctrl = _make_controller_mock()
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("volume", "volume 0")

        assert result.success is True
        ctrl.set_volume.assert_called_once_with(0.0)

    def test_volume_100(self):
        ctrl = _make_controller_mock()
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("volume", "volume 100")

        assert result.success is True
        ctrl.set_volume.assert_called_once_with(1.0)

    def test_volume_over_100(self):
        ctrl = _make_controller_mock()
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("volume", "volume 150")

        assert result.success is False
        assert "0 und 100" in result.text

    def test_volume_no_controller(self):
        handler = RemoteCommandHandler()
        result = handler.execute("volume", "volume 50")

        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_volume_controller_error(self):
        ctrl = _make_controller_mock()
        ctrl.set_volume.side_effect = RuntimeError("pycaw kaputt")
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("volume", "volume 50")

        assert result.success is False
        assert "fehlgeschlagen" in result.text

    def test_volume_german_keyword(self):
        ctrl = _make_controller_mock()
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("volume", "lautstärke 30")

        assert result.success is True
        ctrl.set_volume.assert_called_once_with(0.3)

    def test_volume_invalid_raw_text(self):
        handler = RemoteCommandHandler(controller=_make_controller_mock())
        result = handler.execute("volume", "bitte volume setzen")

        assert result.success is False
        assert "Ungültiges Format" in result.text

    def test_volume_in_sentence(self):
        ctrl = _make_controller_mock()
        handler = RemoteCommandHandler(controller=ctrl)
        result = handler.execute("volume", "setz lautstärke 50")

        assert result.success is True
        ctrl.set_volume.assert_called_once_with(0.5)


# ---------------------------------------------------------------------------
# execute: unknown command
# ---------------------------------------------------------------------------

class TestUnknownCommand:
    def test_unknown(self):
        handler = RemoteCommandHandler()
        result = handler.execute("foobar", "foobar")

        assert result.success is False
        assert "Unbekannter Command" in result.text


# ---------------------------------------------------------------------------
# Volume-Pattern Regex
# ---------------------------------------------------------------------------

class TestVolumePattern:
    def test_matches(self):
        assert VOLUME_PATTERN.search("volume 50")
        assert VOLUME_PATTERN.search("vol 75")
        assert VOLUME_PATTERN.search("lautstärke 100")
        assert VOLUME_PATTERN.search("lautstarke 30")
        assert VOLUME_PATTERN.search("Volume 0")
        assert VOLUME_PATTERN.search("setz volume 50 bitte")

    def test_no_match(self):
        assert not VOLUME_PATTERN.search("volume")
        assert not VOLUME_PATTERN.search("volume abc")
        assert not VOLUME_PATTERN.search("volume 1000")  # 4 digits


# ---------------------------------------------------------------------------
# MEDIA_KEYS Mapping
# ---------------------------------------------------------------------------

class TestMediaKeys:
    def test_all_keys_mapped(self):
        assert MEDIA_KEYS["pause"] == "playpause"
        assert MEDIA_KEYS["play"] == "playpause"
        assert MEDIA_KEYS["skip"] == "nexttrack"
        assert MEDIA_KEYS["next"] == "nexttrack"
        assert MEDIA_KEYS["prev"] == "prevtrack"
        assert MEDIA_KEYS["previous"] == "prevtrack"
