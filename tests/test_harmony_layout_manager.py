"""Tests fuer HarmonyLayoutManager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elder_berry.robot.harmony_layout_manager import (
    HarmonyLayoutManager,
    _DEFAULT_FERNSEHEN_LAYOUT,
)


# -- Fixtures -------------------------------------------------------------- #

SAMPLE_DETAILED_CONFIG = {
    "activities": [
        {
            "id": "38979034",
            "label": "Fernsehen",
            "volume_device": "Denon AV-Empfänger",
            "channel_device": "Samsung TV",
        },
        {"id": "38979035", "label": "Musik"},
    ],
    "devices": [
        {
            "id": "74828509",
            "label": "Denon AV-Empfänger",
            "control_groups": [
                {
                    "name": "Volume",
                    "commands": ["VolumeUp", "VolumeDown", "Mute"],
                },
                {
                    "name": "Power",
                    "commands": ["PowerOn", "PowerOff"],
                },
            ],
        },
        {
            "id": "74828510",
            "label": "Samsung TV",
            "control_groups": [
                {
                    "name": "Navigation",
                    "commands": ["DirectionUp", "DirectionDown", "Select"],
                },
            ],
        },
    ],
}


@pytest.fixture
def layouts_path(tmp_path: Path) -> Path:
    return tmp_path / "harmony_layouts.json"


@pytest.fixture
def manager(layouts_path: Path) -> HarmonyLayoutManager:
    return HarmonyLayoutManager(layouts_path=layouts_path)


# -- Initialisierung ------------------------------------------------------- #


class TestInit:
    def test_empty_when_no_file(self, manager):
        assert manager.get_layouts() == {}

    def test_loads_existing_file(self, layouts_path: Path):
        data = {"activities": {"Test": {"sections": []}}}
        layouts_path.write_text(json.dumps(data), encoding="utf-8")
        mgr = HarmonyLayoutManager(layouts_path=layouts_path)
        assert mgr.get_layouts() == data

    def test_handles_invalid_json(self, layouts_path: Path):
        layouts_path.write_text("not json", encoding="utf-8")
        mgr = HarmonyLayoutManager(layouts_path=layouts_path)
        assert mgr.get_layouts() == {}

    def test_handles_non_dict_json(self, layouts_path: Path):
        layouts_path.write_text("[1, 2, 3]", encoding="utf-8")
        mgr = HarmonyLayoutManager(layouts_path=layouts_path)
        assert mgr.get_layouts() == {}


# -- Save/Load ------------------------------------------------------------- #


class TestSaveLoad:
    def test_save_and_reload(self, layouts_path: Path):
        mgr = HarmonyLayoutManager(layouts_path=layouts_path)
        data = {"activities": {"Gaming": {"sections": []}}}
        mgr.save_layouts(data)

        # Datei existiert
        assert layouts_path.exists()

        # Neu laden
        mgr2 = HarmonyLayoutManager(layouts_path=layouts_path)
        assert mgr2.get_layouts() == data

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        deep_path = tmp_path / "sub" / "dir" / "layouts.json"
        mgr = HarmonyLayoutManager(layouts_path=deep_path)
        mgr.save_layouts({"test": True})
        assert deep_path.exists()

    def test_save_overwrites(self, layouts_path: Path):
        mgr = HarmonyLayoutManager(layouts_path=layouts_path)
        mgr.save_layouts({"v": 1})
        mgr.save_layouts({"v": 2})
        reloaded = json.loads(layouts_path.read_text(encoding="utf-8"))
        assert reloaded == {"v": 2}


# -- ensure_defaults ------------------------------------------------------- #


class TestEnsureDefaults:
    def test_creates_fernsehen_layout(self, manager):
        manager.ensure_defaults(SAMPLE_DETAILED_CONFIG)
        layouts = manager.get_layouts()
        assert "Fernsehen" in layouts["activities"]
        assert layouts["activities"]["Fernsehen"] == _DEFAULT_FERNSEHEN_LAYOUT

    def test_creates_device_layouts(self, manager):
        manager.ensure_defaults(SAMPLE_DETAILED_CONFIG)
        layouts = manager.get_layouts()
        assert "Denon AV-Empfänger" in layouts["devices"]
        assert "Samsung TV" in layouts["devices"]

    def test_device_layout_has_sections(self, manager):
        manager.ensure_defaults(SAMPLE_DETAILED_CONFIG)
        denon = manager.get_layouts()["devices"]["Denon AV-Empfänger"]
        section_labels = [s["label"] for s in denon["sections"]]
        assert "Volume" in section_labels
        assert "Power" in section_labels

    def test_device_section_buttons(self, manager):
        manager.ensure_defaults(SAMPLE_DETAILED_CONFIG)
        denon = manager.get_layouts()["devices"]["Denon AV-Empfänger"]
        vol_section = next(s for s in denon["sections"] if s["label"] == "Volume")
        cmds = [b["cmd"] for b in vol_section["buttons"]]
        assert "VolumeUp" in cmds
        assert "Mute" in cmds

    def test_does_not_overwrite_existing(self, manager):
        custom = {"sections": [{"label": "Custom", "type": "grid"}]}
        manager.save_layouts(
            {
                "activities": {"Fernsehen": custom},
                "devices": {"Denon AV-Empfänger": custom},
            }
        )
        manager.ensure_defaults(SAMPLE_DETAILED_CONFIG)
        layouts = manager.get_layouts()
        # Fernsehen und Denon bleiben custom
        assert layouts["activities"]["Fernsehen"] == custom
        assert layouts["devices"]["Denon AV-Empfänger"] == custom
        # Samsung TV wird neu erzeugt
        assert "Samsung TV" in layouts["devices"]

    def test_persists_after_ensure(self, layouts_path, manager):
        manager.ensure_defaults(SAMPLE_DETAILED_CONFIG)
        assert layouts_path.exists()
        reloaded = json.loads(layouts_path.read_text(encoding="utf-8"))
        assert "Fernsehen" in reloaded["activities"]

    def test_empty_config(self, manager):
        manager.ensure_defaults({"activities": [], "devices": []})
        layouts = manager.get_layouts()
        assert "Fernsehen" in layouts["activities"]
        assert layouts["devices"] == {}

    def test_idempotent(self, manager):
        manager.ensure_defaults(SAMPLE_DETAILED_CONFIG)
        layouts1 = json.dumps(manager.get_layouts(), sort_keys=True)
        manager.ensure_defaults(SAMPLE_DETAILED_CONFIG)
        layouts2 = json.dumps(manager.get_layouts(), sort_keys=True)
        assert layouts1 == layouts2


# -- Auto-Sections -------------------------------------------------------- #


class TestAutoSections:
    def test_auto_sections_from_device(self):
        device = {
            "label": "TestDevice",
            "control_groups": [
                {"name": "Power", "commands": ["PowerOn", "PowerOff"]},
                {"name": "Volume", "commands": ["VolumeUp"]},
            ],
        }
        sections = HarmonyLayoutManager._auto_sections(device)
        assert len(sections) == 2
        assert sections[0]["label"] == "Power"
        assert sections[0]["type"] == "grid"
        assert len(sections[0]["buttons"]) == 2

    def test_auto_sections_skips_empty_groups(self):
        device = {
            "label": "TestDevice",
            "control_groups": [
                {"name": "Empty", "commands": []},
                {"name": "HasCmds", "commands": ["DoIt"]},
            ],
        }
        sections = HarmonyLayoutManager._auto_sections(device)
        assert len(sections) == 1
        assert sections[0]["label"] == "HasCmds"

    def test_auto_sections_button_device_matches_label(self):
        device = {
            "label": "Mein Gerät",
            "control_groups": [
                {"name": "Test", "commands": ["Cmd1"]},
            ],
        }
        sections = HarmonyLayoutManager._auto_sections(device)
        assert sections[0]["buttons"][0]["device"] == "Mein Gerät"

    def test_auto_sections_empty_device(self):
        sections = HarmonyLayoutManager._auto_sections(
            {"label": "Empty", "control_groups": []},
        )
        assert sections == []
