"""Tests für DashboardAuthManager (Phase 58)."""

from __future__ import annotations


import pytest

from elder_berry.web.dashboard_auth import (
    COOKIE_NAME,
    PASSWORD_HASH_KEY,
    SESSION_SECRET_KEY,
    DashboardAuthManager,
    InvalidSessionError,
    PasswordNotSetError,
)


class _FakeStore:
    """In-Memory-SecretStore für Tests."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get_or_none(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def has(self, key: str) -> bool:
        return key in self._data


@pytest.fixture
def store() -> _FakeStore:
    return _FakeStore()


@pytest.fixture
def auth(store: _FakeStore) -> DashboardAuthManager:
    return DashboardAuthManager(store)


# -- Constructor / TTL ----------------------------------------------- #

class TestConstructor:
    def test_default_ttl_is_12h(self, auth: DashboardAuthManager) -> None:
        assert auth.ttl_seconds == 12 * 3600

    def test_custom_ttl(self, store: _FakeStore) -> None:
        a = DashboardAuthManager(store, ttl_hours=24)
        assert a.ttl_seconds == 24 * 3600

    def test_ttl_too_low_raises(self, store: _FakeStore) -> None:
        with pytest.raises(ValueError):
            DashboardAuthManager(store, ttl_hours=0)

    def test_ttl_too_high_raises(self, store: _FakeStore) -> None:
        with pytest.raises(ValueError):
            DashboardAuthManager(store, ttl_hours=200)


# -- Password Management --------------------------------------------- #

class TestPasswordManagement:
    def test_is_password_set_false_initially(
        self, auth: DashboardAuthManager
    ) -> None:
        assert auth.is_password_set() is False

    def test_set_and_verify_password(
        self, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("supersecret123")
        assert auth.is_password_set() is True
        assert auth.verify_password("supersecret123") is True

    def test_verify_wrong_password(
        self, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("supersecret123")
        assert auth.verify_password("wrong") is False

    def test_password_too_short_raises(
        self, auth: DashboardAuthManager
    ) -> None:
        with pytest.raises(ValueError):
            auth.set_password("short")

    def test_empty_password_raises(
        self, auth: DashboardAuthManager
    ) -> None:
        with pytest.raises(ValueError):
            auth.set_password("")

    def test_password_too_long_raises(
        self, auth: DashboardAuthManager
    ) -> None:
        with pytest.raises(ValueError):
            auth.set_password("a" * 73)

    def test_unicode_password_within_72_bytes(
        self, auth: DashboardAuthManager
    ) -> None:
        # "ä" = 2 bytes UTF-8 → 36 chars × 2 = 72 Bytes
        pw = "ä" * 36
        auth.set_password(pw)
        assert auth.verify_password(pw) is True

    def test_verify_without_password_raises(
        self, auth: DashboardAuthManager
    ) -> None:
        with pytest.raises(PasswordNotSetError):
            auth.verify_password("anything")

    def test_password_hash_stored_in_secretstore(
        self, auth: DashboardAuthManager, store: _FakeStore,
    ) -> None:
        auth.set_password("supersecret123")
        stored = store.get_or_none(PASSWORD_HASH_KEY)
        assert stored is not None
        assert stored.startswith("$2b$")  # bcrypt-Format

    def test_overwriting_password_works(
        self, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("original123")
        auth.set_password("changed123")
        assert auth.verify_password("changed123") is True
        assert auth.verify_password("original123") is False


# -- Session-Cookie -------------------------------------------------- #

class TestSessionCookie:
    def test_issue_session_returns_cookie_and_exp(
        self, auth: DashboardAuthManager
    ) -> None:
        cookie, exp = auth.issue_session(now=1000)
        assert "." in cookie
        assert exp == 1000 + auth.ttl_seconds

    def test_verify_valid_session(
        self, auth: DashboardAuthManager
    ) -> None:
        cookie, _ = auth.issue_session(now=1000)
        payload = auth.verify_session(cookie, now=1100)
        assert payload["iat"] == 1000
        assert payload["exp"] == 1000 + auth.ttl_seconds

    def test_verify_expired_session_raises(
        self, auth: DashboardAuthManager
    ) -> None:
        cookie, exp = auth.issue_session(now=1000)
        with pytest.raises(InvalidSessionError):
            auth.verify_session(cookie, now=exp + 1)

    def test_verify_empty_cookie_raises(
        self, auth: DashboardAuthManager
    ) -> None:
        with pytest.raises(InvalidSessionError):
            auth.verify_session(None)
        with pytest.raises(InvalidSessionError):
            auth.verify_session("")

    def test_verify_malformed_cookie_raises(
        self, auth: DashboardAuthManager
    ) -> None:
        with pytest.raises(InvalidSessionError):
            auth.verify_session("notvalid")

    def test_tampered_signature_rejected(
        self, auth: DashboardAuthManager
    ) -> None:
        cookie, _ = auth.issue_session(now=1000)
        payload, sig = cookie.rsplit(".", 1)
        tampered = f"{payload}.AAAA{sig[4:]}"
        with pytest.raises(InvalidSessionError):
            auth.verify_session(tampered, now=1100)

    def test_tampered_payload_rejected(
        self, auth: DashboardAuthManager
    ) -> None:
        cookie, _ = auth.issue_session(now=1000)
        _, sig = cookie.rsplit(".", 1)
        # Anderes Payload, alte Signatur → muss scheitern
        import base64
        import json
        new_payload = json.dumps(
            {"iat": 1000, "exp": 9999999999}, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        encoded = base64.urlsafe_b64encode(new_payload).rstrip(b"=").decode("ascii")
        tampered = f"{encoded}.{sig}"
        with pytest.raises(InvalidSessionError):
            auth.verify_session(tampered, now=1100)

    def test_cookie_from_other_secret_rejected(
        self, store: _FakeStore
    ) -> None:
        a1 = DashboardAuthManager(store)
        cookie, _ = a1.issue_session(now=1000)
        # Secret rotieren → altes Cookie ungültig
        a1.rotate_session_secret()
        with pytest.raises(InvalidSessionError):
            a1.verify_session(cookie, now=1100)

    def test_session_secret_auto_generated(
        self, auth: DashboardAuthManager, store: _FakeStore,
    ) -> None:
        assert store.get_or_none(SESSION_SECRET_KEY) is None
        auth.issue_session(now=1000)
        assert store.get_or_none(SESSION_SECRET_KEY) is not None

    def test_session_secret_persists_across_calls(
        self, auth: DashboardAuthManager, store: _FakeStore,
    ) -> None:
        auth.issue_session(now=1000)
        first = store.get_or_none(SESSION_SECRET_KEY)
        auth.issue_session(now=2000)
        second = store.get_or_none(SESSION_SECRET_KEY)
        assert first == second


# -- Sliding Renewal ------------------------------------------------- #

class TestExtendSession:
    def test_extend_returns_new_cookie_with_later_exp(
        self, auth: DashboardAuthManager
    ) -> None:
        cookie, original_exp = auth.issue_session(now=1000)
        new_cookie, new_exp = auth.extend_session(cookie, now=5000)
        assert new_exp > original_exp
        assert new_exp == 5000 + auth.ttl_seconds

    def test_extend_expired_session_raises(
        self, auth: DashboardAuthManager
    ) -> None:
        cookie, exp = auth.issue_session(now=1000)
        with pytest.raises(InvalidSessionError):
            auth.extend_session(cookie, now=exp + 1)


# -- Constants ------------------------------------------------------- #

class TestConstants:
    def test_cookie_name_is_eb_prefixed(self) -> None:
        assert COOKIE_NAME == "eb_dashboard_session"
