"""Tests: UpdateCommandHandler – Self-Update, Rollback, Backup."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.update_commands import (
    ROLLBACK_PATTERN,
    UPDATE_ALL_PATTERN,
    UPDATE_PATTERN,
    UPDATE_RPI_PATTERN,
    UpdateCommandHandler,
    _is_valid_git_hash,
    _pip_install_groups,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def handler(tmp_path, monkeypatch):
    """Handler mit isoliertem Backup-Verzeichnis."""
    monkeypatch.setattr(
        "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
        tmp_path / ".elder-berry",
    )
    return UpdateCommandHandler(project_root=tmp_path)


@pytest.fixture
def handler_no_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
        tmp_path / ".elder-berry",
    )
    return UpdateCommandHandler(project_root=None)


@pytest.fixture
def handler_with_robot(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
        tmp_path / ".elder-berry",
    )
    robot = MagicMock()
    robot.update_rpi.return_value = MagicMock(success=True, message="OK")
    return UpdateCommandHandler(project_root=tmp_path, robot_client=robot)


# ---------------------------------------------------------------------------
# Pattern Tests
# ---------------------------------------------------------------------------

class TestUpdatePattern:
    @pytest.mark.parametrize("text", [
        "update", "update dich", "update saleria", "update mich",
        "aktualisiere dich", "aktualisieren",
    ])
    def test_valid(self, text):
        assert UPDATE_PATTERN.match(text) is not None

    def test_invalid(self):
        assert UPDATE_PATTERN.match("update rpi") is None


class TestRollbackPattern:
    @pytest.mark.parametrize("text", [
        "rollback", "update zurücksetzen", "zurückrollen",
    ])
    def test_valid(self, text):
        assert ROLLBACK_PATTERN.match(text) is not None


class TestUpdateRpiPattern:
    @pytest.mark.parametrize("text", [
        "update rpi", "rpi update", "aktualisiere rpi",
    ])
    def test_valid(self, text):
        assert UPDATE_RPI_PATTERN.match(text) is not None


class TestUpdateAllPattern:
    @pytest.mark.parametrize("text", [
        "update alles", "alles updaten",
    ])
    def test_valid(self, text):
        assert UPDATE_ALL_PATTERN.match(text) is not None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

class TestIsValidGitHash:
    def test_valid_short(self):
        assert _is_valid_git_hash("abc1234") is True

    def test_valid_full(self):
        assert _is_valid_git_hash("a" * 40) is True

    def test_too_short(self):
        assert _is_valid_git_hash("abc") is False

    def test_invalid_chars(self):
        assert _is_valid_git_hash("xyz12345") is False

    def test_empty(self):
        assert _is_valid_git_hash("") is False


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class TestUpdateInterface:
    def test_simple_commands(self, handler):
        cmds = handler.simple_commands
        assert "update" in cmds
        assert "rollback" in cmds

    def test_patterns(self, handler):
        names = [p[1] for p in handler.patterns]
        assert "update" in names
        assert "rollback" in names

    def test_keywords(self, handler):
        kw = handler.keywords
        assert "update" in kw
        assert "rollback" in kw


# ---------------------------------------------------------------------------
# Update Tower
# ---------------------------------------------------------------------------

class TestUpdateTower:
    def test_no_project_root(self, handler_no_root):
        result = handler_no_root.execute("update", "update")
        assert result.success is False
        assert "nicht konfiguriert" in result.text

    @patch("elder_berry.comms.commands.update_commands.run_cmd")
    def test_already_up_to_date_asks_restart(self, mock_run_cmd, handler):
        from elder_berry.comms.commands.cmd_utils import CmdResult
        mock_run_cmd.side_effect = [
            CmdResult(success=True, output=""),    # fetch
            CmdResult(success=True, output="0"),   # behind
        ]
        result = handler.execute("update", "update")
        assert result.success is True
        assert "aktuell" in result.text.lower()
        assert result.restart is False
        assert result.pending_confirmation is True
        assert result.pending_data == {"action": "restart"}

    @patch("elder_berry.comms.commands.update_commands.run_cmd")
    def test_fetch_fails(self, mock_run_cmd, handler):
        from elder_berry.comms.commands.cmd_utils import CmdResult
        mock_run_cmd.return_value = CmdResult(success=False, output="network error")
        result = handler.execute("update", "update")
        assert result.success is False
        assert "Fetch" in result.text

    @patch("elder_berry.comms.commands.update_commands.run_cmd")
    def test_local_changes_abort(self, mock_run_cmd, handler):
        from elder_berry.comms.commands.cmd_utils import CmdResult
        mock_run_cmd.side_effect = [
            CmdResult(success=True, output=""),       # fetch
            CmdResult(success=True, output="3"),      # behind
            CmdResult(success=True, output="M dirty"),  # status dirty
        ]
        result = handler.execute("update", "update")
        assert result.success is False
        assert "Lokale Änderungen" in result.text


# ---------------------------------------------------------------------------
# Update RPi
# ---------------------------------------------------------------------------

class TestUpdateRpi:
    def test_no_robot(self, handler):
        result = handler.execute("update_rpi", "update rpi")
        assert result.success is False
        assert "RobotClient" in result.text

    def test_rpi_success(self, handler_with_robot):
        result = handler_with_robot.execute("update_rpi", "update rpi")
        assert result.success is True
        assert "RPi5" in result.text

    def test_rpi_exception(self, handler_with_robot):
        handler_with_robot._robot.update_rpi.side_effect = RuntimeError("offline")
        result = handler_with_robot.execute("update_rpi", "update rpi")
        assert result.success is False


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

class TestRollback:
    def test_no_project_root(self, handler_no_root):
        result = handler_no_root.execute("rollback", "rollback")
        assert result.success is False

    def test_no_backup(self, handler):
        result = handler.execute("rollback", "rollback")
        assert result.success is False
        assert "Backup" in result.text or "nicht vorhanden" in result.text

    @patch("elder_berry.comms.commands.update_commands.run_cmd")
    def test_rollback_hash_not_found(self, mock_run_cmd, handler):
        from elder_berry.comms.commands.cmd_utils import CmdResult
        # Write backup via handler (uses monkeypatched DEFAULT_BACKUP_DIR)
        handler._write_backup("abc123def456", "main")

        mock_run_cmd.return_value = CmdResult(success=False, output="not found")
        result = handler.execute("rollback", "rollback")
        assert result.success is False
        assert "existiert nicht" in result.text


# ---------------------------------------------------------------------------
# Backup Write/Read
# ---------------------------------------------------------------------------

class TestBackup:
    def test_write_and_read(self, handler):
        handler._write_backup("abc123full", "main")
        data = handler._read_backup()
        assert data is not None
        assert data["hash"] == "abc123full"
        assert data["branch"] == "main"

    def test_read_nonexistent(self, handler):
        # Fresh handler, no backup written → should be None
        data = handler._read_backup()
        assert data is None

    def test_read_corrupt_json(self, handler):
        path = handler._get_backup_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json", encoding="utf-8")
        data = handler._read_backup()
        assert data is None


# ---------------------------------------------------------------------------
# Update All: pending_confirmation durchreichen
# ---------------------------------------------------------------------------

class TestUpdateAllExecution:
    @patch("elder_berry.comms.commands.update_commands.run_cmd")
    def test_update_all_up_to_date_asks_restart(self, mock_run_cmd, handler):
        from elder_berry.comms.commands.cmd_utils import CmdResult
        mock_run_cmd.side_effect = [
            CmdResult(success=True, output=""),    # fetch
            CmdResult(success=True, output="0"),   # behind
        ]
        result = handler.execute("update_all", "update alles")
        assert result.success is True
        assert result.pending_confirmation is True
        assert result.pending_data == {"action": "restart"}
        assert "aktuell" in result.text.lower()


# ---------------------------------------------------------------------------
# Unknown Command
# ---------------------------------------------------------------------------

class TestUnknownCommand:
    def test_unknown(self, handler):
        result = handler.execute("unknown", "unknown")
        assert result.success is False


# ---------------------------------------------------------------------------
# Pip Install Groups
# ---------------------------------------------------------------------------

class TestPipInstallGroups:
    def test_windows_groups(self):
        with patch("elder_berry.comms.commands.update_commands.platform") as mock_plat:
            mock_plat.system.return_value = "Windows"
            groups = _pip_install_groups()
            assert "windows" in groups
            assert "tts-neural" in groups
            assert "server" not in groups

    def test_linux_groups(self):
        with patch("elder_berry.comms.commands.update_commands.platform") as mock_plat:
            mock_plat.system.return_value = "Linux"
            groups = _pip_install_groups()
            assert groups == ".[server]"
            assert "windows" not in groups
