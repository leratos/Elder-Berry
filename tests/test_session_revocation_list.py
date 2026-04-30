"""Tests fuer SessionRevocationList (Phase 70 H-1)."""

from __future__ import annotations

import json

import pytest

from elder_berry.web.session_revocation_list import SessionRevocationList


class TestRevoke:
    def test_revoke_marks_cookie(self) -> None:
        rl = SessionRevocationList()
        rl.revoke("cookie-abc", expires_at=1000.0, now=500.0)
        assert rl.is_revoked("cookie-abc", now=500.0) is True

    def test_unknown_cookie_not_revoked(self) -> None:
        rl = SessionRevocationList()
        assert rl.is_revoked("never-seen", now=500.0) is False

    def test_already_expired_revoke_is_noop(self) -> None:
        rl = SessionRevocationList()
        # exp <= now -> Eintrag wird gar nicht erst aufgenommen
        rl.revoke("cookie", expires_at=500.0, now=500.0)
        assert rl.is_revoked("cookie", now=500.0) is False
        assert len(rl) == 0

    def test_revoke_drops_after_expiry(self) -> None:
        rl = SessionRevocationList()
        rl.revoke("cookie", expires_at=600.0, now=500.0)
        assert rl.is_revoked("cookie", now=550.0) is True
        # Nach exp -> nicht mehr revoked, Eintrag wird beim Lookup geputzt
        assert rl.is_revoked("cookie", now=700.0) is False

    def test_distinct_cookies_independent(self) -> None:
        rl = SessionRevocationList()
        rl.revoke("cookie-a", expires_at=1000.0, now=500.0)
        assert rl.is_revoked("cookie-b", now=500.0) is False

    def test_hash_does_not_leak_cookie(self) -> None:
        """Wir wollen nie den Cookie selbst speichern."""
        rl = SessionRevocationList()
        rl.revoke("super-secret-token", expires_at=1000.0, now=500.0)
        # Internal-Map enthaelt nur den Hash
        keys = list(rl._entries.keys())
        assert keys
        for k in keys:
            assert "super-secret-token" not in k


class TestCleanup:
    def test_cleanup_runs_when_interval_passed(self) -> None:
        rl = SessionRevocationList(cleanup_interval_seconds=10)
        rl.revoke("cookie-a", expires_at=600.0, now=500.0)
        rl.revoke("cookie-b", expires_at=900.0, now=500.0)

        # Nach Ablauf von cookie-a + Cleanup-Intervall:
        # naechster is_revoked-Call triggert _maybe_cleanup
        rl.is_revoked("any", now=700.0)
        assert len(rl) == 1  # nur cookie-b uebrig

    def test_cleanup_skipped_within_interval(self) -> None:
        rl = SessionRevocationList(cleanup_interval_seconds=600)
        rl.revoke("cookie-a", expires_at=600.0, now=500.0)
        # Innerhalb des Intervalls: kein Cleanup, Eintrag bleibt liegen
        # bis er per Lookup angefasst wird.
        rl.is_revoked("foo", now=550.0)
        assert len(rl) == 1


class TestPersistence:
    def test_persists_to_file(self, tmp_path) -> None:
        path = tmp_path / "revocations.json"
        rl = SessionRevocationList(persist_path=path)
        rl.revoke("cookie", expires_at=9_999_999_999.0, now=1000.0)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert len(data) == 1

    def test_loads_from_existing_file(self, tmp_path) -> None:
        path = tmp_path / "revocations.json"
        rl1 = SessionRevocationList(persist_path=path)
        rl1.revoke("cookie", expires_at=9_999_999_999.0, now=1000.0)
        # Neue Instanz auf gleicher Datei -> Eintrag vorhanden
        rl2 = SessionRevocationList(persist_path=path)
        assert rl2.is_revoked("cookie", now=1000.0) is True

    def test_load_drops_expired_entries(self, tmp_path) -> None:
        path = tmp_path / "revocations.json"
        # Datei mit abgelaufenem + gueltigem Eintrag manuell befuellen
        import hashlib

        digest_old = hashlib.sha256(b"old").hexdigest()
        digest_new = hashlib.sha256(b"new").hexdigest()
        path.write_text(
            json.dumps({digest_old: 100.0, digest_new: 9_999_999_999.0}),
            encoding="utf-8",
        )
        rl = SessionRevocationList(persist_path=path)
        # Abgelaufener Eintrag muss beim Load weg sein
        assert rl.is_revoked("old", now=1000.0) is False
        assert rl.is_revoked("new", now=1000.0) is True

    def test_corrupt_file_starts_empty(self, tmp_path) -> None:
        path = tmp_path / "revocations.json"
        path.write_text("not-json{{", encoding="utf-8")
        rl = SessionRevocationList(persist_path=path)
        assert len(rl) == 0

    def test_missing_file_starts_empty(self, tmp_path) -> None:
        path = tmp_path / "subdir" / "revocations.json"
        rl = SessionRevocationList(persist_path=path)
        assert len(rl) == 0


class TestConstruction:
    def test_invalid_cleanup_interval(self) -> None:
        with pytest.raises(ValueError):
            SessionRevocationList(cleanup_interval_seconds=0)
