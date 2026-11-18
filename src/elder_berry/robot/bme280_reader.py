"""Bme280Reader -- Temperatur der Gehaeuseluft vom BME280 (Phase 111, E3, D1).

Minimal und streichbar (D1, #1475): nur Temperatur, kein Druck, keine
Feuchte. KEIN ``SensorManager`` (Ae11: ``get_battery`` passt nicht).

Kompensation selbst implementiert nach der Integer-Formel aus dem
Bosch-Datenblatt (BME280, Abschnitt 4.2.3 "Compensation formulas";
identisch zur Temperaturformel des BMP280). Getestet gegen das
Rechenbeispiel aus dem BMP280-Datenblatt (Abschnitt 3.12: dig_T1=27504,
dig_T2=26435, dig_T3=-1000, adc_T=519888 -> t_fine=128422, T=25,08 Grad C).
Grund gegen eine Bibliothek: eine zusaetzliche Abhaengigkeit fuer ca. 20
Zeilen Rechnung. Die in #1441 benutzte ``RPi.bme280`` (MIT) hatte als
letzte Version 0.2.4 und wird nicht aktiv gepflegt.

Messablauf: Forced Mode, Temperatur-Oversampling x1, Druck/Feuchte aus
(ctrl_meas 0xF4 = 0x21), warten bis status 0xF3 Bit 3 frei ist, dann
0xFA..0xFC lesen.

Plattformhinweis: wie der APDS-9960 an I2C-Bus 1, Adresse 0x76 (#1439).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from elder_berry.robot.apds9960_proximity import SMBusLike

logger = logging.getLogger(__name__)

REG_CHIP_ID = 0xD0
REG_CALIB_T = 0x88
REG_STATUS = 0xF3
REG_CTRL_MEAS = 0xF4
REG_TEMP_MSB = 0xFA

EXPECTED_CHIP_ID = 0x60
CTRL_MEAS_FORCED_T1 = 0x21  # osrs_t=1, osrs_p=0 (aus), mode=forced
_STATUS_MEASURING = 0x08


class Bme280Error(OSError):
    """I2C-Zugriff auf den BME280 ist fehlgeschlagen."""


def compensate_temperature(
    adc_t: int, dig_t1: int, dig_t2: int, dig_t3: int
) -> tuple[int, float]:
    """Integer-Kompensation nach Datenblatt.

    Returns:
        ``(t_fine, grad_celsius)``.
    """
    var1 = (((adc_t >> 3) - (dig_t1 << 1)) * dig_t2) >> 11
    var2 = (((((adc_t >> 4) - dig_t1) * ((adc_t >> 4) - dig_t1)) >> 12) * dig_t3) >> 14
    t_fine = var1 + var2
    hundredths = (t_fine * 5 + 128) >> 8
    return t_fine, hundredths / 100.0


def _u16(lsb: int, msb: int) -> int:
    return (msb << 8) | lsb


def _s16(lsb: int, msb: int) -> int:
    value = _u16(lsb, msb)
    return value - 0x10000 if value & 0x8000 else value


def _default_bus_factory(bus: int) -> SMBusLike:
    from smbus2 import SMBus  # lazy: nur auf dem Rahmen-Pi noetig

    opened: SMBusLike = SMBus(bus)  # ohne installiertes smbus2 (CI-mypy) sonst Any
    return opened


class Bme280Reader:
    """Liest die Temperatur der Gehaeuseluft.

    Args:
        bus: I2C-Bus (RPi: 1).
        address: 0x76 (#1439) oder 0x77.
        bus_factory: Erzeugt den Bus (Tests: Fake).
        sleep: Wartefunktion (Tests: no-op).
    """

    def __init__(
        self,
        bus: int = 1,
        address: int = 0x76,
        *,
        bus_factory: Callable[[int], SMBusLike] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._bus_no = bus
        self._address = address
        self._bus_factory = bus_factory or _default_bus_factory
        self._sleep = sleep
        self._bus: SMBusLike | None = None
        self._calib: tuple[int, int, int] | None = None
        self._unavailable_logged = False

    def open(self) -> None:
        """Bus oeffnen, Chip-ID pruefen, Kalibrierdaten lesen.

        Raises:
            Bme280Error: Bus/Geraet nicht erreichbar oder kein BME280.
        """
        if self._bus is not None:
            return
        try:
            bus = self._bus_factory(self._bus_no)
        except (ImportError, OSError) as exc:
            raise Bme280Error(
                f"I2C-Bus {self._bus_no} nicht verfuegbar: {exc}"
            ) from exc
        try:
            chip_id = bus.read_byte_data(self._address, REG_CHIP_ID)
            if chip_id != EXPECTED_CHIP_ID:
                raise Bme280Error(
                    f"Chip-ID 0x{chip_id:02X} an 0x{self._address:02X} ist kein BME280 "
                    f"(erwartet 0x{EXPECTED_CHIP_ID:02X})"
                )
            raw = [bus.read_byte_data(self._address, REG_CALIB_T + i) for i in range(6)]
        except OSError as exc:
            bus.close()
            if isinstance(exc, Bme280Error):
                raise
            raise Bme280Error(
                f"BME280 an Bus {self._bus_no}, Adresse 0x{self._address:02X} antwortet nicht: {exc}"
            ) from exc
        self._calib = (_u16(raw[0], raw[1]), _s16(raw[2], raw[3]), _s16(raw[4], raw[5]))
        self._bus = bus
        logger.info(
            "BME280 bereit: Bus %d, Adresse 0x%02X", self._bus_no, self._address
        )

    def is_available(self) -> bool:
        """True, wenn geoeffnet oder oeffenbar; sonst genau EINE WARNING."""
        try:
            self.open()
        except Bme280Error as exc:
            if not self._unavailable_logged:
                logger.warning("BME280 nicht verfuegbar: %s", exc)
                self._unavailable_logged = True
            return False
        return True

    def read_temperature_c(self) -> float:
        """Eine Messung im Forced Mode.

        Raises:
            Bme280Error: nicht geoeffnet, I2C-Fehler oder Messung haengt.
        """
        if self._bus is None or self._calib is None:
            raise Bme280Error("BME280 nicht geoeffnet")
        bus, addr = self._bus, self._address
        try:
            bus.write_byte_data(addr, REG_CTRL_MEAS, CTRL_MEAS_FORCED_T1)
            for _ in range(20):  # x1-Oversampling dauert typisch ~2 ms
                if not bus.read_byte_data(addr, REG_STATUS) & _STATUS_MEASURING:
                    break
                self._sleep(0.002)
            else:
                raise Bme280Error("Messung nicht fertig geworden")
            msb, lsb, xlsb = (
                bus.read_byte_data(addr, REG_TEMP_MSB + i) for i in range(3)
            )
        except Bme280Error:
            raise
        except OSError as exc:
            raise Bme280Error(f"Temperatur lesen fehlgeschlagen: {exc}") from exc
        adc_t = (msb << 12) | (lsb << 4) | (xlsb >> 4)
        _, celsius = compensate_temperature(adc_t, *self._calib)
        return celsius

    def close(self) -> None:
        if self._bus is not None:
            bus, self._bus = self._bus, None
            bus.close()
