"""ProximityAttentionProvider -- PDATA eines Naeherungssensors -> AttentionState.

Phase 111, E3 (Konzept §4.2, §4.4). Erste echte Implementierung der
``AttentionProvider``-ABC (Phase 83.6). Der Rahmen nutzt ihn als Ausloeser;
der Stamm-Renderloop bleibt unberuehrt (Nicht-Ziel #1469).

Schwellen relativ zu einem KONFIGURIERTEN Grundwert (keine
Auto-Kalibrierung, §7 M5). Mit ``r = PDATA - baseline``:

* ``r <  away_below``                       -> AWAY
* ``r >= present_above``                    -> PRESENT
* dazwischen                                -> bisheriger Zustand (Hysterese)
* FOCUSED ein: ``r >= focused_on`` ununterbrochen ``debounce_s`` lang
* FOCUSED aus: ``r <  focused_off``

DEFAULTS SIND PLATZHALTER, VOR M5 NICHT KALIBRIERT: Grundwert 128 und
FOCUSED ein/aus bei +30/+15 stammen aus dem Steckbrett-Test mit
Konfiguration B (#1440, Grundwert-Ausschlaege bis +9, Rauschen ca. +-11).
Nach dem Einbau liegt der Grundwert anders (§4.4).

Sensorfehler (§4.4): ununterbrochen gesaettigt (``PDATA >= saturation_value``)
ODER ununterbrochen FOCUSED laenger als ``fault_after_s`` -> ``is_faulted``,
einmal WARNING, ``current()`` liefert UNKNOWN. Zurueck erst nach
``fault_clear_s`` ununterbrochen unter ``present_above``; dann INFO.

Lesefehler (``OSError``, z.B. ``Apds9960Error``): UNKNOWN, gezaehlt,
hoechstens eine WARNING pro ``error_log_interval_s``.

Abtastung: ``current()`` liest hoechstens alle ``sample_interval_s`` und
liefert sonst den letzten Zustand. Kein eigener Thread: Der Aufrufer (Render-
bzw. Zustandsschleife) fragt ohnehin regelmaessig, und ein I2C-Byte dauert
weit unter einer Millisekunde.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from elder_berry.avatar.attention import AttentionProvider, AttentionState

logger = logging.getLogger(__name__)

#: Toleranz fuer Zeitvergleiche: Monotone Zeiten sind Gleitkommazahlen, und
#: ``0.2 - 0.15`` ist knapp kleiner als ``0.05``. Ohne Toleranz faellt ein
#: Sample auf der Intervallgrenze (oder die Entprellung um einen Takt) aus.
_EPS = 1e-6


class ProximitySensor(Protocol):
    """Liefert einen Rohwert 0-255; wirft ``OSError`` bei Lesefehlern."""

    def read_proximity(self) -> int: ...


@dataclass(frozen=True)
class ProximityThresholds:
    """Schwellen und Zeiten. Defaults: Platzhalter, vor M5 nicht kalibriert."""

    baseline: int = 128
    away_below: int = 10
    present_above: int = 12
    focused_off: int = 15
    focused_on: int = 30
    debounce_s: float = 0.15
    sample_interval_s: float = 0.05
    saturation_value: int = 255
    fault_after_s: float = 60.0
    fault_clear_s: float = 10.0
    error_log_interval_s: float = 60.0

    def __post_init__(self) -> None:
        if not (
            self.away_below <= self.present_above <= self.focused_off < self.focused_on
        ):
            raise ValueError(
                "Schwellen muessen away_below <= present_above <= focused_off < "
                f"focused_on erfuellen (war: {self.away_below}, {self.present_above}, "
                f"{self.focused_off}, {self.focused_on})"
            )
        if not 0 <= self.baseline <= 255:
            raise ValueError("baseline muss zwischen 0 und 255 liegen")
        for name in (
            "debounce_s",
            "sample_interval_s",
            "fault_after_s",
            "fault_clear_s",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} darf nicht negativ sein")


class ProximityAttentionProvider(AttentionProvider):
    """``AttentionProvider`` auf Basis eines Naeherungssensors.

    Args:
        sensor: Liefert PDATA (z.B. ``Apds9960Proximity``).
        thresholds: Schwellen und Zeiten.
        clock: Monotone Zeitquelle (Tests: Fake-Uhr).
    """

    def __init__(
        self,
        sensor: ProximitySensor,
        thresholds: ProximityThresholds | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sensor = sensor
        self._t = thresholds or ProximityThresholds()
        self._clock = clock
        self._state = AttentionState.AWAY
        self._result = AttentionState.UNKNOWN
        self._last_read: float | None = None
        self._above_on_since: float | None = None
        self._focused_since: float | None = None
        self._saturated_since: float | None = None
        self._below_since: float | None = None
        self._faulted = False
        self._last_error_log: float | None = None
        self.last_value: int | None = None
        self.sample_count = 0
        self.error_count = 0

    @property
    def thresholds(self) -> ProximityThresholds:
        return self._t

    @property
    def is_faulted(self) -> bool:
        return self._faulted

    def current(self) -> AttentionState:
        now = self._clock()
        if (
            self._last_read is not None
            and now - self._last_read < self._t.sample_interval_s - _EPS
        ):
            return self._result
        self._last_read = now
        try:
            value = self._sensor.read_proximity()
        except OSError as exc:
            self._on_read_error(now, exc)
            self._result = AttentionState.UNKNOWN
            return self._result
        self.last_value = value
        self.sample_count += 1
        self._result = self._evaluate(now, value)
        return self._result

    # ------------------------------------------------------------------
    # Logik
    # ------------------------------------------------------------------

    def _evaluate(self, now: float, value: int) -> AttentionState:
        t = self._t
        relative = value - t.baseline
        if self._faulted:
            return self._evaluate_faulted(now, relative)

        self._saturated_since = (
            (self._saturated_since if self._saturated_since is not None else now)
            if value >= t.saturation_value
            else None
        )

        if self._state is AttentionState.FOCUSED:
            if relative < t.focused_off:
                # Aus FOCUSED faellt man nach PRESENT, nur bei klar niedrigem
                # Wert direkt nach AWAY (Zwischenbereich = Hysterese -> PRESENT).
                self._state = (
                    AttentionState.AWAY
                    if relative < t.away_below
                    else AttentionState.PRESENT
                )
                self._focused_since = None
                self._above_on_since = None  # Wiedereintritt erneut entprellen
        else:
            if relative >= t.focused_on:
                if self._above_on_since is None:
                    self._above_on_since = now
                if now - self._above_on_since >= t.debounce_s - _EPS:
                    self._state = AttentionState.FOCUSED
                    self._focused_since = now
            else:
                self._above_on_since = None
            if self._state is not AttentionState.FOCUSED:
                if relative >= t.present_above:
                    self._state = AttentionState.PRESENT
                elif relative < t.away_below:
                    self._state = AttentionState.AWAY
        if self._state is not AttentionState.FOCUSED:
            self._focused_since = None

        reason = self._fault_reason(now)
        if reason is not None:
            self._enter_fault(now, reason)
            return AttentionState.UNKNOWN
        return self._state

    def _fault_reason(self, now: float) -> str | None:
        limit = self._t.fault_after_s
        if self._saturated_since is not None and now - self._saturated_since > limit:
            return f"PDATA ununterbrochen gesaettigt (>= {self._t.saturation_value})"
        if self._focused_since is not None and now - self._focused_since > limit:
            return "ununterbrochen FOCUSED"
        return None

    def _enter_fault(self, now: float, reason: str) -> None:
        self._faulted = True
        self._below_since = None
        logger.warning(
            "Naeherungssensor: Sensorfehler angenommen (%s seit > %.0f s, letzter "
            "Wert %s, Grundwert %d) -- Ausloesung aus, bis der Wert %.0f s unter "
            "Grundwert+%d liegt.",
            reason,
            self._t.fault_after_s,
            self.last_value,
            self._t.baseline,
            self._t.fault_clear_s,
            self._t.present_above,
        )

    def _evaluate_faulted(self, now: float, relative: int) -> AttentionState:
        t = self._t
        if relative < t.present_above:
            if self._below_since is None:
                self._below_since = now
            if now - self._below_since >= t.fault_clear_s - _EPS:
                self._faulted = False
                self._state = AttentionState.AWAY
                self._above_on_since = None
                self._focused_since = None
                self._saturated_since = None
                logger.info(
                    "Naeherungssensor: Fehlerzustand aufgehoben (%.0f s unter "
                    "Grundwert+%d).",
                    t.fault_clear_s,
                    t.present_above,
                )
                return self._state
        else:
            self._below_since = None
        return AttentionState.UNKNOWN

    def _on_read_error(self, now: float, exc: OSError) -> None:
        self.error_count += 1
        if (
            self._last_error_log is None
            or now - self._last_error_log >= self._t.error_log_interval_s
        ):
            self._last_error_log = now
            logger.warning(
                "Naeherungssensor: Lesefehler (%s), bisher %d -- Zustand UNKNOWN.",
                exc,
                self.error_count,
            )
