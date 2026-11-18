"""Tests fuer Apds9960Proximity (Phase 111, E3) mit Fake-SMBus."""

from __future__ import annotations

import logging

import pytest

from elder_berry.robot.apds9960_proximity import (
    REG_CONTROL,
    REG_ENABLE,
    REG_ATIME,
    REG_ID,
    REG_PDATA,
    REG_POFFSET_DL,
    REG_POFFSET_UR,
    REG_PPULSE,
    Apds9960Error,
    Apds9960Proximity,
    Apds9960Settings,
    encode_offset,
)


class FakeBus:
    def __init__(self, chip_id=0xAB, pdata=(128,), fail_reads=False, fail_writes=False):
        self.chip_id = chip_id
        self.pdata = list(pdata)
        self.fail_reads = fail_reads
        self.fail_writes = fail_writes
        self.writes: list[tuple[int, int, int]] = []
        self.closed = False

    def read_byte_data(self, addr, register):
        if self.fail_reads:
            raise OSError(121, "Remote I/O error")
        if register == REG_ID:
            return self.chip_id
        if register == REG_PDATA:
            return self.pdata.pop(0) if len(self.pdata) > 1 else self.pdata[0]
        raise AssertionError(f"unerwartetes Register 0x{register:02X}")

    def write_byte_data(self, addr, register, value):
        if self.fail_writes:
            raise OSError(121, "Remote I/O error")
        self.writes.append((addr, register, value))

    def close(self):
        self.closed = True


def _driver(bus, settings=None):
    opened = []

    def factory(number):
        opened.append(number)
        return bus

    return Apds9960Proximity(settings, bus_factory=factory), opened


def test_configuration_b_registers_and_order():
    bus = FakeBus()
    driver, opened = _driver(bus)
    driver.open()
    assert opened == [1]
    assert bus.writes == [
        (0x39, REG_ENABLE, 0x00),
        (0x39, REG_ATIME, 0xDB),
        (0x39, REG_PPULSE, 0xFF),
        (0x39, REG_CONTROL, 0x0D),
        (0x39, REG_ENABLE, 0x07),
    ]
    assert driver.chip_id == 0xAB


def test_bus_and_address_from_settings():
    bus = FakeBus()
    driver, opened = _driver(bus, Apds9960Settings(bus=3, address=0x29))
    driver.open()
    assert opened == [3]
    assert {addr for addr, _, _ in bus.writes} == {0x29}


def test_id_mismatch_warns_but_continues(caplog):
    caplog.set_level(logging.WARNING)
    bus = FakeBus(chip_id=0xA8)
    driver, _ = _driver(bus)
    driver.open()
    assert "ID 0xA8 statt 0xAB" in caplog.text
    assert bus.writes[-1] == (0x39, REG_ENABLE, 0x07)
    assert driver.read_proximity() == 128


def test_offsets_only_when_configured():
    bus = FakeBus()
    driver, _ = _driver(bus, Apds9960Settings(offset_ur=-20, offset_dl=5))
    driver.open()
    registers = [reg for _, reg, _ in bus.writes]
    assert registers == [
        REG_ENABLE,
        REG_ATIME,
        REG_PPULSE,
        REG_CONTROL,
        REG_POFFSET_UR,
        REG_POFFSET_DL,
        REG_ENABLE,
    ]
    values = {
        reg: val
        for _, reg, val in bus.writes
        if reg in (REG_POFFSET_UR, REG_POFFSET_DL)
    }
    assert values == {REG_POFFSET_UR: 0x80 | 20, REG_POFFSET_DL: 5}


def test_no_offset_registers_by_default():
    bus = FakeBus()
    driver, _ = _driver(bus)
    driver.open()
    assert all(reg not in (REG_POFFSET_UR, REG_POFFSET_DL) for _, reg, _ in bus.writes)


@pytest.mark.parametrize(
    ("value", "encoded"), [(0, 0), (127, 127), (-1, 0x81), (-127, 0xFF)]
)
def test_encode_offset(value, encoded):
    assert encode_offset(value) == encoded


def test_encode_offset_range():
    with pytest.raises(ValueError):
        encode_offset(128)


def test_read_proximity():
    driver, _ = _driver(FakeBus(pdata=(3, 200, 255)))
    driver.open()
    assert [driver.read_proximity() for _ in range(3)] == [3, 200, 255]


def test_is_available_without_device_warns_once(caplog):
    caplog.set_level(logging.WARNING)

    def no_bus(number):
        raise FileNotFoundError(2, "No such file or directory: '/dev/i2c-1'")

    driver = Apds9960Proximity(bus_factory=no_bus)
    assert [driver.is_available() for _ in range(5)] == [False] * 5
    assert caplog.text.count("APDS-9960 nicht verfuegbar") == 1


def test_device_not_answering_closes_bus():
    bus = FakeBus(fail_reads=True)
    driver, _ = _driver(bus)
    with pytest.raises(Apds9960Error, match="antwortet nicht"):
        driver.open()
    assert bus.closed


def test_missing_smbus2_is_reported_as_unavailable(caplog):
    caplog.set_level(logging.WARNING)

    def no_module(number):
        raise ImportError("No module named 'smbus2'")

    assert Apds9960Proximity(bus_factory=no_module).is_available() is False
    assert "smbus2 fehlt" in caplog.text


def test_read_error_raises_driver_error():
    bus = FakeBus()
    driver, _ = _driver(bus)
    driver.open()
    bus.fail_reads = True
    with pytest.raises(Apds9960Error) as excinfo:
        driver.read_proximity()
    assert isinstance(excinfo.value, OSError)


def test_read_without_open_raises():
    with pytest.raises(Apds9960Error, match="nicht geoeffnet"):
        Apds9960Proximity(bus_factory=lambda n: FakeBus()).read_proximity()


def test_close_disables_and_closes():
    bus = FakeBus()
    driver, _ = _driver(bus)
    driver.open()
    driver.close()
    assert bus.writes[-1] == (0x39, REG_ENABLE, 0x00)
    assert bus.closed
    driver.close()  # idempotent
