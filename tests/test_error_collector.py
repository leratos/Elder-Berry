"""Tests für ErrorCollectorHandler – Deduplizierung, Rate-Limiting, Alerting."""
import logging
import time
from unittest.mock import MagicMock


from elder_berry.core.error_collector import ErrorCollectorHandler


class TestErrorCollectorBasic:
    def test_emits_on_error(self):
        """ERROR-Level Einträge werden verarbeitet."""
        callback = MagicMock()
        handler = ErrorCollectorHandler(alert_callback=callback)
        logger = logging.getLogger("test.basic")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            logger.error("Testfehler")
            callback.assert_called_once()
            assert "Testfehler" in callback.call_args[0][0]
        finally:
            logger.removeHandler(handler)

    def test_ignores_warning(self):
        """WARNING-Level wird nicht verarbeitet."""
        callback = MagicMock()
        handler = ErrorCollectorHandler(alert_callback=callback)
        logger = logging.getLogger("test.warn")
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        try:
            logger.warning("Nur Warnung")
            callback.assert_not_called()
        finally:
            logger.removeHandler(handler)

    def test_no_callback_no_crash(self):
        """Ohne Callback: kein Crash, kein Alert."""
        handler = ErrorCollectorHandler()
        logger = logging.getLogger("test.nocb")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            logger.error("Kein Callback gesetzt")
            # Kein Crash erwartet
        finally:
            logger.removeHandler(handler)

    def test_set_alert_callback(self):
        """set_alert_callback() setzt den Callback nachträglich."""
        handler = ErrorCollectorHandler()
        callback = MagicMock()
        handler.set_alert_callback(callback)
        logger = logging.getLogger("test.setcb")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            logger.error("Jetzt mit Callback")
            callback.assert_called_once()
        finally:
            logger.removeHandler(handler)


class TestDeduplication:
    def test_same_error_deduplicated(self):
        """Gleicher Fehler innerhalb Cooldown wird nur einmal alerted."""
        callback = MagicMock()
        handler = ErrorCollectorHandler(alert_callback=callback, cooldown=300)
        logger = logging.getLogger("test.dedup")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            logger.error("Gleicher Fehler")
            logger.error("Gleicher Fehler")
            logger.error("Gleicher Fehler")
            assert callback.call_count == 1
        finally:
            logger.removeHandler(handler)

    def test_different_errors_not_deduplicated(self):
        """Verschiedene Fehler werden nicht dedupliziert."""
        callback = MagicMock()
        handler = ErrorCollectorHandler(alert_callback=callback, cooldown=300)
        logger = logging.getLogger("test.diff")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            logger.error("Fehler A")
            logger.error("Fehler B")
            logger.error("Fehler C")
            assert callback.call_count == 3
        finally:
            logger.removeHandler(handler)

    def test_exception_type_in_dedup_key(self):
        """Exception-Typ wird für Deduplizierung genutzt."""
        callback = MagicMock()
        handler = ErrorCollectorHandler(alert_callback=callback, cooldown=300)
        logger = logging.getLogger("test.exc")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            try:
                raise ValueError("val")
            except ValueError:
                logger.error("Fehler", exc_info=True)
            try:
                raise TypeError("typ")
            except TypeError:
                logger.error("Fehler", exc_info=True)
            # Zwei verschiedene Exception-Typen = 2 Alerts
            assert callback.call_count == 2
        finally:
            logger.removeHandler(handler)

    def test_cooldown_expired_allows_repeat(self):
        """Nach Cooldown-Ablauf wird der gleiche Fehler erneut alerted."""
        callback = MagicMock()
        handler = ErrorCollectorHandler(alert_callback=callback, cooldown=0)
        logger = logging.getLogger("test.cooldown")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            logger.error("Gleicher Fehler")
            logger.error("Gleicher Fehler")
            # cooldown=0 → sofort wieder erlaubt
            assert callback.call_count == 2
        finally:
            logger.removeHandler(handler)


class TestRateLimiting:
    def test_rate_limit_enforced(self):
        """Max-Alerts pro Fenster wird eingehalten."""
        callback = MagicMock()
        handler = ErrorCollectorHandler(
            alert_callback=callback, cooldown=0, max_alerts=3,
        )
        logger = logging.getLogger("test.rate")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            for i in range(10):
                logger.error("Fehler %d", i)
            assert callback.call_count == 3
        finally:
            logger.removeHandler(handler)

    def test_rate_window_resets(self):
        """Nach Ablauf des Rate-Fensters werden wieder Alerts gesendet."""
        callback = MagicMock()
        handler = ErrorCollectorHandler(
            alert_callback=callback, cooldown=0, max_alerts=2,
        )
        # Manuell das Fenster in die Vergangenheit setzen
        handler._window_start = time.monotonic() - 700  # > 600s RATE_WINDOW
        handler._alert_count = 2  # Limit erreicht

        logger = logging.getLogger("test.window")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            logger.error("Nach Window-Reset")
            callback.assert_called_once()
        finally:
            logger.removeHandler(handler)


class TestAlertFormat:
    def test_format_without_exception(self):
        """Alert-Format ohne Exception enthält Logger-Name und Message."""
        callback = MagicMock()
        handler = ErrorCollectorHandler(alert_callback=callback)
        logger = logging.getLogger("elder_berry.comms.bridge")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            logger.error("Connection lost")
            msg = callback.call_args[0][0]
            assert "elder_berry.comms.bridge" in msg
            assert "Connection lost" in msg
            assert "⚠" in msg
        finally:
            logger.removeHandler(handler)

    def test_format_with_exception(self):
        """Alert-Format mit Exception enthält Exception-Typ."""
        callback = MagicMock()
        handler = ErrorCollectorHandler(alert_callback=callback)
        logger = logging.getLogger("test.fmtexc")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            try:
                raise ConnectionError("timeout")
            except ConnectionError:
                logger.error("API-Fehler", exc_info=True)
            msg = callback.call_args[0][0]
            assert "ConnectionError" in msg
            assert "API-Fehler" in msg
        finally:
            logger.removeHandler(handler)

    def test_callback_exception_swallowed(self):
        """Exception im Callback crasht nicht den Logger."""
        callback = MagicMock(side_effect=RuntimeError("Callback kaputt"))
        handler = ErrorCollectorHandler(alert_callback=callback)
        logger = logging.getLogger("test.cbcrash")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            logger.error("Sollte nicht crashen")
            # Kein Crash erwartet
            callback.assert_called_once()
        finally:
            logger.removeHandler(handler)
