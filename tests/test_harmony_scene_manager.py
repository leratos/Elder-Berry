"""Tests fuer HarmonySceneManager."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from elder_berry.robot.harmony_scene_manager import (
    HarmonySceneManager,
    SceneExecutionError,
    SceneNotFoundError,
)


# -- Fixtures -------------------------------------------------------------- #

SAMPLE_SCENE = {
    "name": "Gaming",
    "steps": [
        {"device": "Denon AV-Empfänger", "cmd": "PowerOn", "delay_after": 0.01},
        {"device": "Denon AV-Empfänger", "cmd": "InputGame", "delay_after": 0.01},
        {"device": "Samsung TV", "cmd": "PowerOn"},
    ],
}

SAMPLE_SCENE_2 = {
    "name": "Musik",
    "steps": [
        {"device": "Denon AV-Empfänger", "cmd": "PowerOn"},
        {"device": "Denon AV-Empfänger", "cmd": "InputCD"},
    ],
}


@pytest.fixture
def scenes_path(tmp_path: Path) -> Path:
    return tmp_path / "harmony_scenes.json"


@pytest.fixture
def manager(scenes_path: Path) -> HarmonySceneManager:
    return HarmonySceneManager(scenes_path=scenes_path)


@pytest.fixture
def mock_adapter():
    adapter = AsyncMock()
    adapter.send_command = AsyncMock(return_value=True)
    return adapter


@pytest.fixture
def manager_with_adapter(scenes_path, mock_adapter):
    return HarmonySceneManager(
        adapter=mock_adapter,
        scenes_path=scenes_path,
    )


# -- Initialisierung ------------------------------------------------------- #


class TestInit:
    def test_empty_when_no_file(self, manager):
        assert manager.list_scenes() == []

    def test_loads_existing_file(self, scenes_path):
        scenes_path.write_text(
            json.dumps([SAMPLE_SCENE]),
            encoding="utf-8",
        )
        mgr = HarmonySceneManager(scenes_path=scenes_path)
        assert len(mgr.list_scenes()) == 1
        assert mgr.list_scenes()[0]["name"] == "Gaming"

    def test_handles_invalid_json(self, scenes_path):
        scenes_path.write_text("broken", encoding="utf-8")
        mgr = HarmonySceneManager(scenes_path=scenes_path)
        assert mgr.list_scenes() == []

    def test_handles_non_list_json(self, scenes_path):
        scenes_path.write_text('{"not": "a list"}', encoding="utf-8")
        mgr = HarmonySceneManager(scenes_path=scenes_path)
        assert mgr.list_scenes() == []


# -- CRUD ------------------------------------------------------------------ #


class TestCRUD:
    def test_save_scene(self, manager):
        manager.save_scene(SAMPLE_SCENE)
        assert len(manager.list_scenes()) == 1
        assert manager.list_scenes()[0]["name"] == "Gaming"

    def test_save_scene_persists(self, scenes_path, manager):
        manager.save_scene(SAMPLE_SCENE)
        assert scenes_path.exists()
        data = json.loads(scenes_path.read_text(encoding="utf-8"))
        assert len(data) == 1

    def test_save_multiple_scenes(self, manager):
        manager.save_scene(SAMPLE_SCENE)
        manager.save_scene(SAMPLE_SCENE_2)
        assert len(manager.list_scenes()) == 2

    def test_save_scene_update_existing(self, manager):
        manager.save_scene(SAMPLE_SCENE)
        updated = {
            "name": "Gaming",
            "steps": [{"device": "PS4", "cmd": "PowerOn"}],
        }
        manager.save_scene(updated)
        assert len(manager.list_scenes()) == 1
        assert manager.list_scenes()[0]["steps"][0]["device"] == "PS4"

    def test_save_scene_case_insensitive_update(self, manager):
        manager.save_scene(SAMPLE_SCENE)
        updated = {"name": "gaming", "steps": [{"device": "PS4", "cmd": "On"}]}
        manager.save_scene(updated)
        assert len(manager.list_scenes()) == 1

    def test_save_scene_no_name_raises(self, manager):
        with pytest.raises(ValueError, match="Namen"):
            manager.save_scene({"name": "", "steps": []})

    def test_save_scene_no_steps_raises(self, manager):
        with pytest.raises(ValueError, match="Steps"):
            manager.save_scene({"name": "Test"})

    def test_get_scene(self, manager):
        manager.save_scene(SAMPLE_SCENE)
        scene = manager.get_scene("Gaming")
        assert scene["name"] == "Gaming"
        assert len(scene["steps"]) == 3

    def test_get_scene_case_insensitive(self, manager):
        manager.save_scene(SAMPLE_SCENE)
        scene = manager.get_scene("gaming")
        assert scene["name"] == "Gaming"

    def test_get_scene_not_found(self, manager):
        with pytest.raises(SceneNotFoundError):
            manager.get_scene("Nonexistent")

    def test_delete_scene(self, manager):
        manager.save_scene(SAMPLE_SCENE)
        manager.delete_scene("Gaming")
        assert len(manager.list_scenes()) == 0

    def test_delete_scene_case_insensitive(self, manager):
        manager.save_scene(SAMPLE_SCENE)
        manager.delete_scene("gaming")
        assert len(manager.list_scenes()) == 0

    def test_delete_scene_not_found(self, manager):
        with pytest.raises(SceneNotFoundError):
            manager.delete_scene("Nonexistent")

    def test_delete_scene_persists(self, scenes_path, manager):
        manager.save_scene(SAMPLE_SCENE)
        manager.delete_scene("Gaming")
        data = json.loads(scenes_path.read_text(encoding="utf-8"))
        assert len(data) == 0


# -- Ausfuehrung ---------------------------------------------------------- #


def _run(coro):
    """Hilfsfunktion: async Coroutine synchron ausfuehren."""
    return asyncio.new_event_loop().run_until_complete(coro)


class TestExecution:
    def test_start_scene_all_ok(self, manager_with_adapter, mock_adapter):
        manager_with_adapter.save_scene(SAMPLE_SCENE)
        result = _run(manager_with_adapter.start_scene("Gaming"))
        assert result["steps_total"] == 3
        assert result["steps_ok"] == 3
        assert result["steps_failed"] == 0
        assert result["errors"] == []
        assert mock_adapter.send_command.await_count == 3

    def test_start_scene_with_failure(
        self,
        manager_with_adapter,
        mock_adapter,
    ):
        mock_adapter.send_command = AsyncMock(
            side_effect=[True, False, True],
        )
        manager_with_adapter.save_scene(SAMPLE_SCENE)
        result = _run(manager_with_adapter.start_scene("Gaming"))
        assert result["steps_ok"] == 2
        assert result["steps_failed"] == 1
        assert len(result["errors"]) == 1

    def test_start_scene_not_found(self, manager_with_adapter):
        with pytest.raises(SceneNotFoundError):
            _run(manager_with_adapter.start_scene("Nonexistent"))

    def test_start_scene_no_adapter(self, manager):
        manager.save_scene(SAMPLE_SCENE)
        with pytest.raises(SceneExecutionError):
            _run(manager.start_scene("Gaming"))

    def test_start_scene_sends_correct_commands(
        self,
        manager_with_adapter,
        mock_adapter,
    ):
        manager_with_adapter.save_scene(SAMPLE_SCENE)
        _run(manager_with_adapter.start_scene("Gaming"))
        calls = mock_adapter.send_command.call_args_list
        assert calls[0].kwargs == {"device": "Denon AV-Empfänger", "command": "PowerOn"}
        assert calls[1].kwargs == {
            "device": "Denon AV-Empfänger",
            "command": "InputGame",
        }
        assert calls[2].kwargs == {"device": "Samsung TV", "command": "PowerOn"}

    def test_start_scene_case_insensitive(
        self,
        manager_with_adapter,
        mock_adapter,
    ):
        manager_with_adapter.save_scene(SAMPLE_SCENE)
        result = _run(manager_with_adapter.start_scene("gaming"))
        assert result["steps_ok"] == 3

    def test_start_scene_skips_invalid_steps(
        self,
        manager_with_adapter,
        mock_adapter,
    ):
        scene = {
            "name": "Broken",
            "steps": [
                {"device": "", "cmd": "PowerOn"},
                {"device": "TV", "cmd": ""},
                {"device": "TV", "cmd": "PowerOn"},
            ],
        }
        manager_with_adapter.save_scene(scene)
        result = _run(manager_with_adapter.start_scene("Broken"))
        assert result["steps_ok"] == 1
        assert result["steps_failed"] == 2

    def test_start_scene_empty_steps(
        self,
        manager_with_adapter,
        mock_adapter,
    ):
        scene = {"name": "Empty", "steps": []}
        manager_with_adapter.save_scene(scene)
        result = _run(manager_with_adapter.start_scene("Empty"))
        assert result["steps_total"] == 0
        assert result["steps_ok"] == 0
