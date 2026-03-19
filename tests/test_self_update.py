"""Tests: Self-Update Command in ProcessCommandHandler (Phase 15)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.process_commands import (
    ProcessCommandHandler,
    UPDATE_PATTERN,
    _CmdResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def handler(tmp_path):
    """ProcessCommandHandler mit temporärem project_root."""
    return ProcessCommandHandler(project_root=tmp_path)


@pytest.fixture
def handler_no_root():
    """ProcessCommandHandler ohne project_root."""
    return ProcessCommandHandler(project_root=None)


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
        """Patcht subprocess.run mit einer Liste von Return-Values."""
        return patch(
            "elder_berry.comms.commands.process_commands.subprocess.run",
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
            _make_run_result(True, "abc123\n"),  # rev-parse old hash
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
            _make_run_result(True, "abc123\n"),   # rev-parse old
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
            _make_run_result(True, "abc123\n"),    # rev-parse old
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
            _make_run_result(True, "abc123\n"),    # rev-parse old
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
# _run_cmd() – Helper-Tests
# ---------------------------------------------------------------------------

class TestRunCmd:
    def test_timeout(self, handler, tmp_path):
        """Timeout → success=False."""
        with patch(
            "elder_berry.comms.commands.process_commands.subprocess.run",
            side_effect=__import__("subprocess").TimeoutExpired(cmd=["x"], timeout=1),
        ):
            result = handler._run_cmd(["x"], cwd=str(tmp_path), timeout=1)
        assert not result.success
        assert "timeout" in result.output.lower()

    def test_file_not_found(self, handler, tmp_path):
        """FileNotFoundError → success=False."""
        with patch(
            "elder_berry.comms.commands.process_commands.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = handler._run_cmd(["nonexistent_cmd"], cwd=str(tmp_path))
        assert not result.success
        assert "nicht gefunden" in result.output.lower()

    def test_success(self, handler, tmp_path):
        """Erfolgreicher Befehl → success=True."""
        with patch(
            "elder_berry.comms.commands.process_commands.subprocess.run",
            return_value=_make_run_result(True, "hello\n"),
        ):
            result = handler._run_cmd(["echo", "hello"], cwd=str(tmp_path))
        assert result.success
        assert "hello" in result.output

    def test_cmd_result_dataclass(self):
        """_CmdResult DTO korrekt initialisiert."""
        r = _CmdResult(success=True, output="test")
        assert r.success
        assert r.output == "test"
