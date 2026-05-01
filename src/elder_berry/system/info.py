"""
elder_berry.system.info
-----------------------
SystemMonitor-Klasse: CPU, RAM, GPU (nvidia-smi), laufende Prozesse.
Plattform: Windows (Tower) und Linux (RPi5/Devcontainer).
GPU-Abfrage nur auf Windows/Linux mit installiertem nvidia-smi verfügbar.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, field

import psutil


# ---------------------------------------------------------------------------
# Daten-Klassen (DTOs)
# ---------------------------------------------------------------------------


@dataclass
class CpuInfo:
    usage_percent: float  # aktuelle Gesamtauslastung in %
    per_core_percent: list[float]  # Auslastung je Kern
    freq_mhz: float | None  # aktuelle Taktfrequenz in MHz (None wenn nicht verfügbar)
    core_count: int  # physische Kerne
    thread_count: int  # logische Threads


@dataclass
class RamInfo:
    total_mb: float
    used_mb: float
    available_mb: float
    usage_percent: float


@dataclass
class GpuInfo:
    name: str
    vram_total_mb: float
    vram_used_mb: float
    vram_free_mb: float
    gpu_util_percent: float
    temperature_c: float


@dataclass
class SystemInfo:
    platform: str
    cpu: CpuInfo
    ram: RamInfo
    gpus: list[GpuInfo] = field(default_factory=list)
    top_processes: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SystemMonitor-Klasse
# ---------------------------------------------------------------------------


class SystemMonitor:
    """
    Liest Systemdaten aus: CPU, RAM, GPU, Prozesse.
    Eine Instanz pro Laufzeit reicht – kein interner Zustand.
    """

    def get_cpu(self) -> CpuInfo:
        freq = psutil.cpu_freq()
        return CpuInfo(
            usage_percent=psutil.cpu_percent(interval=0.2),
            per_core_percent=psutil.cpu_percent(interval=0.2, percpu=True),
            freq_mhz=freq.current if freq else None,
            core_count=psutil.cpu_count(logical=False) or 0,
            thread_count=psutil.cpu_count(logical=True) or 0,
        )

    def get_ram(self) -> RamInfo:
        mem = psutil.virtual_memory()
        to_mb = 1 / (1024**2)
        return RamInfo(
            total_mb=mem.total * to_mb,
            used_mb=mem.used * to_mb,
            available_mb=mem.available * to_mb,
            usage_percent=mem.percent,
        )

    def get_gpu(self) -> list[GpuInfo]:
        """
        Fragt nvidia-smi ab. Gibt leere Liste zurück wenn:
        - nvidia-smi nicht im PATH (Linux/kein NVIDIA)
        - Aufruf schlägt fehl
        Hinweis: plattformspezifisch (Windows + Linux mit NVIDIA-Treiber).
        """
        if not shutil.which("nvidia-smi"):
            return []

        query = (
            "name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu"
        )
        try:
            result = subprocess.run(
                ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        if result.returncode != 0:
            return []

        gpus: list[GpuInfo] = []
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 6:
                continue
            try:
                gpus.append(
                    GpuInfo(
                        name=parts[0],
                        vram_total_mb=float(parts[1]),
                        vram_used_mb=float(parts[2]),
                        vram_free_mb=float(parts[3]),
                        gpu_util_percent=float(parts[4]),
                        temperature_c=float(parts[5]),
                    )
                )
            except ValueError:
                continue
        return gpus

    def get_top_processes(self, n: int = 10) -> list[dict]:
        """Gibt die n CPU-intensivsten Prozesse zurück."""
        procs = []
        for proc in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_percent"]
        ):
            try:
                info = proc.info
                procs.append(
                    {
                        "pid": info["pid"],
                        "name": info["name"],
                        "cpu_percent": info["cpu_percent"] or 0.0,
                        "memory_percent": round(info["memory_percent"] or 0.0, 2),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return sorted(procs, key=lambda p: p["cpu_percent"], reverse=True)[:n]

    def get_info(self, top_processes: int = 10) -> SystemInfo:
        """Gibt ein vollständiges SystemInfo-Objekt zurück."""
        return SystemInfo(
            platform=platform.system(),
            cpu=self.get_cpu(),
            ram=self.get_ram(),
            gpus=self.get_gpu(),
            top_processes=self.get_top_processes(n=top_processes),
        )
