"""Tests für die kanonische LLM-Modi-Quelle (elder_berry.llm.modes)."""

from elder_berry.llm.modes import (
    DEFAULT_LLM_MODE,
    LLM_MODE_KEY,
    LLM_MODE_LABELS,
    LLM_MODES,
    llm_mode_options,
    normalize_llm_mode,
)


class TestCanonicalConstants:
    def test_modes_are_the_three_canonical(self):
        assert LLM_MODES == ("api_preferred", "local_preferred", "local_only")

    def test_default_is_api_preferred(self):
        assert DEFAULT_LLM_MODE == "api_preferred"
        assert DEFAULT_LLM_MODE in LLM_MODES

    def test_every_mode_has_a_label(self):
        assert set(LLM_MODE_LABELS) == set(LLM_MODES)

    def test_mode_key_is_llm_mode(self):
        assert LLM_MODE_KEY == "llm_mode"


class TestNormalizeLlmMode:
    def test_valid_modes_pass_through(self):
        for mode in LLM_MODES:
            assert normalize_llm_mode(mode) == mode

    def test_legacy_fallback_only_maps_to_local_only(self):
        assert normalize_llm_mode("fallback_only") == "local_only"

    def test_unknown_returns_none(self):
        assert normalize_llm_mode("turbo") is None

    def test_none_returns_none(self):
        assert normalize_llm_mode(None) is None

    def test_whitespace_is_trimmed(self):
        assert normalize_llm_mode("  api_preferred  ") == "api_preferred"

    def test_empty_string_returns_none(self):
        assert normalize_llm_mode("") is None


class TestLlmModeOptions:
    def test_options_match_modes_in_order(self):
        options = llm_mode_options()
        assert [opt["value"] for opt in options] == list(LLM_MODES)

    def test_each_option_has_value_and_label(self):
        for opt in llm_mode_options():
            assert opt["value"] in LLM_MODES
            assert opt["label"] == LLM_MODE_LABELS[opt["value"]]
