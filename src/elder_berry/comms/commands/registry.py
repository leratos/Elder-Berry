"""Plugin-Registry – Discovery und Sortierung von CommandPlugins (Phase 77).

Lädt CommandPlugin-Manifeste aus drei Quellen:

1. **Builtin** – ``elder_berry.comms.commands.<name>_commands`` Modulen,
   die ein ``PLUGIN``-Objekt auf Modul-Ebene exportieren.
2. **User-Directory** – ``~/.elder-berry/plugins/*.py`` (Etappe 3, hier Stub).
3. **Entry-Points** – ``elder_berry.commands`` Group via
   ``importlib.metadata`` (Etappe 3, hier Stub).

In Etappe 1 ist nur Quelle 1 aktiv. Die Stubs für 2/3 stehen schon, damit
die Sortier-/Dedup-Logik fertig ist und Etappe 3 nur die Loader-Bodies
fuellen muss.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Iterator
from pathlib import Path

from elder_berry.comms.commands.base import CommandPlugin

logger = logging.getLogger(__name__)


def _load_builtin() -> Iterator[CommandPlugin]:
    """Lädt PLUGIN-Objekte aus comms/commands/<name>_commands.py.

    Iteriert ueber alle ``*_commands.py`` Dateien neben dieser Datei,
    importiert sie als Modul und yieldet das ``PLUGIN``-Attribut, falls
    es ein ``CommandPlugin`` ist. Module ohne ``PLUGIN``-Export werden
    schweigend uebersprungen (Etappe 1: nur 3 Pilot-Handler haben das,
    der Rest folgt in Etappe 2).
    """
    base_dir = Path(__file__).parent
    for path in sorted(base_dir.glob("*_commands.py")):
        module_name = f"elder_berry.comms.commands.{path.stem}"
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            logger.warning("Builtin-Plugin %s uebersprungen: %s", path.stem, exc)
            continue
        plugin = getattr(module, "PLUGIN", None)
        if isinstance(plugin, CommandPlugin):
            yield plugin


def _load_user_directory() -> Iterator[CommandPlugin]:
    """Lädt Plugins aus ~/.elder-berry/plugins/*.py (Etappe 3 Stub).

    In Etappe 1 ein leerer Generator. Die Loader-Logik kommt mit Etappe 3
    (siehe Konzept §3.3).
    """
    yield from ()


def _load_entry_points() -> Iterator[CommandPlugin]:
    """Lädt Plugins aus pip-installierten Paketen (Etappe 3 Stub).

    Entry-Point-Group: ``elder_berry.commands``. In Etappe 1 ein leerer
    Generator, weil sonst beim Test-Lauf zufaellig installierte Pakete
    mit dieser Group geladen wuerden.
    """
    yield from ()


def load_plugins() -> list[CommandPlugin]:
    """Lädt alle Plugins, dedupliziert nach Name, sortiert nach Priorität.

    Praezedenz bei Namens-Konflikt (Konzept §3.3):
    User-Dir > Entry-Point > Builtin. In Etappe 1 nur Builtin aktiv,
    daher ist das vorerst irrelevant.
    """
    plugins: list[CommandPlugin] = list(_load_builtin())
    plugins.extend(_load_entry_points())
    plugins.extend(_load_user_directory())

    # Eindeutigkeit per Name (User-Dir bzw. Entry-Point ueberschreiben Builtin).
    by_name: dict[str, CommandPlugin] = {}
    for plugin in plugins:
        if plugin.name in by_name:
            logger.info(
                "Plugin %s wird ueberschrieben (vorher v%s, jetzt v%s)",
                plugin.name,
                by_name[plugin.name].version,
                plugin.version,
            )
        by_name[plugin.name] = plugin

    return sorted(by_name.values(), key=lambda p: p.priority)
