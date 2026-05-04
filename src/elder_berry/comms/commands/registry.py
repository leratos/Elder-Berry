"""Plugin-Registry – Discovery und Sortierung von CommandPlugins (Phase 77).

Lädt CommandPlugin-Manifeste aus drei Quellen:

1. **Builtin** – ``elder_berry.comms.commands.<name>_commands`` Modulen,
   die ein ``PLUGIN``-Objekt auf Modul-Ebene exportieren.
2. **User-Directory** – ``~/.elder-berry/plugins/*.py``. Endnutzer
   koennen eigene Plugins ohne pip-Install ablegen.
3. **Entry-Points** – ``elder_berry.commands`` Group via
   ``importlib.metadata``. Distributable Drittanbieter-Plugins.

Test-Sandbox: ``tests/conftest.py`` ersetzt ``_load_user_directory``
und ``_load_entry_points`` per autouse-Fixture mit leeren Iteratoren,
damit die Test-Suite deterministisch laeuft (Phase 77 Etappe 3).
Tests, die diese Loader testen, opt-in per
``pytestmark = pytest.mark.real_plugin_loaders``.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

from elder_berry.comms.commands.base import CommandPlugin

logger = logging.getLogger(__name__)

USER_PLUGIN_DIR_NAME = ".elder-berry"
"""Top-Level-Verzeichnis im User-Home (~/<USER_PLUGIN_DIR_NAME>/plugins/)."""

ENTRY_POINT_GROUP = "elder_berry.commands"
"""Entry-Point-Group fuer pip-installierte Plugins."""


def _load_builtin() -> Iterator[CommandPlugin]:
    """Lädt PLUGIN-Objekte aus comms/commands/<name>_commands.py.

    Iteriert ueber alle ``*_commands.py`` Dateien neben dieser Datei,
    importiert sie als Modul und yieldet das ``PLUGIN``-Attribut, falls
    es ein ``CommandPlugin`` ist. Module ohne ``PLUGIN``-Export werden
    schweigend uebersprungen.
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


def _user_plugin_dir() -> Path:
    """Pfad zum User-Plugin-Verzeichnis (~/.elder-berry/plugins/)."""
    return Path.home() / USER_PLUGIN_DIR_NAME / "plugins"


def _load_user_directory() -> Iterator[CommandPlugin]:
    """Lädt Plugins aus ``~/.elder-berry/plugins/*.py`` (Konzept §3.3).

    Robust gegen kaputte Plugins (R6 im Konzept): jede Exception waehrend
    Spec-Erstellung oder Modul-Execution wird gefangen und geloggt, der
    Loader macht mit dem naechsten Plugin weiter. Dateien mit ``_``-Prefix
    werden uebersprungen (Konvention fuer __init__/private Helfer).
    """
    user_dir = _user_plugin_dir()
    if not user_dir.exists():
        return
    for path in sorted(user_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"elder_berry_user_plugin_{path.stem}", path
            )
        except Exception as exc:
            logger.warning(
                "User-Plugin %s: spec_from_file_location fehlgeschlagen: %s",
                path.name,
                exc,
            )
            continue
        if spec is None or spec.loader is None:
            logger.warning(
                "User-Plugin %s: kein gueltiger Spec/Loader, uebersprungen.",
                path.name,
            )
            continue
        module: ModuleType = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            logger.warning("User-Plugin %s fehlgeschlagen: %s", path.name, exc)
            continue
        plugin = getattr(module, "PLUGIN", None)
        if isinstance(plugin, CommandPlugin):
            yield plugin


def _load_entry_points() -> Iterator[CommandPlugin]:
    """Lädt Plugins aus pip-installierten Paketen.

    Entry-Point-Group: ``elder_berry.commands``. R3 im Konzept: wer ein
    ``pip install elder-berry-plugin-foo`` macht, laedt fremden Code --
    bewusste Designentscheidung, weil Plugins Nutzer-Code sind. Spaeter
    deaktivierbar per Setting (out of scope dieser Phase).

    Stub-Versions-Drift: ``importlib.metadata.entry_points(group=...)``
    und ``EntryPoint.load()`` werden je nach typeshed-Version mal als
    typed, mal als untyped gefuehrt (vgl. Phase 76c b8ecbc0 fuer das
    google-auth-Aequivalent). Dual-ignore deckt beide Stub-Varianten ab.
    """
    from importlib.metadata import entry_points

    # Stub-Versions-Drift: in alten Stubs typed, in neuen untyped.
    eps = entry_points(group=ENTRY_POINT_GROUP)  # type: ignore[no-untyped-call,unused-ignore]
    for ep in eps:
        try:
            plugin = ep.load()  # type: ignore[no-untyped-call,unused-ignore]
        except Exception as exc:
            logger.warning("Entry-Point %s fehlgeschlagen: %s", ep.name, exc)
            continue
        if isinstance(plugin, CommandPlugin):
            yield plugin


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
