"""Tests für den AttentionProvider-Stub (Phase 83.6 / §3.7)."""

from __future__ import annotations

from elder_berry.avatar.attention import (
    AttentionProvider,
    AttentionState,
    NoopAttentionProvider,
)


class TestAttentionState:
    def test_enum_values(self):
        assert AttentionState.UNKNOWN.value == "unknown"
        assert AttentionState.AWAY.value == "away"
        assert AttentionState.PRESENT.value == "present"
        assert AttentionState.FOCUSED.value == "focused"


class TestNoopAttentionProvider:
    def test_is_attention_provider(self):
        assert isinstance(NoopAttentionProvider(), AttentionProvider)

    def test_always_unknown(self):
        provider = NoopAttentionProvider()
        # Default-Stub liefert stabil UNKNOWN → Idle-Policy verhält sich sensorlos.
        assert provider.current() is AttentionState.UNKNOWN
        assert provider.current() is AttentionState.UNKNOWN
