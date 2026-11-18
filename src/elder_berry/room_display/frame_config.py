"""FrameConfig -- Konfiguration des Geraeteprofils "frame" (Phase 111, E2).

Pfad-Aufloesung analog ``avatar_config_loader`` (#1474 Ae13):

* ``DEFAULT_CONFIG_PATH`` -- getrackter Default im Paket.
* ``USER_CONFIG_PATH`` (``~/.elder-berry/frame_config.yaml``) -- optionaler
  Override, nicht im Repo.

Abweichung vom Avatar-Muster: Der User-Override ersetzt die Datei nicht
ganz, sondern wird pro Sektion ueber den Default gelegt (er braucht nur die
abweichenden Schluessel). Und ein ungueltiger Wert faellt NICHT still auf den
Default zurueck, sondern bricht mit :class:`FrameConfigError` ab -- eine
falsche Rotation soll beim Start auffallen, nicht auf dem Display.

In E2 nur die Sektionen ``display`` und ``mode``. Die Generierungs-
Einstellungen liegen in ``portrait/scenes.yaml`` (#1477 A1).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from elder_berry.room_display.config_values import FrameConfigError
from elder_berry.room_display.sensor_config import (
    ProximityConfig,
    ThermalConfig,
    parse_proximity,
    parse_thermal,
)

__all__ = [
    "FrameConfig",
    "FrameConfigError",
    "ProximityConfig",
    "ThermalConfig",
    "apply_overrides",
    "load_frame_config",
]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "frame_config.yaml"
USER_CONFIG_PATH = Path.home() / ".elder-berry" / "frame_config.yaml"

ALLOWED_ROTATIONS = (0, 90, 180, 270)
ALLOWED_MODES = ("diagnostic",)
DIAGNOSTIC_VIEWS = ("testbild", "ueberblendung", "naeherung")


@dataclass(frozen=True)
class DisplaySettings:
    rotation: int
    fps: int
    transition_s: float
    video_driver: str | None
    fullscreen: bool


@dataclass(frozen=True)
class DiagnosticSettings:
    view: str
    transitions: int
    hold_s: float


@dataclass(frozen=True)
class FrameConfig:
    display: DisplaySettings
    mode: str
    diagnostic: DiagnosticSettings
    proximity: ProximityConfig
    thermal: ThermalConfig
    source: str


def load_frame_config(
    path: Path | None = None, *, user_path: Path | None = None
) -> FrameConfig:
    """Laedt die Konfiguration.

    Args:
        path: Expliziter Pfad. Wird gesetzt, gilt NUR diese Datei (ueber den
            Default gelegt), der User-Override wird nicht gelesen.
        user_path: Pfad des User-Overrides (Tests). Default
            :data:`USER_CONFIG_PATH`.

    Raises:
        FrameConfigError: unlesbar, kein YAML-Mapping oder ungueltiger Wert.
    """
    data = _read(DEFAULT_CONFIG_PATH)
    sources = [str(DEFAULT_CONFIG_PATH)]
    override_path = path if path is not None else (user_path or USER_CONFIG_PATH)
    if path is not None or override_path.exists():
        data = _merge(data, _read(override_path))
        sources.append(str(override_path))
    return _parse(data, " + ".join(sources))


def apply_overrides(
    config: FrameConfig,
    *,
    rotation: int | None = None,
    fps: int | None = None,
    video_driver: str | None = None,
    view: str | None = None,
) -> FrameConfig:
    """CLI-Overrides anwenden; ``None`` laesst den Wert unveraendert."""
    display = config.display
    if rotation is not None:
        display = replace(display, rotation=_rotation(rotation, "--frame-rotation"))
    if fps is not None:
        display = replace(display, fps=_fps(fps, "--frame-fps"))
    if video_driver is not None:
        display = replace(display, video_driver=video_driver or None)
    diagnostic = config.diagnostic
    if view is not None:
        diagnostic = replace(diagnostic, view=_view(view, "--frame-view"))
    return replace(config, display=display, diagnostic=diagnostic)


# ----------------------------------------------------------------------
# intern
# ----------------------------------------------------------------------


def _read(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FrameConfigError(f"{path}: nicht lesbar ({exc})") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise FrameConfigError(f"{path}: kein gueltiges YAML ({exc})") from exc
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise FrameConfigError(f"{path}: oberste Ebene ist kein Mapping")
    return dict(data)


def _merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Legt ``override`` rekursiv ueber ``base`` (Mappings werden gemischt)."""
    merged = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _section(data: Mapping[str, Any], name: str, source: str) -> Mapping[str, Any]:
    section = data.get(name)
    if not isinstance(section, Mapping):
        raise FrameConfigError(
            f"{source}: Sektion '{name}' fehlt oder ist kein Mapping"
        )
    return section


def _parse(data: Mapping[str, Any], source: str) -> FrameConfig:
    display = _section(data, "display", source)
    mode = _section(data, "mode", source)
    diagnostic = mode.get("diagnostic", {})
    if not isinstance(diagnostic, Mapping):
        raise FrameConfigError(f"{source}: mode.diagnostic ist kein Mapping")

    driver = display.get("video_driver")
    if driver is not None and (not isinstance(driver, str) or not driver.strip()):
        raise FrameConfigError(
            f"{source}: display.video_driver muss Text oder null sein"
        )
    fullscreen = display.get("fullscreen", True)
    if not isinstance(fullscreen, bool):
        raise FrameConfigError(f"{source}: display.fullscreen muss true/false sein")
    mode_name = mode.get("name")
    if mode_name not in ALLOWED_MODES:
        raise FrameConfigError(
            f"{source}: mode.name muss eins von {list(ALLOWED_MODES)} sein "
            f"(war: {mode_name!r})"
        )
    return FrameConfig(
        display=DisplaySettings(
            rotation=_rotation(display.get("rotation"), f"{source}: display.rotation"),
            fps=_fps(display.get("fps"), f"{source}: display.fps"),
            transition_s=_seconds(
                display.get("transition_s"), f"{source}: display.transition_s", 0.05
            ),
            video_driver=driver.strip() if isinstance(driver, str) else None,
            fullscreen=fullscreen,
        ),
        mode=str(mode_name),
        diagnostic=DiagnosticSettings(
            view=_view(
                diagnostic.get("view", "testbild"), f"{source}: diagnostic.view"
            ),
            transitions=_positive_int(
                diagnostic.get("transitions", 10), f"{source}: diagnostic.transitions"
            ),
            hold_s=_seconds(
                diagnostic.get("hold_s", 1.0), f"{source}: diagnostic.hold_s", 0.0
            ),
        ),
        proximity=parse_proximity(data, source),
        thermal=parse_thermal(data, source),
        source=source,
    )


def _rotation(value: object, where: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value not in ALLOWED_ROTATIONS
    ):
        raise FrameConfigError(
            f"{where} muss eins von {list(ALLOWED_ROTATIONS)} sein (war: {value!r})"
        )
    return value


def _fps(value: object, where: str) -> int:
    number = _positive_int(value, where)
    if number > 120:
        raise FrameConfigError(
            f"{where} muss zwischen 1 und 120 liegen (war: {number})"
        )
    return number


def _positive_int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise FrameConfigError(
            f"{where} muss eine ganze Zahl >= 1 sein (war: {value!r})"
        )
    return value


def _seconds(value: object, where: str, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise FrameConfigError(f"{where} muss eine Zahl sein (war: {value!r})")
    if not minimum <= float(value) <= 60.0:
        raise FrameConfigError(
            f"{where} muss zwischen {minimum} und 60 liegen (war: {value})"
        )
    return float(value)


def _view(value: object, where: str) -> str:
    if value not in DIAGNOSTIC_VIEWS:
        raise FrameConfigError(
            f"{where} muss eins von {list(DIAGNOSTIC_VIEWS)} sein (war: {value!r})"
        )
    return str(value)
