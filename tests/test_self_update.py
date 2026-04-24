"""Tests: Self-Update, Backup/Rollback, SelfCheck – aufgeteilt in eigene Handler."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.update_commands import (
    BACKUP_FILENAME,
    UpdateCommandHandler,
    ROLLBACK_PATTERN,
    UPDATE_ALL_PATTERN,
    UPDATE_PATTERN,
    UPDATE_RPI_PATTERN,
)
from elder_berry.comms.commands.selfcheck_commands import (
    SelfcheckCommandHandler,
    SELFCHECK_PATTERN,
)
from elder_berry.comms.commands.cmd_utils import CmdResult
from elder_berry.comms.commands.base import CommandResult
from elder_berry.robot.protocol import ApiResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def handler(tmp_path):
    """UpdateCommandHandler mit temporärem project_root."""
    return UpdateCommandHandler(project_root=tmp_path)


@pytest.fixture
def handler_no_root():
    """UpdateCommandHandler ohne project_root."""
    return UpdateCommandHandler(project_root=None)


@pytest.fixture
def selfcheck_handler(tmp_path):
    """SelfcheckCommandHandler mit temporärem project_root."""
    return SelfcheckCommandHandler(project_root=tmp_path)


# ---------------------------------------------------------------------------
# Pattern-Tests
# ---------------------------------------------------------------------------

class TestUpdatePattern:
    def test_update(self):
        assert UPDATE_PATTERN.match("update")

    def test_update_dich(self):
        assert UPDATE_PATTERN.match("update dich")

    def test_update_saleria(self):
        assert UPDATE_PATTERN.match("update saleria")

    def test_aktualisiere_dich(self):
        assert UPDATE_PATTERN.match("aktualisiere dich")

    def test_aktualisieren(self):
        assert UPDATE_PATTERN.match("aktualisieren")

    def test_case_insensitive(self):
        assert UPDATE_PATTERN.match("UPDATE DICH")
        assert UPDATE_PATTERN.match("Aktualisiere Dich")

    def test_no_match_git_pull(self):
        assert not UPDATE_PATTERN.match("git pull")

    def test_no_match_status(self):
        assert not UPDATE_PATTERN.match("status")


# ---------------------------------------------------------------------------
# simple_commands / keywords
# ---------------------------------------------------------------------------

class TestUpdateRegistration:
    def test_update_in_simple_commands(self, handler):
        assert "update" in handler.simple_commands

    def test_update_in_keywords(self, handler):
        keywords = handler.keywords
        assert "update" in keywords
        assert "update dich" in keywords["update"]
        assert "aktualisiere dich" in keywords["update"]
        assert "neue funktionen" in keywords["update"]

    def test_update_pattern_in_patterns(self, handler):
        pattern_commands = [name for (_, name, _, _) in handler.patterns]
        assert "update" in pattern_commands


# ---------------------------------------------------------------------------
# execute() – Kein project_root
# ---------------------------------------------------------------------------

class TestUpdateNoRoot:
    def test_no_project_root(self, handler_no_root):
        result = handler_no_root.execute("update", "update dich")
        assert not result.success
        assert "nicht konfiguriert" in result.text.lower()


# ---------------------------------------------------------------------------
# execute() – Mock-basierte Tests
# ---------------------------------------------------------------------------

def _make_run_result(success: bool, output: str = "") -> MagicMock:
    """Hilfsfunktion: Erzeugt ein subprocess.CompletedProcess Mock."""
    m = MagicMock()
    m.returncode = 0 if success else 1
    m.stdout = output
    m.stderr = ""
    return m


class TestUpdateExecute:
    def _patch_run(self, side_effects):
        """Patcht subprocess.run via cmd_utils (dort wird subprocess genutzt)."""
        return patch(
            "elder_berry.comms.commands.cmd_utils.subprocess.run",
            side_effect=side_effects,
        )

    def test_git_fetch_fails(self, handler):
        """git fetch schlägt fehl → Fehler, kein Pull."""
        with self._patch_run([
            _make_run_result(False, "fatal: could not read remote"),  # fetch
        ]):
            result = handler.execute("update", "update")
        assert not result.success
        assert "fetch" in result.text.lower()
        assert not result.restart

    def test_already_up_to_date(self, handler):
        """0 Commits behind → 'Alles aktuell', kein Restart."""
        with self._patch_run([
            _make_run_result(True),            # fetch
            _make_run_result(True, "0\n"),     # rev-list (0 behind)
        ]):
            result = handler.execute("update", "update")
        assert result.success
        assert "aktuell" in result.text.lower()
        assert not result.restart

    def test_local_changes_abort(self, handler):
        """Lokale Änderungen → Update abgebrochen."""
        with self._patch_run([
            _make_run_result(True),               # fetch
            _make_run_result(True, "2\n"),         # rev-list (2 behind)
            _make_run_result(True, "M  src/x.py\n"),  # status (dirty)
        ]):
            result = handler.execute("update", "update")
        assert not result.success
        assert "lokale änderungen" in result.text.lower()
        assert not result.restart

    def test_git_pull_fails(self, handler):
        """git pull schlägt fehl → Fehler, kein Restart."""
        with self._patch_run([
            _make_run_result(True),           # fetch
            _make_run_result(True, "1\n"),    # rev-list (1 behind)
            _make_run_result(True, ""),       # status (clean)
            _make_run_result(True, "abc123\n"),  # rev-parse old (short)
            _make_run_result(True, "abc123full\n"),  # rev-parse old (full, backup)
            _make_run_result(True, "main\n"),  # rev-parse branch (backup)
            _make_run_result(False, "CONFLICT: merge conflict"),  # pull
        ]):
            result = handler.execute("update", "update")
        assert not result.success
        assert "pull fehlgeschlagen" in result.text.lower()
        assert not result.restart

    def test_success_no_dep_change(self, handler):
        """Erfolg ohne Dependency-Änderung → restart=True."""
        with self._patch_run([
            _make_run_result(True),              # fetch
            _make_run_result(True, "1\n"),        # rev-list
            _make_run_result(True, ""),           # status clean
            _make_run_result(True, "abc123\n"),   # rev-parse old (short)
            _make_run_result(True, "abc123full\n"),  # rev-parse old (full, backup)
            _make_run_result(True, "main\n"),     # rev-parse branch (backup)
            _make_run_result(True, "Fast-forward"),  # pull
            _make_run_result(True, "def456\n"),   # rev-parse new
            _make_run_result(True, "feat: add update command\n"),  # git log
            _make_run_result(True, "src/x.py\n"),  # diff --name-only (no pyproject)
        ]):
            result = handler.execute("update", "update")
        assert result.success
        assert result.restart
        assert "aktualisiert" in result.text.lower()
        assert "keine neuen dependencies" in result.text.lower()

    def test_success_with_dep_change(self, handler):
        """Erfolg mit pyproject.toml geändert → pip install läuft, restart=True."""
        with self._patch_run([
            _make_run_result(True),               # fetch
            _make_run_result(True, "1\n"),         # rev-list
            _make_run_result(True, ""),            # status clean
            _make_run_result(True, "abc123\n"),    # rev-parse old (short)
            _make_run_result(True, "abc123full\n"),  # rev-parse old (full, backup)
            _make_run_result(True, "main\n"),      # rev-parse branch (backup)
            _make_run_result(True, "Fast-forward"),   # pull
            _make_run_result(True, "def456\n"),    # rev-parse new
            _make_run_result(True, "feat: deps\n"),   # git log
            _make_run_result(True, "pyproject.toml\nsrc/x.py\n"),  # diff (pyproject changed)
            _make_run_result(True, ""),            # pip install
        ]):
            result = handler.execute("update", "update")
        assert result.success
        assert result.restart
        assert "dependencies installiert" in result.text.lower()

    def test_pip_install_fails_not_fatal(self, handler):
        """pip install fehlgeschlagen → Warnung (nicht fatal), restart=True."""
        with self._patch_run([
            _make_run_result(True),               # fetch
            _make_run_result(True, "1\n"),         # rev-list
            _make_run_result(True, ""),            # status clean
            _make_run_result(True, "abc123\n"),    # rev-parse old (short)
            _make_run_result(True, "abc123full\n"),  # rev-parse old (full, backup)
            _make_run_result(True, "main\n"),      # rev-parse branch (backup)
            _make_run_result(True, "Fast-forward"),   # pull
            _make_run_result(True, "def456\n"),    # rev-parse new
            _make_run_result(True, ""),            # git log
            _make_run_result(True, "pyproject.toml\n"),  # diff
            _make_run_result(False, "ERROR: Could not find package"),  # pip fail
        ]):
            result = handler.execute("update", "update")
        assert result.success
        assert result.restart
        assert "warnung" in result.text.lower() or "pip" in result.text.lower()


# ---------------------------------------------------------------------------
# run_cmd() – Helper-Tests
# ---------------------------------------------------------------------------

class TestRunCmd:
    def test_timeout(self, tmp_path):
        """Timeout → success=False."""
        from elder_berry.comms.commands.cmd_utils import run_cmd
        with patch(
            "elder_berry.comms.commands.cmd_utils.subprocess.run",
            side_effect=__import__("subprocess").TimeoutExpired(cmd=["x"], timeout=1),
        ):
            result = run_cmd(["x"], cwd=str(tmp_path), timeout=1)
        assert not result.success
        assert "timeout" in result.output.lower()

    def test_file_not_found(self, tmp_path):
        """FileNotFoundError → success=False."""
        from elder_berry.comms.commands.cmd_utils import run_cmd
        with patch(
            "elder_berry.comms.commands.cmd_utils.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = run_cmd(["nonexistent_cmd"], cwd=str(tmp_path))
        assert not result.success
        assert "nicht gefunden" in result.output.lower()

    def test_success(self, tmp_path):
        """Erfolgreicher Befehl → success=True."""
        from elder_berry.comms.commands.cmd_utils import run_cmd
        with patch(
            "elder_berry.comms.commands.cmd_utils.subprocess.run",
            return_value=_make_run_result(True, "hello\n"),
        ):
            result = run_cmd(["echo", "hello"], cwd=str(tmp_path))
        assert result.success
        assert "hello" in result.output

    def test_cmd_result_dataclass(self):
        """CmdResult DTO korrekt initialisiert."""
        r = CmdResult(success=True, output="test")
        assert r.success
        assert r.output == "test"


# ===========================================================================
# Rollback-Pattern-Tests
# ===========================================================================

class TestRollbackPattern:
    def test_rollback(self):
        assert ROLLBACK_PATTERN.match("rollback")

    def test_update_zuruecksetzen(self):
        assert ROLLBACK_PATTERN.match("update zurücksetzen")

    def test_update_zurueck(self):
        assert ROLLBACK_PATTERN.match("update zurück")

    def test_zurueckrollen(self):
        assert ROLLBACK_PATTERN.match("zurückrollen")

    def test_case_insensitive(self):
        assert ROLLBACK_PATTERN.match("Rollback")
        assert ROLLBACK_PATTERN.match("ROLLBACK")

    def test_no_match_update(self):
        assert not ROLLBACK_PATTERN.match("update")

    def test_no_match_random(self):
        assert not ROLLBACK_PATTERN.match("git reset")


# ===========================================================================
# SelfCheck-Pattern-Tests
# ===========================================================================

class TestSelfCheckPattern:
    def test_selfcheck(self):
        assert SELFCHECK_PATTERN.match("selfcheck")

    def test_self_check_space(self):
        assert SELFCHECK_PATTERN.match("self check")

    def test_systemcheck(self):
        assert SELFCHECK_PATTERN.match("systemcheck")

    def test_system_check_space(self):
        assert SELFCHECK_PATTERN.match("system check")

    def test_pruef_dich(self):
        assert SELFCHECK_PATTERN.match("prüf dich")

    def test_alles_ok(self):
        assert SELFCHECK_PATTERN.match("alles ok?")

    def test_alles_ok_no_question_mark(self):
        assert SELFCHECK_PATTERN.match("alles ok")

    def test_gesundheitscheck(self):
        assert SELFCHECK_PATTERN.match("gesundheitscheck")

    def test_case_insensitive(self):
        assert SELFCHECK_PATTERN.match("SelfCheck")
        assert SELFCHECK_PATTERN.match("SYSTEMCHECK")

    def test_no_match_status(self):
        assert not SELFCHECK_PATTERN.match("status")


# ===========================================================================
# Registration-Tests
# ===========================================================================

class TestNewCommandRegistration:
    def test_rollback_in_simple_commands(self, handler):
        assert "rollback" in handler.simple_commands

    def test_selfcheck_in_simple_commands(self, selfcheck_handler):
        assert "selfcheck" in selfcheck_handler.simple_commands

    def test_rollback_in_keywords(self, handler):
        assert "rollback" in handler.keywords
        assert "update zurücksetzen" in handler.keywords["rollback"]

    def test_selfcheck_in_keywords(self, selfcheck_handler):
        assert "selfcheck" in selfcheck_handler.keywords
        assert "prüf dich" in selfcheck_handler.keywords["selfcheck"]

    def test_rollback_pattern_in_patterns(self, handler):
        pattern_commands = [name for (_, name, _, _) in handler.patterns]
        assert "rollback" in pattern_commands

    def test_selfcheck_pattern_in_patterns(self, selfcheck_handler):
        pattern_commands = [name for (_, name, _, _) in selfcheck_handler.patterns]
        assert "selfcheck" in pattern_commands


# ===========================================================================
# Backup – Schreiben und Lesen
# ===========================================================================

class TestBackupIO:
    def test_write_and_read_backup(self, tmp_path):
        """Backup schreiben und wieder lesen."""
        handler = UpdateCommandHandler(project_root=tmp_path)
        with patch(
            "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ):
            handler._write_backup("abc123full", "main")
            backup = handler._read_backup()

        assert backup is not None
        assert backup["hash"] == "abc123full"
        assert backup["branch"] == "main"
        assert "timestamp" in backup

    def test_read_no_backup(self, tmp_path):
        """Kein Backup vorhanden → None."""
        handler = UpdateCommandHandler(project_root=tmp_path)
        with patch(
            "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ):
            assert handler._read_backup() is None

    def test_read_corrupt_backup(self, tmp_path):
        """Kaputte JSON-Datei → None."""
        handler = UpdateCommandHandler(project_root=tmp_path)
        backup_file = tmp_path / BACKUP_FILENAME
        backup_file.write_text("not json {{{", encoding="utf-8")
        with patch(
            "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ):
            assert handler._read_backup() is None

    def test_read_backup_missing_hash(self, tmp_path):
        """JSON ohne 'hash' Key → None."""
        handler = UpdateCommandHandler(project_root=tmp_path)
        backup_file = tmp_path / BACKUP_FILENAME
        backup_file.write_text('{"branch": "main"}', encoding="utf-8")
        with patch(
            "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ):
            assert handler._read_backup() is None


# ===========================================================================
# Update schreibt Backup
# ===========================================================================

class TestUpdateWritesBackup:
    def _patch_run(self, side_effects):
        return patch(
            "elder_berry.comms.commands.cmd_utils.subprocess.run",
            side_effect=side_effects,
        )

    def test_update_creates_backup(self, tmp_path):
        """Erfolgreicher Update erstellt Backup-Datei."""
        handler = UpdateCommandHandler(project_root=tmp_path)
        with self._patch_run([
            _make_run_result(True),               # fetch
            _make_run_result(True, "1\n"),          # rev-list
            _make_run_result(True, ""),             # status clean
            _make_run_result(True, "abc123\n"),     # rev-parse short
            _make_run_result(True, "abc123fullhash\n"),  # rev-parse full
            _make_run_result(True, "main\n"),       # rev-parse branch
            _make_run_result(True, "Fast-forward"),    # pull
            _make_run_result(True, "def456\n"),     # rev-parse new
            _make_run_result(True, "feat: x\n"),    # git log
            _make_run_result(True, "src/x.py\n"),   # diff --name-only
        ]), patch(
            "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ):
            result = handler.execute("update", "update")

        assert result.success
        assert result.restart
        assert "backup" in result.text.lower()

        # Backup-Datei prüfen
        backup_file = tmp_path / BACKUP_FILENAME
        assert backup_file.exists()
        data = json.loads(backup_file.read_text())
        assert data["hash"] == "abc123fullhash"
        assert data["branch"] == "main"


# ===========================================================================
# Rollback-Tests
# ===========================================================================

class TestRollbackExecute:
    def _patch_run(self, side_effects):
        return patch(
            "elder_berry.comms.commands.cmd_utils.subprocess.run",
            side_effect=side_effects,
        )

    def test_no_project_root(self):
        """Kein project_root → Fehler."""
        handler = UpdateCommandHandler(project_root=None)
        result = handler.execute("rollback", "rollback")
        assert not result.success
        assert "nicht konfiguriert" in result.text.lower()

    def test_no_backup(self, tmp_path):
        """Kein Backup vorhanden → Fehler."""
        handler = UpdateCommandHandler(project_root=tmp_path)
        with patch(
            "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ):
            result = handler.execute("rollback", "rollback")
        assert not result.success
        assert "nicht vorhanden" in result.text.lower()

    def test_hash_not_found(self, tmp_path):
        """Commit existiert nicht mehr → Fehler."""
        handler = UpdateCommandHandler(project_root=tmp_path)
        backup_file = tmp_path / BACKUP_FILENAME
        backup_file.write_text(
            json.dumps({"hash": "deadbeef", "branch": "main", "timestamp": "t"}),
            encoding="utf-8",
        )
        with self._patch_run([
            _make_run_result(False, "fatal: not a valid object"),  # cat-file
        ]), patch(
            "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ):
            result = handler.execute("rollback", "rollback")
        assert not result.success
        assert "existiert nicht" in result.text.lower()

    def test_git_reset_fails(self, tmp_path):
        """git reset fehlgeschlagen → Fehler."""
        handler = UpdateCommandHandler(project_root=tmp_path)
        backup_file = tmp_path / BACKUP_FILENAME
        backup_file.write_text(
            json.dumps({"hash": "abc123", "branch": "main", "timestamp": "t"}),
            encoding="utf-8",
        )
        with self._patch_run([
            _make_run_result(True, "commit"),       # cat-file
            _make_run_result(False, "error: reset"),  # reset --hard
        ]), patch(
            "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ):
            result = handler.execute("rollback", "rollback")
        assert not result.success
        assert "reset fehlgeschlagen" in result.text.lower()

    def test_success_with_restart(self, tmp_path):
        """Erfolgreicher Rollback → restart=True, Backup gelöscht."""
        handler = UpdateCommandHandler(project_root=tmp_path)
        backup_file = tmp_path / BACKUP_FILENAME
        backup_file.write_text(
            json.dumps({"hash": "abc123full", "branch": "main", "timestamp": "t"}),
            encoding="utf-8",
        )
        with self._patch_run([
            _make_run_result(True, "commit"),        # cat-file
            _make_run_result(True, "HEAD is now at"), # reset --hard
            _make_run_result(True, ""),               # pip install
        ]), patch(
            "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ):
            result = handler.execute("rollback", "rollback")

        assert result.success
        assert result.restart
        assert "zurückgesetzt" in result.text.lower()
        # Backup-Datei sollte gelöscht sein
        assert not backup_file.exists()

    def test_pip_warning_not_fatal(self, tmp_path):
        """pip install Warnung → trotzdem Erfolg."""
        handler = UpdateCommandHandler(project_root=tmp_path)
        backup_file = tmp_path / BACKUP_FILENAME
        backup_file.write_text(
            json.dumps({"hash": "abc123", "branch": "main", "timestamp": "t"}),
            encoding="utf-8",
        )
        with self._patch_run([
            _make_run_result(True, "commit"),
            _make_run_result(True, "HEAD is now at"),
            _make_run_result(False, "ERROR: pip"),    # pip fail
        ]), patch(
            "elder_berry.comms.commands.update_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ):
            result = handler.execute("rollback", "rollback")
        assert result.success
        assert result.restart
        assert "warnung" in result.text.lower() or "pip" in result.text.lower()


# ===========================================================================
# SelfCheck-Tests
# ===========================================================================

class TestSelfCheckExecute:
    def _patch_run(self, side_effects):
        return patch(
            "elder_berry.comms.commands.cmd_utils.subprocess.run",
            side_effect=side_effects,
        )

    def test_no_project_root(self):
        """Ohne project_root → Warnung, aber kein Crash."""
        handler = SelfcheckCommandHandler(project_root=None)
        result = handler.execute("selfcheck", "selfcheck")
        assert "systemcheck" in result.text.lower()
        assert "nicht konfiguriert" in result.text.lower()

    def test_all_healthy(self, tmp_path):
        """Alles OK → success=True, 'Alles in Ordnung'."""
        mock_store = MagicMock()
        mock_store.list_keys.return_value = ["key1"]
        handler = SelfcheckCommandHandler(
            project_root=tmp_path, secret_store=mock_store,
        )

        with self._patch_run([
            _make_run_result(True, "main\n"),       # branch
            _make_run_result(True, ""),              # status clean
            _make_run_result(True, ""),              # fetch
            _make_run_result(True, "0\n"),           # rev-list behind
            _make_run_result(True, ""),              # pip check
        ]), patch(
            "elder_berry.comms.commands.selfcheck_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ), patch(
            "urllib.request.urlopen",
        ) as mock_urlopen:
            # Ollama mock
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = json.dumps(
                {"models": [{"name": "phi4:14b"}]}
            ).encode()
            mock_urlopen.return_value = mock_resp

            result = handler.execute("selfcheck", "selfcheck")

        assert result.success
        assert "alles in ordnung" in result.text.lower()

    def test_git_dirty_shows_warning(self, tmp_path):
        """Uncommitted changes → Warnung."""
        handler = SelfcheckCommandHandler(project_root=tmp_path)

        with self._patch_run([
            _make_run_result(True, "main\n"),        # branch
            _make_run_result(True, "M src/x.py\n"),  # status dirty
            _make_run_result(True, ""),               # fetch
            _make_run_result(True, "0\n"),            # rev-list
            _make_run_result(True, ""),               # pip check
        ]), patch(
            "elder_berry.comms.commands.selfcheck_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ), patch(
            "urllib.request.urlopen",
            side_effect=Exception("connection refused"),
        ):
            result = handler.execute("selfcheck", "selfcheck")

        assert "uncommitted" in result.text.lower()

    def test_behind_remote_shows_warning(self, tmp_path):
        """Hinter Remote → Warnung mit Commit-Anzahl."""
        handler = SelfcheckCommandHandler(project_root=tmp_path)

        with self._patch_run([
            _make_run_result(True, "main\n"),
            _make_run_result(True, ""),
            _make_run_result(True, ""),               # fetch
            _make_run_result(True, "3\n"),             # 3 behind
            _make_run_result(True, ""),                # pip check
        ]), patch(
            "elder_berry.comms.commands.selfcheck_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ), patch(
            "urllib.request.urlopen",
            side_effect=Exception("connection refused"),
        ):
            result = handler.execute("selfcheck", "selfcheck")

        assert "3 commits hinter remote" in result.text.lower()

    def test_ollama_unreachable(self, tmp_path):
        """Ollama nicht erreichbar → Fehler."""
        handler = SelfcheckCommandHandler(project_root=tmp_path)

        with self._patch_run([
            _make_run_result(True, "main\n"),
            _make_run_result(True, ""),
            _make_run_result(True, ""),
            _make_run_result(True, "0\n"),
            _make_run_result(True, ""),               # pip check
        ]), patch(
            "elder_berry.comms.commands.selfcheck_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ), patch(
            "urllib.request.urlopen",
            side_effect=Exception("connection refused"),
        ):
            result = handler.execute("selfcheck", "selfcheck")

        assert "ollama" in result.text.lower()
        assert "nicht erreichbar" in result.text.lower()

    def test_secret_store_error(self, tmp_path):
        """SecretStore Fehler → Fehler anzeigen."""
        mock_store = MagicMock()
        mock_store.list_keys.side_effect = Exception("decrypt failed")
        handler = SelfcheckCommandHandler(
            project_root=tmp_path, secret_store=mock_store,
        )

        with self._patch_run([
            _make_run_result(True, "main\n"),
            _make_run_result(True, ""),
            _make_run_result(True, ""),
            _make_run_result(True, "0\n"),
            _make_run_result(True, ""),
        ]), patch(
            "elder_berry.comms.commands.selfcheck_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ), patch(
            "urllib.request.urlopen",
            side_effect=Exception("refused"),
        ):
            result = handler.execute("selfcheck", "selfcheck")

        assert not result.success
        assert "secretstore" in result.text.lower()
        assert "decrypt" in result.text.lower()

    def test_backup_shown_in_selfcheck(self, tmp_path):
        """Wenn Backup existiert → wird im SelfCheck angezeigt."""
        handler = SelfcheckCommandHandler(project_root=tmp_path)
        backup_file = tmp_path / BACKUP_FILENAME
        backup_file.write_text(
            json.dumps({
                "hash": "abc123fullhash",
                "branch": "main",
                "timestamp": "2026-03-19T18:30:00",
            }),
            encoding="utf-8",
        )

        with self._patch_run([
            _make_run_result(True, "main\n"),
            _make_run_result(True, ""),
            _make_run_result(True, ""),
            _make_run_result(True, "0\n"),
            _make_run_result(True, ""),
        ]), patch(
            "elder_berry.comms.commands.selfcheck_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ), patch(
            "urllib.request.urlopen",
            side_effect=Exception("refused"),
        ):
            result = handler.execute("selfcheck", "selfcheck")

        assert "abc123fu" in result.text
        assert "backup" in result.text.lower()

    def test_pip_check_conflict(self, tmp_path):
        """pip check findet Konflikte → Warnung."""
        handler = SelfcheckCommandHandler(project_root=tmp_path)

        with self._patch_run([
            _make_run_result(True, "main\n"),
            _make_run_result(True, ""),
            _make_run_result(True, ""),
            _make_run_result(True, "0\n"),
            _make_run_result(False, "package-x 1.0 requires y>=2.0\n"),
        ]), patch(
            "elder_berry.comms.commands.selfcheck_commands.DEFAULT_BACKUP_DIR",
            tmp_path,
        ), patch(
            "urllib.request.urlopen",
            side_effect=Exception("refused"),
        ):
            result = handler.execute("selfcheck", "selfcheck")

        assert "dependencies" in result.text.lower()
        assert "package-x" in result.text.lower()


# ---------------------------------------------------------------------------
# RPi-Update Pattern Tests
# ---------------------------------------------------------------------------

class TestUpdateRpiPattern:
    def test_update_rpi(self):
        assert UPDATE_RPI_PATTERN.match("update rpi")

    def test_rpi_update(self):
        assert UPDATE_RPI_PATTERN.match("rpi update")

    def test_aktualisiere_rpi(self):
        assert UPDATE_RPI_PATTERN.match("aktualisiere rpi")

    def test_case_insensitive(self):
        assert UPDATE_RPI_PATTERN.match("Update RPi")

    def test_no_match_update_alone(self):
        assert UPDATE_RPI_PATTERN.match("update") is None

    def test_no_match_update_dich(self):
        assert UPDATE_RPI_PATTERN.match("update dich") is None


class TestUpdateAllPattern:
    def test_update_alles(self):
        assert UPDATE_ALL_PATTERN.match("update alles")

    def test_alles_updaten(self):
        assert UPDATE_ALL_PATTERN.match("alles updaten")

    def test_alles_update(self):
        assert UPDATE_ALL_PATTERN.match("alles update")

    def test_case_insensitive(self):
        assert UPDATE_ALL_PATTERN.match("Update Alles")

    def test_no_match_update_alone(self):
        assert UPDATE_ALL_PATTERN.match("update") is None


# ---------------------------------------------------------------------------
# RPi-Update Registration Tests
# ---------------------------------------------------------------------------

class TestUpdateRpiRegistration:
    def test_simple_commands(self, handler):
        assert "update rpi" in handler.simple_commands
        assert "update alles" in handler.simple_commands

    def test_keywords_update_rpi(self, handler):
        kws = handler.keywords
        assert "update_rpi" in kws
        assert "update rpi" in kws["update_rpi"]

    def test_keywords_update_all(self, handler):
        kws = handler.keywords
        assert "update_all" in kws
        assert "update alles" in kws["update_all"]

    def test_command_descriptions(self, handler):
        descs = "\n".join(handler.command_descriptions)
        assert "update rpi" in descs.lower()
        assert "update alles" in descs.lower() or "tower + rpi" in descs.lower()


# ---------------------------------------------------------------------------
# RPi-Update Execute Tests
# ---------------------------------------------------------------------------

class TestUpdateRpiExecute:
    def test_no_robot_client(self, handler):
        result = handler.execute("update_rpi", "update rpi")
        assert result.success is False
        assert "nicht verfügbar" in result.text.lower() or "nicht verbunden" in result.text.lower()

    def test_rpi_update_success(self, tmp_path):
        robot = MagicMock()
        robot.update_rpi.return_value = ApiResponse(
            success=True, message="2 Commits | Code aktualisiert | Neustart",
        )
        h = UpdateCommandHandler(project_root=tmp_path, robot_client=robot)
        result = h.execute("update_rpi", "update rpi")
        assert result.success is True
        assert "RPi5" in result.text
        robot.update_rpi.assert_called_once()

    def test_rpi_update_failure(self, tmp_path):
        robot = MagicMock()
        robot.update_rpi.return_value = ApiResponse(
            success=False, message="Git Pull fehlgeschlagen",
        )
        h = UpdateCommandHandler(project_root=tmp_path, robot_client=robot)
        result = h.execute("update_rpi", "update rpi")
        assert result.success is False

    def test_rpi_update_connection_error(self, tmp_path):
        robot = MagicMock()
        robot.update_rpi.side_effect = Exception("Connection refused")
        h = UpdateCommandHandler(project_root=tmp_path, robot_client=robot)
        result = h.execute("update_rpi", "update rpi")
        assert result.success is False
        assert "❌" in result.text


class TestUpdateAllExecute:
    @patch.object(UpdateCommandHandler, "_cmd_update")
    def test_update_all_both_succeed(self, mock_tower_update, tmp_path):
        robot = MagicMock()
        robot.update_rpi.return_value = ApiResponse(
            success=True, message="RPi5 aktualisiert",
        )
        mock_tower_update.return_value = CommandResult(
            command="update", success=True, text="Tower aktualisiert", restart=True,
        )
        h = UpdateCommandHandler(project_root=tmp_path, robot_client=robot)
        result = h.execute("update_all", "update alles")
        assert result.success is True
        assert result.restart is True
        assert "RPi5" in result.text
        assert "Tower" in result.text

    @patch.object(UpdateCommandHandler, "_cmd_update")
    def test_update_all_no_robot(self, mock_tower_update, tmp_path):
        mock_tower_update.return_value = CommandResult(
            command="update", success=True, text="Alles aktuell", restart=False,
        )
        h = UpdateCommandHandler(project_root=tmp_path, robot_client=None)
        result = h.execute("update_all", "update alles")
        assert "uebersprungen" in result.text.lower() or "nicht verbunden" in result.text.lower()
