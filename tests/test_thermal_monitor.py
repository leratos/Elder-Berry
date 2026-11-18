"""Tests fuer ThermalMonitor (Phase 111, E3, §4.8)."""

from __future__ import annotations

import logging
import time

import pytest

from elder_berry.room_display.thermal_monitor import (
    ThermalMonitor,
    parse_cpu_temp,
    parse_throttled,
)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("throttled=0x0\n", 0),
        ("throttled=0x50005\n", 0x50005),
        ("throttled=0x80000", 0x80000),
    ],
)
def test_parse_throttled(text, value):
    assert parse_throttled(text) == value


def test_parse_throttled_unknown_format():
    with pytest.raises(ValueError):
        parse_throttled("VCHI initialization failed")


def test_parse_cpu_temp():
    assert parse_cpu_temp("52312\n") == pytest.approx(52.312)


def _monitor(
    tmp_path, *, cpu="52312\n", throttled="throttled=0x0\n", enclosure=None, **kw
):
    path = tmp_path / "temp"
    if cpu is not None:
        path.write_text(cpu, encoding="ascii")
    calls = []

    def run(cmd):
        calls.append(tuple(cmd))
        if isinstance(throttled, BaseException):
            raise throttled
        return throttled

    monitor = ThermalMonitor(
        cpu_temp_path=path, run_command=run, enclosure_sensor=enclosure, **kw
    )
    return monitor, calls


def test_normal_line(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    monitor, calls = _monitor(tmp_path, enclosure=lambda: 31.25)
    monitor.check()
    assert "CPU 52.3 C, throttled=0x0, Gehaeuseluft 31.2 C" in caplog.text
    assert calls == [("vcgencmd", "get_throttled")]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_cpu_threshold_warning(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    monitor, _ = _monitor(tmp_path, cpu="80000\n")
    monitor.check()
    assert "CPU-Temperatur 80.0 C >= 80 C" in caplog.text
    caplog.clear()
    monitor, _ = _monitor(tmp_path, cpu="79900\n")
    monitor.check()
    assert "CPU-Temperatur" not in caplog.text


def test_throttled_warning(tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    monitor, _ = _monitor(tmp_path, throttled="throttled=0x50005\n")
    monitor.check()
    assert "throttled=0x50005" in caplog.text


def test_enclosure_warning(tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    monitor, _ = _monitor(tmp_path, enclosure=lambda: 50.0, enclosure_warn_c=50.0)
    monitor.check()
    assert "Gehaeuseluft 50.0 C >= 50 C" in caplog.text


def test_missing_command_and_file_logged_once(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    monitor, _ = _monitor(
        tmp_path, cpu=None, throttled=FileNotFoundError(2, "vcgencmd")
    )
    for _ in range(3):
        monitor.check()
    assert caplog.text.count("vcgencmd nicht vorhanden") == 1
    assert caplog.text.count("CPU-Temperatur nicht lesbar") == 1
    assert caplog.text.count("Temperatur: CPU -, throttled=-, Gehaeuseluft -") == 3
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_enclosure_read_error_logged_once(tmp_path, caplog):
    caplog.set_level(logging.INFO)

    def broken():
        raise OSError(121, "Remote I/O error")

    monitor, _ = _monitor(tmp_path, enclosure=broken)
    monitor.check()
    monitor.check()
    assert caplog.text.count("Gehaeuseluft nicht lesbar") == 1


def test_interval_with_fake_clock(tmp_path):
    monitor, calls = _monitor(tmp_path, interval_s=300)
    assert monitor.tick(0.0) is True  # erste Messung sofort
    assert monitor.tick(299.9) is False
    assert monitor.tick(300.0) is True
    assert monitor.tick(400.0) is False
    assert monitor.tick(600.0) is True
    assert monitor.checks == 3 == len(calls)


def test_thread_starts_measures_and_stops(tmp_path):
    monitor, calls = _monitor(tmp_path, interval_s=300)
    monitor.start(poll_s=0.01)
    deadline = time.monotonic() + 2
    while monitor.checks == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    monitor.stop()
    assert monitor.checks == 1
    assert monitor._thread is None


def test_invalid_interval():
    with pytest.raises(ValueError):
        ThermalMonitor(interval_s=0)
