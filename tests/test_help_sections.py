"""Tests für Phase 51.1 – Kategorisierte Hilfe (help_sections.py)."""
from __future__ import annotations


from elder_berry.comms.commands.help_sections import (
    CATEGORY_LABELS,
    HELP_SECTIONS,
    build_full_help,
    build_overview,
    get_section,
)
from elder_berry.comms.remote_commands import (
    HELP_OVERVIEW,
    HELP_TEXT,
    RemoteCommandHandler,
)


class TestHelpSectionsData:
    def test_every_category_has_section(self) -> None:
        for key in CATEGORY_LABELS:
            assert key in HELP_SECTIONS, f"Kategorie '{key}' hat keinen Text"
            assert HELP_SECTIONS[key].strip(), f"Leerer Text für '{key}'"

    def test_overview_lists_all_categories(self) -> None:
        overview = build_overview()
        for key in CATEGORY_LABELS:
            assert f"hilfe {key}" in overview
        assert "hilfe alles" in overview

    def test_full_help_contains_key_commands(self) -> None:
        full = build_full_help()
        for needle in [
            "status",
            "screenshot",
            "termine",
            "wetter",
            "claude",
            "pdf ocr",
            "harmony",
            "update",
        ]:
            assert needle in full.lower(), f"'{needle}' fehlt im Volltext"

    def test_get_section_unknown_returns_none(self) -> None:
        assert get_section("nonexistent") is None

    def test_get_section_case_insensitive(self) -> None:
        assert get_section("KALENDER") is not None
        assert get_section("Kalender") is not None


class TestParseHelpSubcommands:
    def setup_method(self) -> None:
        self.handler = RemoteCommandHandler()

    def test_plain_hilfe(self) -> None:
        assert self.handler.parse_command("hilfe") == "hilfe"
        assert self.handler.parse_command("help") == "hilfe"

    def test_hilfe_alles(self) -> None:
        assert self.handler.parse_command("hilfe alles") == "hilfe:alles"
        assert self.handler.parse_command("help alles") == "hilfe:alles"

    def test_hilfe_category(self) -> None:
        assert self.handler.parse_command("hilfe kalender") == "hilfe:kalender"
        assert self.handler.parse_command("hilfe mail") == "hilfe:mail"
        assert self.handler.parse_command("hilfe smart-home") == "hilfe:smart-home"

    def test_hilfe_unknown_category(self) -> None:
        result = self.handler.parse_command("hilfe quatsch")
        assert result == "hilfe:?quatsch"

    def test_hilfe_after_filler_prefix(self) -> None:
        # Phase 51.3: Füllwörter vor hilfe sollen ignoriert werden
        assert self.handler.parse_command("bitte hilfe kalender") == "hilfe:kalender"


class TestHelpOverviewConstant:
    def test_help_overview_is_short(self) -> None:
        # Overview soll deutlich kürzer sein als der Volltext
        assert len(HELP_OVERVIEW) < len(HELP_TEXT) / 5
        assert len(HELP_OVERVIEW.splitlines()) < 25
