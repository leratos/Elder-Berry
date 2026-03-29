"""Tests fuer HarmonyMockServer -- FastAPI TestClient."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from elder_berry.server.harmony_mock_server import create_app


# -- Fixtures -------------------------------------------------------------- #

SAMPLE_CONFIG = {
    "activity": [
        {"id": 38979034, "label": "Fernsehen"},
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
                    ],
                },
            ],
        },
        {
            "id": "74828510",
            "label": "Samsung TV",
            "controlGroup": [],
        },
    ],
}


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    p = tmp_path / "harmony_config.json"
    p.write_text(json.dumps(SAMPLE_CONFIG), encoding="utf-8")
    return p


@pytest.fixture
def client(config_file: Path) -> TestClient:
    app = create_app(config_path=config_file)
    return TestClient(app)


@pytest.fixture
def client_no_config(tmp_path: Path) -> TestClient:
    app = create_app(config_path=tmp_path / "missing.json")
    return TestClient(app)


# -- Tests ----------------------------------------------------------------- #

class TestGetConfig:
    def test_get_config_returns_backup(self, client):
        r = client.post("/account/getConfig")
        assert r.status_code == 200
        data = r.json()
        assert "activity" in data
        assert data["activity"][0]["label"] == "Fernsehen"

    def test_missing_backup_returns_404(self, client_no_config):
        r = client_no_config.post("/account/getConfig")
        assert r.status_code == 404


class TestSaveConfig:
    def test_save_config_persists(self, client, config_file):
        new_config = {"activity": [{"id": 1, "label": "Test"}], "device": []}
        r = client.post(
            "/account/saveConfig",
            content=json.dumps(new_config),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        # Pruefen ob Datei aktualisiert wurde
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved["activity"][0]["label"] == "Test"

    def test_get_config_after_save_returns_updated(self, client):
        new_config = {
            "activity": [{"id": 99, "label": "Neu"}],
            "device": [],
        }
        client.post(
            "/account/saveConfig",
            content=json.dumps(new_config),
        )
        r = client.post("/account/getConfig")
        assert r.status_code == 200
        assert r.json()["activity"][0]["label"] == "Neu"

    def test_save_config_invalid_json_400(self, client):
        r = client.post(
            "/account/saveConfig",
            content="{{not json}}",
        )
        assert r.status_code == 400


class TestGetDeviceInfo:
    def test_get_device_info_known_device(self, client):
        r = client.post(
            "/account/getDeviceInfo",
            content=json.dumps({"device": "Denon AVR-X3500H"}),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["label"] == "Denon AVR-X3500H"
        assert len(data["controlGroup"]) == 1

    def test_get_device_info_case_insensitive(self, client):
        r = client.post(
            "/account/getDeviceInfo",
            content=json.dumps({"device": "denon avr-x3500h"}),
        )
        assert r.status_code == 200

    def test_get_device_info_unknown_device_404(self, client):
        r = client.post(
            "/account/getDeviceInfo",
            content=json.dumps({"device": "Xbox"}),
        )
        assert r.status_code == 404

    def test_get_device_info_missing_field_400(self, client):
        r = client.post(
            "/account/getDeviceInfo",
            content=json.dumps({}),
        )
        assert r.status_code == 400

    def test_get_device_info_no_config_404(self, client_no_config):
        r = client_no_config.post(
            "/account/getDeviceInfo",
            content=json.dumps({"device": "test"}),
        )
        assert r.status_code == 404
