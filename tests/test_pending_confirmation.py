"""Tests für PendingConfirmationStore."""
from __future__ import annotations

import time


from elder_berry.comms.pending_confirmation import (
    DEFAULT_TTL_SECONDS,
    PendingAction,
    PendingConfirmationStore,
)


# ---------------------------------------------------------------------------
# PendingAction
# ---------------------------------------------------------------------------

class TestPendingAction:
    def test_not_expired_within_ttl(self):
        action = PendingAction(
            action_type="mail_reply", description="test", ttl=300,
        )
        assert action.is_expired is False

    def test_expired_after_ttl(self):
        action = PendingAction(
            action_type="mail_reply", description="test",
            created_at=time.time() - 400, ttl=300,
        )
        assert action.is_expired is True

    def test_default_ttl(self):
        action = PendingAction(action_type="x", description="y")
        assert action.ttl == DEFAULT_TTL_SECONDS


# ---------------------------------------------------------------------------
# PendingConfirmationStore – set/get/clear
# ---------------------------------------------------------------------------

class TestStoreBasics:
    def test_set_and_get(self):
        store = PendingConfirmationStore()
        action = PendingAction(action_type="mail_reply", description="d")
        store.set("@user:mx", action)
        assert store.get("@user:mx") is action

    def test_get_none_when_empty(self):
        store = PendingConfirmationStore()
        assert store.get("@nobody:mx") is None

    def test_get_none_when_expired(self):
        store = PendingConfirmationStore()
        action = PendingAction(
            action_type="x", description="y",
            created_at=time.time() - 600, ttl=300,
        )
        store.set("@user:mx", action)
        assert store.get("@user:mx") is None

    def test_clear(self):
        store = PendingConfirmationStore()
        action = PendingAction(action_type="x", description="y")
        store.set("@user:mx", action)
        store.clear("@user:mx")
        assert store.get("@user:mx") is None

    def test_overwrite_existing(self):
        store = PendingConfirmationStore()
        a1 = PendingAction(action_type="first", description="1")
        a2 = PendingAction(action_type="second", description="2")
        store.set("@user:mx", a1)
        store.set("@user:mx", a2)
        assert store.get("@user:mx").action_type == "second"

    def test_multiple_users_independent(self):
        store = PendingConfirmationStore()
        a1 = PendingAction(action_type="x", description="a")
        store.set("@alice:mx", a1)
        assert store.get("@alice:mx") is a1
        assert store.get("@bob:mx") is None


# ---------------------------------------------------------------------------
# check_response
# ---------------------------------------------------------------------------

class TestCheckResponse:
    def _store_with_action(self):
        store = PendingConfirmationStore()
        action = PendingAction(
            action_type="mail_reply", description="d",
            data={"msg_id": "123"},
        )
        store.set("@user:mx", action)
        return store, action

    def test_confirm(self):
        store, action = self._store_with_action()
        rtype, act = store.check_response("@user:mx", "ja")
        assert rtype == "confirm"
        assert act is action
        # Action wird NICHT gelöscht bei confirm (Bridge macht das)
        assert store.get("@user:mx") is action

    def test_confirm_variants(self):
        for word in ("ja", "yes", "senden", "ok", "passt", "abschicken"):
            store, _ = self._store_with_action()
            rtype, _ = store.check_response("@user:mx", word)
            assert rtype == "confirm", f"'{word}' should be confirm"

    def test_cancel(self):
        store, action = self._store_with_action()
        rtype, act = store.check_response("@user:mx", "nein")
        assert rtype == "cancel"
        assert act is action
        # Cancel löscht sofort
        assert store.get("@user:mx") is None

    def test_cancel_variants(self):
        for word in ("nein", "no", "abbrechen", "cancel", "verwerfen", "stopp"):
            store, _ = self._store_with_action()
            rtype, _ = store.check_response("@user:mx", word)
            assert rtype == "cancel", f"'{word}' should be cancel"

    def test_modify(self):
        store, action = self._store_with_action()
        rtype, act = store.check_response("@user:mx", "ändern: formeller")
        assert rtype == "modify"
        assert act.data["modify_instruction"] == "formeller"

    def test_modify_preserves_action(self):
        store, _ = self._store_with_action()
        store.check_response("@user:mx", "ändern: kürzer")
        # Action bleibt offen
        assert store.get("@user:mx") is not None

    def test_pending_other_text(self):
        store, action = self._store_with_action()
        rtype, act = store.check_response("@user:mx", "hallo welt")
        assert rtype == "pending"
        assert act is action

    def test_none_when_empty(self):
        store = PendingConfirmationStore()
        rtype, act = store.check_response("@user:mx", "ja")
        assert rtype == "none"
        assert act is None

    def test_none_when_expired(self):
        store = PendingConfirmationStore()
        action = PendingAction(
            action_type="x", description="y",
            created_at=time.time() - 600, ttl=300,
        )
        store.set("@user:mx", action)
        rtype, act = store.check_response("@user:mx", "ja")
        assert rtype == "none"
        assert act is None
