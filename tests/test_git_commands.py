"""Tests: GitCommandHandler – Git-Befehle via Matrix (Whitelist)."""
from unittest.mock import MagicMock, patch
import subprocess

import pytest

from elder_berry.comms.commands.git_commands import (
    GIT_PATTERN,
    GitCommandHandler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def handler(tmp_path):
    return GitCommandHandler(project_root=tmp_path)


@pytest.fixture
def handler_no_root():
    return GitCommandHandler(project_root=None)


# ---------------------------------------------------------------------------
# Pattern Tests
# ---------------------------------------------------------------------------

class TestGitPattern:
    @pytest.mark.parametrize("text,subcmd", [
        ("git status", "status"),
        ("git pull", "pull"),
        ("git log", "log"),
        ("git diff", "diff"),
        ("GIT STATUS", "STATUS"),
        ("git log --all", "log"),
    ])
    def test_valid_patterns(self, text, subcmd):
        m = GIT_PATTERN.match(text)
        assert m is not None
        assert m.group(1).lower() == subcmd.lower()

    @pytest.mark.parametrize("text", [
        "git push",
        "git commit -m 'test'",
        "git reset --hard",
        "git checkout main",
        "notgit status",
    ])
    def test_invalid_patterns(self, text):
        m = GIT_PATTERN.match(text)
        assert m is None


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class TestGitInterface:
    def test_patterns_registered(self, handler):
        assert len(handler.patterns) == 1
        assert handler.patterns[0][1] == "git"

    def test_command_descriptions(self, handler):
        descs = handler.command_descriptions
        assert len(descs) > 0
        assert any("git" in d.lower() for d in descs)


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

class TestGitExecute:
    def test_unknown_command(self, handler):
        result = handler.execute("unknown", "unknown")
        assert result.success is False

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_git_status(self, mock_run, handler):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="On branch main\nnothing to commit", stderr="",
        )
        result = handler.execute("git", "git status")
        assert result.success is True
        assert "git status" in result.text
        assert "On branch main" in result.text

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_git_pull(self, mock_run, handler):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Already up to date.", stderr="",
        )
        result = handler.execute("git", "git pull")
        assert result.success is True

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_git_log_adds_flags(self, mock_run, handler):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="abc1234 commit msg", stderr="",
        )
        result = handler.execute("git", "git log")
        assert result.success is True
        cmd = mock_run.call_args[0][0]
        assert "--oneline" in cmd
        assert "-20" in cmd

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_git_diff(self, mock_run, handler):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="diff output", stderr="",
        )
        result = handler.execute("git", "git diff")
        assert result.success is True

    def test_invalid_format(self, handler):
        result = handler.execute("git", "git push origin main")
        assert result.success is False
        assert "Erlaubt" in result.text

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_output_truncated(self, mock_run, handler):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="x" * 5000, stderr="",
        )
        result = handler.execute("git", "git status")
        assert "gekürzt" in result.text
        assert len(result.text) < 5500

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_git_not_found(self, mock_run, handler):
        mock_run.side_effect = FileNotFoundError()
        result = handler.execute("git", "git status")
        assert result.success is False
        assert "nicht gefunden" in result.text.lower()

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_timeout(self, mock_run, handler):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=30)
        result = handler.execute("git", "git status")
        assert result.success is False
        assert "Timeout" in result.text

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_generic_error(self, mock_run, handler):
        mock_run.side_effect = OSError("permission denied")
        result = handler.execute("git", "git status")
        assert result.success is False
        assert "❌" in result.text and "Git" in result.text
