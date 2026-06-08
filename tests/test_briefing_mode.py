"""Tests für den BriefingModeProvider-Stub (Phase 83.6)."""

from __future__ import annotations

from elder_berry.avatar.briefing_mode import (
    BriefingModeProvider,
    CasualBriefingModeProvider,
)


class TestCasualBriefingModeProvider:
    def test_is_briefing_mode_provider(self):
        assert isinstance(CasualBriefingModeProvider(), BriefingModeProvider)

    def test_always_casual(self):
        # Default: kein formeller Modus (echtes Bot→RPi5-Wiring = Folgephase).
        assert CasualBriefingModeProvider().is_formal() is False
