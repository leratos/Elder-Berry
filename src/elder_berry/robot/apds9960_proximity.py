"""Apds9960Proximity -- minimaler smbus2-Treiber fuer die Naeherung des APDS-9960.

Phase 111, E3 (Konzept §4.2). Nur der Naeherungskanal (PDATA), keine Gesten,
kein Licht. Registerwerte nach den Messungen am Steckbrett (#1439/#1440):

* ID-Register 0x92, erwartet 0xAB. Abweichung -> WARNING, KEIN Abbruch
  (#1436 T3: Klone melden andere IDs und funktionieren trotzdem).
* Konfiguration B (#1440, maximale Empfindlichkeit ohne LED-Boost):
  ATIME 0x81=0xDB, PPULSE 0x8E=0xFF, CONTROL 0x8F=0x0D, ENABLE 0x80=0x07.
  Schreibreihenfolge: ENABLE=0x00 (aus), ATIME, PPULSE, CONTROL, optional
  POFFSET_UR/POFFSET_DL, zuletzt ENABLE. So wird nie mit halber
  Konfiguration gemessen.
* PDATA 0x9C: 0-255. In Konfiguration B liegt der Grundwert ohne Objekt bei
  ca. 128 (internes Uebersprechen LED->Fotodiode, #1440).
* Offset-Register POFFSET_UR 0x9D / POFFSET_DL 0x9E: Vorzeichen-Betrag-
  Format (Bit 7 = negativ, Bits 6..0 = Betrag), -127..127. Default aus.

Fehler im Betrieb loest :class:`Apds9960Error` aus (Unterklasse von
``OSError``); der Aufrufer entscheidet, was daraus wird.

Plattformhinweis: braucht ``/dev/i2c-<bus>`` (RPi: I2C per raspi-config
aktivieren, Benutzer in Gruppe ``i2c``) und smbus2 (Extra ``[frame]``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

REG_ENABLE = 0x80
REG_ATIME = 0x81
REG_PPULSE = 0x8E
REG_CONTROL = 0x8F
REG_ID = 0x92
REG_PDATA = 0x9C
REG_POFFSET_UR = 0x9D
REG_POFFSET_DL = 0x9E

EXPECTED_ID = 0xAB


class SMBusLike(Protocol):
    """Die Teilmenge von ``smbus2.SMBus``, die der Treiber braucht."""

    def read_byte_data(self, i2c_addr: int, register: int) -> int: ...

    def write_byte_data(self, i2c_addr: int, register: int, value: int) -> None: ...

    def close(self) -> None: ...


class Apds9960Error(OSError):
    """I2C-Zugriff auf den APDS-9960 ist fehlgeschlagen."""


@dataclass(frozen=True)
class Apds9960Settings:
    """Bus, Adresse und Registerwerte. Default = Konfiguration B (#1440)."""

    bus: int = 1
    address: int = 0x39
    atime: int = 0xDB
    ppulse: int = 0xFF
    control: int = 0x0D
    enable: int = 0x07
    offset_ur: int | None = None
    offset_dl: int | None = None


def encode_offset(value: int) -> int:
    """Offset -127..127 ins Vorzeichen-Betrag-Format der POFFSET-Register."""
    if not -127 <= value <= 127:
        raise ValueError(f"Offset muss zwischen -127 und 127 liegen (war: {value})")
    return (0x80 | -value) if value < 0 else value


def _default_bus_factory(bus: int) -> SMBusLike:
    from smbus2 import SMBus  # lazy: nur auf dem Rahmen-Pi noetig

    opened: SMBusLike = SMBus(bus)  # ohne installiertes smbus2 (CI-mypy) sonst Any
    return opened


class Apds9960Proximity:
    """Naeherungssensor APDS-9960 (nur PDATA).

    Args:
        settings: Bus, Adresse, Registerwerte.
        bus_factory: Erzeugt den I2C-Bus (Tests: Fake). Default ``smbus2.SMBus``.
    """

    def __init__(
        self,
        settings: Apds9960Settings | None = None,
        *,
        bus_factory: Callable[[int], SMBusLike] | None = None,
    ) -> None:
        self._settings = settings or Apds9960Settings()
        self._bus_factory = bus_factory or _default_bus_factory
        self._bus: SMBusLike | None = None
        self._unavailable_logged = False
        self.chip_id: int | None = None

    @property
    def settings(self) -> Apds9960Settings:
        return self._settings

    def open(self) -> None:
        """Bus oeffnen, ID pruefen, Konfiguration schreiben.

        Raises:
            Apds9960Error: Bus oder Geraet nicht erreichbar.
        """
        if self._bus is not None:
            return
        s = self._settings
        try:
            bus = self._bus_factory(s.bus)
        except ImportError as exc:
            raise Apds9960Error(
                f"smbus2 fehlt ({exc}) -- pip install -e '.[frame]'"
            ) from exc
        except OSError as exc:
            raise Apds9960Error(f"I2C-Bus {s.bus} nicht verfuegbar: {exc}") from exc
        try:
            chip_id = bus.read_byte_data(s.address, REG_ID)
            if chip_id != EXPECTED_ID:
                logger.warning(
                    "APDS-9960 an 0x%02X meldet ID 0x%02X statt 0x%02X -- "
                    "fahre trotzdem fort (#1436 T3).",
                    s.address,
                    chip_id,
                    EXPECTED_ID,
                )
            writes = [
                (REG_ENABLE, 0x00),
                (REG_ATIME, s.atime),
                (REG_PPULSE, s.ppulse),
                (REG_CONTROL, s.control),
            ]
            if s.offset_ur is not None:
                writes.append((REG_POFFSET_UR, encode_offset(s.offset_ur)))
            if s.offset_dl is not None:
                writes.append((REG_POFFSET_DL, encode_offset(s.offset_dl)))
            writes.append((REG_ENABLE, s.enable))
            for register, value in writes:
                bus.write_byte_data(s.address, register, value)
        except OSError as exc:
            bus.close()
            raise Apds9960Error(
                f"APDS-9960 an Bus {s.bus}, Adresse 0x{s.address:02X} antwortet nicht: {exc}"
            ) from exc
        self.chip_id = chip_id
        self._bus = bus
        logger.info(
            "APDS-9960 bereit: Bus %d, Adresse 0x%02X, ID 0x%02X, PPULSE 0x%02X, "
            "CONTROL 0x%02X, Offset UR/DL %s/%s",
            s.bus,
            s.address,
            chip_id,
            s.ppulse,
            s.control,
            s.offset_ur,
            s.offset_dl,
        )

    def is_available(self) -> bool:
        """True, wenn der Sensor geoeffnet ist oder sich oeffnen laesst.

        Ohne Geraet: False mit genau EINER WARNING ueber die Lebensdauer des
        Objekts (kein Dauerlog bei wiederholten Aufrufen).
        """
        try:
            self.open()
        except Apds9960Error as exc:
            if not self._unavailable_logged:
                logger.warning("APDS-9960 nicht verfuegbar: %s", exc)
                self._unavailable_logged = True
            return False
        return True

    def read_proximity(self) -> int:
        """PDATA lesen (0-255).

        Raises:
            Apds9960Error: nicht geoeffnet oder I2C-Fehler.
        """
        if self._bus is None:
            raise Apds9960Error("APDS-9960 nicht geoeffnet")
        try:
            return self._bus.read_byte_data(self._settings.address, REG_PDATA) & 0xFF
        except OSError as exc:
            raise Apds9960Error(f"PDATA lesen fehlgeschlagen: {exc}") from exc

    def close(self) -> None:
        """Naeherung abschalten und Bus schliessen (Fehler werden ignoriert)."""
        if self._bus is None:
            return
        bus, self._bus = self._bus, None
        try:
            bus.write_byte_data(self._settings.address, REG_ENABLE, 0x00)
        except OSError:
            logger.debug("APDS-9960: Abschalten beim Schliessen fehlgeschlagen")
        bus.close()
