"""Tests: SelfcheckCommandHandler – Systemgesundheitsprüfung."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.selfcheck_commands import (
    SELFCHECK_PATTERN,
    SelfcheckCommandHandler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def secret_store():
    store = MagicMock()
    store.list_keys.return_value = ["key1", "key2"]
    return store


@pytest.fixture
def handler(tmp_path, secret_store):
    return SelfcheckCommandHandler(
        project_root=tmp_path,
        secret_store=secret_store,
    )


@pytest.fixture
def handler_minimal():
    return SelfcheckCommandHandler(project_root=None, secret_store=None)


# ---------------------------------------------------------------------------
# Pattern Tests
# ---------------------------------------------------------------------------

class TestSelfcheckPattern:
    @pytest.mark.parametrize("text", [
        "selfcheck", "self check", "system check", "systemcheck",
        "prüf dich", "prüfdich", "alles ok?", "alles ok",
        "gesundheitscheck",
    ])
    def test_valid_patterns(self, text):
        assert SELFCHECK_PATTERN.match(text) is not None

    @pytest.mark.parametrize("text", [
        "selfcheck bitte", "mach self check", "status",
    ])
    def test_invalid_patterns(self, text):
        assert SELFCHECK_PATTERN.match(text) is None


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class TestSelfcheckInterface:
    def test_simple_commands(self, handler):
        assert "selfcheck" in handler.simple_commands

    def test_keywords(self, handler):
        kw = handler.keywords
        assert "selfcheck" in kw
        assert len(kw["selfcheck"]) > 0

    def test_command_descriptions(self, handler):
        descs = handler.command_descriptions
        assert any("selfcheck" in d.lower() or "gesundheit" in d.lower() for d in descs)


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

class TestSelfcheckExecute:
    def test_unknown_command(self, handler):
        result = handler.execute("unknown", "unknown")
        assert result.success is False

    @patch("elder_berry.comms.commands.selfcheck_commands.run_cmd")
    @patch("shutil.disk_usage")
    def test_selfcheck_happy_path(self, mock_disk, mock_run_cmd, handler):
        """Selfcheck mit allen Prüfungen (Git, Disk, etc.)."""
        from elder_berry.comms.commands.cmd_utils import CmdResult

        # Git-Commands mocken
        mock_run_cmd.side_effect = [
            CmdResult(success=True, output="main"),       # branch
            CmdResult(success=True, output=""),            # status (clean)
            CmdResult(success=True, output=""),            # fetch
            CmdResult(success=True, output="0"),           # behind
            CmdResult(success=True, output="No broken"),   # pip check
        ]

        # Disk
        mock_disk.return_value = MagicMock(
            total=500 * 1024**3, used=200 * 1024**3, free=300 * 1024**3,
        )

        result = handler.execute("selfcheck", "selfcheck")
        assert result.success is True
        assert "Systemcheck" in result.text
        assert "Git" in result.text
        assert "Python" in result.text

    @patch("elder_berry.comms.commands.selfcheck_commands.run_cmd")
    @patch("shutil.disk_usage")
    def test_selfcheck_with_warnings(self, mock_disk, mock_run_cmd, handler):
        """Selfcheck mit uncommitted changes → Warnung."""
        from elder_berry.comms.commands.cmd_utils import CmdResult

        mock_run_cmd.side_effect = [
            CmdResult(success=True, output="main"),
            CmdResult(success=True, output="M file.py"),  # dirty
            CmdResult(success=True, output=""),
            CmdResult(success=True, output="3"),           # behind
            CmdResult(success=True, output="No broken"),
        ]

        mock_disk.return_value = MagicMock(
            total=500 * 1024**3, used=200 * 1024**3, free=300 * 1024**3,
        )

        result = handler.execute("selfcheck", "selfcheck")
        assert "Warnung" in result.text or "⚠️" in result.text

    @patch("shutil.disk_usage")
    def test_selfcheck_no_project_root(self, mock_disk, handler_minimal):
        """Selfcheck ohne project_root → Git-Warnung."""
        mock_disk.return_value = MagicMock(
            total=500 * 1024**3, used=200 * 1024**3, free=300 * 1024**3,
        )
        result = handler_minimal.execute("selfcheck", "selfcheck")
        assert "Systemcheck" in result.text
        assert "nicht konfiguriert" in result.text
