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


# ---------------------------------------------------------------------------
# Phase 70 (H-4): Absolute Lifetime Cap
# ---------------------------------------------------------------------------


class TestAbsoluteLifetimeCap:
    def test_default_cap_is_24h(self, auth: DashboardAuthManager) -> None:
        assert auth.max_absolute_lifetime_seconds == 24 * 3600

    def test_cap_too_low_raises(self, store: _FakeStore) -> None:
        with pytest.raises(ValueError):
            DashboardAuthManager(store, max_absolute_lifetime_hours=0)

    def test_cap_smaller_than_ttl_raises(self, store: _FakeStore) -> None:
        # ttl=12 h, cap=1 h -> Cookie waere sofort ueber dem Cap
        with pytest.raises(ValueError):
            DashboardAuthManager(
                store, ttl_hours=12, max_absolute_lifetime_hours=1,
            )

    def test_issue_session_writes_iat_original(
        self, auth: DashboardAuthManager,
    ) -> None:
        cookie, _ = auth.issue_session(now=1000)
        payload = auth.verify_session(cookie, now=1100)
        assert payload["iat_original"] == 1000
        assert payload["iat"] == 1000

    def test_session_within_cap_passes(
        self, store: _FakeStore,
    ) -> None:
        auth = DashboardAuthManager(
            store, ttl_hours=24, max_absolute_lifetime_hours=24,
        )
        cookie, _ = auth.issue_session(now=1000)
        # 23 h spaeter -- noch im Cap (auch noch innerhalb exp)
        payload = auth.verify_session(cookie, now=1000 + 23 * 3600 - 5)
        assert payload["iat_original"] == 1000

    def test_session_beyond_cap_rejected(
        self, store: _FakeStore,
    ) -> None:
        auth = DashboardAuthManager(
            store, ttl_hours=24, max_absolute_lifetime_hours=24,
        )
        # extend_session laeuft im selben "Login" und reicht iat_original
        # weiter -- nach 24 h ist die Session hart raus.
        cookie, _ = auth.issue_session(now=1000)
        cookie2, _ = auth.extend_session(cookie, now=1000 + 12 * 3600)
        # Auch nach Renewal: iat_original bleibt 1000
        payload = auth.verify_session(cookie2, now=1000 + 13 * 3600)
        assert payload["iat_original"] == 1000
        # Knapp ueber dem Cap -- 401
        with pytest.raises(InvalidSessionError, match="absoluten"):
            auth.verify_session(cookie2, now=1000 + 24 * 3600 + 1)

    def test_extend_preserves_iat_original(
        self, store: _FakeStore,
    ) -> None:
        auth = DashboardAuthManager(
            store, ttl_hours=1, max_absolute_lifetime_hours=24,
        )
        cookie, _ = auth.issue_session(now=1000)
        new_cookie, _ = auth.extend_session(cookie, now=2000)
        payload = auth.verify_session(new_cookie, now=2500)
        assert payload["iat_original"] == 1000  # NICHT 2000
        assert payload["iat"] == 2000

    def test_extend_beyond_cap_rejected(
        self, store: _FakeStore,
    ) -> None:
        auth = DashboardAuthManager(
            store, ttl_hours=4, max_absolute_lifetime_hours=8,
        )
        # Sliding-Renewals fuettern iat_original durch -- nach 6 h sind
        # wir noch im Cap, exp des frischesten Cookies waere 1000+10 h.
        cookie1, _ = auth.issue_session(now=1000)
        cookie2, _ = auth.extend_session(cookie1, now=1000 + 3 * 3600)
        cookie3, _ = auth.extend_session(cookie2, now=1000 + 6 * 3600)
        # 9 h nach dem ersten Login: exp=10 h ok, Cap=8 h -- muss raisen.
        with pytest.raises(InvalidSessionError, match="absoluten"):
            auth.extend_session(cookie3, now=1000 + 9 * 3600)

    def test_legacy_cookie_without_iat_original_fallback_to_iat(
        self, store: _FakeStore,
    ) -> None:
        """Migration: Cookies aus Phase-58/65 haben kein iat_original.

        Erwartung: Fallback auf ``iat`` -- so verlieren existierende
        Sessions beim Deploy nicht sofort den Zugang, sind aber
        spaetestens nach max_absolute_lifetime ausgeloggt.
        """
        import base64
        import hashlib
        import hmac
        import json

        auth = DashboardAuthManager(
            store, ttl_hours=8, max_absolute_lifetime_hours=8,
        )
        # Manuell ein Legacy-Cookie ohne iat_original erzeugen
        secret = auth._get_session_secret()
        # exp weit in der Zukunft, damit der exp-Check nicht vorher greift
        legacy_payload = {"iat": 1000, "exp": 1000 + 24 * 3600}
        payload_bytes = json.dumps(
            legacy_payload, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")
        digest = hmac.new(
            secret, encoded.encode("ascii"), hashlib.sha256,
        ).digest()
        sig = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        legacy_cookie = f"{encoded}.{sig}"

        # 5 h nach iat: noch im Cap (Cap = 8 h, Fallback iat=1000)
        payload = auth.verify_session(legacy_cookie, now=1000 + 5 * 3600)
        assert payload["iat"] == 1000
        assert "iat_original" not in payload

    def test_legacy_cookie_beyond_cap_rejected(
        self, store: _FakeStore,
    ) -> None:
        """Legacy-Cookie ohne iat_original wird auch durch den Cap erfasst."""
        import base64
        import hashlib
        import hmac
        import json

        auth = DashboardAuthManager(
            store, ttl_hours=8, max_absolute_lifetime_hours=8,
        )
        secret = auth._get_session_secret()
        # Legacy-Cookie mit iat=1000, sehr langem exp
        legacy_payload = {"iat": 1000, "exp": 1000 + 100 * 3600}
        payload_bytes = json.dumps(
            legacy_payload, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")
        digest = hmac.new(
            secret, encoded.encode("ascii"), hashlib.sha256,
        ).digest()
        sig = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        legacy_cookie = f"{encoded}.{sig}"

        # 9 h spaeter: ueber dem Cap (Fallback auf iat=1000)
        with pytest.raises(InvalidSessionError, match="absoluten"):
            auth.verify_session(legacy_cookie, now=1000 + 9 * 3600)


# ---------------------------------------------------------------------------
# Phase 70 (H-1): Server-side Revocation
# ---------------------------------------------------------------------------


class TestServerSideRevocation:
    def test_no_revocation_list_returns_false(
        self, auth: DashboardAuthManager,
    ) -> None:
        cookie, _ = auth.issue_session(now=1000)
        assert auth.revoke_session(cookie, now=1100) is False

    def test_revoke_then_verify_raises(self, store: _FakeStore) -> None:
        from elder_berry.web.session_revocation_list import SessionRevocationList

        rl = SessionRevocationList()
        auth = DashboardAuthManager(store, revocation_list=rl)
        cookie, _ = auth.issue_session(now=1000)
        # Vor revoke: ok
        auth.verify_session(cookie, now=1100)

        result = auth.revoke_session(cookie, now=1100)
        assert result is True

        # Nach revoke: 401
        with pytest.raises(InvalidSessionError, match="widerrufen"):
            auth.verify_session(cookie, now=1200)

    def test_revoke_invalid_cookie_returns_false(
        self, store: _FakeStore,
    ) -> None:
        from elder_berry.web.session_revocation_list import SessionRevocationList

        rl = SessionRevocationList()
        auth = DashboardAuthManager(store, revocation_list=rl)
        # Garbage-Cookie -- verify_session faellt durch, also wird
        # die Liste nicht angefasst.
        assert auth.revoke_session("garbage", now=1000) is False
        assert len(rl) == 0

    def test_revoke_empty_cookie_returns_false(
        self, store: _FakeStore,
    ) -> None:
        from elder_berry.web.session_revocation_list import SessionRevocationList

        auth = DashboardAuthManager(
            store, revocation_list=SessionRevocationList(),
        )
        assert auth.revoke_session(None) is False
        assert auth.revoke_session("") is False

    def test_other_session_unaffected_by_revoke(
        self, store: _FakeStore,
    ) -> None:
        from elder_berry.web.session_revocation_list import SessionRevocationList

        auth = DashboardAuthManager(
            store, revocation_list=SessionRevocationList(),
        )
        # Unterschiedliche iat -> unterschiedliche Cookie-Strings, sonst
        # waeren beide Cookies bytes-identisch und der gleiche Hash.
        cookie_a, _ = auth.issue_session(now=1000)
        cookie_b, _ = auth.issue_session(now=1001)
        assert cookie_a != cookie_b
        auth.revoke_session(cookie_a, now=1100)
        # cookie_b lebt weiter -- gezielter Single-Logout
        auth.verify_session(cookie_b, now=1200)
        with pytest.raises(InvalidSessionError):
            auth.verify_session(cookie_a, now=1200)

    def test_extend_session_blocked_after_revoke(
        self, store: _FakeStore,
    ) -> None:
        from elder_berry.web.session_revocation_list import SessionRevocationList

        auth = DashboardAuthManager(
            store, revocation_list=SessionRevocationList(),
        )
        cookie, _ = auth.issue_session(now=1000)
        auth.revoke_session(cookie, now=1100)
        with pytest.raises(InvalidSessionError, match="widerrufen"):
            auth.extend_session(cookie, now=1200)
