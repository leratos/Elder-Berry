"""Tests für SECRET_REGISTRY – Single Source of Truth (Phase 52.0).

Stellt sicher, dass:
- Keine doppelten Keys
- Alle vom Settings-Dashboard erwarteten Keys vorhanden sind
- Behavior-Einträge konsistent als non-sensitive markiert sind
- Alle Einträge gültige Pflichtfelder haben
- risk_level (falls gesetzt) gehört zu {low, medium, high}
- Konvertierung Registry → SettingDefinition funktioniert für alle
  Dashboard-Keys
"""

from __future__ import annotations

import pytest

try:
    from elder_berry.web.secrets_api import (
        SECRET_REGISTRY,
        _REGISTRY_BY_KEY,
        _VALID_KEY_RE,
    )
    from elder_berry.web.settings_dashboard import SettingsDashboard
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


class TestRegistryIntegrity:
    """Strukturelle Integrität der Registry."""

    def test_no_duplicate_keys(self):
        keys = [entry["key"] for entry in SECRET_REGISTRY]
        assert len(keys) == len(set(keys)), (
            f"Doppelte Keys gefunden: "
            f"{[k for k in keys if keys.count(k) > 1]}"
        )

    def test_all_keys_match_naming_pattern(self):
        for entry in SECRET_REGISTRY:
            assert _VALID_KEY_RE.match(entry["key"]), (
                f"Key '{entry['key']}' verletzt das Naming-Pattern."
            )

    def test_all_entries_have_required_fields(self):
        for entry in SECRET_REGISTRY:
            assert "key" in entry
            assert "label" in entry
            assert "category" in entry
            assert entry["label"], f"Leeres Label für {entry['key']}"
            assert entry["category"], f"Leere Kategorie für {entry['key']}"

    def test_risk_level_is_valid(self):
        valid = {"low", "medium", "high"}
        for entry in SECRET_REGISTRY:
            risk = entry.get("risk_level")
            if risk is not None:
                assert risk in valid, (
                    f"Ungültiges risk_level '{risk}' für {entry['key']}"
                )

    def test_registry_by_key_is_consistent(self):
        assert len(_REGISTRY_BY_KEY) == len(SECRET_REGISTRY)
        for entry in SECRET_REGISTRY:
            assert _REGISTRY_BY_KEY[entry["key"]] is entry


class TestBehaviorEntries:
    """Behavior-Settings (Phase 52)."""

    def test_behavior_entries_are_not_sensitive(self):
        for entry in SECRET_REGISTRY:
            if entry.get("behavior"):
                assert entry.get("sensitive", True) is False, (
                    f"Behavior-Setting '{entry['key']}' darf nicht "
                    f"sensitive=True sein."
                )

    def test_required_behavior_keys_present(self):
        keys = {e["key"] for e in SECRET_REGISTRY if e.get("behavior")}
        assert {"user_timezone", "stt_timeout", "llm_mode"}.issubset(keys)

    def test_select_options_for_select_types(self):
        # user_timezone bekommt die Optionen erst zur Laufzeit injiziert
        # (UI-spezifisch). llm_mode muss select_options in der Registry haben.
        llm = _REGISTRY_BY_KEY["llm_mode"]
        assert llm.get("type") == "select"
        options = llm.get("select_options") or []
        values = {opt["value"] for opt in options}
        assert {"api_preferred", "local_preferred", "fallback_only"} == values


class TestDashboardConsumption:
    """Settings-Dashboard nutzt die Registry korrekt."""

    def test_all_dashboard_keys_in_registry(self):
        for key in SettingsDashboard.DASHBOARD_SETTING_KEYS:
            assert key in _REGISTRY_BY_KEY, (
                f"Dashboard-Key '{key}' fehlt in SECRET_REGISTRY."
            )

    def test_dashboard_keys_have_label_and_category(self):
        for key in SettingsDashboard.DASHBOARD_SETTING_KEYS:
            entry = _REGISTRY_BY_KEY[key]
            assert entry.get("label")
            assert entry.get("category")

    def test_matrix_allowed_senders_is_high_risk(self):
        entry = _REGISTRY_BY_KEY["matrix_allowed_senders"]
        assert entry.get("risk_level") == "high"
        assert entry.get("type") == "textarea"


class TestRegistryToSettingDefinition:
    """Konvertierung Registry → SettingDefinition."""

    def _dashboard(self):
        from elder_berry.core.audio_router import AudioRouter
        return SettingsDashboard(audio_router=AudioRouter(local_available=True))

    def test_all_dashboard_definitions_buildable(self):
        dashboard = self._dashboard()
        defs = dashboard._setting_definitions()
        assert len(defs) == len(SettingsDashboard.DASHBOARD_SETTING_KEYS)
        keys = [d.key for d in defs]
        assert keys == list(SettingsDashboard.DASHBOARD_SETTING_KEYS)

    def test_timezone_definition_has_options(self):
        dashboard = self._dashboard()
        defs = {d.key: d for d in dashboard._setting_definitions()}
        tz = defs["user_timezone"]
        assert tz.type == "select"
        assert len(tz.options) > 0
        assert any(opt["value"] == "Europe/Berlin" for opt in tz.options)

    def test_llm_mode_definition_has_options(self):
        dashboard = self._dashboard()
        defs = {d.key: d for d in dashboard._setting_definitions()}
        llm = defs["llm_mode"]
        assert llm.type == "select"
        values = {opt["value"] for opt in llm.options}
        assert {"api_preferred", "local_preferred", "fallback_only"} == values
        assert llm.restart_required is True

    def test_stt_timeout_has_min_max(self):
        dashboard = self._dashboard()
        defs = {d.key: d for d in dashboard._setting_definitions()}
        stt = defs["stt_timeout"]
        assert stt.type == "number"
        assert stt.min_value == 5.0
        assert stt.max_value == 600.0

    def test_allowed_senders_marked_high_risk(self):
        dashboard = self._dashboard()
        defs = {d.key: d for d in dashboard._setting_definitions()}
        senders = defs["matrix_allowed_senders"]
        assert senders.type == "textarea"
        assert senders.risk_level == "high"
        assert senders.restart_required is True

    def test_behavior_definitions_not_marked_secret(self):
        dashboard = self._dashboard()
        defs = dashboard._setting_definitions()
        for d in defs:
            if d.key in ("user_timezone", "stt_timeout", "llm_mode"):
                assert d.secret is False
