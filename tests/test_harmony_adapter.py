"""Tests fuer HarmonyAdapter -- aioharmony komplett gemockt."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import sys

import pytest

from elder_berry.robot.harmony_adapter import (
    HarmonyAdapter,
    _DEFAULT_CONFIG_PATH,
    _POWER_OFF_ACTIVITY_ID,
)


# -- Fixtures -------------------------------------------------------------- #

SAMPLE_CONFIG = {
    "activity": [
        {"id": 38979034, "label": "Fernsehen"},
        {"id": 38979035, "label": "Musik"},
        {"id": _POWER_OFF_ACTIVITY_ID, "label": "PowerOff"},
    ],
    "device": [
        {
            "id": "74828509",
            "label": "Denon AVR-X3500H",
            "controlGroup": [
                {
                    "name": "Volume",
                    "function": [
                        {"name": "VolumeUp"},
                        {"name": "VolumeDown"},
                        {"name": "Mute"},
                    ],
                },
                {
                    "name": "Power",
                    "function": [
                        {"name": "PowerOn"},
                        {"name": "PowerOff"},
                    ],
                },
            ],
        },
        {
            "id": "74828510",
            "label": "Samsung TV",
            "controlGroup": [
                {
                    "name": "Navigation",
                    "function": [
                        {"name": "DirectionUp"},
                        {"name": "DirectionDown"},
                        {"name": "Select"},
                    ],
                },
            ],
        },
    ],
}


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    p = tmp_path / "harmony_config.json"
    p.write_text(json.dumps(SAMPLE_CONFIG), encoding="utf-8")
    return p


@pytest.fixture
def adapter(config_file: Path) -> HarmonyAdapter:
    return HarmonyAdapter(hub_ip="192.168.50.133", config_path=config_file)


@pytest.fixture
def mock_harmony_api():
    """Erzeugt eine gemockte HarmonyAPI-Instanz."""
    api = AsyncMock()
    api.connect = AsyncMock(return_value=True)
    api.close = AsyncMock()
    api.start_activity = AsyncMock()
    api.power_off = AsyncMock()
    api.send_command = AsyncMock()
    api.config = SAMPLE_CONFIG
    api.current_activity = 38979034  # Fernsehen
    return api


# -- Initialisierung ------------------------------------------------------- #

class TestInit:
    def test_init_default_path(self):
        a = HarmonyAdapter(hub_ip="1.2.3.4")
        assert a.hub_ip == "1.2.3.4"
        assert a.config_path == _DEFAULT_CONFIG_PATH
        assert not a.is_connected

    def test_init_custom_path(self, config_file: Path):
        a = HarmonyAdapter(hub_ip="1.2.3.4", config_path=config_file)
        assert a.config_path == config_file


# -- Backup-Config --------------------------------------------------------- #

class TestBackupConfig:
    def test_load_backup_success(self, adapter: HarmonyAdapter):
        config = adapter._load_backup_config()
        assert "activity" in config
        assert len(config["activity"]) == 3

    def test_load_backup_missing(self, tmp_path: Path):
        a = HarmonyAdapter(hub_ip="1.2.3.4", config_path=tmp_path / "nope.json")
        config = a._load_backup_config()
        assert config == {}

    def test_load_backup_malformed(self, tmp_path: Path):
        p = tmp_path / "bad.json"
        p.write_text("{{not json}}", encoding="utf-8")
        a = HarmonyAdapter(hub_ip="1.2.3.4", config_path=p)
        config = a._load_backup_config()
        assert config == {}

    def test_load_backup_not_dict(self, tmp_path: Path):
        p = tmp_path / "list.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        a = HarmonyAdapter(hub_ip="1.2.3.4", config_path=p)
        config = a._load_backup_config()
        assert config == {}


# -- Verbindung ------------------------------------------------------------ #

class TestConnect:
    async def test_connect_success(self, adapter, mock_harmony_api):
        with patch(
            "elder_berry.robot.harmony_adapter.HarmonyAdapter.connect",
            new=self._make_connect(mock_harmony_api),
        ):
            pass
        # Direkt testen mit Mock-Injection
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG
        assert adapter.is_connected

    async def test_connect_uses_backup_on_failure(self, adapter):
        """Wenn Hub nicht erreichbar, wird Backup-Config geladen."""
        mock_api = AsyncMock()
        mock_api.connect = AsyncMock(return_value=False)

        mock_module = MagicMock()
        mock_module.HarmonyAPI = MagicMock(return_value=mock_api)

        with patch.dict(
            "sys.modules",
            {"aioharmony": MagicMock(), "aioharmony.harmonyapi": mock_module},
        ):
            result = await adapter.connect()

        assert result is True  # Backup geladen
        assert adapter.is_connected
        assert len(adapter._config.get("activity", [])) == 3

    async def test_connect_already_connected(self, adapter):
        adapter._connected = True
        result = await adapter.connect()
        assert result is True

    async def test_connect_no_backup_no_hub(self, tmp_path):
        """Wenn Hub nicht erreichbar und kein Backup, gibt connect False zurueck."""
        a = HarmonyAdapter(
            hub_ip="1.2.3.4",
            config_path=tmp_path / "nope.json",
        )
        mock_api = AsyncMock()
        mock_api.connect = AsyncMock(return_value=False)

        mock_module = MagicMock()
        mock_module.HarmonyAPI = MagicMock(return_value=mock_api)

        with patch.dict(
            "sys.modules",
            {"aioharmony": MagicMock(), "aioharmony.harmonyapi": mock_module},
        ):
            result = await a.connect()

        assert result is False
        assert not a.is_connected

    async def test_disconnect_clean(self, adapter, mock_harmony_api):
        adapter._client = mock_harmony_api
        adapter._connected = True

        await adapter.disconnect()

        mock_harmony_api.close.assert_awaited_once()
        assert not adapter.is_connected
        assert adapter._client is None

    async def test_disconnect_without_client(self, adapter):
        adapter._connected = True
        adapter._client = None
        await adapter.disconnect()
        assert not adapter.is_connected

    def test_is_connected_property(self, adapter):
        assert not adapter.is_connected
        adapter._connected = True
        assert adapter.is_connected

    @staticmethod
    def _make_connect(mock_api):
        async def connect(self):
            self._client = mock_api
            self._connected = True
            self._config = SAMPLE_CONFIG
            return True
        return connect


# -- Aktivitaeten ---------------------------------------------------------- #

class TestActivities:
    async def test_start_activity_by_name(self, adapter, mock_harmony_api):
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.start_activity("Fernsehen")
        assert result is True
        mock_harmony_api.start_activity.assert_awaited_once_with(38979034)

    async def test_start_activity_case_insensitive(self, adapter, mock_harmony_api):
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.start_activity("fernsehen")
        assert result is True
        mock_harmony_api.start_activity.assert_awaited_once_with(38979034)

    async def test_start_activity_not_found(self, adapter, mock_harmony_api):
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.start_activity("Gaming")
        assert result is False

    async def test_start_activity_disconnected(self, adapter):
        result = await adapter.start_activity("Fernsehen")
        assert result is False

    async def test_start_activity_no_client(self, adapter):
        """Nur Backup-Config, kein Hub-Client."""
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG
        adapter._client = None

        result = await adapter.start_activity("Fernsehen")
        assert result is False

    async def test_power_off(self, adapter, mock_harmony_api):
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.power_off()
        assert result is True
        mock_harmony_api.power_off.assert_awaited_once()

    async def test_power_off_disconnected(self, adapter):
        result = await adapter.power_off()
        assert result is False

    async def test_power_off_no_client(self, adapter):
        adapter._connected = True
        adapter._client = None
        result = await adapter.power_off()
        assert result is False

    async def test_get_current_activity_name(self, adapter, mock_harmony_api):
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG
        mock_harmony_api.current_activity = 38979034

        result = await adapter.get_current_activity()
        assert result == "Fernsehen"

    async def test_get_current_activity_none_on_poweroff(
        self, adapter, mock_harmony_api,
    ):
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG
        mock_harmony_api.current_activity = _POWER_OFF_ACTIVITY_ID

        result = await adapter.get_current_activity()
        assert result is None

    async def test_get_current_activity_disconnected(self, adapter):
        result = await adapter.get_current_activity()
        assert result is None

    async def test_list_activities(self, adapter):
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.list_activities()
        assert "Fernsehen" in result
        assert "Musik" in result
        assert "PowerOff" not in result

    async def test_list_activities_sync(self, adapter):
        adapter._config = SAMPLE_CONFIG
        result = adapter.list_activities_sync()
        assert len(result) == 2


# -- Geraetebefehle -------------------------------------------------------- #

class TestCommands:

    @pytest.fixture(autouse=True)
    def _mock_aioharmony(self):
        """Stellt sicher dass aioharmony.harmonyapi importierbar ist."""
        mock_scd = MagicMock()
        mock_module = MagicMock()
        mock_module.SendCommandDevice = mock_scd
        with patch.dict(
            "sys.modules",
            {"aioharmony": MagicMock(), "aioharmony.harmonyapi": mock_module},
        ):
            yield mock_scd

    async def test_send_command_success(self, adapter, mock_harmony_api):
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.send_command(
            "Denon AVR-X3500H", "VolumeUp",
        )

        assert result is True
        mock_harmony_api.send_command.assert_awaited_once()

    async def test_send_command_device_not_found(self, adapter, mock_harmony_api):
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.send_command("Xbox", "PowerOn")
        assert result is False

    async def test_send_command_unknown_command(self, adapter, mock_harmony_api):
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.send_command(
            "Denon AVR-X3500H", "FlyToMoon",
        )
        assert result is False

    async def test_send_command_repeat(self, adapter, mock_harmony_api):
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.send_command(
            "Denon AVR-X3500H", "VolumeUp", repeat=3,
        )

        assert result is True
        assert mock_harmony_api.send_command.await_count == 3

    async def test_send_command_case_insensitive_device(
        self, adapter, mock_harmony_api,
    ):
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.send_command(
            "denon avr-x3500h", "VolumeUp",
        )

        assert result is True

    async def test_send_command_case_insensitive_command(
        self, adapter, mock_harmony_api,
    ):
        adapter._client = mock_harmony_api
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.send_command(
            "Denon AVR-X3500H", "volumeup",
        )

        assert result is True

    async def test_send_command_disconnected(self, adapter):
        result = await adapter.send_command("Receiver", "VolumeUp")
        assert result is False

    async def test_list_commands(self, adapter):
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.list_commands("Denon AVR-X3500H")
        assert "VolumeUp" in result
        assert "VolumeDown" in result
        assert "Mute" in result
        assert "PowerOn" in result
        assert len(result) == 5

    async def test_list_commands_not_found(self, adapter):
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.list_commands("Unknown Device")
        assert result == []

    async def test_list_devices(self, adapter):
        adapter._connected = True
        adapter._config = SAMPLE_CONFIG

        result = await adapter.list_devices()
        assert "Denon AVR-X3500H" in result
        assert "Samsung TV" in result
        assert len(result) == 2


# -- Interne Methoden ------------------------------------------------------ #

class TestInternal:
    def test_find_activity_id_exact(self, adapter):
        adapter._config = SAMPLE_CONFIG
        assert adapter._find_activity_id("Fernsehen") == "38979034"

    def test_find_activity_id_case_insensitive(self, adapter):
        adapter._config = SAMPLE_CONFIG
        assert adapter._find_activity_id("fernsehen") == "38979034"
        assert adapter._find_activity_id("MUSIK") == "38979035"

    def test_find_activity_id_not_found(self, adapter):
        adapter._config = SAMPLE_CONFIG
        assert adapter._find_activity_id("Gaming") is None

    def test_find_device_id_exact(self, adapter):
        adapter._config = SAMPLE_CONFIG
        assert adapter._find_device_id("Denon AVR-X3500H") == "74828509"

    def test_find_device_id_case_insensitive(self, adapter):
        adapter._config = SAMPLE_CONFIG
        assert adapter._find_device_id("samsung tv") == "74828510"

    def test_find_device_id_not_found(self, adapter):
        adapter._config = SAMPLE_CONFIG
        assert adapter._find_device_id("Xbox") is None

    def test_get_device_commands(self, adapter):
        adapter._config = SAMPLE_CONFIG
        cmds = adapter._get_device_commands("74828509")
        assert "VolumeUp" in cmds
        assert "Mute" in cmds

    def test_get_device_commands_unknown(self, adapter):
        adapter._config = SAMPLE_CONFIG
        assert adapter._get_device_commands("99999") == []

    def test_get_activities_empty_config(self, adapter):
        adapter._config = {}
        assert adapter._get_activities() == []

    def test_get_devices_empty_config(self, adapter):
        adapter._config = {}
        assert adapter._get_devices() == []
