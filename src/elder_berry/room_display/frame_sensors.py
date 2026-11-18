"""frame_sensors -- Sensor-Wiring fuer das Profil "frame" (Phase 111, E3).

Baut aus der frame_config:
* APDS-9960 + ProximityAttentionProvider (``build_proximity``),
* ThermalMonitor, optional mit BME280-Gehaeuseluft (``build_thermal``).

Fehlende Hardware ist kein Startfehler: Der Treiber meldet sich einmal per
WARNING, das Profil laeuft ohne den Sensor weiter.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from elder_berry.avatar.proximity_attention_provider import (
    ProximityAttentionProvider,
    ProximityThresholds,
)
from elder_berry.robot.apds9960_proximity import (
    Apds9960Proximity,
    Apds9960Settings,
    SMBusLike,
)
from elder_berry.robot.bme280_reader import Bme280Reader
from elder_berry.room_display.sensor_config import ProximityConfig, ThermalConfig
from elder_berry.room_display.thermal_monitor import ThermalMonitor

logger = logging.getLogger(__name__)

BusFactory = Callable[[int], SMBusLike]


@dataclass
class ProximitySetup:
    driver: Apds9960Proximity
    provider: ProximityAttentionProvider


def build_proximity(
    config: ProximityConfig, *, bus_factory: BusFactory | None = None
) -> ProximitySetup | None:
    """Treiber oeffnen und Provider bauen; ``None`` wenn aus oder nicht da."""
    if not config.enabled:
        logger.info("Naeherungssensor in der Konfiguration abgeschaltet.")
        return None
    driver = Apds9960Proximity(
        Apds9960Settings(
            bus=config.bus,
            address=config.address,
            atime=config.atime,
            ppulse=config.ppulse,
            control=config.control,
            enable=config.enable_register,
            offset_ur=config.offset_ur,
            offset_dl=config.offset_dl,
        ),
        bus_factory=bus_factory,
    )
    if not driver.is_available():
        return None
    provider = ProximityAttentionProvider(
        driver,
        ProximityThresholds(
            baseline=config.baseline,
            away_below=config.away_below,
            present_above=config.present_above,
            focused_off=config.focused_off,
            focused_on=config.focused_on,
            debounce_s=config.debounce_s,
            sample_interval_s=config.sample_interval_s,
            saturation_value=config.saturation_value,
            fault_after_s=config.fault_after_s,
            fault_clear_s=config.fault_clear_s,
        ),
    )
    return ProximitySetup(driver=driver, provider=provider)


@dataclass
class ThermalSetup:
    monitor: ThermalMonitor
    bme280: Bme280Reader | None


def build_thermal(
    config: ThermalConfig, *, bus_factory: BusFactory | None = None
) -> ThermalSetup | None:
    """ThermalMonitor bauen (nicht starten); BME280 nur wenn verfuegbar."""
    if not config.enabled:
        logger.info("Temperaturueberwachung in der Konfiguration abgeschaltet.")
        return None
    bme: Bme280Reader | None = None
    if config.bme280_enabled:
        candidate = Bme280Reader(
            config.bme280_bus, config.bme280_address, bus_factory=bus_factory
        )
        if candidate.is_available():
            bme = candidate
    monitor = ThermalMonitor(
        interval_s=config.interval_s,
        cpu_warn_c=config.cpu_warn_c,
        enclosure_warn_c=config.enclosure_warn_c,
        enclosure_sensor=bme.read_temperature_c if bme is not None else None,
    )
    return ThermalSetup(monitor=monitor, bme280=bme)
