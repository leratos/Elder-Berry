"""AlertMonitor – Proaktive Alerts via Matrix (Hintergrund-Monitoring).

Überwacht System-Zustände und sendet Warnungen an einen Matrix-Raum:
- Disk-Nutzung >90%
- Überwachte Prozesse crashed (nicht mehr laufend)

Läuft als Daemon-Thread im Hintergrund, pollt periodisch.

Verwendung:
    monitor = AlertMonitor(
        channel=matrix_channel,
        room_id="!room:matrix.example.com",
        poll_interval=60,
    )
    monitor.start()
    pass
    monitor.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Schwellwerte
DISK_THRESHOLD_PERCENT = 90


@dataclass
class AlertConfig:
    """Konfiguration für den AlertMonitor."""

    disk_threshold_percent: float = DISK_THRESHOLD_PERCENT
    """Ab welchem Prozentsatz Disk-Warnung gesendet wird."""

    watch_processes: list[str] = field(default_factory=list)
    """Prozessnamen die überwacht werden (z.B. ['ollama', 'synapse'])."""


class AlertMonitor:
    """Proaktives Monitoring mit Alerts via MessageChannel.

    Läuft als Daemon-Thread. Sendet Nachrichten über einen MessageChannel
    (z.B. MatrixChannel) an einen konfigurierten Raum.
    """

    def __init__(
        self,
        send_alert: Callable[[str], None],
        poll_interval: int = 60,
        config: AlertConfig | None = None,
    ) -> None:
        """
        Args:
            send_alert: Callable(text: str) → wird aufgerufen wenn ein Alert
                        gesendet werden soll. Muss thread-safe sein.
            poll_interval: Sekunden zwischen Checks.
            config: Alert-Konfiguration (Schwellwerte, überwachte Prozesse).
        """
        self._send_alert = send_alert
        self._poll_interval = poll_interval
        self._config = config or AlertConfig()
        self._thread: threading.Thread | None = None
        self._running = False

        # State: welche Alerts schon gesendet (Deduplizierung)
        self._disk_alerted: set[str] = set()
        self._process_was_running: set[str] = set()

    @property
    def is_running(self) -> bool:
        """True wenn der Monitor-Thread aktiv ist."""
        return self._running

    def start(self) -> None:
        """Startet den Monitor-Thread (nicht-blockierend)."""
        if self._running:
            logger.warning("AlertMonitor läuft bereits")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="alert-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "AlertMonitor gestartet (Intervall: %ds, Prozesse: %s)",
            self._poll_interval,
            self._config.watch_processes or "keine",
        )

    def stop(self) -> None:
        """Stoppt den Monitor-Thread."""
        if not self._running:
            return

        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._poll_interval + 5)
            if self._thread.is_alive():
                logger.warning("AlertMonitor-Thread konnte nicht sauber beendet werden")

        self._thread = None
        logger.info("AlertMonitor gestoppt")

    def _run_loop(self) -> None:
        """Hauptschleife: periodisch Checks ausführen."""
        logger.debug("AlertMonitor Loop gestartet")

        # Initiale Prozess-Erkennung
        self._init_watched_processes()

        while self._running:
            try:
                self._check_disk()
                self._check_processes()
            except Exception as e:
                logger.error("AlertMonitor Check-Fehler: %s", e)

            # Warte poll_interval, aber prüfe _running alle 1s
            for _ in range(self._poll_interval):
                # mypy narrowt self._running im while-Body auf Literal[True];
                # in der Praxis setzt stop() das Flag aus einem anderen Thread.
                if not self._running:
                    break  # type: ignore[unreachable]
                time.sleep(1)

        logger.debug("AlertMonitor Loop beendet")

    def _init_watched_processes(self) -> None:
        """Erkennt initial welche überwachten Prozesse laufen."""
        if not self._config.watch_processes:
            return

        try:
            import psutil  # noqa: F401

            running = self._get_running_process_names()
            for proc_name in self._config.watch_processes:
                if proc_name.lower() in running:
                    self._process_was_running.add(proc_name.lower())
                    logger.debug("Überwachter Prozess läuft: %s", proc_name)
        except ImportError:
            logger.warning("psutil nicht verfügbar – Prozess-Überwachung deaktiviert")

    def _check_disk(self) -> None:
        """Prüft Disk-Nutzung aller Partitionen."""
        try:
            import psutil
        except ImportError:
            return

        threshold = self._config.disk_threshold_percent

        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except PermissionError:
                continue

            mount = part.mountpoint

            if usage.percent >= threshold:
                if mount not in self._disk_alerted:
                    self._disk_alerted.add(mount)
                    total_gb = usage.total / (1024**3)
                    free_gb = usage.free / (1024**3)
                    self._send_alert(
                        f"Disk-Warnung: {mount} ist zu "
                        f"{usage.percent}% belegt!\n"
                        f"Frei: {free_gb:.1f} / {total_gb:.1f} GB"
                    )
                    logger.warning(
                        "Disk-Alert gesendet: %s bei %s%%",
                        mount,
                        usage.percent,
                    )
            else:
                # Unter Schwelle → Alert-Status zurücksetzen
                self._disk_alerted.discard(mount)

    def _check_processes(self) -> None:
        """Prüft ob überwachte Prozesse noch laufen."""
        if not self._config.watch_processes:
            return

        try:
            import psutil  # noqa: F401
        except ImportError:
            return

        running = self._get_running_process_names()

        for proc_name in self._config.watch_processes:
            name_lower = proc_name.lower()

            if name_lower in self._process_was_running:
                if name_lower not in running:
                    # Prozess war da, ist jetzt weg → Alert
                    self._process_was_running.discard(name_lower)
                    self._send_alert(
                        f"Prozess-Warnung: '{proc_name}' läuft nicht mehr!"
                    )
                    logger.warning("Prozess-Alert: %s crashed/beendet", proc_name)
            else:
                # Prozess war nicht da, läuft jetzt → merken
                if name_lower in running:
                    self._process_was_running.add(name_lower)
                    logger.debug("Überwachter Prozess gestartet: %s", proc_name)

    @staticmethod
    def _get_running_process_names() -> set[str]:
        """Gibt alle laufenden Prozessnamen zurück (lowercase)."""
        import psutil

        names = set()
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info["name"]
                if name:
                    names.add(name.lower())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return names
