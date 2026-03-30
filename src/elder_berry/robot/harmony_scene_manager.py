"""HarmonySceneManager -- Szenen-Engine fuer die Harmony Remote.

Szenen sind benannte Befehlsketten die sequenziell ausgefuehrt werden.
Ersetzt echte Hub-Aktivitaeten fuer neue Geraetekombinationen.
Genutzt von PWA und Saleria (Matrix-Commands).

Speicherort: ~/.elder-berry/harmony_scenes.json

Beispiel-Szene:
    {
        "name": "Gaming",
        "steps": [
            {"device": "Denon AV-Empfänger", "cmd": "PowerOn", "delay_after": 2.0},
            {"device": "Denon AV-Empfänger", "cmd": "InputGame", "delay_after": 1.0},
            {"device": "Samsung TV", "cmd": "PowerOn", "delay_after": 2.0},
            {"device": "Samsung TV", "cmd": "InputHdmi2"}
        ]
    }
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from elder_berry.robot.harmony_adapter import HarmonyAdapter

logger = logging.getLogger(__name__)

_DEFAULT_SCENES_PATH = Path.home() / ".elder-berry" / "harmony_scenes.json"


class SceneNotFoundError(Exception):
    """Szene mit diesem Namen existiert nicht."""


class SceneExecutionError(Exception):
    """Fehler bei der Ausfuehrung einer Szene."""


class HarmonySceneManager:
    """Verwaltet und fuehrt Harmony-Szenen aus.

    Args:
        adapter: HarmonyAdapter fuer die Befehlsausfuehrung.
        scenes_path: Pfad zur JSON-Datei fuer persistente Speicherung.
    """

    def __init__(
        self,
        adapter: HarmonyAdapter | None = None,
        scenes_path: Path = _DEFAULT_SCENES_PATH,
    ) -> None:
        self._adapter = adapter
        self._path = scenes_path
        self._scenes: list[dict[str, Any]] = []
        self._load()

    # -- CRUD -------------------------------------------------------------- #

    def list_scenes(self) -> list[dict[str, Any]]:
        """Gibt alle Szenen zurueck."""
        return self._scenes

    def get_scene(self, name: str) -> dict[str, Any]:
        """Gibt eine Szene per Name zurueck.

        Raises:
            SceneNotFoundError: Szene existiert nicht.
        """
        for scene in self._scenes:
            if scene.get("name", "").lower() == name.lower():
                return scene
        raise SceneNotFoundError(f"Szene '{name}' nicht gefunden")

    def save_scene(self, scene: dict[str, Any]) -> None:
        """Erstellt oder aktualisiert eine Szene.

        Args:
            scene: Dict mit "name" und "steps" Keys.
        """
        name = scene.get("name", "")
        if not name:
            raise ValueError("Szene braucht einen Namen")
        if "steps" not in scene:
            raise ValueError("Szene braucht Steps")

        # Existierende Szene ersetzen oder neue hinzufuegen
        for i, existing in enumerate(self._scenes):
            if existing.get("name", "").lower() == name.lower():
                self._scenes[i] = scene
                self._persist()
                logger.info("Szene aktualisiert: %s", name)
                return

        self._scenes.append(scene)
        self._persist()
        logger.info("Szene erstellt: %s (%d Steps)", name, len(scene["steps"]))

    def delete_scene(self, name: str) -> None:
        """Loescht eine Szene per Name.

        Raises:
            SceneNotFoundError: Szene existiert nicht.
        """
        for i, scene in enumerate(self._scenes):
            if scene.get("name", "").lower() == name.lower():
                self._scenes.pop(i)
                self._persist()
                logger.info("Szene gelöscht: %s", name)
                return
        raise SceneNotFoundError(f"Szene '{name}' nicht gefunden")

    # -- Ausfuehrung ------------------------------------------------------- #

    async def start_scene(self, name: str) -> dict[str, Any]:
        """Fuehrt eine Szene sequenziell aus.

        Args:
            name: Name der Szene.

        Returns:
            Dict mit Ergebnis: steps_total, steps_ok, steps_failed, errors.

        Raises:
            SceneNotFoundError: Szene existiert nicht.
            SceneExecutionError: Kein Adapter verbunden.
        """
        if self._adapter is None:
            raise SceneExecutionError("Kein HarmonyAdapter konfiguriert")

        scene = self.get_scene(name)
        steps = scene.get("steps", [])

        result = {
            "scene": name,
            "steps_total": len(steps),
            "steps_ok": 0,
            "steps_failed": 0,
            "errors": [],
        }

        for i, step in enumerate(steps):
            device = step.get("device", "")
            cmd = step.get("cmd", "")
            delay = step.get("delay_after", 0.0)

            if not device or not cmd:
                result["steps_failed"] += 1
                result["errors"].append(
                    f"Step {i}: device oder cmd fehlt"
                )
                continue

            success = await self._adapter.send_command(
                device=device, command=cmd,
            )

            if success:
                result["steps_ok"] += 1
                logger.info(
                    "Szene '%s' Step %d/%d: %s → %s ✓",
                    name, i + 1, len(steps), device, cmd,
                )
            else:
                result["steps_failed"] += 1
                result["errors"].append(
                    f"Step {i}: {device} → {cmd} fehlgeschlagen"
                )
                logger.warning(
                    "Szene '%s' Step %d/%d: %s → %s ✗",
                    name, i + 1, len(steps), device, cmd,
                )

            if delay > 0:
                await asyncio.sleep(delay)

        logger.info(
            "Szene '%s' abgeschlossen: %d/%d OK",
            name, result["steps_ok"], result["steps_total"],
        )
        return result

    # -- Persistenz -------------------------------------------------------- #

    def _load(self) -> None:
        """Laedt Szenen aus Datei."""
        if not self._path.exists():
            self._scenes = []
            return
        try:
            text = self._path.read_text(encoding="utf-8")
            data = json.loads(text)
            if isinstance(data, list):
                self._scenes = data
            else:
                logger.warning("Szenen-Datei ist keine Liste, ignoriert")
                self._scenes = []
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Szenen-Datei laden fehlgeschlagen: %s", e)
            self._scenes = []

    def _persist(self) -> None:
        """Schreibt Szenen in Datei."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._scenes, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error("Szenen speichern fehlgeschlagen: %s", e)
