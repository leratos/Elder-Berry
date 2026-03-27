"""Tests: cmd_utils – CmdResult DTO und run_cmd Shell-Helper."""
from unittest.mock import MagicMock, patch
import subprocess

import pytest

from elder_berry.comms.commands.cmd_utils import CmdResult, run_cmd


# ---------------------------------------------------------------------------
# CmdResult DTO
# ---------------------------------------------------------------------------

class TestCmdResult:
    def test_success_result(self):
        r = CmdResult(success=True, output="hello")
        assert r.success is True
        assert r.output == "hello"

    def test_failure_result(self):
        r = CmdResult(success=False, output="error msg")
        assert r.success is False
        assert r.output == "error msg"

    def test_empty_output(self):
        r = CmdResult(success=True, output="")
        assert r.output == ""


# ---------------------------------------------------------------------------
# run_cmd
# ---------------------------------------------------------------------------

class TestRunCmd:
    @patch("elder_berry.comms.commands.cmd_utils.subprocess.run")
    def test_success_stdout(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="output text", stderr="",
        )
        result = run_cmd(["echo", "hi"], cwd="/tmp")
        assert result.success is True
        assert result.output == "output text"
        mock_run.assert_called_once_with(
            ["echo", "hi"],
            capture_output=True, text=True, timeout=30, cwd="/tmp",
        )

    @patch("elder_berry.comms.commands.cmd_utils.subprocess.run")
    def test_success_stderr_fallback(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr="stderr text",
        )
        result = run_cmd(["cmd"], cwd="/tmp")
        assert result.success is True
        assert result.output == "stderr text"

    @patch("elder_berry.comms.commands.cmd_utils.subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr="",
        )
        result = run_cmd(["cmd"], cwd="/tmp")
        assert result.output == ""

    @patch("elder_berry.comms.commands.cmd_utils.subprocess.run")
    def test_nonzero_returncode(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="fail",
        )
        result = run_cmd(["cmd"], cwd="/tmp")
        assert result.success is False
        assert result.output == "fail"

    @patch("elder_berry.comms.commands.cmd_utils.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=5)
        result = run_cmd(["slow"], cwd="/tmp", timeout=5)
        assert result.success is False
        assert "Timeout" in result.output
        assert "5s" in result.output

    @patch("elder_berry.comms.commands.cmd_utils.subprocess.run")
    def test_file_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = run_cmd(["nonexistent"], cwd="/tmp")
        assert result.success is False
        assert "nicht gefunden" in result.output
        assert "nonexistent" in result.output

    @patch("elder_berry.comms.commands.cmd_utils.subprocess.run")
    def test_generic_exception(self, mock_run):
        mock_run.side_effect = OSError("permission denied")
        result = run_cmd(["cmd"], cwd="/tmp")
        assert result.success is False
        assert "permission denied" in result.output

    @patch("elder_berry.comms.commands.cmd_utils.subprocess.run")
    def test_custom_timeout(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="ok", stderr="",
        )
        run_cmd(["cmd"], cwd="/tmp", timeout=60)
        mock_run.assert_called_once_with(
            ["cmd"],
            capture_output=True, text=True, timeout=60, cwd="/tmp",
        )
