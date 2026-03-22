"""ErrorCollectorHandler – Logging-Handler für ERROR+ mit Deduplizierung und Alerting.

Sammelt ERROR- und CRITICAL-Einträge, dedupliziert nach Logger+Exception-Typ
und sendet optional Alerts über einen Callback (z.B. Matrix-Nachricht).

Rate-Limiting verhindert Matrix-Spam bei API-Ausfällen oder Loops.
"""
from __future__ import annotations

import logging
import threading
import time


class ErrorCollectorHandler(logging.Handler):
    """Logging-Handler der ERROR+ Einträge sammelt und optional alerted.

    - Deduplizierung: gleicher Fehler (Logger + Exception-Typ) wird nur
      alle ``cooldown`` Sekunden erneut an den Callback gesendet
    - Rate-Limiting: max ``max_alerts`` Alerts pro 10-Minuten-Fenster
    - Thread-safe: eigener Lock für ``_seen`` Dict
    """

    RATE_WINDOW = 600  # 10 Minuten

    def __init__(
        self,
        alert_callback: callable | None = None,
        cooldown: int = 300,
        max_alerts: int = 5,
    ) -> None:
        super().__init__(level=logging.ERROR)
        self._alert_callback = alert_callback
        self._cooldown = cooldown
        self._max_alerts = max_alerts
        self._seen: dict[str, float] = {}
        self._alert_count = 0
        self._window_start = 0.0
        self._lock = threading.Lock()

    def set_alert_callback(self, callback: callable) -> None:
        """Setzt den Alert-Callback (z.B. Matrix-Nachricht senden)."""
        self._alert_callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        """Verarbeitet einen ERROR+ Log-Eintrag."""
        now = time.monotonic()

        # Deduplizierungs-Key: Logger + Exception-Typ
        if record.exc_info and record.exc_info[1]:
            key = f"{record.name}:{record.exc_info[1].__class__.__name__}"
        else:
            key = f"{record.name}:{record.getMessage()[:80]}"

        with self._lock:
            # Deduplizierung
            if key in self._seen and (now - self._seen[key]) < self._cooldown:
                return
            self._seen[key] = now

            # Rate-Limiting (10-Minuten-Fenster)
            if now - self._window_start > self.RATE_WINDOW:
                self._alert_count = 0
                self._window_start = now

            if self._alert_callback and self._alert_count < self._max_alerts:
                self._alert_count += 1
                should_alert = True
            else:
                should_alert = False

        if should_alert:
            # Alert außerhalb des Locks senden
            msg = self._format_alert(record)
            try:
                self._alert_callback(msg)
            except Exception:
                pass  # Alert-Fehler darf nicht den Logger crashen

    def _format_alert(self, record: logging.LogRecord) -> str:
        """Formatiert einen kurzen Alert-Text für Matrix."""
        exc_type = ""
        if record.exc_info and record.exc_info[1]:
            exc_type = f": {record.exc_info[1].__class__.__name__}"
        return f"⚠ {record.name}{exc_type} – {record.getMessage()}"
