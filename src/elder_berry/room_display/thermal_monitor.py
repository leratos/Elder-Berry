"""ThermalMonitor -- Temperatur und Drosselung ins Log (Phase 111, E3, §4.8).

Alle ``interval_s`` (Default 5 min) eine INFO-Zeile mit
* CPU-Temperatur aus ``/sys/class/thermal/thermal_zone0/temp`` (Milligrad),
* ``vcgencmd get_throttled`` (falls vorhanden),
* Gehaeuseluft vom BME280 (falls verfuegbar, D1).
WARNING bei CPU >= ``cpu_warn_c`` (80 Grad C), ``throttled != 0x0`` oder
Gehaeuseluft >= ``enclosure_warn_c`` (Default 50 Grad C, Platzhalter bis M8).

Liefert die Logzeilen fuer M8 (3 h im geschlossenen Rahmen) und M9
(Unterspannung = Bit 0/16 von get_throttled).

Laeuft in einem eigenen Daemon-Thread: ``vcgencmd`` ist ein Subprozess und
soll die Render-Schleife nie blockieren. Die Logik steckt in
:meth:`tick` und ist mit Fake-Uhr testbar; Pfad, Kommando und Ausfuehrung
kommen per DI.

Plattformhinweis: Pfad und Kommando sind RPi-spezifisch. Fehlen sie (z.B. im
Codespace), wird das einmal gemeldet und die Groesse ausgelassen.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CPU_TEMP_PATH = Path("/sys/class/thermal/thermal_zone0/temp")
DEFAULT_THROTTLED_CMD = ("vcgencmd", "get_throttled")

#: Fuehrt ein Kommando aus und liefert stdout. Wirft OSError/SubprocessError.
CommandRunner = Callable[[Sequence[str]], str]


def _run_command(cmd: Sequence[str]) -> str:
    completed = subprocess.run(  # noqa: S603 -- festes Kommando, kein Shell
        list(cmd), capture_output=True, text=True, timeout=5, check=True
    )
    return completed.stdout


def parse_cpu_temp(text: str) -> float:
    """``"52312\\n"`` (Milligrad) -> 52.312."""
    return int(text.strip()) / 1000.0


def parse_throttled(text: str) -> int:
    """``"throttled=0x50005\\n"`` -> 0x50005.

    Raises:
        ValueError: unbekanntes Format.
    """
    _, sep, value = text.strip().partition("=")
    if not sep:
        raise ValueError(f"unbekanntes Format: {text.strip()!r}")
    return int(value.strip(), 16)


class ThermalMonitor:
    """Periodische Temperatur-/Drosselungs-Logzeile.

    Args:
        interval_s: Abstand zwischen zwei Messungen.
        cpu_warn_c: WARNING ab dieser CPU-Temperatur.
        enclosure_warn_c: WARNING ab dieser Gehaeuseluft-Temperatur.
        enclosure_sensor: Liefert die Gehaeuseluft in Grad C oder wirft
            ``OSError``; ``None`` = kein BME280.
        cpu_temp_path: Pfad der thermal_zone.
        throttled_cmd: Kommando fuer get_throttled.
        run_command: Kommando-Ausfuehrung (Tests: Fake).
        clock: Monotone Zeitquelle.
    """

    def __init__(
        self,
        *,
        interval_s: float = 300.0,
        cpu_warn_c: float = 80.0,
        enclosure_warn_c: float = 50.0,
        enclosure_sensor: Callable[[], float] | None = None,
        cpu_temp_path: Path = DEFAULT_CPU_TEMP_PATH,
        throttled_cmd: Sequence[str] = DEFAULT_THROTTLED_CMD,
        run_command: CommandRunner = _run_command,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s muss > 0 sein.")
        self._interval = interval_s
        self._cpu_warn = cpu_warn_c
        self._enclosure_warn = enclosure_warn_c
        self._enclosure_sensor = enclosure_sensor
        self._cpu_path = cpu_temp_path
        self._cmd = tuple(throttled_cmd)
        self._run = run_command
        self._clock = clock
        self._last: float | None = None
        self._missing_logged: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.checks = 0

    # ------------------------------------------------------------------
    # Logik
    # ------------------------------------------------------------------

    def tick(self, now: float) -> bool:
        """Misst, wenn das Intervall abgelaufen ist (erster Aufruf sofort).

        Returns:
            True, wenn gemessen wurde.
        """
        if self._last is not None and now - self._last < self._interval:
            return False
        self._last = now
        self.check()
        return True

    def check(self) -> None:
        """Eine Messung und Logzeile."""
        self.checks += 1
        cpu = self._read_cpu()
        throttled = self._read_throttled()
        enclosure = self._read_enclosure()
        logger.info(
            "Temperatur: CPU %s, throttled=%s, Gehaeuseluft %s",
            "-" if cpu is None else f"{cpu:.1f} C",
            "-" if throttled is None else f"0x{throttled:X}",
            "-" if enclosure is None else f"{enclosure:.1f} C",
        )
        if cpu is not None and cpu >= self._cpu_warn:
            logger.warning(
                "CPU-Temperatur %.1f C >= %.0f C -- Kuehlung/Lueftung pruefen (M8).",
                cpu,
                self._cpu_warn,
            )
        if throttled:
            logger.warning(
                "Drosselung/Unterspannung gemeldet: throttled=0x%X "
                "(Bit 0/16 = Unterspannung, M9; Bit 1-3/17-19 = Takt/Temperatur).",
                throttled,
            )
        if enclosure is not None and enclosure >= self._enclosure_warn:
            logger.warning(
                "Gehaeuseluft %.1f C >= %.0f C -- Rueckkasten/Lueftung pruefen (M8).",
                enclosure,
                self._enclosure_warn,
            )

    def _missing_once(self, key: str, message: str, *args: object) -> None:
        if key not in self._missing_logged:
            self._missing_logged.add(key)
            logger.info(message, *args)

    def _read_cpu(self) -> float | None:
        try:
            return parse_cpu_temp(self._cpu_path.read_text(encoding="ascii"))
        except (OSError, ValueError) as exc:
            self._missing_once(
                "cpu", "CPU-Temperatur nicht lesbar (%s) -- ausgelassen.", exc
            )
            return None

    def _read_throttled(self) -> int | None:
        try:
            return parse_throttled(self._run(self._cmd))
        except FileNotFoundError:
            self._missing_once(
                "throttled",
                "%s nicht vorhanden -- throttled ausgelassen.",
                self._cmd[0],
            )
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            self._missing_once("throttled", "get_throttled fehlgeschlagen (%s).", exc)
        return None

    def _read_enclosure(self) -> float | None:
        if self._enclosure_sensor is None:
            return None
        try:
            return self._enclosure_sensor()
        except OSError as exc:
            self._missing_once("enclosure", "Gehaeuseluft nicht lesbar (%s).", exc)
            return None

    # ------------------------------------------------------------------
    # Thread
    # ------------------------------------------------------------------

    def start(self, poll_s: float = 1.0) -> None:
        """Startet den Hintergrund-Thread (erste Messung sofort)."""
        if self._thread is not None:
            return
        self._stop.clear()

        def _loop() -> None:
            while True:
                try:
                    self.tick(self._clock())
                except Exception:  # noqa: BLE001 -- Monitor darf nie sterben
                    logger.exception("ThermalMonitor: unerwarteter Fehler")
                if self._stop.wait(poll_s):
                    return

        self._thread = threading.Thread(
            target=_loop, name="thermal-monitor", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
