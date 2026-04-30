"""Tests: Assistant.process() mit system_status Aktion."""

import json
from unittest.mock import MagicMock

import pytest

from elder_berry.actions.base import ActionController
from elder_berry.actions.db import ActionsDB
from elder_berry.core.assistant import Assistant
from elder_berry.llm.base import LLMClient
from elder_berry.system.info import (
    CpuInfo,
    GpuInfo,
    RamInfo,
    SystemInfo,
    SystemMonitor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_system_status():
    """LLM das system_status als Aktion zurückgibt."""
    llm = MagicMock(spec=LLMClient)
    llm.generate.return_value = json.dumps(
        {
            "action": "system_status",
            "params": {},
            "response": "Hier ist der aktuelle Zustand deines PCs:",
        }
    )
    return llm


@pytest.fixture
def mock_llm_no_action():
    llm = MagicMock(spec=LLMClient)
    llm.generate.return_value = json.dumps(
        {
            "action": None,
            "params": {},
            "response": "Alles klar!",
        }
    )
    return llm


@pytest.fixture
def mock_db(tmp_path):
    return ActionsDB(db_path=tmp_path / "test.db")


@pytest.fixture
def mock_controller():
    return MagicMock(spec=ActionController)


@pytest.fixture
def mock_system_monitor():
    monitor = MagicMock(spec=SystemMonitor)
    monitor.get_info.return_value = SystemInfo(
        platform="Windows",
        cpu=CpuInfo(
            usage_percent=35.2,
            per_core_percent=[30.0, 40.0, 35.0, 36.0],
            freq_mhz=3200.0,
            core_count=4,
            thread_count=8,
        ),
        ram=RamInfo(
            total_mb=16384.0,
            used_mb=8500.0,
            available_mb=7884.0,
            usage_percent=51.9,
        ),
        gpus=[
            GpuInfo(
                name="NVIDIA RTX 4070 Ti Super",
                vram_total_mb=16384.0,
                vram_used_mb=4200.0,
                vram_free_mb=12184.0,
                gpu_util_percent=12.0,
                temperature_c=45.0,
            )
        ],
        top_processes=[
            {
                "pid": 1,
                "name": "ollama.exe",
                "cpu_percent": 25.0,
                "memory_percent": 8.5,
            },
            {
                "pid": 2,
                "name": "chrome.exe",
                "cpu_percent": 5.0,
                "memory_percent": 12.3,
            },
            {"pid": 3, "name": "python.exe", "cpu_percent": 2.0, "memory_percent": 3.1},
        ],
    )
    return monitor


# ---------------------------------------------------------------------------
# system_status Aktion
# ---------------------------------------------------------------------------


class TestSystemStatus:
    def test_system_status_returns_data(
        self,
        mock_llm_system_status,
        mock_db,
        mock_controller,
        mock_system_monitor,
    ):
        """system_status Aktion liefert CPU/RAM/GPU Daten in der Response."""
        assistant = Assistant(
            llm=mock_llm_system_status,
            actions_db=mock_db,
            controller=mock_controller,
            system_monitor=mock_system_monitor,
        )
        result = assistant.process("Wie geht es meinem PC?")

        assert result.action_executed == "system_status"
        assert result.action_success is True
        assert "CPU:" in result.response
        assert "RAM:" in result.response
        assert "GPU:" in result.response
        assert "35.2%" in result.response
        assert "RTX 4070 Ti Super" in result.response

    def test_system_status_includes_processes(
        self,
        mock_llm_system_status,
        mock_db,
        mock_controller,
        mock_system_monitor,
    ):
        """Top-Prozesse sind in der Response enthalten."""
        assistant = Assistant(
            llm=mock_llm_system_status,
            actions_db=mock_db,
            controller=mock_controller,
            system_monitor=mock_system_monitor,
        )
        result = assistant.process("PC Status?")

        assert "ollama.exe" in result.response
        assert "chrome.exe" in result.response

    def test_system_status_includes_llm_response(
        self,
        mock_llm_system_status,
        mock_db,
        mock_controller,
        mock_system_monitor,
    ):
        """LLM-Antwort wird beibehalten, Systemdaten angehängt."""
        assistant = Assistant(
            llm=mock_llm_system_status,
            actions_db=mock_db,
            controller=mock_controller,
            system_monitor=mock_system_monitor,
        )
        result = assistant.process("Status?")

        assert result.response.startswith("Hier ist der aktuelle Zustand")
        assert "CPU:" in result.response

    def test_system_status_without_monitor(
        self,
        mock_llm_system_status,
        mock_db,
        mock_controller,
    ):
        """Ohne SystemMonitor: action_success False, nur LLM-Response."""
        assistant = Assistant(
            llm=mock_llm_system_status,
            actions_db=mock_db,
            controller=mock_controller,
            system_monitor=None,
        )
        result = assistant.process("PC Status?")

        assert result.action_executed == "system_status"
        assert result.action_success is False
        assert "CPU:" not in result.response

    def test_system_status_monitor_error(
        self,
        mock_llm_system_status,
        mock_db,
        mock_controller,
    ):
        """SystemMonitor wirft Exception: graceful degradation."""
        monitor = MagicMock(spec=SystemMonitor)
        monitor.get_info.side_effect = RuntimeError("psutil error")

        assistant = Assistant(
            llm=mock_llm_system_status,
            actions_db=mock_db,
            controller=mock_controller,
            system_monitor=monitor,
        )
        result = assistant.process("Status?")

        assert result.action_executed == "system_status"
        assert result.action_success is False

    def test_system_status_no_gpu(
        self,
        mock_llm_system_status,
        mock_db,
        mock_controller,
    ):
        """System ohne GPU: kein GPU-Abschnitt, aber CPU/RAM vorhanden."""
        monitor = MagicMock(spec=SystemMonitor)
        monitor.get_info.return_value = SystemInfo(
            platform="Linux",
            cpu=CpuInfo(
                usage_percent=10.0,
                per_core_percent=[10.0],
                freq_mhz=None,
                core_count=1,
                thread_count=1,
            ),
            ram=RamInfo(
                total_mb=4096.0,
                used_mb=2000.0,
                available_mb=2096.0,
                usage_percent=48.8,
            ),
            gpus=[],
            top_processes=[],
        )

        assistant = Assistant(
            llm=mock_llm_system_status,
            actions_db=mock_db,
            controller=mock_controller,
            system_monitor=monitor,
        )
        result = assistant.process("Status?")

        assert result.action_success is True
        assert "CPU:" in result.response
        assert "RAM:" in result.response
        assert "GPU:" not in result.response

    def test_system_status_no_freq(
        self,
        mock_llm_system_status,
        mock_db,
        mock_controller,
    ):
        """CPU ohne Frequenz-Info: kein MHz im Output."""
        monitor = MagicMock(spec=SystemMonitor)
        monitor.get_info.return_value = SystemInfo(
            platform="Linux",
            cpu=CpuInfo(
                usage_percent=5.0,
                per_core_percent=[5.0],
                freq_mhz=None,
                core_count=4,
                thread_count=4,
            ),
            ram=RamInfo(
                total_mb=8192.0,
                used_mb=4000.0,
                available_mb=4192.0,
                usage_percent=48.8,
            ),
        )

        assistant = Assistant(
            llm=mock_llm_system_status,
            actions_db=mock_db,
            controller=mock_controller,
            system_monitor=monitor,
        )
        result = assistant.process("Status?")

        assert "MHz" not in result.response
        assert "4 Kerne" in result.response


# ---------------------------------------------------------------------------
# Rückwärtskompatibilität
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_without_system_monitor(
        self,
        mock_llm_no_action,
        mock_db,
        mock_controller,
    ):
        """Assistant ohne SystemMonitor funktioniert wie bisher."""
        assistant = Assistant(
            llm=mock_llm_no_action,
            actions_db=mock_db,
            controller=mock_controller,
        )
        result = assistant.process("Hallo")

        assert result.response == "Alles klar!"
        assert result.action_executed is None
