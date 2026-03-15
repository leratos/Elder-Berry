"""Tests: RemoteCommandHandler – Direkte Befehle via Matrix."""
import asyncio
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.remote_commands import (
    AVATAR_EMOTION_PATTERN,
    AVATAR_EMOTIONS,
    CLIP_WRITE_PATTERN,
    DOCKER_PATTERN,
    DOWNLOAD_PATTERN,
    GIT_PATTERN,
    KILL_PROCESS_PATTERN,
    KILL_WHITELIST,
    MAX_FILE_SIZE_BYTES,
    MEDIA_KEYS,
    SEND_FILE_PATTERN,
    START_PROCESS_PATTERN,
    START_WHITELIST,
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
            command="screenshot", success=True,
            text="Screenshot aufgenommen.", image_path=Path("/tmp/screen.png"),
        )
        assert result.image_path == Path("/tmp/screen.png")

    def test_defaults(self):
        result = CommandResult(command="x", success=False)
        assert result.text is None
        assert result.image_path is None
        assert result.file_path is None

    def test_creation_with_file(self):
        result = CommandResult(
            command="send_file", success=True,
            text="Datei wird gesendet.", file_path=Path("/tmp/datei.pdf"),
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
        assert handler.parse_command("download https://example.com/file.zip") == "download"
        assert handler.parse_command("download http://example.com/data.csv") == "download"

    def test_download_no_url(self):
        handler = RemoteCommandHandler()
        assert handler.parse_command("download") is None
        assert handler.parse_command("download ftp://bad.com") is None

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
            result = handler._cmd_clipboard_read()

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
            result = handler._cmd_clipboard_read()

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
            result = handler._cmd_clipboard_read()

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
            result = handler._cmd_clipboard_write("clip: Hallo Welt")

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
            result = handler._cmd_clipboard_write("clip: some text")

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
            result = handler._cmd_clipboard_write("clip some text")

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
            result = handler._cmd_clipboard_write("clip: text")

        assert result.success is False
        assert "pyperclip" in result.text


# ---------------------------------------------------------------------------
# execute: send_file
# ---------------------------------------------------------------------------

class TestCmdSendFile:
    def test_send_file_success(self, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"PDF content " * 100)

        handler = RemoteCommandHandler()
        result = handler.execute("send_file", f"schick mir {test_file}")

        assert result.success is True
        assert result.file_path == test_file
        assert "test.pdf" in result.text

    def test_send_file_not_found(self):
        handler = RemoteCommandHandler()
        result = handler.execute("send_file", "schick mir C:\\nonexistent\\file.pdf")

        assert result.success is False
        assert "nicht gefunden" in result.text

    def test_send_file_too_large(self, tmp_path):
        test_file = tmp_path / "large.bin"
        # Erstelle eine Datei knapp über dem Limit
        test_file.write_bytes(b"\x00" * (MAX_FILE_SIZE_BYTES + 1))

        handler = RemoteCommandHandler()
        result = handler.execute("send_file", f"schick mir {test_file}")

        assert result.success is False
        assert "zu groß" in result.text

    def test_send_file_directory(self, tmp_path):
        handler = RemoteCommandHandler()
        result = handler.execute("send_file", f"schick mir {tmp_path}")

        assert result.success is False
        assert "keine Datei" in result.text

    def test_send_file_no_path(self):
        handler = RemoteCommandHandler()
        result = handler.execute("send_file", "schick mir bitte irgendwas")

        assert result.success is False
        assert "nicht erkannt" in result.text


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
        assert "nicht gefunden" in result.text.lower() or "kein laufender" in result.text.lower()

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
            result = handler.execute("download", "download https://example.com/file.zip")

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
            result = handler.execute("download", "download https://example.com/large.bin")

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
        assert "fehlgeschlagen" in result.text

    def test_selfie_alias(self):
        mock_renderer = MagicMock()
        mock_renderer.render_to_file.return_value = Path("/tmp/test.png")

        handler = RemoteCommandHandler(avatar_renderer=mock_renderer)
        result = handler.execute("selfie", "selfie")

        assert result.success is True
