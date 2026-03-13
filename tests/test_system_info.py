"""
Tests für elder_berry.system.info – SystemMonitor-Klasse
Laufen auf allen Plattformen (Linux/Windows).
GPU-Tests werden übersprungen wenn nvidia-smi nicht verfügbar.
"""

import shutil

import pytest

from elder_berry.system.info import (
    CpuInfo,
    GpuInfo,
    RamInfo,
    SystemInfo,
    SystemMonitor,
)


@pytest.fixture
def monitor() -> SystemMonitor:
    return SystemMonitor()


def test_get_info_returns_correct_type(monitor):
    info = monitor.get_info()
    assert isinstance(info, SystemInfo)


def test_cpu_info_plausible(monitor):
    cpu = monitor.get_cpu()
    assert isinstance(cpu, CpuInfo)
    assert 0.0 <= cpu.usage_percent <= 100.0
    assert cpu.core_count >= 1
    assert cpu.thread_count >= cpu.core_count
    assert len(cpu.per_core_percent) == cpu.thread_count


def test_ram_info_plausible(monitor):
    ram = monitor.get_ram()
    assert isinstance(ram, RamInfo)
    assert ram.total_mb > 0
    assert ram.used_mb >= 0
    assert ram.available_mb >= 0
    assert ram.used_mb + ram.available_mb <= ram.total_mb + 1  # kleine Float-Toleranz
    assert 0.0 <= ram.usage_percent <= 100.0


def test_top_processes_count(monitor):
    procs = monitor.get_top_processes(n=5)
    assert len(procs) <= 5
    for proc in procs:
        assert "pid" in proc
        assert "name" in proc
        assert "cpu_percent" in proc
        assert "memory_percent" in proc


def test_get_info_top_processes_limit(monitor):
    info = monitor.get_info(top_processes=3)
    assert len(info.top_processes) <= 3


@pytest.mark.skipif(
    not shutil.which("nvidia-smi"),
    reason="nvidia-smi nicht verfügbar – kein NVIDIA-GPU",
)
def test_gpu_info_plausible(monitor):
    gpus = monitor.get_gpu()
    assert len(gpus) >= 1
    gpu = gpus[0]
    assert isinstance(gpu, GpuInfo)
    assert gpu.vram_total_mb > 0
    assert 0.0 <= gpu.gpu_util_percent <= 100.0
    assert gpu.temperature_c > 0
