"""Tests fuer SceneCatalog (Phase 111, E1, Konzept §4.5 + §6)."""

from __future__ import annotations

import random
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from elder_berry.room_display.portrait.scene_catalog import (
    CORE_PROMPT,
    DEFAULT_SCENES_PATH,
    REQUIRED_CORE_TERMS,
    GenerationSettings,
    Scene,
    SceneCatalog,
    SceneCatalogError,
    compose_prompt,
)

VALID_YAML = """
generation:
  model: openai/gpt-image-2.6-flare
  quality: low
  provider:
    data_collection: deny
    zdr: true
scenes:
  - id: a
    title: A
    prompt: Scene A.
  - id: b
    prompt: Scene B.
  - id: c
    prompt: Scene C.
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "scenes.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def _catalog(n: int, seed: int) -> SceneCatalog:
    scenes = [Scene(id=f"s{i}", title=f"S{i}", prompt=f"Scene {i}.") for i in range(n)]
    return SceneCatalog(
        scenes, GenerationSettings(model="m", quality="low"), rng=random.Random(seed)
    )


# ---------------------------------------------------------------------------
# Paket-Datei
# ---------------------------------------------------------------------------


class TestPackagedScenes:
    def test_default_file_loads_six_scenes(self):
        catalog = SceneCatalog.load()
        assert DEFAULT_SCENES_PATH.name == "scenes.yaml"
        assert [scene.id for scene in catalog.scenes] == [
            "s1_moonlit_parlour",
            "s2_forgotten_library",
            "s3_crypt",
            "s4_abandoned_ballroom",
            "s5_hall_of_mirrors",
            "s6_attic_of_dolls",
        ]

    def test_default_generation_settings(self):
        generation = SceneCatalog.load().generation
        assert generation.model == "openai/gpt-image-2.6-flare"
        assert generation.quality == "low"
        assert dict(generation.provider_options) == {
            "data_collection": "deny",
            "zdr": True,
        }

    def test_every_composed_prompt_contains_core_terms(self):
        catalog = SceneCatalog.load()
        for scene in catalog.scenes:
            prompt = compose_prompt(scene).lower()
            for term in REQUIRED_CORE_TERMS:
                assert term in prompt, (scene.id, term)

    def test_core_prompt_contains_all_terms(self):
        for term in REQUIRED_CORE_TERMS:
            assert term in CORE_PROMPT.lower()

    def test_scene_prompts_do_not_repeat_core(self):
        """Der Kern wird angehaengt, nicht in jeder Szene wiederholt (§4.5)."""
        for scene in SceneCatalog.load().scenes:
            assert "no gore" not in scene.prompt.lower()

    def test_composed_prompt_is_scene_then_core(self):
        scene = Scene(id="x", title="X", prompt="  Scene X.  ")
        assert compose_prompt(scene) == f"Scene X. {CORE_PROMPT}"


# ---------------------------------------------------------------------------
# Shuffle-Bag
# ---------------------------------------------------------------------------


class TestShuffleBag:
    @pytest.mark.parametrize("seed", range(20))
    def test_no_repeat_within_a_cycle(self, seed):
        catalog = _catalog(6, seed)
        for _cycle in range(5):
            picks = [catalog.next_scene().id for _ in range(6)]
            assert sorted(picks) == [f"s{i}" for i in range(6)]

    @pytest.mark.parametrize("seed", range(50))
    def test_no_double_at_reshuffle(self, seed):
        catalog = _catalog(4, seed)
        picks = [catalog.next_scene().id for _ in range(4 * 30)]
        for previous, current in zip(picks, picks[1:], strict=False):
            assert previous != current

    def test_same_seed_same_order(self):
        a = _catalog(6, 7)
        b = _catalog(6, 7)
        assert [a.next_scene().id for _ in range(12)] == [
            b.next_scene().id for _ in range(12)
        ]

    def test_single_scene_repeats(self):
        catalog = _catalog(1, 0)
        assert [catalog.next_scene().id for _ in range(3)] == ["s0", "s0", "s0"]

    def test_get_unknown_raises_keyerror(self):
        with pytest.raises(KeyError):
            _catalog(2, 0).get("nope")


# ---------------------------------------------------------------------------
# Laden und Validierung
# ---------------------------------------------------------------------------


class TestLoad:
    def test_valid_file(self, tmp_path):
        catalog = SceneCatalog.load(_write(tmp_path, VALID_YAML))
        assert [scene.id for scene in catalog.scenes] == ["a", "b", "c"]
        assert catalog.get("a").title == "A"
        assert catalog.get("b").title == "b"  # Titel faellt auf ID zurueck

    def test_provider_optional(self, tmp_path):
        text = VALID_YAML.replace(
            "  provider:\n    data_collection: deny\n    zdr: true\n", ""
        )
        catalog = SceneCatalog.load(_write(tmp_path, text))
        assert dict(catalog.generation.provider_options) == {}

    def test_missing_file(self, tmp_path):
        with pytest.raises(SceneCatalogError, match="nicht lesbar"):
            SceneCatalog.load(tmp_path / "fehlt.yaml")

    @pytest.mark.parametrize("text", ["", "   \n", "# nur Kommentar\n", "- a\n- b\n"])
    def test_empty_or_not_mapping(self, tmp_path, text):
        with pytest.raises(SceneCatalogError, match="leer oder kein Mapping"):
            SceneCatalog.load(_write(tmp_path, text))

    def test_broken_yaml(self, tmp_path):
        with pytest.raises(SceneCatalogError, match="kein gueltiges YAML"):
            SceneCatalog.load(_write(tmp_path, "scenes: [\n  - id: a\n"))

    @pytest.mark.parametrize(
        ("old", "new", "match"),
        [
            ("generation:", "generationX:", "generation' fehlt"),
            ("model: openai/gpt-image-2.6-flare", "model: ''", "model fehlt"),
            ("quality: low", "quality: ultra", "quality"),
            ("zdr: true", "zdr: 'yes'", "zdr"),
            ("data_collection: deny", "data_collection: maybe", "data_collection"),
            ("    zdr: true", "    zdr: true\n    order: [x]", "unbekannte provider"),
            ("scenes:", "scenesX:", "'scenes' fehlt"),
            ("- id: a", "- id: 'A B'", "id fehlt oder ist ungueltig"),
            ("prompt: Scene A.", "prompt: ''", "prompt fehlt"),
            ("- id: b", "- id: a", "nicht eindeutig"),
        ],
    )
    def test_invalid_content(self, tmp_path, old, new, match):
        assert old in VALID_YAML
        with pytest.raises(SceneCatalogError, match=match):
            SceneCatalog.load(_write(tmp_path, VALID_YAML.replace(old, new, 1)))

    def test_empty_scene_list(self, tmp_path):
        text = VALID_YAML.split("scenes:")[0] + "scenes: []\n"
        with pytest.raises(SceneCatalogError, match="'scenes' fehlt oder ist leer"):
            SceneCatalog.load(_write(tmp_path, text))

    def test_constructor_requires_scenes(self):
        with pytest.raises(SceneCatalogError):
            SceneCatalog([], GenerationSettings(model="m", quality="low"))


def test_room_display_packages_import_nothing_heavy():
    """room_display/__init__ und portrait/__init__ laden kein pygame/httpx/LLM."""
    code = (
        "import sys; import elder_berry.room_display, elder_berry.room_display.portrait; "
        "heavy = [m for m in ('pygame', 'httpx', 'anthropic', 'elder_berry.llm', 'yaml') "
        "if m in sys.modules]; print(heavy); sys.exit(1 if heavy else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
