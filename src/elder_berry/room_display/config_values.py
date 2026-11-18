"""Gemeinsame Pruef-Helfer fuer frame_config (Phase 111).

Ausgelagert, damit ``frame_config`` und ``sensor_config`` sie nutzen koennen,
ohne sich gegenseitig zu importieren. ``FrameConfigError`` wird von
``frame_config`` re-exportiert (bestehender Importpfad bleibt gueltig).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class FrameConfigError(ValueError):
    """Die Konfiguration ist nicht lesbar oder enthaelt ungueltige Werte."""


def section(data: Mapping[str, Any], name: str, where: str) -> Mapping[str, Any]:
    value = data.get(name)
    if not isinstance(value, Mapping):
        raise FrameConfigError(f"{where}: Sektion '{name}' fehlt oder ist kein Mapping")
    return value


def int_in_range(value: object, where: str, low: int, high: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not low <= value <= high
    ):
        raise FrameConfigError(
            f"{where} muss eine ganze Zahl zwischen {low} und {high} sein (war: {value!r})"
        )
    return value


def optional_int_in_range(value: object, where: str, low: int, high: int) -> int | None:
    return None if value is None else int_in_range(value, where, low, high)


def number_in_range(value: object, where: str, low: float, high: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not low <= float(value) <= high
    ):
        raise FrameConfigError(
            f"{where} muss eine Zahl zwischen {low} und {high} sein (war: {value!r})"
        )
    return float(value)


def boolean(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise FrameConfigError(f"{where} muss true/false sein (war: {value!r})")
    return value
