"""Tests fuer PathGuard -- Allow-List-basierte Pfad-Validierung.

Verhindert Path-Traversal in Matrix-Commands (Phase 69 Security-Fix).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

from elder_berry.core.path_guard import EB_ALLOWED_PATHS_ENV, PathGuard


# ---------------------------------------------------------------------------
# Konstruktion
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_empty_bases_raises(self) -> None:
        with pytest.raises(ValueError):
            PathGuard([])

    def test_normalizes_bases(self, tmp_path: Path) -> None:
        guard = PathGuard([str(tmp_path)])
        # tmp_path ist bereits absolut + resolved -- aber expanduser/resolve
        # darf das Ergebnis nicht veraendern.
        assert tmp_path.resolve() in guard.allowed_bases

    def test_invalid_base_skipped(self, tmp_path: Path) -> None:
        # Ein Null-Byte-Pfad wirft ValueError beim resolve -- der Guard
        # muss ihn ueberspringen, aber der gueltige tmp_path bleibt.
        guard = PathGuard([str(tmp_path), "\x00invalid"])
        assert tmp_path.resolve() in guard.allowed_bases
        assert len(guard.allowed_bases) == 1


# ---------------------------------------------------------------------------
# validate() -- happy path
# ---------------------------------------------------------------------------


class TestValidateAllowed:
    def test_inside_base_returns_resolved(self, tmp_path: Path) -> None:
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF")
        guard = PathGuard([tmp_path])
        result = guard.validate(str(f))
        assert result == f.resolve()

    def test_inside_subdir_works(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub" / "deep"
        sub.mkdir(parents=True)
        f = sub / "doc.pdf"
        f.write_bytes(b"%PDF")
        guard = PathGuard([tmp_path])
        assert guard.validate(str(f)) == f.resolve()

    def test_path_object_accepted(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("hi")
        guard = PathGuard([tmp_path])
        assert guard.validate(f) == f.resolve()


# ---------------------------------------------------------------------------
# validate() -- rejection
# ---------------------------------------------------------------------------


class TestValidateRejected:
    def test_outside_base_raises_permission_error(
        self,
        tmp_path: Path,
    ) -> None:
        # tmp_path als einzige Base, aber Datei liegt im *Eltern*-Verzeichnis.
        outside_dir = tmp_path.parent
        outside_file = outside_dir / "outside_file.txt"
        outside_file.write_text("secret")
        try:
            guard = PathGuard([tmp_path])
            with pytest.raises(PermissionError):
                guard.validate(str(outside_file))
        finally:
            outside_file.unlink(missing_ok=True)

    def test_dotdot_traversal_blocked(self, tmp_path: Path) -> None:
        # base/sub/ erlaubt; base/secret.txt ist *ausserhalb* von base/sub.
        sub = tmp_path / "sub"
        sub.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("top-secret")
        guard = PathGuard([sub])
        traversal = sub / ".." / "secret.txt"
        with pytest.raises(PermissionError):
            guard.validate(str(traversal))

    def test_empty_string_raises_permission_error(self, tmp_path: Path) -> None:
        guard = PathGuard([tmp_path])
        with pytest.raises(PermissionError):
            guard.validate("")

    def test_nonexistent_raises_filenotfound(self, tmp_path: Path) -> None:
        # FileNotFoundError ist ein *Caller-Hint*, kein Security-Reject:
        # der Caller darf einen Remote-Fallback (z.B. NC) versuchen.
        guard = PathGuard([tmp_path])
        with pytest.raises(FileNotFoundError):
            guard.validate(str(tmp_path / "does_not_exist.pdf"))

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Symlink-Erstellung auf Windows benoetigt Admin/Developer-Mode",
    )
    def test_symlink_escape_blocked(self, tmp_path: Path) -> None:
        # base = tmp_path/safe; Symlink in base zeigt auf Datei *ausserhalb*.
        safe = tmp_path / "safe"
        safe.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        link = safe / "escape_link"
        os.symlink(outside, link)

        guard = PathGuard([safe])
        with pytest.raises(PermissionError):
            guard.validate(str(link))


# ---------------------------------------------------------------------------
# Default-Konstruktion
# ---------------------------------------------------------------------------


class TestDefault:
    def test_default_includes_tempdir(self) -> None:
        # tempdir + CWD sind praktisch immer vorhanden -> Default muss
        # mindestens einen davon enthalten.
        guard = PathGuard.default()
        bases_str = [str(b) for b in guard.allowed_bases]
        tempdir = str(Path(tempfile.gettempdir()).resolve())
        assert any(tempdir in b for b in bases_str)

    def test_default_validates_file_in_tempdir(self, tmp_path: Path) -> None:
        # tmp_path liegt unter tempfile.gettempdir() (pytest-Default).
        # PathGuard.default() muss eine Datei dort akzeptieren.
        f = tmp_path / "ok.txt"
        f.write_text("ok")
        guard = PathGuard.default()
        # Kein Raise erwartet:
        result = guard.validate(str(f))
        assert result == f.resolve()


# ---------------------------------------------------------------------------
# Env-Override
# ---------------------------------------------------------------------------


class TestEnvOverride:
    def test_env_override_replaces_defaults(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Nur tmp_path erlaubt -- tempdir + Home werden ignoriert.
        monkeypatch.setenv(EB_ALLOWED_PATHS_ENV, str(tmp_path))
        guard = PathGuard.default()
        assert guard.allowed_bases == (tmp_path.resolve(),)

    def test_env_override_multiple_paths(
        self,
        tmp_path: Path,
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        second = tmp_path_factory.mktemp("second_base")
        env_value = os.pathsep.join([str(tmp_path), str(second)])
        monkeypatch.setenv(EB_ALLOWED_PATHS_ENV, env_value)
        guard = PathGuard.default()
        assert tmp_path.resolve() in guard.allowed_bases
        assert second.resolve() in guard.allowed_bases

    def test_env_override_empty_falls_through_to_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Leerer Env-Wert -> normale Defaults (kein ValueError).
        monkeypatch.setenv(EB_ALLOWED_PATHS_ENV, "")
        guard = PathGuard.default()
        assert len(guard.allowed_bases) >= 1


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestSecurityLogging:
    def test_rejection_logs_to_security_logger(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Audit-Events sollen an "elder_berry.security" gehen, damit sie
        # in logs/security.log landen (Phase 59-Konvention).
        outside = tmp_path.parent / "outside_audit.txt"
        outside.write_text("x")
        try:
            guard = PathGuard([tmp_path])
            with caplog.at_level("WARNING", logger="elder_berry.security"):
                with pytest.raises(PermissionError):
                    guard.validate(str(outside))
            assert any(rec.name == "elder_berry.security" for rec in caplog.records)
        finally:
            outside.unlink(missing_ok=True)

    def test_empty_path_logs_to_security_logger(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        guard = PathGuard([tmp_path])
        with caplog.at_level("WARNING", logger="elder_berry.security"):
            with pytest.raises(PermissionError):
                guard.validate("")
        assert any(rec.name == "elder_berry.security" for rec in caplog.records)
