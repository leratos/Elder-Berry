"""Tests: ProcessCommandHandler – Prozess-Start/Kill (Whitelist)."""
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.process_commands import (
    START_PROCESS_PATTERN,
    KILL_PROCESS_PATTERN,
    ProcessCommandHandler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def handler():
    return ProcessCommandHandler()


# ---------------------------------------------------------------------------
# Pattern Tests
# ---------------------------------------------------------------------------

class TestStartProcessPattern:
    @pytest.mark.parametrize("text,program", [
        ("starte chrome", "chrome"),
        ("start firefox", "firefox"),
        ("öffne notepad", "notepad"),
        ("open vlc", "vlc"),
        ("Starte Chrome", "Chrome"),
    ])
    def test_valid_patterns(self, text, program):
        m = START_PROCESS_PATTERN.match(text)
        assert m is not None
        assert m.group(1) == program

    @pytest.mark.parametrize("text", [
        "starte",           # kein Programm
        "start",            # kein Programm
    ])
    def test_invalid_patterns(self, text):
        assert START_PROCESS_PATTERN.match(text) is None

    def test_multi_word_program(self):
        """Programmnamen mit Leerzeichen sollen matchen (Phase 47)."""
        m = START_PROCESS_PATTERN.match("starte Visual Studio Code")
        assert m is not None
        assert m.group(1).strip() == "Visual Studio Code"

    @pytest.mark.parametrize("text", [
        "starte tv",
        "starte fernsehen",
        "starte musik",
        "starte tv an",
        "starte dich neu",
        "starte neu",
    ])
    def test_excluded_patterns(self, text):
        """Harmony-Aktivitaeten und System-Keywords duerfen nicht matchen."""
        assert START_PROCESS_PATTERN.match(text) is None


class TestKillProcessPattern:
    @pytest.mark.parametrize("text,process", [
        ("kill blender", "blender"),
        ("beende chrome", "chrome"),
        ("stoppe vlc", "vlc"),
        ("schließe discord", "discord"),
    ])
    def test_valid_patterns(self, text, process):
        m = KILL_PROCESS_PATTERN.match(text)
        assert m is not None
        assert m.group(1) == process


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class TestProcessInterface:
    def test_patterns_registered(self, handler):
        assert len(handler.patterns) == 2
        names = {p[1] for p in handler.patterns}
        assert "start_process" in names
        assert "kill_process" in names

    def test_command_descriptions(self, handler):
        descs = handler.command_descriptions
        assert len(descs) == 2


# ---------------------------------------------------------------------------
# Start Process
# ---------------------------------------------------------------------------

class TestStartProcess:
    def test_unknown_command_routing(self, handler):
        result = handler.execute("unknown", "unknown")
        assert result.success is False

    @patch("elder_berry.comms.commands.process_commands.subprocess.Popen")
    def test_start_whitelisted(self, mock_popen, handler):
        result = handler.execute("start_process", "starte chrome")
        assert result.success is True
        assert "Gestartet" in result.text
        mock_popen.assert_called_once()

    def test_start_not_whitelisted(self, handler):
        result = handler.execute("start_process", "starte malware")
        assert result.success is False
        assert "nicht in der Start-Whitelist" in result.text

    def test_invalid_format(self, handler):
        result = handler.execute("start_process", "starte")
        assert result.success is False

    @patch("elder_berry.comms.commands.process_commands.subprocess.Popen")
    def test_start_file_not_found(self, mock_popen, handler):
        mock_popen.side_effect = FileNotFoundError()
        result = handler.execute("start_process", "starte chrome")
        assert result.success is False
        assert "nicht gefunden" in result.text.lower()

    @patch("elder_berry.comms.commands.process_commands.subprocess.Popen")
    def test_start_generic_error(self, mock_popen, handler):
        mock_popen.side_effect = OSError("access denied")
        result = handler.execute("start_process", "starte chrome")
        assert result.success is False
        assert "❌" in result.text


# ---------------------------------------------------------------------------
# Kill Process
# ---------------------------------------------------------------------------

class TestKillProcess:
    @patch("psutil.process_iter")
    def test_kill_success(self, mock_iter, handler):
        mock_proc = MagicMock()
        mock_proc.info = {"name": "blender.exe"}
        mock_iter.return_value = [mock_proc]
        result = handler.execute("kill_process", "kill blender")
        assert result.success is True
        assert "Beendet" in result.text
        mock_proc.terminate.assert_called_once()

    @patch("psutil.process_iter")
    def test_kill_no_process_found(self, mock_iter, handler):
        mock_iter.return_value = []
        result = handler.execute("kill_process", "kill blender")
        assert result.success is False
        assert "nicht gefunden" in result.text.lower() or "Kein" in result.text

    def test_kill_not_whitelisted(self, handler):
        result = handler.execute("kill_process", "kill systemd")
        assert result.success is False
        assert "nicht in der Kill-Whitelist" in result.text

    def test_kill_invalid_format(self, handler):
        result = handler.execute("kill_process", "kill")
        assert result.success is False

    @patch("psutil.process_iter")
    def test_kill_multiple_processes(self, mock_iter, handler):
        proc1 = MagicMock()
        proc1.info = {"name": "chrome.exe"}
        proc2 = MagicMock()
        proc2.info = {"name": "chrome_helper.exe"}
        mock_iter.return_value = [proc1, proc2]
        result = handler.execute("kill_process", "kill chrome")
        assert result.success is True
        assert "2 Prozesse" in result.text

    def test_kill_psutil_not_installed(self, handler):
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("no psutil")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute("kill_process", "kill blender")
            assert result.success is False
            assert "psutil" in result.text.lower()
