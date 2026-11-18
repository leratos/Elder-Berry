"""Tests fuer frame_sensors und die Sensor-Sektionen der frame_config (E3)."""

from __future__ import annotations

import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from elder_berry.avatar.attention import AttentionState
from elder_berry.room_display.frame_config import FrameConfigError, load_frame_config
from elder_berry.room_display.frame_sensors import build_proximity, build_thermal


def _config(tmp_path: Path, text: str = ""):
    user = tmp_path / "frame_config.yaml"
    user.write_text(textwrap.dedent(text), encoding="utf-8")
    return load_frame_config(user_path=user)


class AnyBus:
    """Antwortet als APDS-9960 (0x39) und BME280 (0x76)."""

    def __init__(self, pdata=128):
        self.pdata = pdata
        self.writes = []

    def read_byte_data(self, addr, register):
        if addr == 0x39:
            return {0x92: 0xAB, 0x9C: self.pdata}[register]
        if addr == 0x76:
            if register == 0xD0:
                return 0x60
            return 0
        raise OSError(121, "Remote I/O error")

    def write_byte_data(self, addr, register, value):
        self.writes.append((addr, register, value))

    def close(self):
        pass


def _no_bus(number):
    raise FileNotFoundError(2, f"No such file or directory: '/dev/i2c-{number}'")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestSensorConfig:
    def test_defaults(self, tmp_path):
        config = _config(tmp_path)
        p = config.proximity
        assert (p.enabled, p.bus, p.address) == (True, 1, 0x39)
        assert (p.atime, p.ppulse, p.control, p.enable_register) == (
            0xDB,
            0xFF,
            0x0D,
            0x07,
        )
        assert (p.offset_ur, p.offset_dl) == (None, None)
        assert (
            p.baseline,
            p.away_below,
            p.present_above,
            p.focused_off,
            p.focused_on,
        ) == (
            128,
            10,
            12,
            15,
            30,
        )
        assert (p.debounce_s, p.sample_interval_s) == (0.15, 0.05)
        assert (p.saturation_value, p.fault_after_s, p.fault_clear_s) == (
            255,
            60.0,
            10.0,
        )
        t = config.thermal
        assert (t.enabled, t.interval_s, t.cpu_warn_c) == (True, 300.0, 80.0)
        assert (
            t.bme280_enabled,
            t.bme280_bus,
            t.bme280_address,
            t.enclosure_warn_c,
        ) == (
            True,
            1,
            0x76,
            50.0,
        )

    def test_override_thresholds_only(self, tmp_path):
        config = _config(
            tmp_path,
            """
            proximity:
              thresholds:
                baseline: 140
                focused_on: 45
            """,
        )
        assert config.proximity.baseline == 140
        assert config.proximity.focused_on == 45
        assert config.proximity.focused_off == 15  # aus dem Default

    def test_offsets(self, tmp_path):
        config = _config(tmp_path, "proximity:\n  offset_ur: -20\n  offset_dl: 5\n")
        assert (config.proximity.offset_ur, config.proximity.offset_dl) == (-20, 5)

    @pytest.mark.parametrize(
        ("text", "match"),
        [
            ("proximity:\n  address: 0x99\n", "proximity.address"),
            ("proximity:\n  registers:\n    ppulse: 300\n", "ppulse"),
            ("proximity:\n  offset_ur: 200\n", "offset_ur"),
            ("proximity:\n  thresholds:\n    focused_on: 10\n", "focused_on"),
            ("proximity:\n  thresholds:\n    baseline: -1\n", "baseline"),
            ("proximity:\n  debounce_ms: -5\n", "debounce_ms"),
            ("proximity:\n  sample_interval_ms: 0\n", "sample_interval_ms"),
            ("proximity:\n  enabled: 'ja'\n", "enabled"),
            ("proximity: 5\n", "proximity"),
            ("thermal:\n  cpu_warn_c: 200\n", "cpu_warn_c"),
            ("thermal:\n  bme280:\n    address: 0x40\n", "bme280.address"),
            ("thermal:\n  interval_s: 0\n", "interval_s"),
        ],
    )
    def test_invalid_values(self, tmp_path, text, match):
        with pytest.raises(FrameConfigError, match=match):
            _config(tmp_path, text)

    def test_naeherung_is_a_valid_view(self, tmp_path):
        config = _config(tmp_path, "mode:\n  diagnostic:\n    view: naeherung\n")
        assert config.diagnostic.view == "naeherung"


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_build_proximity_with_device(tmp_path):
    bus = AnyBus(pdata=128 + 12)
    setup = build_proximity(_config(tmp_path).proximity, bus_factory=lambda n: bus)
    assert setup is not None
    assert setup.provider.current() == AttentionState.PRESENT
    assert setup.provider.thresholds.baseline == 128
    assert (0x39, 0x8E, 0xFF) in bus.writes


def test_build_proximity_without_device(tmp_path):
    assert build_proximity(_config(tmp_path).proximity, bus_factory=_no_bus) is None


def test_build_proximity_disabled(tmp_path):
    config = replace(_config(tmp_path).proximity, enabled=False)
    assert (
        build_proximity(config, bus_factory=lambda n: pytest.fail("kein Zugriff"))
        is None
    )


def test_build_thermal_with_and_without_bme(tmp_path):
    config = _config(tmp_path).thermal
    with_bme = build_thermal(config, bus_factory=lambda n: AnyBus())
    assert with_bme is not None and with_bme.bme280 is not None
    without = build_thermal(config, bus_factory=_no_bus)
    assert without is not None and without.bme280 is None
    assert build_thermal(replace(config, enabled=False)) is None
    no_bme = build_thermal(replace(config, bme280_enabled=False), bus_factory=_no_bus)
    assert no_bme is not None and no_bme.bme280 is None
