"""SceneCatalog -- Szenen fuer das Grusel-Portrait (Phase 111, Konzept §4.5).

Laedt ``scenes.yaml`` (Default: neben diesem Modul), haengt jeder Szene den
FESTEN KERN an und waehlt Szenen per Shuffle-Bag:

* Innerhalb eines Durchlaufs kommt jede Szene genau einmal dran.
* Beim Neumischen ist die erste Szene nie die zuletzt gezeigte (sofern es
  mehr als eine Szene gibt).
* Nach einem Neustart darf sich eine Szene wiederholen (kein Zustand auf
  Platte).

Die Szene waehlt der Code, nicht das Modell (§2 Punkt 7). Der feste Kern
steht bewusst im Code (:data:`CORE_PROMPT`) und nicht in der YAML: Eine
Bearbeitung der Szenen kann die Kernbedingungen so nicht entfernen.

Neben den Szenen traegt die YAML die Generierungs-Einstellungen (Modell,
Qualitaet, ``provider``-Optionen), damit Szenen-Test-CLI und Betrieb
dieselbe Quelle lesen (§4.6).
"""

from __future__ import annotations

import random
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

import yaml

#: Fester Kern (Anhang A, #1470), formuliert fuer eine beliebige Personenzahl.
CORE_PROMPT = (
    "Keep every face in this photo clearly recognizable. Painterly "
    "brushstrokes, aged canvas with cracked varnish. Horror through "
    "atmosphere only: no blood, no wounds, no gore, no violence. "
    "Not photorealistic. Landscape format 16:9."
)

#: Bedingungen, die jeder zusammengesetzte Prompt enthalten muss (Test §6).
REQUIRED_CORE_TERMS = (
    "recognizable",
    "no blood",
    "no wounds",
    "no gore",
    "no violence",
    "not photorealistic",
    "16:9",
)

DEFAULT_SCENES_PATH = Path(__file__).resolve().parent / "scenes.yaml"

ALLOWED_QUALITIES = frozenset({"auto", "low", "medium", "high", "xhigh", "max"})
_ALLOWED_PROVIDER_KEYS = frozenset({"data_collection", "zdr"})
_ALLOWED_DATA_COLLECTION = frozenset({"deny", "allow"})
_SCENE_ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")


class SceneCatalogError(ValueError):
    """Die Szenendatei fehlt, ist kein gueltiges YAML oder unvollstaendig."""


@dataclass(frozen=True)
class Scene:
    """Eine Szene (ohne festen Kern)."""

    id: str
    title: str
    prompt: str


@dataclass(frozen=True)
class GenerationSettings:
    """Generierungs-Einstellungen aus der Sektion ``generation``."""

    model: str
    quality: str
    provider_options: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )


def compose_prompt(scene: Scene) -> str:
    """Szene + fester Kern."""
    return f"{scene.prompt.strip()} {CORE_PROMPT}"


class SceneCatalog:
    """Szenen plus Shuffle-Bag-Auswahl.

    Args:
        scenes: Mindestens eine Szene, IDs eindeutig.
        generation: Generierungs-Einstellungen.
        rng: Zufallsquelle (Tests: ``random.Random(seed)``).
    """

    def __init__(
        self,
        scenes: list[Scene],
        generation: GenerationSettings,
        *,
        rng: random.Random | None = None,
    ) -> None:
        if not scenes:
            raise SceneCatalogError("Mindestens eine Szene noetig.")
        ids = [scene.id for scene in scenes]
        if len(set(ids)) != len(ids):
            raise SceneCatalogError(f"Szenen-IDs nicht eindeutig: {ids}")
        self._scenes = tuple(scenes)
        self._by_id = {scene.id: scene for scene in scenes}
        self._generation = generation
        self._rng = rng if rng is not None else random.Random()
        self._bag: list[Scene] = []
        self._last: Scene | None = None

    # ------------------------------------------------------------------
    # Laden
    # ------------------------------------------------------------------

    @classmethod
    def load(
        cls, path: Path | None = None, *, rng: random.Random | None = None
    ) -> SceneCatalog:
        """Laedt und validiert eine Szenendatei.

        Raises:
            SceneCatalogError: bei fehlender, leerer, kaputter oder
                unvollstaendiger Datei. Die Meldung nennt Datei und Grund.
        """
        source = path if path is not None else DEFAULT_SCENES_PATH
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise SceneCatalogError(f"{source}: nicht lesbar ({exc})") from exc
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SceneCatalogError(f"{source}: kein gueltiges YAML ({exc})") from exc
        if not isinstance(data, Mapping):
            raise SceneCatalogError(
                f"{source}: leer oder kein Mapping auf oberster Ebene"
            )
        generation = _parse_generation(source, data.get("generation"))
        scenes = _parse_scenes(source, data.get("scenes"))
        return cls(scenes, generation, rng=rng)

    # ------------------------------------------------------------------
    # Zugriff
    # ------------------------------------------------------------------

    @property
    def scenes(self) -> tuple[Scene, ...]:
        return self._scenes

    @property
    def generation(self) -> GenerationSettings:
        return self._generation

    def get(self, scene_id: str) -> Scene:
        """Szene per ID.

        Raises:
            KeyError: unbekannte ID.
        """
        return self._by_id[scene_id]

    def next_scene(self) -> Scene:
        """Naechste Szene aus dem Shuffle-Bag."""
        if not self._bag:
            self._refill()
        scene = self._bag.pop()
        self._last = scene
        return scene

    def _refill(self) -> None:
        bag = list(self._scenes)
        self._rng.shuffle(bag)
        # pop() nimmt vom Ende: das letzte Element ist die naechste Szene.
        if self._last is not None and len(bag) > 1 and bag[-1] == self._last:
            swap = self._rng.randrange(len(bag) - 1)
            bag[-1], bag[swap] = bag[swap], bag[-1]
        self._bag = bag


def _parse_generation(source: Path, raw: object) -> GenerationSettings:
    if not isinstance(raw, Mapping):
        raise SceneCatalogError(f"{source}: Sektion 'generation' fehlt")
    model = raw.get("model")
    if not isinstance(model, str) or not model.strip():
        raise SceneCatalogError(f"{source}: generation.model fehlt")
    quality = raw.get("quality")
    if quality not in ALLOWED_QUALITIES:
        raise SceneCatalogError(
            f"{source}: generation.quality muss eins von "
            f"{sorted(ALLOWED_QUALITIES)} sein (war: {quality!r})"
        )
    provider_raw = raw.get("provider")
    provider: dict[str, object] = {}
    if provider_raw is not None:
        if not isinstance(provider_raw, Mapping):
            raise SceneCatalogError(f"{source}: generation.provider ist kein Mapping")
        unknown = set(provider_raw) - _ALLOWED_PROVIDER_KEYS
        if unknown:
            raise SceneCatalogError(
                f"{source}: unbekannte provider-Optionen {sorted(unknown)}"
            )
        data_collection = provider_raw.get("data_collection")
        if data_collection is not None:
            if data_collection not in _ALLOWED_DATA_COLLECTION:
                raise SceneCatalogError(
                    f"{source}: provider.data_collection muss deny oder allow sein"
                )
            provider["data_collection"] = data_collection
        zdr = provider_raw.get("zdr")
        if zdr is not None:
            if not isinstance(zdr, bool):
                raise SceneCatalogError(f"{source}: provider.zdr muss true/false sein")
            provider["zdr"] = zdr
    return GenerationSettings(
        model=model.strip(),
        quality=str(quality),
        provider_options=MappingProxyType(provider),
    )


def _parse_scenes(source: Path, raw: object) -> list[Scene]:
    if not isinstance(raw, list) or not raw:
        raise SceneCatalogError(f"{source}: Liste 'scenes' fehlt oder ist leer")
    scenes: list[Scene] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise SceneCatalogError(f"{source}: scenes[{index}] ist kein Mapping")
        scene_id = item.get("id")
        if not isinstance(scene_id, str) or not _SCENE_ID_RE.match(scene_id):
            raise SceneCatalogError(
                f"{source}: scenes[{index}].id fehlt oder ist ungueltig "
                "(nur a-z, 0-9, _; max. 40 Zeichen)"
            )
        prompt = item.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise SceneCatalogError(f"{source}: Szene {scene_id}: prompt fehlt")
        title = item.get("title")
        scenes.append(
            Scene(
                id=scene_id,
                title=title.strip()
                if isinstance(title, str) and title.strip()
                else scene_id,
                prompt=prompt.strip(),
            )
        )
    return scenes
