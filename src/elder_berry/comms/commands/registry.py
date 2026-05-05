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

Phase 77.5 (Plugin-Inspector): Loader liefern intern ``LoadedPlugin``-
Wrapper mit Quellen-Information. ``load_plugins()`` bleibt
rueckwaertskompatibel (extrahiert ``.plugin`` fuer die alte API), neuer
Helfer ``load_plugins_with_sources()`` liefert die Wrapper fuer den
Inspector und den System-Prompt-Block.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import ModuleType

from elder_berry.comms.commands.base import CommandPlugin

logger = logging.getLogger(__name__)

USER_PLUGIN_DIR_NAME = ".elder-berry"
"""Top-Level-Verzeichnis im User-Home (~/<USER_PLUGIN_DIR_NAME>/plugins/)."""

ENTRY_POINT_GROUP = "elder_berry.commands"
"""Entry-Point-Group fuer pip-installierte Plugins."""


class PluginSource(Enum):
    """Quelle eines geladenen Plugins (Phase 77.5).

    Die drei Loader (``_load_builtin``, ``_load_user_directory``,
    ``_load_entry_points``) annotieren jedes Plugin mit dem zugehoerigen
    Wert. Der Inspector-API und der System-Prompt-Block koennen so
    unterscheiden, ob ein Plugin Teil des Repos, eine User-Datei oder
    ein pip-installiertes Drittanbieter-Paket ist.
    """

    BUILTIN = "builtin"
    USER_DIR = "user_dir"
    ENTRY_POINT = "entry_point"


@dataclass(frozen=True)
class LoadedPlugin:
    """Wrapper fuer ein geladenes Plugin mit Quellen-Information (Phase 77.5).

    ``CommandPlugin`` ist ``frozen=True`` und Plugin-Autoren-Eigentum --
    erweitern wuerde Manifeste brechen. Stattdessen kapselt
    ``LoadedPlugin`` das Plugin-Manifest plus Loader-Metadaten:

    - ``source``: aus welchem der drei Loader das Plugin stammt.
    - ``source_path``: Datei-Pfad bzw. Distribution-Name, debug-only.
      Builtin -> ``<name>_commands.py``,
      User-Dir -> absoluter Pfad,
      Entry-Point -> Distribution-Name (z.B. ``elder-berry-plugin-foo``).
    """

    plugin: CommandPlugin
    source: PluginSource
    source_path: str | None = None


def _load_builtin() -> Iterator[LoadedPlugin]:
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
            yield LoadedPlugin(
                plugin=plugin,
                source=PluginSource.BUILTIN,
                source_path=path.name,
            )


def _user_plugin_dir() -> Path:
    """Pfad zum User-Plugin-Verzeichnis (~/.elder-berry/plugins/)."""
    return Path.home() / USER_PLUGIN_DIR_NAME / "plugins"


def _load_user_directory() -> Iterator[LoadedPlugin]:
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
            yield LoadedPlugin(
                plugin=plugin,
                source=PluginSource.USER_DIR,
                source_path=str(path),
            )


def _load_entry_points() -> Iterator[LoadedPlugin]:
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
            # Distribution-Name ist nicht garantiert verfuegbar (lokale
            # eggs ohne dist), darum None-tolerant.
            dist_name: str | None = None
            dist = getattr(ep, "dist", None)
            if dist is not None:
                dist_name = getattr(dist, "name", None) or getattr(
                    dist, "project_name", None
                )
            yield LoadedPlugin(
                plugin=plugin,
                source=PluginSource.ENTRY_POINT,
                source_path=dist_name,
            )


def _dedupe_and_sort(loaded: list[LoadedPlugin]) -> list[LoadedPlugin]:
    """Dedupliziert nach Plugin-Name und sortiert nach Priority.

    Praezedenz bei Namens-Konflikt (Konzept §3.3): User-Dir > Entry-Point
    > Builtin. Reihenfolge der ``loaded``-Liste muss diese Praezedenz
    bereits widerspiegeln (Builtin zuerst, dann Entry-Point, dann
    User-Dir), damit spaetere Eintraege fruehere ueberschreiben.
    """
    by_name: dict[str, LoadedPlugin] = {}
    for entry in loaded:
        existing = by_name.get(entry.plugin.name)
        if existing is not None:
            logger.info(
                "Plugin %s wird ueberschrieben (vorher v%s aus %s, jetzt v%s aus %s)",
                entry.plugin.name,
                existing.plugin.version,
                existing.source.value,
                entry.plugin.version,
                entry.source.value,
            )
        by_name[entry.plugin.name] = entry

    return sorted(by_name.values(), key=lambda e: e.plugin.priority)


def load_plugins_with_sources() -> list[LoadedPlugin]:
    """Lädt alle Plugins inklusive Quellen-Information (Phase 77.5).

    Praezedenz bei Namens-Konflikt: User-Dir > Entry-Point > Builtin.
    Sortierung nach ``CommandPlugin.priority``.
    """
    loaded: list[LoadedPlugin] = list(_load_builtin())
    loaded.extend(_load_entry_points())
    loaded.extend(_load_user_directory())
    return _dedupe_and_sort(loaded)


def load_plugins() -> list[CommandPlugin]:
    """Lädt alle Plugins, dedupliziert nach Name, sortiert nach Priorität.

    Praezedenz bei Namens-Konflikt (Konzept §3.3):
    User-Dir > Entry-Point > Builtin.

    Phase 77.5: bleibt rueckwaertskompatibel (alle bestehenden Aufrufer
    erwarten ``list[CommandPlugin]``). Wer Quellen-Info braucht, nutzt
    ``load_plugins_with_sources()``.
    """
    return [entry.plugin for entry in load_plugins_with_sources()]
