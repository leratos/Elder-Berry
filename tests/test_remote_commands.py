"""Tests: RemoteCommandHandler – Direkte Befehle via Matrix."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.advanced_commands import (
    AUDIO_LOCAL_PATTERN,
    DOCUMENT_SUMMARY_PATTERN,
)
from elder_berry.comms.commands.base import CommandResult
from elder_berry.comms.commands.file_commands import (
    CLIP_WRITE_PATTERN,
    DOWNLOAD_PATTERN,
    MAX_FILE_SIZE_BYTES,
    SEND_FILE_PATTERN,
)
from elder_berry.comms.commands.docker_commands import DOCKER_PATTERN
from elder_berry.comms.commands.git_commands import GIT_PATTERN
from elder_berry.comms.commands.process_commands import (
    KILL_PROCESS_PATTERN,
    START_PROCESS_PATTERN,
)
from elder_berry.comms.commands.system_commands import (
    AVATAR_EMOTION_PATTERN,
    MEDIA_KEYS,
    VOLUME_PATTERN,
)
from elder_berry.comms.remote_commands import RemoteCommandHandler


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


def _make_secret_store_mock(mac="AA:BB:CC:DD:EE:FF"):
    """Erstellt einen Mock-SecretStore."""
    store = MagicMock()
    store.get.return_value = mac
    return store


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
            command="screenshot",
            success=True,
            text="Screenshot aufgenommen.",
            image_path=Path("/tmp/screen.png"),
        )
        assert result.image_path == Path("/tmp/screen.png")

    def test_defaults(self):
        result = CommandResult(command="x", success=False)
        assert result.text is None
        assert result.image_path is None
        assert result.file_path is None

    def test_creation_with_file(self):
        result = CommandResult(
            command="send_file",
            success=True,
            text="Datei wird gesendet.",
            file_path=Path("/tmp/datei.pdf"),
        )
        assert result.file_path == Path("/tmp/datei.pdf")


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
        assert (
            handler.parse_command("Schick mir bitte ein Screenshot vom pc")
            == "screenshot"
        )
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
        assert handler.parse_command("stell lautstärke auf 70") == "volume"

    # --- Tier 2: Clipboard ---
    def test_clipboard_read(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("clipboard") == "clipboard"
        assert handler.parse_command("Clipboard") == "clipboard"

    def test_clipboard_write(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("clip: text hier") == "clip_write"
        assert handler.parse_command("clip text hier") == "clip_write"
        assert handler.parse_command("Clip: Hallo Welt") == "clip_write"

    def test_clipboard_keyword(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("was ist im clipboard?") == "clipboard"
        assert handler.parse_command("zeig mir die zwischenablage") == "clipboard"

    # --- Tier 2: Send File ---
    def test_send_file(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("schick mir C:\\Users\\datei.pdf") == "send_file"
        assert handler.parse_command("send file C:\\test.txt") == "send_file"
        assert handler.parse_command("sende mir /home/pi/test.txt") == "send_file"

    # --- Tier 2: Process Control ---
    def test_start_process(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("starte chrome") == "start_process"
        assert handler.parse_command("start notepad") == "start_process"
        assert handler.parse_command("öffne firefox") == "start_process"

    def test_kill_process(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("kill blender") == "kill_process"
        assert handler.parse_command("beende chrome") == "kill_process"
        assert handler.parse_command("stoppe firefox") == "kill_process"

    # --- Tier 2: Wake-on-LAN ---
    def test_wol(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("wol") == "wol"
        assert handler.parse_command("WOL") == "wol"

    def test_wol_keyword(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("weck tower auf") == "wol"
        assert handler.parse_command("tower aufwecken bitte") == "wol"

    # --- Tier 3: Git ---
    def test_git(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("git status") == "git"
        assert handler.parse_command("git pull") == "git"
        assert handler.parse_command("git log") == "git"
        assert handler.parse_command("git diff") == "git"

    def test_git_not_allowed(self):
        handler = RemoteCommandHandler()
        # "git push" wird nicht als git-Command erkannt (nicht in Whitelist-Regex)
        assert handler.parse_command("git push") is None
        assert handler.parse_command("git commit") is None

    # --- Tier 3: Docker ---
    def test_docker(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("docker ps") == "docker"
        assert handler.parse_command("docker restart synapse") == "docker"
        assert handler.parse_command("docker logs synapse") == "docker"

    def test_docker_not_allowed(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("docker rm synapse") is None
        assert handler.parse_command("docker exec bash") is None

    # --- Tier 3: Download ---
    def test_download(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command("download https://example.com/file.zip") == "download"
        )
        assert (
            handler.parse_command("download http://example.com/data.csv") == "download"
        )

    def test_download_no_url(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("download") is None
        assert handler.parse_command("download ftp://bad.com") is None

    # --- Hilfe ---
    def test_hilfe(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("hilfe") == "hilfe"
        # "help" wird auf "hilfe" normalisiert (Phase 51.1)
        assert handler.parse_command("help") == "hilfe"

    def test_hilfe_keyword(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("was kannst du alles?") == "hilfe"
        assert handler.parse_command("welche befehle gibt es") == "hilfe"
        assert handler.parse_command("was geht so?") == "hilfe"

    # --- Avatar / Selfie ---
    def test_avatar(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("avatar") == "avatar"
        assert handler.parse_command("selfie") == "selfie"
        assert handler.parse_command("Avatar") == "avatar"

    def test_avatar_with_emotion(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("selfie angry") == "avatar"
        assert handler.parse_command("avatar cheerful") == "avatar"

    def test_avatar_keyword(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("zeig dich mal") == "avatar"
        assert handler.parse_command("wie siehst du aus?") == "avatar"
        assert handler.parse_command("schick ein bild von dir") == "avatar"

    def test_log_keyword_does_not_match_blog_url(self):
        """Regression: Live-Befund 2026-05-08. Bare 'log' als log-Keyword
        triggerte Substring-Match auf '/blog/' in URLs und parste die
        web-summary-Anfrage faelschlich als log-Command.
        """
        handler = RemoteCommandHandler()
        text = (
            "fasse mir https://www.fpv24.com/de/blog/52/drohnenbuild2022 zusammen bitte"
        )
        # Darf NICHT als log-Command erkannt werden -- entweder None
        # (LLM-Fallback uebernimmt) oder web_summary, aber nicht log.
        assert handler.parse_command(text) != "log"

    def test_log_keyword_does_not_match_login_path(self):
        """Auch '/login/' in URLs darf log-Command nicht ausloesen."""
        handler = RemoteCommandHandler()
        assert handler.parse_command("geh auf https://example.com/login/page") != "log"

    def test_log_command_still_works_with_imperative(self):
        """Sicherstellen dass die sinnvollen Aufrufe weiter greifen."""
        handler = RemoteCommandHandler()
        # Direct-Match via simple_commands
        assert handler.parse_command("log") == "log"
        # Pattern-Match via LOG_PATTERN
        assert handler.parse_command("log errors 5") == "log"
        # Keyword-Match via Imperativ-Phrase
        assert handler.parse_command("zeig mir logs vom letzten Stunde") == "log"


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
    """Phase 55.2: Screenshot-Tests dürfen nicht die echte mss-API
    aufrufen, weil SendMessageTimeoutW-Broadcasts und Display-State auf
    manchen Windows-Systemen hängen oder minuten-lange Delays erzeugen.
    Wir mocken mss komplett.
    """

    def _make_mss_module(self, png_bytes: bytes = b"\x89PNG"):
        """Liefert ein Mock-mss-Modul mit grab/to_png-Stubs."""
        sct = MagicMock()
        screenshot = MagicMock()
        screenshot.rgb = b"\x00" * 12
        screenshot.size = (2, 2)
        sct.monitors = [
            {"top": 0, "left": 0},
            {"top": 0, "left": 0, "width": 100, "height": 100},
        ]
        sct.grab.return_value = screenshot

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=sct)
        cm.__exit__ = MagicMock(return_value=False)

        mss_mod = MagicMock()
        mss_mod.mss = MagicMock(return_value=cm)

        def _to_png(rgb, size, output=None):
            if output:
                Path(output).write_bytes(png_bytes)

        mss_tools = MagicMock()
        mss_tools.to_png.side_effect = _to_png
        mss_mod.tools = mss_tools
        return mss_mod, mss_tools

    def test_screenshot_result_shape(self):
        """Screenshot liefert ein erfolgreiches CommandResult (mss gemockt)."""
        mss_mod, mss_tools = self._make_mss_module()

        handler = RemoteCommandHandler()
        with patch.dict("sys.modules", {"mss": mss_mod, "mss.tools": mss_tools}):
            with patch.object(
                type(handler._handlers[0]) if handler._handlers else object,
                "_wake_monitor",
                lambda *a, **kw: None,
                create=True,
            ):
                # Simpler: direkt _wake_monitor auf dem SystemCommandHandler mocken
                from elder_berry.comms.commands.system_commands import (
                    SystemCommandHandler,
                )

                with patch.object(
                    SystemCommandHandler, "_wake_monitor", lambda *a, **kw: None
                ):
                    result = handler.execute("screenshot", "screenshot")

        assert result.command == "screenshot"
        assert result.success is True
        assert result.image_path is not None
        assert result.image_path.exists()
        result.image_path.unlink(missing_ok=True)

    def test_screenshot_via_execute(self):
        """execute('screenshot', ...) ruft _cmd_screenshot auf (mss gemockt)."""
        mss_mod, mss_tools = self._make_mss_module()

        handler = RemoteCommandHandler()
        from elder_berry.comms.commands.system_commands import SystemCommandHandler

        with patch.dict("sys.modules", {"mss": mss_mod, "mss.tools": mss_tools}):
            with patch.object(
                SystemCommandHandler, "_wake_monitor", lambda *a, **kw: None
            ):
                result = handler.execute("screenshot", "screenshot")

        assert result.command == "screenshot"
        assert result.success is True
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
                result = handler.execute("screenshot", "screenshot")

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
        assert "❌" in result.text


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
        assert "❌" in result.text

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
        result = handler.execute("volume", "stell lautstärke auf 50")

        assert result.success is True
        ctrl.set_volume.assert_called_once_with(0.5)


# ---------------------------------------------------------------------------
# execute: clipboard
# ---------------------------------------------------------------------------


class TestCmdClipboard:
    def test_clipboard_read_success(self):
        handler = RemoteCommandHandler()
        import builtins

        original_import = builtins.__import__

        mock_pyperclip = MagicMock()
        mock_pyperclip.paste.return_value = "Hello World"

        def mock_import(name, *args, **kwargs):
            if name == "pyperclip":
                return mock_pyperclip
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute("clipboard", "clipboard")

        assert result.success is True
        assert "Hello World" in result.text

    def test_clipboard_read_empty(self):
        handler = RemoteCommandHandler()
        import builtins

        original_import = builtins.__import__

        mock_pyperclip = MagicMock()
        mock_pyperclip.paste.return_value = ""

        def mock_import(name, *args, **kwargs):
            if name == "pyperclip":
                return mock_pyperclip
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute("clipboard", "clipboard")

        assert result.success is True
        assert "leer" in result.text

    def test_clipboard_read_no_pyperclip(self):
        handler = RemoteCommandHandler()
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyperclip":
                raise ImportError("No module named 'pyperclip'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute("clipboard", "clipboard")

        assert result.success is False
        assert "pyperclip" in result.text

    def test_clipboard_write_success(self):
        handler = RemoteCommandHandler()
        import builtins

        original_import = builtins.__import__

        mock_pyperclip = MagicMock()

        def mock_import(name, *args, **kwargs):
            if name == "pyperclip":
                return mock_pyperclip
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute("clip_write", "clip: Hallo Welt")

        assert result.success is True
        assert "kopiert" in result.text
        mock_pyperclip.copy.assert_called_once_with("Hallo Welt")

    def test_clipboard_write_colon_format(self):
        handler = RemoteCommandHandler()
        import builtins

        original_import = builtins.__import__

        mock_pyperclip = MagicMock()

        def mock_import(name, *args, **kwargs):
            if name == "pyperclip":
                return mock_pyperclip
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute("clip_write", "clip: some text")

        assert result.success is True
        mock_pyperclip.copy.assert_called_once_with("some text")

    def test_clipboard_write_space_format(self):
        handler = RemoteCommandHandler()
        import builtins

        original_import = builtins.__import__

        mock_pyperclip = MagicMock()

        def mock_import(name, *args, **kwargs):
            if name == "pyperclip":
                return mock_pyperclip
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute("clip_write", "clip some text")

        assert result.success is True
        mock_pyperclip.copy.assert_called_once_with("some text")

    def test_clipboard_write_no_pyperclip(self):
        handler = RemoteCommandHandler()
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyperclip":
                raise ImportError("No module named 'pyperclip'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute("clip_write", "clip: text")

        assert result.success is False
        assert "pyperclip" in result.text


# ---------------------------------------------------------------------------
# execute: send_file
# ---------------------------------------------------------------------------


class TestCmdSendFile:
    def test_send_file_success(self, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"PDF content " * 100)

        handler = RemoteCommandHandler(send_file_allowed_roots=(tmp_path,))
        result = handler.execute("send_file", f"schick mir {test_file}")

        assert result.success is True
        assert result.file_path == test_file
        assert "test.pdf" in result.text

    def test_send_file_not_found(self, tmp_path):
        missing = tmp_path / "nonexistent" / "file.pdf"
        handler = RemoteCommandHandler(send_file_allowed_roots=(tmp_path,))
        result = handler.execute("send_file", f"schick mir {missing}")

        assert result.success is False
        assert "nicht gefunden" in result.text

    def test_send_file_too_large(self, tmp_path):
        test_file = tmp_path / "large.bin"
        # Erstelle eine Datei knapp über dem Limit
        test_file.write_bytes(b"\x00" * (MAX_FILE_SIZE_BYTES + 1))

        handler = RemoteCommandHandler(send_file_allowed_roots=(tmp_path,))
        result = handler.execute("send_file", f"schick mir {test_file}")

        assert result.success is False
        assert "zu groß" in result.text

    def test_send_file_directory(self, tmp_path):
        handler = RemoteCommandHandler(send_file_allowed_roots=(tmp_path.parent,))
        result = handler.execute("send_file", f"schick mir {tmp_path}")

        assert result.success is False
        assert "keine Datei" in result.text

    def test_send_file_no_path(self):
        handler = RemoteCommandHandler()
        result = handler.execute("send_file", "schick mir bitte irgendwas")

        assert result.success is False
        assert "nicht erkannt" in result.text

    def test_send_file_outside_allowed_roots(self, tmp_path):
        """Dateien außerhalb der erlaubten Wurzeln werden abgewiesen."""
        test_file = tmp_path / "secret.key"
        test_file.write_bytes(b"key material")

        other_dir = tmp_path / "other"
        other_dir.mkdir()
        handler = RemoteCommandHandler(send_file_allowed_roots=(other_dir,))
        result = handler.execute("send_file", f"schick mir {test_file}")

        assert result.success is False
        assert "Zugriff verweigert" in result.text


# ---------------------------------------------------------------------------
# execute: process control
# ---------------------------------------------------------------------------


class TestCmdProcessControl:
    def test_start_not_in_whitelist(self):
        handler = RemoteCommandHandler()
        result = handler.execute("start_process", "starte malware")

        assert result.success is False
        assert "nicht in der Start-Whitelist" in result.text

    def test_start_in_whitelist(self):
        handler = RemoteCommandHandler()
        with patch("subprocess.Popen") as mock_popen:
            result = handler.execute("start_process", "starte notepad")

        assert result.success is True
        assert "Gestartet" in result.text
        mock_popen.assert_called_once()

    def test_start_file_not_found(self):
        handler = RemoteCommandHandler()
        with patch("subprocess.Popen", side_effect=FileNotFoundError):
            result = handler.execute("start_process", "starte notepad")

        assert result.success is False
        assert "nicht gefunden" in result.text

    def test_kill_not_in_whitelist(self):
        handler = RemoteCommandHandler()
        result = handler.execute("kill_process", "kill systemd")

        assert result.success is False
        assert "nicht in der Kill-Whitelist" in result.text

    def test_kill_no_process_found(self):
        handler = RemoteCommandHandler()

        mock_psutil = MagicMock()
        mock_psutil.process_iter.return_value = []
        mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        mock_psutil.AccessDenied = type("AccessDenied", (Exception,), {})

        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                return mock_psutil
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute("kill_process", "kill blender")

        assert result.success is False
        assert (
            "nicht gefunden" in result.text.lower()
            or "kein laufender" in result.text.lower()
        )

    def test_kill_success(self):
        handler = RemoteCommandHandler()

        mock_proc = MagicMock()
        mock_proc.info = {"name": "blender.exe"}

        mock_psutil = MagicMock()
        mock_psutil.process_iter.return_value = [mock_proc]
        mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        mock_psutil.AccessDenied = type("AccessDenied", (Exception,), {})

        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                return mock_psutil
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute("kill_process", "kill blender")

        assert result.success is True
        assert "Beendet" in result.text
        mock_proc.terminate.assert_called_once()


# ---------------------------------------------------------------------------
# execute: wake-on-lan
# ---------------------------------------------------------------------------


class TestCmdWoL:
    def test_wol_success(self):
        store = _make_secret_store_mock("AA:BB:CC:DD:EE:FF")
        handler = RemoteCommandHandler(secret_store=store)

        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value = mock_sock
            result = handler.execute("wol", "wol")

        assert result.success is True
        assert "gesendet" in result.text
        mock_sock.sendto.assert_called_once()
        # Magic Packet: 6×FF + 16× MAC
        packet = mock_sock.sendto.call_args[0][0]
        assert packet[:6] == b"\xff" * 6
        assert len(packet) == 6 + 16 * 6  # 102 bytes

    def test_wol_no_secret_store(self):
        handler = RemoteCommandHandler()
        result = handler.execute("wol", "wol")

        assert result.success is False
        assert "SecretStore" in result.text

    def test_wol_no_mac(self):
        store = MagicMock()
        store.get.side_effect = KeyError("not found")
        handler = RemoteCommandHandler(secret_store=store)
        result = handler.execute("wol", "wol")

        assert result.success is False
        assert "tower_mac_address" in result.text

    def test_wol_invalid_mac(self):
        store = _make_secret_store_mock("invalid")
        handler = RemoteCommandHandler(secret_store=store)
        result = handler.execute("wol", "wol")

        assert result.success is False
        assert "Ungültige MAC" in result.text

    def test_wol_mac_with_dashes(self):
        store = _make_secret_store_mock("AA-BB-CC-DD-EE-FF")
        handler = RemoteCommandHandler(secret_store=store)

        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value = mock_sock
            result = handler.execute("wol", "wol")

        assert result.success is True


# ---------------------------------------------------------------------------
# execute: git
# ---------------------------------------------------------------------------


class TestCmdGit:
    def test_git_status(self, tmp_path):
        handler = RemoteCommandHandler(project_root=tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="On branch main\nnothing to commit",
                stderr="",
            )
            result = handler.execute("git", "git status")

        assert result.success is True
        assert "git status" in result.text
        assert "On branch main" in result.text

    def test_git_pull(self, tmp_path):
        handler = RemoteCommandHandler(project_root=tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Already up to date.",
                stderr="",
            )
            result = handler.execute("git", "git pull")

        assert result.success is True

    def test_git_log(self, tmp_path):
        handler = RemoteCommandHandler(project_root=tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="abc1234 commit msg",
                stderr="",
            )
            result = handler.execute("git", "git log")

        assert result.success is True
        # Prüfe dass --oneline -20 angehängt wird
        call_args = mock_run.call_args[0][0]
        assert "--oneline" in call_args
        assert "-20" in call_args

    def test_git_not_installed(self, tmp_path):
        handler = RemoteCommandHandler(project_root=tmp_path)

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = handler.execute("git", "git status")

        assert result.success is False
        assert "nicht gefunden" in result.text

    def test_git_timeout(self, tmp_path):
        handler = RemoteCommandHandler(project_root=tmp_path)

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            result = handler.execute("git", "git status")

        assert result.success is False
        assert "Timeout" in result.text


# ---------------------------------------------------------------------------
# execute: docker
# ---------------------------------------------------------------------------


class TestCmdDocker:
    def test_docker_ps(self):
        handler = RemoteCommandHandler()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="CONTAINER ID   IMAGE   STATUS",
                stderr="",
            )
            result = handler.execute("docker", "docker ps")

        assert result.success is True
        assert "docker ps" in result.text

    def test_docker_restart(self):
        handler = RemoteCommandHandler()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="synapse",
                stderr="",
            )
            result = handler.execute("docker", "docker restart synapse")

        assert result.success is True

    def test_docker_logs(self):
        handler = RemoteCommandHandler()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="log line 1\nlog line 2",
                stderr="",
            )
            result = handler.execute("docker", "docker logs synapse")

        assert result.success is True
        # Prüfe dass --tail 50 angehängt wird
        call_args = mock_run.call_args[0][0]
        assert "--tail" in call_args

    def test_docker_restart_no_container(self):
        handler = RemoteCommandHandler()
        result = handler.execute("docker", "docker restart")

        assert result.success is False
        assert "Container-Name fehlt" in result.text

    def test_docker_not_installed(self):
        handler = RemoteCommandHandler()

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = handler.execute("docker", "docker ps")

        assert result.success is False
        assert "nicht gefunden" in result.text


# ---------------------------------------------------------------------------
# execute: download
# ---------------------------------------------------------------------------


class TestCmdDownload:
    def test_download_success(self, tmp_path):
        handler = RemoteCommandHandler(download_dir=tmp_path)

        mock_response = MagicMock()
        mock_response.headers = {"content-length": "100"}
        mock_response.iter_bytes.return_value = [b"data" * 25]
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.raise_for_status = MagicMock()

        import builtins

        original_import = builtins.__import__

        mock_httpx = MagicMock()
        mock_httpx.stream.return_value = mock_response
        mock_httpx.HTTPStatusError = type("HTTPStatusError", (Exception,), {})
        mock_httpx.RequestError = type("RequestError", (Exception,), {})

        def mock_import(name, *args, **kwargs):
            if name == "httpx":
                return mock_httpx
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute(
                "download", "download https://example.com/file.zip"
            )

        assert result.success is True
        assert "file.zip" in result.text

    def test_download_invalid_url(self):
        handler = RemoteCommandHandler()
        result = handler.execute("download", "download not-a-url")

        assert result.success is False

    def test_download_too_large(self, tmp_path):
        handler = RemoteCommandHandler(download_dir=tmp_path)

        mock_response = MagicMock()
        mock_response.headers = {"content-length": str(MAX_FILE_SIZE_BYTES + 1)}
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.raise_for_status = MagicMock()

        import builtins

        original_import = builtins.__import__

        mock_httpx = MagicMock()
        mock_httpx.stream.return_value = mock_response
        mock_httpx.HTTPStatusError = type("HTTPStatusError", (Exception,), {})
        mock_httpx.RequestError = type("RequestError", (Exception,), {})

        def mock_import(name, *args, **kwargs):
            if name == "httpx":
                return mock_httpx
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute(
                "download", "download https://example.com/large.bin"
            )

        assert result.success is False
        assert "zu groß" in result.text


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
        assert VOLUME_PATTERN.match("volume 50")
        assert VOLUME_PATTERN.match("vol 75")
        assert VOLUME_PATTERN.match("lautstärke 100")
        assert VOLUME_PATTERN.match("lautstarke 30")
        assert VOLUME_PATTERN.match("Volume 0")
        assert VOLUME_PATTERN.match("setz volume 50")
        assert VOLUME_PATTERN.match("stell lautstärke auf 70")

    def test_no_match(self):
        assert not VOLUME_PATTERN.match("volume")
        assert not VOLUME_PATTERN.match("volume abc")
        assert not VOLUME_PATTERN.match("volume 1000")  # 4 digits
        assert not VOLUME_PATTERN.match("bitte volume 30 setzen")  # zu lose


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


# ---------------------------------------------------------------------------
# Neue Regex-Patterns
# ---------------------------------------------------------------------------


class TestNewPatterns:
    def test_clip_write_pattern(self):
        assert CLIP_WRITE_PATTERN.match("clip: text hier")
        assert CLIP_WRITE_PATTERN.match("clip text hier")
        assert CLIP_WRITE_PATTERN.match("Clip: Hallo Welt")
        assert not CLIP_WRITE_PATTERN.match("clipboard")  # Kein Match

    def test_send_file_pattern(self):
        assert SEND_FILE_PATTERN.search("schick mir C:\\Users\\test.pdf")
        assert SEND_FILE_PATTERN.search("send file C:\\test.txt")
        assert SEND_FILE_PATTERN.search("sende mir /home/pi/test.txt")
        assert not SEND_FILE_PATTERN.search("schick mir was nettes")

    def test_start_process_pattern(self):
        assert START_PROCESS_PATTERN.match("starte chrome")
        assert START_PROCESS_PATTERN.match("start notepad")
        assert START_PROCESS_PATTERN.match("öffne firefox")
        assert not START_PROCESS_PATTERN.match("starte")  # kein Argument

    def test_kill_process_pattern(self):
        assert KILL_PROCESS_PATTERN.match("kill blender")
        assert KILL_PROCESS_PATTERN.match("beende chrome")
        assert KILL_PROCESS_PATTERN.match("stoppe firefox")
        assert not KILL_PROCESS_PATTERN.match("kill")  # kein Argument

    def test_git_pattern(self):
        assert GIT_PATTERN.match("git status")
        assert GIT_PATTERN.match("git pull")
        assert GIT_PATTERN.match("git log")
        assert GIT_PATTERN.match("git diff")
        assert not GIT_PATTERN.match("git push")
        assert not GIT_PATTERN.match("git commit")

    def test_docker_pattern(self):
        assert DOCKER_PATTERN.match("docker ps")
        assert DOCKER_PATTERN.match("docker restart synapse")
        assert DOCKER_PATTERN.match("docker logs synapse")
        assert not DOCKER_PATTERN.match("docker rm container")
        assert not DOCKER_PATTERN.match("docker exec bash")

    def test_download_pattern(self):
        assert DOWNLOAD_PATTERN.match("download https://example.com/file.zip")
        assert DOWNLOAD_PATTERN.match("download http://example.com/data.csv")
        assert not DOWNLOAD_PATTERN.match("download")
        assert not DOWNLOAD_PATTERN.match("download ftp://bad.com")

    def test_avatar_emotion_pattern(self):
        m = AVATAR_EMOTION_PATTERN.match("selfie angry")
        assert m and m.group(1) == "angry"
        m = AVATAR_EMOTION_PATTERN.match("avatar cheerful")
        assert m and m.group(1) == "cheerful"
        assert not AVATAR_EMOTION_PATTERN.match("selfie")  # Nur Keyword, kein Match
        assert not AVATAR_EMOTION_PATTERN.match("avatar")


# ---------------------------------------------------------------------------
# execute: avatar
# ---------------------------------------------------------------------------


class TestCmdHilfe:
    def test_hilfe_returns_overview(self):
        # Phase 51.1: "hilfe" zeigt nur Kategorien-Übersicht
        handler = RemoteCommandHandler()
        result = handler.execute("hilfe", "hilfe")

        assert result.success is True
        assert result.command == "hilfe"
        assert "Hilfe-Kategorien" in result.text
        assert "hilfe basis" in result.text
        assert "hilfe alles" in result.text

    def test_hilfe_alles_returns_full_text(self):
        handler = RemoteCommandHandler()
        result = handler.execute("hilfe:alles", "hilfe alles")

        assert result.success is True
        assert "status" in result.text
        assert "screenshot" in result.text
        assert "selfie" in result.text
        assert "claude" in result.text.lower()

    def test_hilfe_category_section(self):
        handler = RemoteCommandHandler()
        result = handler.execute("hilfe:kalender", "hilfe kalender")

        assert result.success is True
        assert "termin" in result.text.lower()
        # Andere Kategorien sollen nicht enthalten sein
        assert "pdf ocr" not in result.text.lower()

    def test_hilfe_unknown_category(self):
        handler = RemoteCommandHandler()
        result = handler.execute("hilfe:?quatsch", "hilfe quatsch")

        assert result.success is True
        assert "Unbekannte Hilfe-Kategorie" in result.text
        assert "hilfe basis" in result.text  # Overview als Fallback

    def test_help_alias(self):
        handler = RemoteCommandHandler()
        result = handler.execute("hilfe", "help")

        assert result.success is True
        assert "Hilfe-Kategorien" in result.text


class TestCmdAvatar:
    def test_avatar_no_renderer(self):
        handler = RemoteCommandHandler()
        result = handler.execute("avatar", "avatar")

        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_avatar_neutral(self, tmp_path):
        mock_renderer = MagicMock()
        mock_renderer.render_to_file.return_value = tmp_path / "avatar.png"

        handler = RemoteCommandHandler(avatar_renderer=mock_renderer)
        result = handler.execute("avatar", "avatar")

        assert result.success is True
        assert result.image_path is not None
        assert "neutral" in result.text
        mock_renderer.render_to_file.assert_called_once()

    def test_avatar_with_emotion(self, tmp_path):
        from elder_berry.character.base import Emotion

        mock_renderer = MagicMock()
        mock_renderer.render_to_file.return_value = tmp_path / "avatar.png"

        handler = RemoteCommandHandler(avatar_renderer=mock_renderer)
        result = handler.execute("avatar", "selfie angry")

        assert result.success is True
        assert "angry" in result.text
        # Prüfe dass Emotion.ANGRY übergeben wurde
        call_args = mock_renderer.render_to_file.call_args
        assert call_args[0][1] == Emotion.ANGRY

    def test_avatar_invalid_emotion_falls_to_neutral(self, tmp_path):
        from elder_berry.character.base import Emotion

        mock_renderer = MagicMock()
        mock_renderer.render_to_file.return_value = tmp_path / "avatar.png"

        handler = RemoteCommandHandler(avatar_renderer=mock_renderer)
        result = handler.execute("avatar", "selfie foobar")

        assert result.success is True
        assert "neutral" in result.text
        call_args = mock_renderer.render_to_file.call_args
        assert call_args[0][1] == Emotion.NEUTRAL

    def test_avatar_not_implemented(self):
        mock_renderer = MagicMock()
        mock_renderer.render_to_file.side_effect = NotImplementedError

        handler = RemoteCommandHandler(avatar_renderer=mock_renderer)
        result = handler.execute("avatar", "avatar")

        assert result.success is False
        assert "Datei-Rendering" in result.text

    def test_avatar_render_error(self):
        mock_renderer = MagicMock()
        mock_renderer.render_to_file.side_effect = RuntimeError("pygame kaputt")

        handler = RemoteCommandHandler(avatar_renderer=mock_renderer)
        result = handler.execute("avatar", "avatar")

        assert result.success is False
        assert "❌" in result.text

    def test_selfie_alias(self):
        mock_renderer = MagicMock()
        mock_renderer.render_to_file.return_value = Path("/tmp/test.png")

        handler = RemoteCommandHandler(avatar_renderer=mock_renderer)
        result = handler.execute("selfie", "selfie")

        assert result.success is True


# ---------------------------------------------------------------------------
# Restart-Command
# ---------------------------------------------------------------------------


class TestRestartCommand:
    """Tests für den restart/neustart Command."""

    def test_parse_restart(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("restart") == "restart"

    def test_parse_neustart(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("neustart") == "neustart"

    def test_execute_neustart_via_simple(self):
        """'neustart' als SIMPLE_COMMAND gibt Bestätigungsdialog zurück."""
        handler = RemoteCommandHandler()
        result = handler.execute("neustart", "neustart")
        assert result.success is True
        assert result.pending_confirmation is True
        assert result.pending_data["action_type"] == "restart"

    def test_parse_keyword_bitte_neustarten(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("bitte neustarten") == "restart"

    def test_parse_keyword_starte_bitte_neu(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("kannst du dich bitte neustarten") == "restart"

    def test_execute_restart_success(self):
        handler = RemoteCommandHandler()
        result = handler.execute("restart", "restart")

        assert result.success is True
        assert result.pending_confirmation is True
        assert "Bestätige" in result.text

    def test_restart_flag_default_false(self):
        """CommandResult hat restart=False als Default."""
        result = CommandResult(command="test", success=True)
        assert result.restart is False

    def test_other_commands_no_restart(self):
        """Andere Commands setzen restart nicht."""
        handler = RemoteCommandHandler()
        result = handler.execute("hilfe", "hilfe")
        assert result.restart is False


# ---------------------------------------------------------------------------
# Calendar-Commands
# ---------------------------------------------------------------------------


class TestCalendarCommands:
    def test_parse_termine(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("termine") == "termine"

    def test_parse_termine_morgen(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("termine morgen") == "termine"

    def test_parse_termine_woche(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("termine woche") == "termine"

    def test_parse_termine_keyword_kalender_exact(self):
        """'kalender' allein → simple_command (exakter Match, listet Termine)."""
        handler = RemoteCommandHandler()
        assert handler.parse_command("kalender") == "kalender"

    def test_parse_kalender_substring_no_match(self):
        """'kalender' als Substring soll NICHT matchen (→ LLM-Fallthrough).

        Verhindert False-Positives wie 'trag den termin in den kalender ein'.
        """
        handler = RemoteCommandHandler()
        assert handler.parse_command("was steht heute im kalender") is None
        assert (
            handler.parse_command("ja trag bitte den termin in den kalender ein")
            is None
        )

    def test_parse_termin_create(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command("termin: Zahnarzt 2026-03-20 14:00")
            == "termin_create"
        )

    def test_parse_termin_create_morgen(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("termin: Zahnarzt morgen 14:00") == "termin_create"

    def test_parse_termin_create_uebermorgen(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command("termin: Meeting übermorgen 10:00") == "termin_create"
        )

    def test_parse_termin_create_dd_mm(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("termin: Zahnarzt 30.03 14:00") == "termin_create"

    def test_parse_termin_create_dd_mm_yyyy(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command("termin: Zahnarzt 30.03.2026 14:00")
            == "termin_create"
        )

    def test_parse_termin_create_mit_um(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command("termin: Zahnarzt morgen um 14:00") == "termin_create"
        )

    def test_parse_termin_create_mit_uhr(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command("termin: Zahnarzt morgen 14:00 Uhr")
            == "termin_create"
        )

    def test_parse_erstelle_termin(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command("erstelle termin Zahnarzt morgen 14:00")
            == "termin_create"
        )

    def test_parse_erstelle_einen_termin(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command("erstelle einen termin Meeting 30.03 10:00")
            == "termin_create"
        )

    def test_execute_termine_no_calendar(self):
        handler = RemoteCommandHandler()
        result = handler.execute("termine", "termine")
        assert result.success is False
        assert "nicht konfiguriert" in result.text

    def test_execute_termine_today(self):
        mock_cal = MagicMock()
        mock_cal.get_today.return_value = []
        mock_cal.format_events.return_value = "Keine Termine."

        handler = RemoteCommandHandler(calendar=mock_cal)
        result = handler.execute("termine", "termine")

        assert result.success is True
        assert "heute" in result.text.lower()
        mock_cal.get_today.assert_called_once()

    def test_execute_termine_morgen(self):
        mock_cal = MagicMock()
        mock_cal.get_tomorrow.return_value = []
        mock_cal.format_events.return_value = "Keine Termine."

        handler = RemoteCommandHandler(calendar=mock_cal)
        result = handler.execute("termine", "termine morgen")

        assert result.success is True
        assert "morgen" in result.text.lower()

    def test_execute_termine_woche(self):
        mock_cal = MagicMock()
        mock_cal.get_events.return_value = []
        mock_cal.format_events.return_value = "Keine Termine."

        handler = RemoteCommandHandler(calendar=mock_cal)
        result = handler.execute("termine", "termine woche")

        assert result.success is True
        mock_cal.get_events.assert_called_once_with(days=7)

    def test_execute_termin_create_no_calendar(self):
        handler = RemoteCommandHandler()
        result = handler.execute("termin_create", "termin: Test 2026-03-20 14:00")
        assert result.success is False

    def test_execute_termin_create_success(self):
        from elder_berry.tools.google_calendar import CalendarEvent
        from datetime import datetime

        mock_cal = MagicMock()
        mock_cal.create_event.return_value = CalendarEvent(
            summary="Zahnarzt",
            start=datetime(2026, 3, 20, 14, 0),
            end=datetime(2026, 3, 20, 15, 0),
        )

        handler = RemoteCommandHandler(calendar=mock_cal)
        result = handler.execute("termin_create", "termin: Zahnarzt 2026-03-20 14:00")

        assert result.success is True
        assert "Zahnarzt" in result.text

    def test_execute_termin_create_morgen(self):
        from elder_berry.tools.google_calendar import CalendarEvent
        from datetime import datetime, date, timedelta

        tomorrow = date.today() + timedelta(days=1)
        expected_start = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 16, 0)

        mock_cal = MagicMock()
        mock_cal.create_event.return_value = CalendarEvent(
            summary="Arzt",
            start=expected_start,
            end=expected_start.replace(hour=17),
        )

        handler = RemoteCommandHandler(calendar=mock_cal)
        result = handler.execute("termin_create", "termin: Arzt morgen 16:00")

        assert result.success is True
        assert "Arzt" in result.text
        call_kwargs = mock_cal.create_event.call_args.kwargs
        assert call_kwargs["start"].hour == 16
        assert call_kwargs["start"].day == tomorrow.day

    def test_execute_termin_create_dd_mm(self):
        from elder_berry.tools.google_calendar import CalendarEvent
        from datetime import datetime, date

        mock_cal = MagicMock()
        mock_cal.create_event.return_value = CalendarEvent(
            summary="Test",
            start=datetime(2026, 3, 30, 12, 0),
            end=datetime(2026, 3, 30, 13, 0),
        )

        handler = RemoteCommandHandler(calendar=mock_cal)
        result = handler.execute("termin_create", "termin: Test 30.03 12:00")

        assert result.success is True
        call_kwargs = mock_cal.create_event.call_args.kwargs
        assert call_kwargs["start"].month == 3
        assert call_kwargs["start"].day == 30
        assert call_kwargs["start"].year == date.today().year

    def test_execute_termin_create_invalid_date(self):
        mock_cal = MagicMock()
        handler = RemoteCommandHandler(calendar=mock_cal)
        result = handler.execute("termin_create", "termin: Test 2026-13-40 25:00")
        assert result.success is False
        assert "Ungültig" in result.text

    def test_parse_termin_suche(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("termin suche Zahnarzt") == "termin_search"

    def test_execute_termin_search_success(self):
        from elder_berry.tools.google_calendar import CalendarEvent
        from datetime import datetime

        mock_cal = MagicMock()
        mock_cal.search_events.return_value = [
            CalendarEvent(
                summary="Zahnarzt Dr. Müller",
                start=datetime(2026, 4, 10, 14, 0),
                end=datetime(2026, 4, 10, 15, 0),
            ),
        ]
        mock_cal.format_events.return_value = "14:00-15:00 Zahnarzt Dr. Müller"

        handler = RemoteCommandHandler(calendar=mock_cal)
        result = handler.execute("termin_search", "termin suche Zahnarzt")

        assert result.success is True
        assert "Zahnarzt" in result.text
        mock_cal.search_events.assert_called_once_with("Zahnarzt", days=90)

    def test_execute_termin_search_no_results(self):
        mock_cal = MagicMock()
        mock_cal.search_events.return_value = []

        handler = RemoteCommandHandler(calendar=mock_cal)
        result = handler.execute("termin_search", "termin suche Nonsense")

        assert result.success is True
        assert "Keine Termine" in result.text


class TestTerminDeleteCommand:
    def _make_events(self, n=3):
        from elder_berry.tools.google_calendar import CalendarEvent
        from datetime import datetime

        return [
            CalendarEvent(
                summary=f"Termin {i}",
                start=datetime(2026, 3, 20, 10 + i, 0),
                end=datetime(2026, 3, 20, 11 + i, 0),
                event_id=f"evt_{i}",
            )
            for i in range(1, n + 1)
        ]

    def test_parse_termin_loeschen(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("termin löschen abc123") == "termin_delete"

    def test_parse_loesche_termin(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("lösche termin Meeting") == "termin_delete"

    def test_parse_loesche_den_termin(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("lösche den termin Zahnarzt") == "termin_delete"

    def test_parse_loesche_alle_termine(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("lösche alle termine") == "termin_delete"

    def test_parse_loesch_den_2_termin(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("lösch den 2. termin") == "termin_delete"

    def test_parse_entferne_termin(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("entferne termin Meeting") == "termin_delete"

    def test_execute_no_calendar(self):
        handler = RemoteCommandHandler()
        result = handler.execute("termin_delete", "lösche termin X")
        assert result.success is False
        assert "nicht konfiguriert" in result.text

    def test_execute_delete_by_index(self):
        mock_cal = MagicMock()
        handler = RemoteCommandHandler(calendar=mock_cal)
        handler._calendar._last_events = self._make_events(3)

        result = handler.execute("termin_delete", "lösche den 2. termin")

        assert result.success is True
        assert "Termin 2" in result.text
        mock_cal.delete_event.assert_called_once_with("evt_2")

    def test_execute_delete_by_title(self):
        mock_cal = MagicMock()
        handler = RemoteCommandHandler(calendar=mock_cal)
        handler._calendar._last_events = self._make_events(3)

        result = handler.execute("termin_delete", "lösche termin Termin 1")

        assert result.success is True
        mock_cal.delete_event.assert_called_once_with("evt_1")

    def test_execute_delete_alle_asks_confirmation(self):
        mock_cal = MagicMock()
        handler = RemoteCommandHandler(calendar=mock_cal)
        handler._calendar._last_events = self._make_events(3)

        result = handler.execute("termin_delete", "lösche alle termine")

        assert result.success is True
        assert result.pending_confirmation is True
        assert result.pending_data["action_type"] == "bulk_delete_events"
        assert len(result.pending_data["event_ids"]) == 3
        mock_cal.delete_event.assert_not_called()

    def test_execute_delete_no_events(self):
        mock_cal = MagicMock()
        handler = RemoteCommandHandler(calendar=mock_cal)
        handler._calendar._last_events = []

        result = handler.execute("termin_delete", "lösche den 1. termin")

        assert result.success is False
        assert "Keine Termine" in result.text

    def test_execute_delete_invalid_index(self):
        mock_cal = MagicMock()
        handler = RemoteCommandHandler(calendar=mock_cal)
        handler._calendar._last_events = self._make_events(2)

        result = handler.execute("termin_delete", "lösche den 5. termin")

        assert result.success is False
        assert "ungültig" in result.text.lower()

    def test_execute_delete_title_not_found(self):
        mock_cal = MagicMock()
        handler = RemoteCommandHandler(calendar=mock_cal)
        handler._calendar._last_events = self._make_events(2)

        result = handler.execute("termin_delete", "lösche termin Gibtsnet")

        assert result.success is False
        assert "nicht" in result.text.lower() or "Kein" in result.text

    def test_execute_delete_api_error(self):
        mock_cal = MagicMock()
        mock_cal.delete_event.side_effect = RuntimeError("API Error")
        handler = RemoteCommandHandler(calendar=mock_cal)
        handler._calendar._last_events = self._make_events(1)

        result = handler.execute("termin_delete", "lösche den 1. termin")

        assert result.success is False
        assert "❌" in result.text

    def test_termine_stores_last_events(self):
        """termine-Command speichert Events für späteres Löschen."""

        mock_cal = MagicMock()
        events = self._make_events(2)
        mock_cal.get_today.return_value = events
        mock_cal.format_events.return_value = "2 Termine"

        handler = RemoteCommandHandler(calendar=mock_cal)
        handler.execute("termine", "termine")

        assert len(handler._calendar._last_events) == 2

    def test_execute_delete_with_filler_single_event(self):
        """'lösch den termin bitte' löscht den einzigen Termin."""
        mock_cal = MagicMock()
        handler = RemoteCommandHandler(calendar=mock_cal)
        handler._calendar._last_events = self._make_events(1)

        result = handler.execute("termin_delete", "lösch den termin bitte")

        assert result.success is True
        assert "Termin 1" in result.text
        mock_cal.delete_event.assert_called_once()

    def test_execute_delete_with_filler_multiple_events_asks(self):
        """'lösch den termin bitte' bei mehreren Events fragt nach."""
        mock_cal = MagicMock()
        handler = RemoteCommandHandler(calendar=mock_cal)
        handler._calendar._last_events = self._make_events(3)

        result = handler.execute("termin_delete", "lösch den termin bitte")

        assert result.success is False
        assert "Welchen?" in result.text

    def test_execute_delete_morgen_filler(self):
        """'lösche den termin morgen' bei 1 Event → löscht ihn."""
        mock_cal = MagicMock()
        handler = RemoteCommandHandler(calendar=mock_cal)
        handler._calendar._last_events = self._make_events(1)

        result = handler.execute("termin_delete", "lösche den termin morgen")

        assert result.success is True
        mock_cal.delete_event.assert_called_once()


# ---------------------------------------------------------------------------
# Email-Commands
# ---------------------------------------------------------------------------


class TestEmailCommands:
    def test_parse_mails(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("mails") == "mails"

    def test_parse_mails_days(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("mails 5") == "mails"

    def test_parse_keyword_neue_mails(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("habe ich neue mails") == "mails"

    def test_parse_keyword_zusammenfassung(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("mail zusammenfassung") == "mail_summary"

    def test_execute_mails_no_client(self):
        handler = RemoteCommandHandler()
        result = handler.execute("mails", "mails")
        assert result.success is False
        assert "nicht konfiguriert" in result.text

    def test_execute_mails_unread(self):
        mock_email = MagicMock()
        mock_email.get_unread.return_value = []
        mock_email.format_mails.return_value = "Keine E-Mails."

        handler = RemoteCommandHandler(email_client=mock_email)
        result = handler.execute("mails", "mails")

        assert result.success is True
        mock_email.get_unread.assert_called_once()

    def test_execute_mails_days(self):
        mock_email = MagicMock()
        mock_email.get_recent.return_value = []
        mock_email.format_mails.return_value = "Keine E-Mails."

        handler = RemoteCommandHandler(email_client=mock_email)
        result = handler.execute("mails", "mails 5")

        assert result.success is True
        mock_email.get_recent.assert_called_once_with(days=5)

    def test_parse_mail_suche(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("mail suche Rechnung") == "mail_search"

    def test_execute_mail_search_success(self):
        from elder_berry.tools.email_client import EmailMessage
        from datetime import datetime

        mock_email = MagicMock()
        mock_email.search.return_value = [
            EmailMessage(
                subject="Rechnung März",
                sender="billing@strato.de",
                date=datetime(2026, 3, 10),
                body_preview="Ihre Rechnung...",
            ),
        ]
        mock_email.format_mails.return_value = (
            "● 10.03 | billing@strato.de | Rechnung März [#42]"
        )
        mock_email.format_mails_detailed.return_value = (
            "--- Mail 1 (ID: 42) ---\nVon: billing@strato.de\n"
            "Betreff: Rechnung März\nInhalt: Ihre Rechnung..."
        )

        handler = RemoteCommandHandler(email_client=mock_email)
        result = handler.execute("mail_search", "mail suche Rechnung")

        assert result.success is True
        assert "Rechnung" in result.text
        # Kurzliste für User, Detail für History
        mock_email.format_mails.assert_called_once()
        mock_email.format_mails_detailed.assert_called_once()
        assert result.history_text is not None
        assert "Inhalt:" in result.history_text

    def test_execute_mail_search_no_results(self):
        mock_email = MagicMock()
        mock_email.search.return_value = []

        handler = RemoteCommandHandler(email_client=mock_email)
        result = handler.execute("mail_search", "mail suche Gibtsnet")

        assert result.success is True
        assert "Keine Mails" in result.text

    def test_execute_mail_summary(self):
        from elder_berry.tools.email_client import EmailMessage
        from datetime import datetime

        mock_email = MagicMock()
        mock_email.get_unread.return_value = [
            EmailMessage(
                subject="Test",
                sender="a@b.com",
                date=datetime(2026, 3, 16),
                body_preview="Inhalt...",
            ),
        ]
        mock_email.format_mails_detailed.return_value = "--- Mail 1 ---\nTest"

        handler = RemoteCommandHandler(email_client=mock_email)
        result = handler.execute("mails", "mail zusammenfassung")

        assert result.success is True
        assert "Mail 1" in result.text


class TestMailAttachmentCommand:
    def test_parse_mail_anhang(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("mail anhang 12345") == "mail_attachment"

    def test_parse_mail_anhaenge(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("mail anhänge 42") == "mail_attachment"

    def test_parse_anhang_von_mail(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("anhang von mail 99") == "mail_attachment"

    def test_parse_mail_id_anhang(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("mail 55 anhang") == "mail_attachment"

    def test_execute_no_client(self):
        handler = RemoteCommandHandler()
        result = handler.execute("mail_attachment", "mail anhang 1")
        assert result.success is False
        assert "nicht konfiguriert" in result.text

    def test_execute_no_attachments(self):
        mock_email = MagicMock()
        mock_email.get_attachments.return_value = []

        handler = RemoteCommandHandler(email_client=mock_email)
        result = handler.execute("mail_attachment", "mail anhang 42")

        assert result.success is True
        assert "Keine Anhänge" in result.text

    def test_execute_with_attachments(self):
        mock_email = MagicMock()
        mock_email.get_attachments.return_value = [
            ("rechnung.pdf", b"%PDF content"),
            ("bild.png", b"\x89PNG data"),
        ]

        handler = RemoteCommandHandler(email_client=mock_email)
        result = handler.execute("mail_attachment", "mail anhang 42")

        assert result.success is True
        assert "2 Anhang" in result.text
        assert "rechnung.pdf" in result.text
        assert "bild.png" in result.text
        assert len(result.file_paths) == 2
        # Temp-Dateien aufräumen
        for p in result.file_paths:
            p.unlink(missing_ok=True)

    def test_execute_error(self):
        mock_email = MagicMock()
        mock_email.get_attachments.side_effect = RuntimeError("IMAP Fehler")

        handler = RemoteCommandHandler(email_client=mock_email)
        result = handler.execute("mail_attachment", "mail anhang 42")

        assert result.success is False
        assert "❌" in result.text


# ---------------------------------------------------------------------------
# Wetter-Commands
# ---------------------------------------------------------------------------


class TestWeatherParse:
    """Parse-Tests für Wetter-Commands."""

    def test_parse_wetter(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("wetter") == "wetter"

    def test_parse_wetter_morgen(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("wetter morgen") == "wetter"

    def test_parse_wetter_woche(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("wetter woche") == "wetter"

    def test_parse_wetter_3(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("wetter 3") == "wetter"

    def test_parse_wetter_heute(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("wetter heute") == "wetter"

    def test_keyword_regnet_es(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("regnet es draußen?") == "wetter"

    def test_keyword_brauche_schirm(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("brauche ich einen schirm?") == "wetter"

    def test_keyword_wie_warm(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("wie warm ist es?") == "wetter"


class TestWeatherExecute:
    """Execute-Tests für Wetter-Commands."""

    def test_execute_no_client(self):
        handler = RemoteCommandHandler()
        result = handler.execute("wetter", "wetter")
        assert result.success is False
        assert "nicht konfiguriert" in result.text

    def test_execute_current(self):
        from elder_berry.tools.weather_client import WeatherData, WeatherForecast
        from datetime import date

        mock_weather = MagicMock()
        mock_weather.get_current.return_value = WeatherData(
            temperature=14.2,
            apparent_temperature=12.5,
            humidity=65,
            wind_speed=12.3,
            weather_code=2,
            description="Teilweise bewölkt",
            city="Berlin",
        )
        mock_weather.get_today.return_value = WeatherForecast(
            date=date.today(),
            temp_min=8.2,
            temp_max=16.5,
            precipitation_mm=0.0,
            precipitation_probability=10,
            weather_code=2,
            description="Teilweise bewölkt",
            city="Berlin",
        )
        mock_weather.format_current.return_value = "⛅ Wetter in Berlin: 14.2°C"
        mock_weather.format_forecast.return_value = "📅 Vorhersage: 8–17°C"

        handler = RemoteCommandHandler(weather=mock_weather)
        result = handler.execute("wetter", "wetter")

        assert result.success is True
        assert "Berlin" in result.text
        mock_weather.get_current.assert_called_once()
        mock_weather.get_today.assert_called_once()

    def test_execute_morgen(self):
        from elder_berry.tools.weather_client import WeatherForecast
        from datetime import date, timedelta

        mock_weather = MagicMock()
        mock_weather.get_days.return_value = [
            WeatherForecast(
                date=date.today(),
                temp_min=8.0,
                temp_max=16.0,
                precipitation_mm=0.0,
                precipitation_probability=5,
                weather_code=0,
                description="Klar",
                city="Berlin",
            ),
            WeatherForecast(
                date=date.today() + timedelta(days=1),
                temp_min=10.0,
                temp_max=18.0,
                precipitation_mm=1.5,
                precipitation_probability=30,
                weather_code=61,
                description="Leichter Regen",
                city="Berlin",
            ),
        ]
        mock_weather.format_forecast.return_value = "📅 Morgen: 10–18°C"

        handler = RemoteCommandHandler(weather=mock_weather)
        result = handler.execute("wetter", "wetter morgen")

        assert result.success is True
        mock_weather.get_days.assert_called_once_with(2)
        # format_forecast mit nur dem zweiten Tag aufgerufen
        args = mock_weather.format_forecast.call_args[0][0]
        assert len(args) == 1

    def test_execute_woche(self):
        mock_weather = MagicMock()
        mock_weather.get_days.return_value = [MagicMock()] * 7
        mock_weather.format_forecast.return_value = "7-Tage-Prognose"

        handler = RemoteCommandHandler(weather=mock_weather)
        result = handler.execute("wetter", "wetter woche")

        assert result.success is True
        mock_weather.get_days.assert_called_once_with(7)


# ---------------------------------------------------------------------------
# Timer & Erinnerungen
# ---------------------------------------------------------------------------


class TestTimerParse:
    """Parse-Tests für Timer/Erinnerung-Commands."""

    def test_parse_timer_20_min(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("timer 20 min") == "timer"

    def test_parse_timer_1_stunde(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("timer 1 stunde") == "timer"

    def test_parse_timer_90_sek(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("timer 90 sek") == "timer"

    def test_parse_erinnere_mich_um(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("erinnere mich um 18:00: Wäsche") == "reminder"

    def test_parse_erinnere_mich_in(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("erinnere mich in 2 stunden: Kuchen") == "reminder"

    def test_parse_erinnerungen(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("erinnerungen") == "erinnerungen"

    def test_parse_loesche_erinnerung(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("lösche erinnerung 3") == "reminder_delete"

    def test_parse_loesche_alle_erinnerungen(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("lösche alle erinnerungen") == "reminder_delete"

    def test_keyword_offene_timer(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("zeig mir offene timer") == "erinnerungen"


class TestTimerExecute:
    """Execute-Tests für Timer/Erinnerung-Commands."""

    def test_timer_no_store(self):
        handler = RemoteCommandHandler()
        result = handler.execute("timer", "timer 20 min")
        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_timer_success(self, tmp_path):
        from elder_berry.tools.reminder_store import ReminderStore

        store = ReminderStore(db_path=tmp_path / "test.db")

        handler = RemoteCommandHandler(reminder_store=store)
        result = handler.execute("timer", "timer 20 min")

        assert result.success is True
        assert "Timer gesetzt" in result.text
        assert "20" in result.text

        # Erinnerung in DB angelegt
        pending = store.get_pending()
        assert len(pending) == 1
        store.close()

    def test_erinnerungen_empty(self, tmp_path):
        from elder_berry.tools.reminder_store import ReminderStore

        store = ReminderStore(db_path=tmp_path / "test.db")

        handler = RemoteCommandHandler(reminder_store=store)
        result = handler.execute("erinnerungen", "erinnerungen")

        assert result.success is True
        assert "Keine offenen" in result.text
        store.close()

    def test_erinnerungen_with_entries(self, tmp_path):
        from elder_berry.tools.reminder_store import ReminderStore
        from datetime import datetime, timezone, timedelta

        store = ReminderStore(db_path=tmp_path / "test.db")
        store.add(
            "_timer_user", "Wäsche", datetime.now(timezone.utc) + timedelta(hours=1)
        )

        handler = RemoteCommandHandler(reminder_store=store)
        result = handler.execute("erinnerungen", "erinnerungen")

        assert result.success is True
        assert "Wäsche" in result.text
        store.close()

    def test_reminder_delete_all_asks_confirmation(self, tmp_path):
        from elder_berry.tools.reminder_store import ReminderStore
        from datetime import datetime, timezone, timedelta

        store = ReminderStore(db_path=tmp_path / "test.db")
        store.add(
            "_timer_user", "Eins", datetime.now(timezone.utc) + timedelta(hours=1)
        )
        store.add(
            "_timer_user", "Zwei", datetime.now(timezone.utc) + timedelta(hours=2)
        )

        handler = RemoteCommandHandler(reminder_store=store)
        result = handler.execute("reminder_delete", "lösche alle erinnerungen")

        assert result.success is True
        assert result.pending_confirmation is True
        assert result.pending_data["action_type"] == "bulk_delete_reminders"
        # Erinnerungen noch da – erst nach Bestätigung löschen
        assert len(store.get_pending()) == 2
        store.close()


# ---------------------------------------------------------------------------
# Briefing-Commands
# ---------------------------------------------------------------------------


class TestBriefingParse:
    def test_parse_briefing(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("briefing") == "briefing"

    def test_keyword_guten_morgen(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("guten morgen!") == "briefing"

    def test_keyword_was_steht_heute_an(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("was steht heute an?") == "briefing"


class TestBriefingExecute:
    def test_no_scheduler(self):
        handler = RemoteCommandHandler()
        result = handler.execute("briefing", "briefing")
        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_with_scheduler(self):
        mock_scheduler = MagicMock()
        mock_scheduler.build_briefing.return_value = "☀️ Guten Morgen! Dein Briefing..."

        handler = RemoteCommandHandler(briefing_scheduler=mock_scheduler)
        result = handler.execute("briefing", "briefing")

        assert result.success is True
        assert "Guten Morgen" in result.text
        mock_scheduler.build_briefing.assert_called_once()

    def test_empty_briefing(self):
        mock_scheduler = MagicMock()
        mock_scheduler.build_briefing.return_value = ""

        handler = RemoteCommandHandler(briefing_scheduler=mock_scheduler)
        result = handler.execute("briefing", "briefing")

        assert result.success is True
        assert "keine Daten" in result.text.lower() or "Kein Briefing" in result.text


# ---------------------------------------------------------------------------
# Mail per ID
# ---------------------------------------------------------------------------


class TestMailByIdParse:
    def test_parse_mail_99(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("mail 99") == "mail_by_id"

    def test_parse_mail_hash_99(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("mail #99") == "mail_by_id"

    def test_parse_fasse_mail_zusammen(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("fasse mail #99 zusammen") == "mail_by_id"

    def test_parse_zeig_mail(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("zeig mail 42") == "mail_by_id"

    def test_parse_lies_mail(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("lies mail #5") == "mail_by_id"

    def test_not_mail_suche(self):
        """'mail suche X' darf NICHT als mail_by_id erkannt werden."""
        handler = RemoteCommandHandler()
        assert handler.parse_command("mail suche Rechnung") != "mail_by_id"


class TestMailByIdExecute:
    def test_no_client(self):
        handler = RemoteCommandHandler()
        result = handler.execute("mail_by_id", "mail 99")
        assert result.success is False
        assert "nicht konfiguriert" in result.text

    def test_mail_found(self):
        from elder_berry.tools.email_client import EmailMessage
        from datetime import datetime

        mock_email = MagicMock()
        mock_email.get_by_uid.return_value = EmailMessage(
            subject="Starlink Lieferung",
            sender="starlink@spacex.com",
            date=datetime(2026, 3, 17, 3, 26),
            body_preview="Ihre Starlink Bestellung ist auf dem Weg...",
            is_unread=True,
            msg_id="99",
        )

        handler = RemoteCommandHandler(email_client=mock_email)
        result = handler.execute("mail_by_id", "mail #99")

        assert result.success is True
        assert "Starlink" in result.text
        assert result.history_text is not None
        assert "auf dem Weg" in result.history_text
        mock_email.get_by_uid.assert_called_once_with("99")

    def test_mail_not_found(self):
        mock_email = MagicMock()
        mock_email.get_by_uid.return_value = None

        handler = RemoteCommandHandler(email_client=mock_email)
        result = handler.execute("mail_by_id", "mail #999")

        assert result.success is False
        assert "nicht gefunden" in result.text


# ---------------------------------------------------------------------------
# Dokument-Zusammenfassung (Phase 11)
# ---------------------------------------------------------------------------


class TestDocumentSummaryPattern:
    """Regex-Pattern für Dokument-Zusammenfassung."""

    def test_zusammenfassung_windows_path(self):
        m = DOCUMENT_SUMMARY_PATTERN.search(r"zusammenfassung C:\Docs\report.pdf")
        assert m is not None
        assert m.group(1) == r"C:\Docs\report.pdf"

    def test_fasse_zusammen_windows_path(self):
        m = DOCUMENT_SUMMARY_PATTERN.search(r"fasse zusammen C:\Users\test\file.txt")
        assert m is not None
        assert m.group(1) == r"C:\Users\test\file.txt"

    def test_fasse_path_zusammen(self):
        m = DOCUMENT_SUMMARY_PATTERN.search(r"fasse C:\Docs\report.pdf zusammen")
        assert m is not None
        assert m.group(2) == r"C:\Docs\report.pdf"

    def test_linux_path(self):
        m = DOCUMENT_SUMMARY_PATTERN.search("zusammenfassung /home/pi/doc.pdf")
        assert m is not None
        assert m.group(1) == "/home/pi/doc.pdf"

    def test_no_match_without_path(self):
        m = DOCUMENT_SUMMARY_PATTERN.search("zusammenfassung")
        assert m is None


class TestDocumentSummaryParseCommand:
    """parse_command erkennt Dokument-Zusammenfassung."""

    def test_zusammenfassung_recognized(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command(r"zusammenfassung C:\test.pdf") == "document_summary"
        )

    def test_fasse_zusammen_recognized(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command(r"fasse zusammen C:\test.txt") == "document_summary"
        )

    def test_fasse_path_zusammen_recognized(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command(r"fasse C:\test.pdf zusammen") == "document_summary"
        )

    def test_keyword_map_match(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("fasse die pdf zusammen") == "document_summary"


class TestDocumentSummaryExecute:
    """execute() für Dokument-Zusammenfassung."""

    def test_no_reader(self):
        handler = RemoteCommandHandler()
        result = handler.execute("document_summary", r"zusammenfassung C:\test.pdf")
        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_success(self, tmp_path):
        from elder_berry.tools.document_reader import DocumentReader

        f = tmp_path / "notes.txt"
        f.write_text("Wichtiger Inhalt hier.", encoding="utf-8")

        reader = DocumentReader()
        handler = RemoteCommandHandler(document_reader=reader)
        result = handler.execute("document_summary", f"zusammenfassung {f}")

        assert result.success is True
        # text enthält nur den Header (Bridge schickt history_text ans LLM)
        assert "notes.txt" in result.text
        assert result.history_text is not None
        assert "Wichtiger Inhalt" in result.history_text

    def test_file_not_found(self):
        from elder_berry.tools.document_reader import DocumentReader

        reader = DocumentReader()
        handler = RemoteCommandHandler(document_reader=reader)
        result = handler.execute(
            "document_summary",
            r"zusammenfassung C:\nope\missing.pdf",
        )
        assert result.success is False
        assert "nicht gefunden" in result.text

    def test_unsupported_format(self, tmp_path):
        from elder_berry.tools.document_reader import DocumentReader

        f = tmp_path / "data.xlsx"
        f.write_bytes(b"fake")

        reader = DocumentReader()
        handler = RemoteCommandHandler(document_reader=reader)
        result = handler.execute("document_summary", f"zusammenfassung {f}")

        assert result.success is False
        assert "nicht unterstützt" in result.text

    def test_pdf_success(self, tmp_path):
        pytest.importorskip("fitz")
        import fitz

        from elder_berry.tools.document_reader import DocumentReader

        pdf_path = tmp_path / "report.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Quartalsbericht Q1 2026")
        doc.save(str(pdf_path))
        doc.close()

        reader = DocumentReader()
        handler = RemoteCommandHandler(document_reader=reader)
        result = handler.execute("document_summary", f"zusammenfassung {pdf_path}")

        assert result.success is True
        assert "1 Seite" in result.text
        assert "Quartalsbericht" in result.history_text


# ────────────────────────────────────────────────────────────────
# Audio-Command (Phase 12)
# ────────────────────────────────────────────────────────────────


class TestAudioLocalPattern:
    """AUDIO_LOCAL_PATTERN Regex."""

    def test_audio_lokal_an(self):
        assert AUDIO_LOCAL_PATTERN.match("audio lokal an")

    def test_audio_lokal_aus(self):
        assert AUDIO_LOCAL_PATTERN.match("audio lokal aus")

    def test_audio_lokal_ein(self):
        assert AUDIO_LOCAL_PATTERN.match("audio lokal ein")

    def test_audio_lokal_on(self):
        assert AUDIO_LOCAL_PATTERN.match("audio lokal on")

    def test_audio_lokal_off(self):
        assert AUDIO_LOCAL_PATTERN.match("audio lokal off")

    def test_audio_alone_no_match(self):
        assert AUDIO_LOCAL_PATTERN.match("audio") is None

    def test_audio_irgendwas_no_match(self):
        assert AUDIO_LOCAL_PATTERN.match("audio foobar") is None


class TestAudioParseCommand:
    """parse_command() erkennt Audio-Commands."""

    def test_audio_simple(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("audio") == "audio"

    def test_audio_lokal_an(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("audio lokal an") == "audio_toggle"

    def test_audio_lokal_aus(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("audio lokal aus") == "audio_toggle"


class TestAudioExecute:
    """execute() für Audio-Command."""

    def test_audio_status_no_router(self):
        handler = RemoteCommandHandler()
        result = handler.execute("audio", "audio")
        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_audio_status_with_router(self):
        from elder_berry.core.audio_router import AudioRouter

        router = AudioRouter(local_available=True)
        handler = RemoteCommandHandler(audio_router=router)
        result = handler.execute("audio", "audio")
        assert result.success is True
        assert "matrix_only" in result.text

    def test_audio_lokal_an(self):
        from elder_berry.core.audio_router import AudioOutputMode, AudioRouter

        router = AudioRouter(local_available=True)
        handler = RemoteCommandHandler(audio_router=router)
        result = handler.execute("audio_toggle", "audio lokal an")
        assert result.success is True
        assert "Lokal" in result.text
        assert router.mode == AudioOutputMode.MATRIX_AND_LOCAL

    def test_audio_lokal_aus(self):
        from elder_berry.core.audio_router import AudioOutputMode, AudioRouter

        router = AudioRouter(
            default_mode=AudioOutputMode.MATRIX_AND_LOCAL,
            local_available=True,
        )
        handler = RemoteCommandHandler(audio_router=router)
        result = handler.execute("audio_toggle", "audio lokal aus")
        assert result.success is True
        assert "Matrix" in result.text
        assert router.mode == AudioOutputMode.MATRIX_ONLY

    def test_audio_lokal_an_no_capability(self):
        from elder_berry.core.audio_router import AudioOutputMode, AudioRouter

        router = AudioRouter(local_available=False)
        handler = RemoteCommandHandler(audio_router=router)
        result = handler.execute("audio_toggle", "audio lokal an")
        assert result.success is True
        # Modus bleibt matrix_only
        assert router.mode == AudioOutputMode.MATRIX_ONLY


# ===========================================================================
# Computer Use – Pattern, Parse, Execute
# ===========================================================================


class TestComputerUsePattern:
    """Tests für COMPUTER_USE_PATTERN."""

    def test_klick_auf(self):
        from elder_berry.comms.commands.advanced_commands import COMPUTER_USE_PATTERN

        assert COMPUTER_USE_PATTERN.match("klick auf den OK-Button")

    def test_klicke_auf(self):
        from elder_berry.comms.commands.advanced_commands import COMPUTER_USE_PATTERN

        assert COMPUTER_USE_PATTERN.match("klicke auf das Suchfeld")

    def test_tippe(self):
        from elder_berry.comms.commands.advanced_commands import COMPUTER_USE_PATTERN

        assert COMPUTER_USE_PATTERN.match("tippe Hello World")

    def test_scroll_runter(self):
        from elder_berry.comms.commands.advanced_commands import COMPUTER_USE_PATTERN

        assert COMPUTER_USE_PATTERN.match("scroll runter")

    def test_scroll_hoch(self):
        from elder_berry.comms.commands.advanced_commands import COMPUTER_USE_PATTERN

        assert COMPUTER_USE_PATTERN.match("scroll hoch")

    def test_drueck(self):
        from elder_berry.comms.commands.advanced_commands import COMPUTER_USE_PATTERN

        assert COMPUTER_USE_PATTERN.match("drück Strg+S")

    def test_druecke(self):
        from elder_berry.comms.commands.advanced_commands import COMPUTER_USE_PATTERN

        assert COMPUTER_USE_PATTERN.match("drücke Enter")

    def test_klick_mal_auf(self):
        from elder_berry.comms.commands.advanced_commands import COMPUTER_USE_PATTERN

        assert COMPUTER_USE_PATTERN.match("klick mal auf das X oben rechts")

    def test_auf_element_klicken(self):
        from elder_berry.comms.commands.advanced_commands import COMPUTER_USE_PATTERN

        assert COMPUTER_USE_PATTERN.match("auf accept klicken")

    def test_no_match_random(self):
        from elder_berry.comms.commands.advanced_commands import COMPUTER_USE_PATTERN

        assert COMPUTER_USE_PATTERN.match("hallo wie geht es dir") is None


class TestComputerUseParseCommand:
    """Tests für parse_command mit Computer-Use-Anweisungen."""

    def test_klick_auf(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("klick auf den OK-Button") == "computer_use"

    def test_tippe(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("tippe Hello World") == "computer_use"

    def test_scroll_runter(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("scroll runter") == "computer_use"

    def test_drueck(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("drück Strg+S") == "computer_use"

    def test_keyword_klick_auf_in_sentence(self):
        handler = RemoteCommandHandler()
        # "klick auf" als Keyword im Satz → "computer_use"
        assert (
            handler.parse_command("bitte klick auf den Discord Button")
            == "computer_use"
        )

    def test_klick_mal_auf(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command("klick mal auf das X oben rechts") == "computer_use"
        )

    def test_kannst_du_auf_klicken(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("kannst du auf accept klicken") == "computer_use"

    def test_auf_element_klicken(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("auf accept klicken") == "computer_use"


class TestComputerUseExecute:
    """Tests für execute('computer_use', ...)."""

    def test_no_controller(self):
        handler = RemoteCommandHandler()
        result = handler.execute("computer_use", "klick auf OK")
        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_successful_execution(self):
        from unittest.mock import MagicMock
        from elder_berry.llm.anthropic_client import ComputerUseAction
        from elder_berry.actions.computer_use import ComputerUseResult

        mock_cu = MagicMock()
        mock_cu.execute_instruction.return_value = ComputerUseResult(
            action=ComputerUseAction(action="left_click", coordinate=(500, 300)),
            success=True,
            message="Aktion ausgeführt: left_click bei (500, 300)",
            verification_image_path=None,
        )
        handler = RemoteCommandHandler(computer_use=mock_cu)
        result = handler.execute("computer_use", "klick auf den Button")
        assert result.success is True
        assert "Aktion ausgeführt" in result.text
        mock_cu.execute_instruction.assert_called_once_with("klick auf den Button")

    def test_execution_error(self):
        from unittest.mock import MagicMock

        mock_cu = MagicMock()
        mock_cu.execute_instruction.side_effect = RuntimeError("Boom")
        handler = RemoteCommandHandler(computer_use=mock_cu)
        result = handler.execute("computer_use", "klick auf OK")
        assert result.success is False
        assert "❌" in result.text

    def test_with_verification_image(self, tmp_path):
        from unittest.mock import MagicMock
        from elder_berry.llm.anthropic_client import ComputerUseAction
        from elder_berry.actions.computer_use import ComputerUseResult

        img = tmp_path / "verify.png"
        img.write_bytes(b"\x89PNG")

        mock_cu = MagicMock()
        mock_cu.execute_instruction.return_value = ComputerUseResult(
            action=ComputerUseAction(action="left_click", coordinate=(100, 200)),
            success=True,
            message="OK",
            verification_image_path=img,
        )
        handler = RemoteCommandHandler(computer_use=mock_cu)
        result = handler.execute("computer_use", "klick auf X")
        assert result.success is True
        assert result.image_path == img


# ---------------------------------------------------------------------------
# Web-Suche (Brave Search)
# ---------------------------------------------------------------------------


class TestWebSearchPattern:
    """WEB_SEARCH_PATTERN Regex Tests."""

    def test_suche_basic(self):
        from elder_berry.comms.commands.advanced_commands import WEB_SEARCH_PATTERN

        m = WEB_SEARCH_PATTERN.match("suche Dachdecker Plattenburg")
        assert m
        assert m.group(1) == "Dachdecker Plattenburg"

    def test_such_mal(self):
        from elder_berry.comms.commands.advanced_commands import WEB_SEARCH_PATTERN

        m = WEB_SEARCH_PATTERN.match("such mal Python Tutorial")
        assert m
        assert m.group(1) == "Python Tutorial"

    def test_google(self):
        from elder_berry.comms.commands.advanced_commands import WEB_SEARCH_PATTERN

        m = WEB_SEARCH_PATTERN.match("google Rezept Lasagne")
        assert m
        assert m.group(1) == "Rezept Lasagne"

    def test_finde(self):
        from elder_berry.comms.commands.advanced_commands import WEB_SEARCH_PATTERN

        m = WEB_SEARCH_PATTERN.match("finde Dachdecker in der Nähe")
        assert m
        assert m.group(1) == "Dachdecker in der Nähe"

    def test_no_match_empty(self):
        from elder_berry.comms.commands.advanced_commands import WEB_SEARCH_PATTERN

        assert WEB_SEARCH_PATTERN.match("suche") is None

    def test_case_insensitive(self):
        from elder_berry.comms.commands.advanced_commands import WEB_SEARCH_PATTERN

        m = WEB_SEARCH_PATTERN.match("SUCHE Test")
        assert m
        assert m.group(1) == "Test"


class TestWebSearchParseCommand:
    """parse_command() erkennt Web-Suche."""

    def test_suche_recognized(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("suche Dachdecker Plattenburg") == "web_search"

    def test_google_recognized(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("google Python Tutorial") == "web_search"

    def test_such_mal_recognized(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("such mal Rezept") == "web_search"

    def test_keyword_such_mir(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("such mir bitte ein gutes Rezept") == "web_search"

    def test_keyword_google_mal(self):
        handler = RemoteCommandHandler()
        assert (
            handler.parse_command("google mal wie das Wetter in Berlin ist")
            == "web_search"
        )

    def test_mail_suche_has_priority(self):
        """Mail-Suche hat Vorrang vor Web-Suche."""
        handler = RemoteCommandHandler()
        result = handler.parse_command("mail suche Rechnung")
        assert result == "mail_search"

    def test_termin_suche_has_priority(self):
        """Termin-Suche hat Vorrang vor Web-Suche."""
        handler = RemoteCommandHandler()
        result = handler.parse_command("termin suche Zahnarzt")
        assert result == "termin_search"


class TestWebSearchExecute:
    """Tests für execute('web_search', ...)."""

    def test_no_client(self):
        handler = RemoteCommandHandler()
        result = handler.execute("web_search", "suche Test")
        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_successful_search(self):
        from unittest.mock import MagicMock
        from elder_berry.tools.brave_search_client import SearchResult

        mock_client = MagicMock()
        mock_client.search.return_value = [
            SearchResult("Ergebnis 1", "https://eins.de", "Beschreibung 1"),
            SearchResult("Ergebnis 2", "https://zwei.de", "Beschreibung 2"),
        ]
        mock_client.format_results.return_value = "Formatierter Text"
        mock_client.format_results_detailed.return_value = "Detaillierter Text"

        handler = RemoteCommandHandler(search_client=mock_client)
        result = handler.execute("web_search", "suche Dachdecker")

        assert result.success is True
        assert result.text == "Formatierter Text"
        assert result.history_text == "Detaillierter Text"
        mock_client.search.assert_called_once_with("Dachdecker")

    def test_search_error(self):
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.search.side_effect = RuntimeError("API Error")

        handler = RemoteCommandHandler(search_client=mock_client)
        result = handler.execute("web_search", "suche Test")

        assert result.success is False
        assert "❌" in result.text

    def test_empty_query_not_parsed(self):
        """'suche ' (ohne Suchbegriff) wird nicht als Command erkannt."""
        handler = RemoteCommandHandler()
        assert handler.parse_command("suche ") is None

    def test_empty_query_via_execute(self):
        """Leerer Query bei execute → Fehler."""
        from unittest.mock import MagicMock

        mock_client = MagicMock()

        handler = RemoteCommandHandler(search_client=mock_client)
        # Direkt execute mit leerem Text (Fallback-Pfad)
        result = handler.execute("web_search", "  ")

        assert result.success is False
        assert "Suchbegriff" in result.text

    def test_keyword_match_extracts_query(self):
        """Bei Keyword-Match wird der Suchbegriff über Prefix-Entfernung extrahiert."""
        from unittest.mock import MagicMock
        from elder_berry.tools.brave_search_client import SearchResult

        mock_client = MagicMock()
        mock_client.search.return_value = [
            SearchResult("Test", "https://test.de", "Desc"),
        ]
        mock_client.format_results.return_value = "OK"
        mock_client.format_results_detailed.return_value = "Detail"

        handler = RemoteCommandHandler(search_client=mock_client)
        # "recherchiere Dachdecker" wird per Keyword-Map erkannt,
        # dann im Handler per Prefix "recherchiere" entfernt
        result = handler.execute("web_search", "recherchiere Dachdecker in Berlin")

        assert result.success is True
        mock_client.search.assert_called_once_with("Dachdecker in Berlin")


# ---------------------------------------------------------------------------
# Phase 92: get_handler-Lookup
# ---------------------------------------------------------------------------


class TestGetHandler:
    def test_returns_handler_by_plugin_name(self) -> None:
        handler = RemoteCommandHandler()
        # weather ist gracefully ohne weather_client; landet trotzdem
        # in _handlers (immer-aktiv-Plugin) und via setattr(_weather, ...).
        h = handler.get_handler("weather")
        assert h is not None
        # type-check fuer die Convention: was setattr setzt, ist auch ein Handler.
        from elder_berry.comms.commands.base import CommandHandler

        assert isinstance(h, CommandHandler)

    def test_returns_none_for_unknown_plugin(self) -> None:
        handler = RemoteCommandHandler()
        assert handler.get_handler("does_not_exist") is None

    def test_returns_none_when_attr_is_not_a_handler(self) -> None:
        handler = RemoteCommandHandler()
        # Conditional plugin ohne Service: setattr legt None ab,
        # also setattr(self, '_route', None) -- get_handler liefert None.
        # route haengt am route_planner; ohne den wird der Handler nicht
        # erzeugt (CommandPlugin.factory liefert None).
        assert handler.get_handler("route") is None
