"""Tests: AlertMonitor – Proaktive Alerts via Matrix."""

import time
from unittest.mock import MagicMock, patch


from elder_berry.comms.alert_monitor import AlertConfig, AlertMonitor


# ---------------------------------------------------------------------------
# AlertConfig DTO
# ---------------------------------------------------------------------------


class TestAlertConfig:
    def test_defaults(self):
        config = AlertConfig()
        assert config.disk_threshold_percent == 90
        assert config.watch_processes == []

    def test_custom_values(self):
        config = AlertConfig(
            disk_threshold_percent=80,
            watch_processes=["ollama", "synapse"],
        )
        assert config.disk_threshold_percent == 80
        assert config.watch_processes == ["ollama", "synapse"]


# ---------------------------------------------------------------------------
# AlertMonitor – Init + Start/Stop
# ---------------------------------------------------------------------------


class TestAlertMonitorLifecycle:
    def test_creation(self):
        monitor = AlertMonitor(send_alert=MagicMock())
        assert not monitor.is_running

    def test_start_stop(self):
        monitor = AlertMonitor(send_alert=MagicMock(), poll_interval=1)
        monitor.start()
        assert monitor.is_running

        time.sleep(0.2)

        monitor.stop()
        time.sleep(0.3)
        assert not monitor.is_running

    def test_double_start(self):
        monitor = AlertMonitor(send_alert=MagicMock(), poll_interval=1)
        monitor.start()
        monitor.start()  # Darf nicht crashen
        assert monitor.is_running
        monitor.stop()
        time.sleep(0.3)

    def test_stop_when_not_running(self):
        monitor = AlertMonitor(send_alert=MagicMock())
        monitor.stop()  # Darf nicht crashen


# ---------------------------------------------------------------------------
# AlertMonitor – Disk-Checks
# ---------------------------------------------------------------------------


class TestDiskAlerts:
    def test_disk_alert_sent_when_over_threshold(self):
        alerts = []
        monitor = AlertMonitor(
            send_alert=lambda text: alerts.append(text),
            config=AlertConfig(disk_threshold_percent=90),
        )

        mock_usage = MagicMock()
        mock_usage.percent = 95
        mock_usage.total = 500 * 1024**3
        mock_usage.free = 25 * 1024**3

        mock_part = MagicMock()
        mock_part.mountpoint = "C:\\"

        with (
            patch("psutil.disk_partitions", return_value=[mock_part]),
            patch("psutil.disk_usage", return_value=mock_usage),
        ):
            monitor._check_disk()

        assert len(alerts) == 1
        assert "C:\\" in alerts[0]
        assert "95%" in alerts[0]

    def test_no_alert_when_under_threshold(self):
        alerts = []
        monitor = AlertMonitor(
            send_alert=lambda text: alerts.append(text),
            config=AlertConfig(disk_threshold_percent=90),
        )

        mock_usage = MagicMock()
        mock_usage.percent = 50
        mock_usage.total = 500 * 1024**3
        mock_usage.free = 250 * 1024**3

        mock_part = MagicMock()
        mock_part.mountpoint = "C:\\"

        with (
            patch("psutil.disk_partitions", return_value=[mock_part]),
            patch("psutil.disk_usage", return_value=mock_usage),
        ):
            monitor._check_disk()

        assert len(alerts) == 0

    def test_disk_alert_deduplicated(self):
        """Gleicher Mountpoint löst nur einmal Alert aus."""
        alerts = []
        monitor = AlertMonitor(
            send_alert=lambda text: alerts.append(text),
            config=AlertConfig(disk_threshold_percent=90),
        )

        mock_usage = MagicMock()
        mock_usage.percent = 95
        mock_usage.total = 500 * 1024**3
        mock_usage.free = 25 * 1024**3

        mock_part = MagicMock()
        mock_part.mountpoint = "C:\\"

        with (
            patch("psutil.disk_partitions", return_value=[mock_part]),
            patch("psutil.disk_usage", return_value=mock_usage),
        ):
            monitor._check_disk()
            monitor._check_disk()  # Zweiter Aufruf
            monitor._check_disk()  # Dritter Aufruf

        assert len(alerts) == 1  # Nur ein Alert

    def test_disk_alert_resets_when_below_threshold(self):
        """Alert wird erneut gesendet wenn Disk unter und wieder über Schwelle geht."""
        alerts = []
        monitor = AlertMonitor(
            send_alert=lambda text: alerts.append(text),
            config=AlertConfig(disk_threshold_percent=90),
        )

        mock_part = MagicMock()
        mock_part.mountpoint = "C:\\"

        mock_over = MagicMock()
        mock_over.percent = 95
        mock_over.total = 500 * 1024**3
        mock_over.free = 25 * 1024**3

        mock_under = MagicMock()
        mock_under.percent = 85
        mock_under.total = 500 * 1024**3
        mock_under.free = 75 * 1024**3

        with patch("psutil.disk_partitions", return_value=[mock_part]):
            # Über Schwelle → Alert
            with patch("psutil.disk_usage", return_value=mock_over):
                monitor._check_disk()
            # Unter Schwelle → Reset
            with patch("psutil.disk_usage", return_value=mock_under):
                monitor._check_disk()
            # Wieder über Schwelle → erneuter Alert
            with patch("psutil.disk_usage", return_value=mock_over):
                monitor._check_disk()

        assert len(alerts) == 2

    def test_disk_no_psutil(self):
        """Kein Crash wenn psutil nicht verfügbar."""
        monitor = AlertMonitor(send_alert=MagicMock())

        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("No module named 'psutil'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            monitor._check_disk()  # Darf nicht crashen


# ---------------------------------------------------------------------------
# AlertMonitor – Prozess-Checks
# ---------------------------------------------------------------------------


class TestProcessAlerts:
    def test_process_crash_alert(self):
        """Alert wenn überwachter Prozess verschwindet."""
        alerts = []
        monitor = AlertMonitor(
            send_alert=lambda text: alerts.append(text),
            config=AlertConfig(watch_processes=["ollama"]),
        )

        # Initial: Prozess läuft
        monitor._process_was_running.add("ollama")

        mock_psutil = MagicMock()
        mock_proc = MagicMock()
        mock_proc.info = {"name": "python.exe"}
        mock_psutil.process_iter.return_value = [mock_proc]
        mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        mock_psutil.AccessDenied = type("AccessDenied", (Exception,), {})

        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                return mock_psutil
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            monitor._check_processes()

        assert len(alerts) == 1
        assert "ollama" in alerts[0]

    def test_no_alert_when_process_still_running(self):
        """Kein Alert wenn Prozess weiterhin läuft."""
        alerts = []
        monitor = AlertMonitor(
            send_alert=lambda text: alerts.append(text),
            config=AlertConfig(watch_processes=["ollama"]),
        )

        monitor._process_was_running.add("ollama")

        mock_psutil = MagicMock()
        mock_proc = MagicMock()
        mock_proc.info = {"name": "ollama"}
        mock_psutil.process_iter.return_value = [mock_proc]
        mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        mock_psutil.AccessDenied = type("AccessDenied", (Exception,), {})

        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                return mock_psutil
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            monitor._check_processes()

        assert len(alerts) == 0

    def test_no_alert_if_process_was_never_running(self):
        """Kein Alert wenn Prozess nie gelaufen ist."""
        alerts = []
        monitor = AlertMonitor(
            send_alert=lambda text: alerts.append(text),
            config=AlertConfig(watch_processes=["ollama"]),
        )

        # process_was_running ist leer → ollama lief nie

        mock_psutil = MagicMock()
        mock_psutil.process_iter.return_value = []
        mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        mock_psutil.AccessDenied = type("AccessDenied", (Exception,), {})

        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                return mock_psutil
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            monitor._check_processes()

        assert len(alerts) == 0

    def test_process_detected_when_starts(self):
        """Prozess wird erkannt wenn er startet."""
        monitor = AlertMonitor(
            send_alert=MagicMock(),
            config=AlertConfig(watch_processes=["ollama"]),
        )

        mock_psutil = MagicMock()
        mock_proc = MagicMock()
        mock_proc.info = {"name": "ollama"}
        mock_psutil.process_iter.return_value = [mock_proc]
        mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        mock_psutil.AccessDenied = type("AccessDenied", (Exception,), {})

        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                return mock_psutil
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            monitor._check_processes()

        assert "ollama" in monitor._process_was_running

    def test_no_processes_configured(self):
        """Keine Checks wenn keine Prozesse konfiguriert."""
        monitor = AlertMonitor(
            send_alert=MagicMock(),
            config=AlertConfig(watch_processes=[]),
        )
        # Darf nicht crashen, macht einfach nichts
        monitor._check_processes()
