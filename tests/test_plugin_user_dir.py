"""Phase 77 Etappe 3: Tests fuer User-Dir-Plugin-Discovery.

Prueft ``_load_user_directory`` und das Override-Verhalten in
``load_plugins``:

- Plugin in ~/.elder-berry/plugins/ wird geladen.
- User-Plugin mit ``name="weather"`` ueberschreibt das Builtin (R2).
- Kaputtes Plugin wirft den Loader nicht (R6).
- Files mit ``_``-Prefix werden uebersprungen.

Setup: ``monkeypatch.setattr(Path, "home", ...)`` redirected ``Path.home()``
auf ein tmp-Verzeichnis. Damit greift die Sandbox-Fixture aus
``conftest.py`` zwar weiter (autouse), aber wir umgehen sie hier
explizit per ``pytestmark = pytest.mark.real_plugin_loaders``.

Test ist NICHT strict-mypy-geprueft (analog test_plugin_registry.py).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from elder_berry.comms.commands.registry import (
    _load_user_directory,
    load_plugins,
)

pytestmark = pytest.mark.real_plugin_loaders


# --- Plugin-Dateien fuer den Loader -------------------------------------

_MINIMAL_PLUGIN = dedent(
    """\
    from elder_berry.comms.commands.base import (
        CommandHandler, CommandPlugin, CommandResult, HandlerContext,
    )

    class _Demo(CommandHandler):
        @property
        def simple_commands(self):
            return {"demo"}
        def execute(self, command, raw_text):
            return CommandResult(command=command, success=True, text="demo!")

    def _factory(ctx: HandlerContext):
        return _Demo()

    PLUGIN = CommandPlugin(
        name="demo_user",
        priority=55,
        category="basis",
        help_section="Demo: hallo",
        factory=_factory,
    )
    """
)

_OVERRIDE_WEATHER_PLUGIN = dedent(
    """\
    from elder_berry.comms.commands.base import (
        CommandHandler, CommandPlugin, CommandResult, HandlerContext,
    )

    class _FakeWeather(CommandHandler):
        @property
        def simple_commands(self):
            return {"wetter"}
        def execute(self, command, raw_text):
            return CommandResult(command=command, success=True, text="42")

    PLUGIN = CommandPlugin(
        name="weather",  # ueberschreibt Builtin
        priority=15,
        category="wetter",
        help_section="Custom Weather",
        factory=lambda ctx: _FakeWeather(),
        version="9.9.9",
    )
    """
)

_BROKEN_PLUGIN = dedent(
    """\
    raise RuntimeError("Plugin ist kaputt -- soll Loader nicht killen.")
    """
)


def _setup_user_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirected Path.home() auf tmp_path und legt plugins-Verzeichnis an."""
    fake_home = tmp_path / "home"
    plugins_dir = fake_home / ".elder-berry" / "plugins"
    plugins_dir.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    return plugins_dir


# --- Tests --------------------------------------------------------------


def test_user_dir_plugin_is_loaded(tmp_path, monkeypatch):
    """Minimal-Plugin in ~/.elder-berry/plugins/demo.py wird gefunden."""
    plugins_dir = _setup_user_dir(tmp_path, monkeypatch)
    (plugins_dir / "demo.py").write_text(_MINIMAL_PLUGIN, encoding="utf-8")

    plugins = list(_load_user_directory())
    names = [p.name for p in plugins]
    assert "demo_user" in names, f"Plugin nicht geladen, gefunden: {names}"


def test_user_dir_skips_underscore_prefixed_files(tmp_path, monkeypatch):
    """Dateien wie __init__.py oder _helpers.py duerfen nicht geladen werden."""
    plugins_dir = _setup_user_dir(tmp_path, monkeypatch)
    (plugins_dir / "_private.py").write_text(_MINIMAL_PLUGIN, encoding="utf-8")
    (plugins_dir / "__init__.py").write_text("", encoding="utf-8")

    plugins = list(_load_user_directory())
    assert plugins == []


def test_user_dir_missing_directory_returns_empty(tmp_path, monkeypatch):
    """Kein ~/.elder-berry/plugins/-Verzeichnis -> leerer Iterator, kein Error."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    plugins = list(_load_user_directory())
    assert plugins == []


def test_user_dir_broken_plugin_does_not_kill_loader(tmp_path, monkeypatch, caplog):
    """R6: kaputtes Plugin geloggt, aber andere Plugins kommen weiter durch."""
    plugins_dir = _setup_user_dir(tmp_path, monkeypatch)
    (plugins_dir / "broken.py").write_text(_BROKEN_PLUGIN, encoding="utf-8")
    (plugins_dir / "ok.py").write_text(_MINIMAL_PLUGIN, encoding="utf-8")

    with caplog.at_level("WARNING"):
        plugins = list(_load_user_directory())

    names = [p.name for p in plugins]
    assert "demo_user" in names, "OK-Plugin wurde uebersprungen wegen kaputtem Nachbarn"
    assert any("broken.py" in r.message for r in caplog.records), (
        "Kaputtes Plugin wurde nicht im Log markiert"
    )


def test_user_plugin_overrides_builtin(tmp_path, monkeypatch):
    """R2: User-Plugin mit name='weather' ueberschreibt das Builtin.

    Akzeptanzkriterium aus Konzept §10: User-Plugin sichtbar in
    load_plugins(), Builtin verschwindet.
    """
    plugins_dir = _setup_user_dir(tmp_path, monkeypatch)
    (plugins_dir / "myweather.py").write_text(
        _OVERRIDE_WEATHER_PLUGIN, encoding="utf-8"
    )

    plugins = load_plugins()
    by_name = {p.name: p for p in plugins}
    assert "weather" in by_name
    weather = by_name["weather"]
    assert weather.version == "9.9.9", (
        f"Builtin nicht ueberschrieben (version={weather.version})"
    )
    assert weather.help_section == "Custom Weather"


def test_user_plugin_without_PLUGIN_is_skipped(tmp_path, monkeypatch):
    """Datei ohne PLUGIN-Konstante wird stumm uebersprungen, kein Error."""
    plugins_dir = _setup_user_dir(tmp_path, monkeypatch)
    (plugins_dir / "no_manifest.py").write_text("x = 42\n", encoding="utf-8")

    plugins = list(_load_user_directory())
    assert plugins == []
