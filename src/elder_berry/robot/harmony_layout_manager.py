"""HarmonyLayoutManager -- Verwaltung der Fernbedienungs-Layouts.

Speichert und laedt Layouts fuer die Harmony Remote PWA.
Layouts definieren welche Buttons in welcher Anordnung angezeigt werden,
sowohl fuer Aktivitaeten (kuratiert) als auch fuer Geraete (auto-generiert).

Speicherort: ~/.elder-berry/harmony_layouts.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_LAYOUTS_PATH = Path.home() / ".elder-berry" / "harmony_layouts.json"

# -- Default Aktivitaets-Layout: Fernsehen --------------------------------- #

_DEFAULT_FERNSEHEN_LAYOUT: dict[str, Any] = {
    "sections": [
        {
            "label": "Navigation",
            "type": "dpad",
            "device": "Samsung TV",
            "center": "Select",
            "extra": [
                {"cmd": "Return", "label": "Zurück"},
                {"cmd": "Menu", "label": "Menü"},
            ],
        },
        {
            "label": "Lautstärke & Sender",
            "type": "grid",
            "columns": 3,
            "buttons": [
                {"device": "Denon AV-Empfänger", "cmd": "VolumeDown", "label": "Vol-"},
                {"device": "Denon AV-Empfänger", "cmd": "Mute", "label": "Stumm"},
                {"device": "Denon AV-Empfänger", "cmd": "VolumeUp", "label": "Vol+"},
                {"device": "Samsung TV", "cmd": "ChannelUp", "label": "CH▲"},
                {"device": "Samsung TV", "cmd": "ChannelPrev", "label": "CH←"},
                {"device": "Samsung TV", "cmd": "ChannelDown", "label": "CH▼"},
            ],
        },
        {
            "label": "Transport",
            "type": "transport",
            "device": "Samsung TV",
        },
        {
            "label": "Nummernblock",
            "type": "numpad",
            "device": "Samsung TV",
        },
        {
            "label": "Extras",
            "type": "grid",
            "columns": 3,
            "buttons": [
                {"device": "Samsung TV", "cmd": "Guide", "label": "Guide"},
                {"device": "Samsung TV", "cmd": "Home", "label": "Home"},
                {"device": "Samsung TV", "cmd": "Source", "label": "Source"},
                {"device": "Samsung TV", "cmd": "Red", "label": "🔴"},
                {"device": "Samsung TV", "cmd": "Green", "label": "🟢"},
                {"device": "Samsung TV", "cmd": "Blue", "label": "🔵"},
            ],
        },
    ],
}


class HarmonyLayoutManager:
    """Verwaltet Fernbedienungs-Layouts fuer die Harmony Remote PWA.

    Args:
        layouts_path: Pfad zur JSON-Datei fuer persistente Speicherung.
    """

    def __init__(
        self,
        layouts_path: Path = _DEFAULT_LAYOUTS_PATH,
    ) -> None:
        self._path = layouts_path
        self._layouts: dict[str, Any] = {}
        self._load()

    # -- Oeffentliche API -------------------------------------------------- #

    def get_layouts(self) -> dict[str, Any]:
        """Gibt die aktuellen Layouts zurueck."""
        return self._layouts

    def save_layouts(self, layouts: dict[str, Any]) -> None:
        """Speichert Layouts (ueberschreibt komplett)."""
        self._layouts = layouts
        self._persist()

    def ensure_defaults(self, detailed_config: dict[str, Any]) -> None:
        """Stellt sicher dass Default-Layouts existieren.

        Erzeugt Aktivitaets- und Geraete-Layouts aus der Hub-Config
        wenn noch keine vorhanden sind.

        Args:
            detailed_config: Ergebnis von HarmonyAdapter.get_detailed_config()
        """
        changed = False

        if "activities" not in self._layouts:
            self._layouts["activities"] = {}
            changed = True

        if "devices" not in self._layouts:
            self._layouts["devices"] = {}
            changed = True

        # Default Fernsehen-Layout wenn nicht vorhanden
        if "Fernsehen" not in self._layouts["activities"]:
            self._layouts["activities"]["Fernsehen"] = _DEFAULT_FERNSEHEN_LAYOUT
            changed = True

        # Geraete-Layouts: auto-generiert aus ControlGroups
        for device in detailed_config.get("devices", []):
            label = device.get("label", "")
            if label and label not in self._layouts["devices"]:
                self._layouts["devices"][label] = {
                    "sections": self._auto_sections(device),
                }
                changed = True

        if changed:
            self._persist()

    # -- Auto-Generierung -------------------------------------------------- #

    @staticmethod
    def _auto_sections(device: dict[str, Any]) -> list[dict[str, Any]]:
        """Erzeugt Sektionen aus den ControlGroups eines Geraets."""
        sections: list[dict[str, Any]] = []
        label = device.get("label", "")

        for group in device.get("control_groups", []):
            group_name = group.get("name", "")
            commands = group.get("commands", [])
            if not commands:
                continue

            buttons = [{"device": label, "cmd": cmd, "label": cmd} for cmd in commands]
            sections.append(
                {
                    "label": group_name,
                    "type": "grid",
                    "columns": 3,
                    "buttons": buttons,
                }
            )

        return sections

    # -- Persistenz -------------------------------------------------------- #

    def _load(self) -> None:
        """Laedt Layouts aus Datei. Leeres Dict wenn nicht vorhanden."""
        if not self._path.exists():
            self._layouts = {}
            return
        try:
            text = self._path.read_text(encoding="utf-8")
            data = json.loads(text)
            if isinstance(data, dict):
                self._layouts = data
            else:
                logger.warning("Layout-Datei ist kein dict, ignoriert")
                self._layouts = {}
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Layout-Datei laden fehlgeschlagen: %s", e)
            self._layouts = {}

    def _persist(self) -> None:
        """Schreibt Layouts in Datei."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._layouts, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Layouts gespeichert: %s", self._path)
        except OSError as e:
            logger.error("Layouts speichern fehlgeschlagen: %s", e)
