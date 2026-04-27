"""Tests: GitCommandHandler – Git-Befehle via Matrix (Whitelist)."""
from unittest.mock import MagicMock, patch
import subprocess

import pytest

from elder_berry.comms.commands.git_commands import (
    GIT_PATTERN,
    MAX_EXTRA_ARGS,
    GitCommandHandler,
    _validate_extra_args,
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


# ---------------------------------------------------------------------------
# Phase 65 (M-2): Whitelist fuer extra_args
# ---------------------------------------------------------------------------


class TestValidateExtraArgsLog:
    """Pure unit tests fuer _validate_extra_args mit subcmd=log."""

    @pytest.mark.parametrize("tokens", [
        [],
        ["--oneline"],
        ["--stat"],
        ["--graph"],
        ["-5"],
        ["-n", "3"],
        ["--max-count=10"],
        ["--since=yesterday"],
        ["--since=2024-01-01"],
        ["--author=user"],
        ["--author=user@example.com"],
        ["--grep=fix bug"],   # reachable via shlex: --grep="fix bug"
        ["abc1234"],
        ["deadbeef1234567890abcdef1234567890abcdef"],  # 40 hex
        ["HEAD"],
        ["HEAD~3"],
        ["HEAD~5..HEAD"],
        ["--oneline", "--graph", "-5", "--author=user"],
    ])
    def test_allowed_tokens(self, tokens):
        ok, bad = _validate_extra_args("log", tokens)
        assert ok is True, f"expected {tokens} to be allowed, got bad={bad!r}"
        assert bad is None

    @pytest.mark.parametrize("tokens,bad_index", [
        (["--output=/tmp/evil"], 0),      # Schreibzugriff
        (["-o", "file"], 0),              # kurz-Form von --output
        (["--exec=cmd.exe"], 0),          # exec-Flag
        (["|", "cat"], 0),                 # Pipe -- kann shell=False zwar nichts, aber kein Whitelist-Match
        (["&&", "ls"], 0),
        (["../../../etc/passwd"], 0),     # Pfad
        (["--no-pager"], 0),              # nicht in Whitelist
        (["-c", "core.pager=cmd"], 0),    # config-overrides
        (["$PATH"], 0),
        (["--oneline", "--exec=cmd"], 1), # zweiter Token boese
    ])
    def test_blocked_tokens(self, tokens, bad_index):
        ok, bad = _validate_extra_args("log", tokens)
        assert ok is False
        assert bad == tokens[bad_index]

    def test_too_many_args_rejected(self):
        ok, bad = _validate_extra_args(
            "log", ["--oneline"] * (MAX_EXTRA_ARGS + 1),
        )
        assert ok is False
        assert "zu viele" in bad

    def test_exactly_max_args_allowed(self):
        ok, bad = _validate_extra_args(
            "log", ["--oneline"] * MAX_EXTRA_ARGS,
        )
        assert ok is True
        assert bad is None


class TestValidateExtraArgsDiff:
    """diff hat engeren Whitelist -- keine grep/author."""

    @pytest.mark.parametrize("tokens", [
        [],
        ["--stat"],
        ["--name-only"],
        ["--cached"],
        ["abc1234"],
        ["HEAD"],
        ["HEAD~2..HEAD"],
    ])
    def test_allowed(self, tokens):
        ok, bad = _validate_extra_args("diff", tokens)
        assert ok is True, f"{tokens} should be allowed"

    @pytest.mark.parametrize("tokens", [
        ["--author=user"],   # fuer diff nicht erlaubt
        ["--grep=bug"],
        ["--since=yesterday"],
        ["--graph"],
    ])
    def test_log_only_args_rejected_for_diff(self, tokens):
        ok, _ = _validate_extra_args("diff", tokens)
        assert ok is False


class TestValidateExtraArgsOther:
    """Andere subcmds (status, pull) duerfen keine extra args."""

    def test_status_with_args_rejected(self):
        ok, _ = _validate_extra_args("status", ["--short"])
        assert ok is False

    def test_status_without_args_allowed(self):
        ok, _ = _validate_extra_args("status", [])
        assert ok is True


class TestGitExecuteExtraArgs:
    """End-to-end durch _cmd_git hindurch."""

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_allowed_extra_arg_passed_to_subprocess(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        result = handler.execute("git", "git log --author=user")
        assert result.success is True
        cmd = mock_run.call_args[0][0]
        assert "--author=user" in cmd

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_blocked_extra_arg_stops_before_subprocess(self, mock_run, handler):
        result = handler.execute("git", "git log --output=/tmp/evil")
        assert result.success is False
        assert "nicht erlaubt" in result.text
        assert "--output=/tmp/evil" in result.text
        mock_run.assert_not_called()

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_blocked_arg_message_lists_examples(self, mock_run, handler):
        result = handler.execute("git", "git log --no-pager")
        assert "--oneline" in result.text or "HEAD" in result.text
        mock_run.assert_not_called()

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_diff_error_message_uses_diff_examples(self, mock_run, handler):
        """Fehlermeldung fuer diff darf --author= nicht als Beispiel nennen."""
        result = handler.execute("git", "git diff --author=user")
        assert result.success is False
        # Der Beispiel-Teil muss diff-spezifisch sein, kein --author=
        examples_part = result.text.split("Erlaubte Beispiele:")[-1]
        assert "--author" not in examples_part
        assert "--stat" in examples_part or "--cached" in examples_part
        mock_run.assert_not_called()

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_status_with_extra_args_rejected_not_silently_ignored(self, mock_run, handler):
        """git status --short muss mit Fehlermeldung abgelehnt werden."""
        result = handler.execute("git", "git status --short")
        assert result.success is False
        assert "--short" in result.text
        mock_run.assert_not_called()

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_pull_with_extra_args_rejected(self, mock_run, handler):
        """git pull --rebase muss abgelehnt werden."""
        result = handler.execute("git", "git pull --rebase")
        assert result.success is False
        assert "--rebase" in result.text
        mock_run.assert_not_called()

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_mixed_allowed_blocked_rejects_whole(self, mock_run, handler):
        # Erste Arg OK, zweite verboten -- darf nicht durchrutschen.
        result = handler.execute("git", "git log --oneline --exec=cmd")
        assert result.success is False
        mock_run.assert_not_called()

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_diff_blocks_log_only_flag(self, mock_run, handler):
        result = handler.execute("git", "git diff --author=user")
        assert result.success is False
        mock_run.assert_not_called()

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_quoted_grep_arg_via_shlex(self, mock_run, handler):
        """--grep=\"fix bug\" wird via shlex.split als ein Token erkannt."""
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        result = handler.execute("git", 'git log --grep="fix bug"')
        assert result.success is True
        cmd = mock_run.call_args[0][0]
        assert "--grep=fix bug" in cmd

    @patch("elder_berry.comms.commands.git_commands.subprocess.run")
    def test_malformed_quotes_rejected(self, mock_run, handler):
        """Nicht geschlossene Quotes werden abgelehnt."""
        result = handler.execute("git", "git log --grep='unclosed")
        assert result.success is False
        mock_run.assert_not_called()
