"""Tests für Phase 51.2 (Did-you-mean) und 51.3 (Füllwort-Stripping)."""

from __future__ import annotations


from elder_berry.comms.remote_commands import RemoteCommandHandler


class TestFillerWordStripping:
    """Phase 51.3 – Füllwörter am Satzanfang dürfen Commands nicht blockieren."""

    def setup_method(self) -> None:
        self.handler = RemoteCommandHandler()

    def test_kannst_du_status(self) -> None:
        assert self.handler.parse_command("kannst du status zeigen") == "status"

    def test_zeig_mir_termine(self) -> None:
        # "termine" ist ein Simple-Command
        assert self.handler.parse_command("zeig mir termine") == "termine"

    def test_bitte_wetter(self) -> None:
        assert self.handler.parse_command("bitte wetter") == "wetter"

    def test_check_mal_status(self) -> None:
        assert self.handler.parse_command("check mal status") == "status"

    def test_kombinierte_floskeln(self) -> None:
        # "kannst du mir mal" + "bitte" → alles entfernt → "status"
        assert self.handler.parse_command("kannst du mir mal bitte status") == "status"

    def test_filler_leaves_real_word_untouched(self) -> None:
        # Keine Füllwörter → kein Effekt
        assert self.handler.parse_command("status") == "status"

    def test_filler_without_command_returns_none(self) -> None:
        # Nur Füllwörter + Unsinn → kein Command
        assert self.handler.parse_command("bitte quatsch unsinn") is None

    def test_mal_allein_keine_kollision(self) -> None:
        # "mal" als Füllwort darf nicht "mail" triggern
        result = self.handler.parse_command("mal")
        # Entweder None oder ein bewusst gematched Command – NICHT "mail"
        assert result != "mail"


class TestDidYouMean:
    """Phase 51.2 – Tippfehler-Erkennung via difflib."""

    def setup_method(self) -> None:
        self.handler = RemoteCommandHandler()

    def test_typo_statsu(self) -> None:
        suggestion = self.handler.suggest_command("statsu")
        assert suggestion is not None
        assert "status" in suggestion.lower()

    def test_typo_screnshot(self) -> None:
        suggestion = self.handler.suggest_command("screnshot")
        assert suggestion is not None
        assert "screenshot" in suggestion.lower()

    def test_exact_command_no_suggestion(self) -> None:
        # Wenn das erste Token schon ein echter Command ist → kein Vorschlag
        assert self.handler.suggest_command("status") is None

    def test_short_word_no_suggestion(self) -> None:
        # Zu kurz (<4 Zeichen) → kein Vorschlag, würde sonst alles triggern
        assert self.handler.suggest_command("abc") is None

    def test_long_sentence_no_suggestion(self) -> None:
        # Ganze Sätze gehen ans LLM, nicht an did-you-mean
        assert (
            self.handler.suggest_command("was denkst du über das wetter heute") is None
        )

    def test_unrelated_word_no_suggestion(self) -> None:
        # "xylophon" ist keinem Command ähnlich genug
        assert self.handler.suggest_command("xylophon") is None

    def test_suggestion_mentions_hilfe(self) -> None:
        suggestion = self.handler.suggest_command("statsu")
        assert suggestion is not None
        assert "hilfe" in suggestion.lower()
