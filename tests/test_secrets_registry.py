"""Tests für secrets_registry – Select-Validierung + kanonische LLM-Optionen.

Phase 98: ``validate_secret`` erzwingt jetzt Select-Werte gegen die
Registry-Optionen, und die llm_mode-Optionen stammen aus der einen Quelle
``elder_berry.llm.modes``.
"""

import pytest

from elder_berry.llm.modes import LLM_MODES, llm_mode_options
from elder_berry.web.secrets_registry import _REGISTRY_BY_KEY, validate_secret


class TestLlmModeRegistryEntry:
    def test_options_come_from_canonical_source(self):
        entry = _REGISTRY_BY_KEY["llm_mode"]
        assert entry["select_options"] == llm_mode_options()

    def test_no_restart_required(self):
        # Phase 98: live anwendbar → kein Neustart mehr.
        assert _REGISTRY_BY_KEY["llm_mode"].get("requires_restart") is False


class TestSelectValidation:
    def test_accepts_all_canonical_modes(self):
        for mode in LLM_MODES:
            validate_secret("llm_mode", mode)  # darf nicht werfen

    def test_rejects_unknown_select_value(self):
        with pytest.raises(ValueError, match="erlaubten Optionen"):
            validate_secret("llm_mode", "turbo")

    def test_rejects_legacy_value_on_write(self):
        # fallback_only ist kein kanonischer Wert mehr – Schreiben verboten
        # (Read-Back normalisiert Altbestände separat).
        with pytest.raises(ValueError):
            validate_secret("llm_mode", "fallback_only")
