"""Sensor-Sektionen der frame_config (Phase 111, E3).

* ``proximity``: APDS-9960 (Bus, Adresse, Register) und die Schwellen des
  ProximityAttentionProvider. Schwellen sind RELATIV zum Grundwert
  ``thresholds.baseline``. Defaults = Platzhalter, vor M5 nicht kalibriert.
* ``thermal``: Temperaturueberwachung und optional BME280 (D1).

Ungueltige Werte brechen mit ``FrameConfigError`` ab (Muster E2).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from elder_berry.room_display.config_values import (
    FrameConfigError,
    boolean,
    int_in_range,
    number_in_range,
    optional_int_in_range,
    section,
)


@dataclass(frozen=True)
class ProximityConfig:
    enabled: bool
    bus: int
    address: int
    atime: int
    ppulse: int
    control: int
    enable_register: int
    offset_ur: int | None
    offset_dl: int | None
    baseline: int
    away_below: int
    present_above: int
    focused_off: int
    focused_on: int
    debounce_s: float
    sample_interval_s: float
    saturation_value: int
    fault_after_s: float
    fault_clear_s: float


@dataclass(frozen=True)
class ThermalConfig:
    enabled: bool
    interval_s: float
    cpu_warn_c: float
    bme280_enabled: bool
    bme280_bus: int
    bme280_address: int
    enclosure_warn_c: float


def parse_proximity(data: Mapping[str, Any], source: str) -> ProximityConfig:
    p = section(data, "proximity", source)
    w = f"{source}: proximity"
    registers = section(p, "registers", w)
    thresholds = section(p, "thresholds", w)
    t = f"{w}.thresholds"
    away_below = int_in_range(
        thresholds.get("away_below"), f"{t}.away_below", -255, 255
    )
    present_above = int_in_range(
        thresholds.get("present_above"), f"{t}.present_above", -255, 255
    )
    focused_off = int_in_range(
        thresholds.get("focused_off"), f"{t}.focused_off", -255, 255
    )
    focused_on = int_in_range(
        thresholds.get("focused_on"), f"{t}.focused_on", -255, 255
    )
    if not away_below <= present_above <= focused_off < focused_on:
        raise FrameConfigError(
            f"{t}: es muss away_below <= present_above <= focused_off < focused_on "
            f"gelten (war: {away_below}, {present_above}, {focused_off}, {focused_on})"
        )
    return ProximityConfig(
        enabled=boolean(p.get("enabled", True), f"{w}.enabled"),
        bus=int_in_range(p.get("bus"), f"{w}.bus", 0, 99),
        address=int_in_range(p.get("address"), f"{w}.address", 0x03, 0x77),
        atime=int_in_range(registers.get("atime"), f"{w}.registers.atime", 0, 255),
        ppulse=int_in_range(registers.get("ppulse"), f"{w}.registers.ppulse", 0, 255),
        control=int_in_range(
            registers.get("control"), f"{w}.registers.control", 0, 255
        ),
        enable_register=int_in_range(
            registers.get("enable"), f"{w}.registers.enable", 0, 255
        ),
        offset_ur=optional_int_in_range(
            p.get("offset_ur"), f"{w}.offset_ur", -127, 127
        ),
        offset_dl=optional_int_in_range(
            p.get("offset_dl"), f"{w}.offset_dl", -127, 127
        ),
        baseline=int_in_range(thresholds.get("baseline"), f"{t}.baseline", 0, 255),
        away_below=away_below,
        present_above=present_above,
        focused_off=focused_off,
        focused_on=focused_on,
        debounce_s=number_in_range(p.get("debounce_ms"), f"{w}.debounce_ms", 0, 5000)
        / 1000.0,
        sample_interval_s=number_in_range(
            p.get("sample_interval_ms"), f"{w}.sample_interval_ms", 5, 1000
        )
        / 1000.0,
        saturation_value=int_in_range(
            p.get("saturation_value"), f"{w}.saturation_value", 1, 255
        ),
        fault_after_s=number_in_range(
            p.get("fault_after_s"), f"{w}.fault_after_s", 1, 3600
        ),
        fault_clear_s=number_in_range(
            p.get("fault_clear_s"), f"{w}.fault_clear_s", 0, 3600
        ),
    )


def parse_thermal(data: Mapping[str, Any], source: str) -> ThermalConfig:
    th = section(data, "thermal", source)
    w = f"{source}: thermal"
    bme = section(th, "bme280", w)
    return ThermalConfig(
        enabled=boolean(th.get("enabled", True), f"{w}.enabled"),
        interval_s=number_in_range(th.get("interval_s"), f"{w}.interval_s", 1, 86400),
        cpu_warn_c=number_in_range(th.get("cpu_warn_c"), f"{w}.cpu_warn_c", 30, 110),
        bme280_enabled=boolean(bme.get("enabled", True), f"{w}.bme280.enabled"),
        bme280_bus=int_in_range(bme.get("bus"), f"{w}.bme280.bus", 0, 99),
        bme280_address=int_in_range(
            bme.get("address"), f"{w}.bme280.address", 0x76, 0x77
        ),
        enclosure_warn_c=number_in_range(
            bme.get("warn_c"), f"{w}.bme280.warn_c", 0, 100
        ),
    )
