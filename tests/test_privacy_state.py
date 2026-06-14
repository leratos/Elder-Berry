"""Tests für PrivacyState – geräteweiter Lokaler-Modus-Schalter (Phase 98)."""

from elder_berry.core.privacy_state import PrivacyState


class TestPrivacyState:
    def test_default_disabled(self):
        assert PrivacyState().is_enabled is False

    def test_explicit_enabled_constructor(self):
        assert PrivacyState(enabled=True).is_enabled is True

    def test_enable(self):
        state = PrivacyState()
        state.enable()
        assert state.is_enabled is True

    def test_disable(self):
        state = PrivacyState(enabled=True)
        state.disable()
        assert state.is_enabled is False

    def test_enable_is_idempotent(self):
        state = PrivacyState(enabled=True)
        state.enable()
        assert state.is_enabled is True

    def test_toggle_returns_new_state(self):
        state = PrivacyState()
        assert state.toggle() is True
        assert state.is_enabled is True
        assert state.toggle() is False
        assert state.is_enabled is False
