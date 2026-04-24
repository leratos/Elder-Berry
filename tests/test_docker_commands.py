"""Tests: DockerCommandHandler – Docker-Befehle via Matrix (Whitelist)."""
from unittest.mock import MagicMock, patch
import subprocess

import pytest

from elder_berry.comms.commands.docker_commands import (
    DOCKER_PATTERN,
    DockerCommandHandler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def handler():
    return DockerCommandHandler()


# ---------------------------------------------------------------------------
# Pattern Tests
# ---------------------------------------------------------------------------

class TestDockerPattern:
    @pytest.mark.parametrize("text,subcmd,container", [
        ("docker ps", "ps", None),
        ("docker restart synapse", "restart", "synapse"),
        ("docker logs synapse", "logs", "synapse"),
        ("DOCKER PS", "PS", None),
    ])
    def test_valid_patterns(self, text, subcmd, container):
        m = DOCKER_PATTERN.match(text)
        assert m is not None
        assert m.group(1).lower() == subcmd.lower()
        if container:
            assert m.group(2) == container

    @pytest.mark.parametrize("text", [
        "docker build .",
        "docker rm container",
        "docker exec -it bash",
        "notdocker ps",
    ])
    def test_invalid_patterns(self, text):
        m = DOCKER_PATTERN.match(text)
        assert m is None


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class TestDockerInterface:
    def test_patterns_registered(self, handler):
        assert len(handler.patterns) == 1
        assert handler.patterns[0][1] == "docker"

    def test_command_descriptions(self, handler):
        descs = handler.command_descriptions
        assert any("docker" in d.lower() for d in descs)


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

class TestDockerExecute:
    def test_unknown_command(self, handler):
        result = handler.execute("unknown", "unknown")
        assert result.success is False

    @patch("elder_berry.comms.commands.docker_commands.subprocess.run")
    def test_docker_ps(self, mock_run, handler):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="CONTAINER ID   IMAGE\nabc123   synapse",
            stderr="",
        )
        result = handler.execute("docker", "docker ps")
        assert result.success is True
        assert "docker ps" in result.text

    @patch("elder_berry.comms.commands.docker_commands.subprocess.run")
    def test_docker_restart(self, mock_run, handler):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="synapse", stderr="",
        )
        result = handler.execute("docker", "docker restart synapse")
        assert result.success is True

    @patch("elder_berry.comms.commands.docker_commands.subprocess.run")
    def test_docker_logs_adds_tail(self, mock_run, handler):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="log line 1", stderr="",
        )
        result = handler.execute("docker", "docker logs synapse")
        assert result.success is True
        cmd = mock_run.call_args[0][0]
        assert "--tail" in cmd
        assert "50" in cmd

    def test_restart_missing_container(self, handler):
        result = handler.execute("docker", "docker restart")
        assert result.success is False
        assert "Container-Name fehlt" in result.text

    def test_logs_missing_container(self, handler):
        result = handler.execute("docker", "docker logs")
        assert result.success is False
        assert "Container-Name fehlt" in result.text

    def test_invalid_format(self, handler):
        result = handler.execute("docker", "docker build .")
        assert result.success is False
        assert "Erlaubt" in result.text or "Ungültiges" in result.text

    @patch("elder_berry.comms.commands.docker_commands.subprocess.run")
    def test_output_truncated(self, mock_run, handler):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="x" * 5000, stderr="",
        )
        result = handler.execute("docker", "docker ps")
        assert "gekürzt" in result.text

    @patch("elder_berry.comms.commands.docker_commands.subprocess.run")
    def test_docker_not_found(self, mock_run, handler):
        mock_run.side_effect = FileNotFoundError()
        result = handler.execute("docker", "docker ps")
        assert result.success is False
        assert "nicht gefunden" in result.text.lower()

    @patch("elder_berry.comms.commands.docker_commands.subprocess.run")
    def test_timeout(self, mock_run, handler):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=30)
        result = handler.execute("docker", "docker ps")
        assert result.success is False
        assert "Timeout" in result.text

    @patch("elder_berry.comms.commands.docker_commands.subprocess.run")
    def test_nonzero_returncode(self, mock_run, handler):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error output",
        )
        result = handler.execute("docker", "docker ps")
        assert result.success is False
