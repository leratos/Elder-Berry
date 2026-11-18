"""Tests fuer Bme280Reader (Phase 111, E3, D1) mit Fake-SMBus."""

from __future__ import annotations

import logging

import pytest

from elder_berry.robot.bme280_reader import (
    CTRL_MEAS_FORCED_T1,
    REG_CALIB_T,
    REG_CHIP_ID,
    REG_CTRL_MEAS,
    REG_STATUS,
    REG_TEMP_MSB,
    Bme280Error,
    Bme280Reader,
    compensate_temperature,
)

# Rechenbeispiel aus dem Bosch-Datenblatt (BMP280, Abschnitt 3.12; gleiche
# Temperaturformel wie BME280 Abschnitt 4.2.3).
DIG_T1, DIG_T2, DIG_T3, ADC_T = 27504, 26435, -1000, 519888


def test_compensation_matches_datasheet_example():
    t_fine, celsius = compensate_temperature(ADC_T, DIG_T1, DIG_T2, DIG_T3)
    assert t_fine == 128422
    assert celsius == 25.08


def _le16(value: int) -> list[int]:
    value &= 0xFFFF
    return [value & 0xFF, value >> 8]


class FakeBme:
    def __init__(self, chip_id=0x60, busy_reads=1):
        calib = _le16(DIG_T1) + _le16(DIG_T2) + _le16(DIG_T3)
        self.registers = {REG_CHIP_ID: chip_id}
        self.registers.update({REG_CALIB_T + i: b for i, b in enumerate(calib)})
        # adc_T = 519888 = 0x7EED0 -> msb 0x7E, lsb 0xED, xlsb 0x00
        self.registers.update(
            {REG_TEMP_MSB: 0x7E, REG_TEMP_MSB + 1: 0xED, REG_TEMP_MSB + 2: 0x00}
        )
        self.busy_reads = busy_reads
        self.writes = []
        self.addresses = set()
        self.closed = False

    def read_byte_data(self, addr, register):
        self.addresses.add(addr)
        if register == REG_STATUS:
            if self.busy_reads > 0:
                self.busy_reads -= 1
                return 0x08
            return 0x00
        return self.registers[register]

    def write_byte_data(self, addr, register, value):
        self.writes.append((addr, register, value))

    def close(self):
        self.closed = True


def _reader(bus, **kwargs):
    return Bme280Reader(bus_factory=lambda n: bus, sleep=lambda s: None, **kwargs)


def test_reads_temperature_from_registers():
    bus = FakeBme()
    reader = _reader(bus)
    assert reader.is_available()
    assert reader.read_temperature_c() == 25.08
    assert bus.writes == [(0x76, REG_CTRL_MEAS, CTRL_MEAS_FORCED_T1)]
    assert bus.addresses == {0x76}


def test_wrong_chip_id_is_unavailable(caplog):
    caplog.set_level(logging.WARNING)
    bus = FakeBme(chip_id=0x58)  # BMP280
    reader = _reader(bus)
    assert reader.is_available() is False
    assert "kein BME280" in caplog.text
    assert bus.closed


def test_unavailable_logs_once(caplog):
    caplog.set_level(logging.WARNING)

    def no_bus(number):
        raise FileNotFoundError(2, "No such file or directory: '/dev/i2c-1'")

    reader = Bme280Reader(bus_factory=no_bus)
    assert [reader.is_available() for _ in range(5)] == [False] * 5
    assert caplog.text.count("BME280 nicht verfuegbar") == 1


def test_measurement_stuck_raises():
    reader = _reader(FakeBme(busy_reads=1000))
    reader.open()
    with pytest.raises(Bme280Error, match="nicht fertig"):
        reader.read_temperature_c()


def test_read_without_open_raises():
    with pytest.raises(Bme280Error):
        Bme280Reader(bus_factory=lambda n: FakeBme()).read_temperature_c()
