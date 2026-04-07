"""Tests für AvatarEditor – FastAPI-Endpoints für den Avatar-Editor."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from elder_berry.character.base import Emotion
from elder_berry.core.audio_router import AudioRouter

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def avatar_assets(tmp_path):
    """Erstellt temporäre Asset-Ordner mit Dummy-PNGs."""
    for subdir, names in [
        ("body", ["idle", "relaxed", "angry"]),
        ("eye", ["eye_left_open", "eye_right_open", "eye_left_close", "eye_right_close"]),
        ("mouth", ["mouth_neutral_close", "mouth_open", "mouth_halfopen"]),
        ("effect", ["effect_tear"]),
    ]:
        d = tmp_path / subdir
        d.mkdir()
        for name in names:
            # Minimales PNG (Header reicht für FileResponse-Test)
            (d / f"{name}.png").write_bytes(
                b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
            )
    return tmp_path


@pytest.fixture
def avatar_config_yaml(tmp_path):
    """Erstellt eine temporäre avatar_config.yaml."""
    config = {
        "version": 1,
        "emotions": {
            "neutral": {
                "body": "relaxed",
                "eye_left": "eye_left_open",
                "eye_right": "eye_right_open",
                "mouth": "mouth_neutral_close",
                "can_blink": True,
            },
            "angry": {
                "body": "angry",
                "eye_left": "eye_left_open",
                "eye_right": "eye_right_open",
                "mouth": "mouth_open",
                "can_blink": False,
            },
        },
        "lip_sync": {
            "frames": {
                "mouth_neutral_close": 0.2,
                "mouth_open": 0.5,
                "mouth_halfopen": 0.3,
            },
            "interval": 0.18,
            "jitter": 0.03,
        },
        "breathing": {
            "enabled": True,
            "speed": 1.2,
            "amplitude": 2.0,
        },
        "idle_actions": [],
    }
    config_path = tmp_path / "avatar_config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False)
    return config_path


@pytest.fixture
def client(avatar_assets, avatar_config_yaml):
    """TestClient mit gemockten Asset- und Config-Pfaden."""
    from elder_berry.web.settings_dashboard import SettingsDashboard
    import elder_berry.web.avatar_editor as ae

    # Patch die Module-Level-Pfade
    original_assets = ae._ASSETS_DIR
    original_config = ae.DEFAULT_CONFIG_PATH
    ae._ASSETS_DIR = avatar_assets
    ae.DEFAULT_CONFIG_PATH = avatar_config_yaml

    # Patch auch den ConfigLoader-Default
    import elder_berry.avatar.avatar_config_loader as acl
    original_loader_path = acl.DEFAULT_CONFIG_PATH
    acl.DEFAULT_CONFIG_PATH = avatar_config_yaml

    router = AudioRouter(local_available=True)
    dashboard = SettingsDashboard(audio_router=router)
    tc = TestClient(dashboard.app)

    yield tc

    # Restore
    ae._ASSETS_DIR = original_assets
    ae.DEFAULT_CONFIG_PATH = original_config
    acl.DEFAULT_CONFIG_PATH = original_loader_path


@pytest.fixture
def client_with_renderer(avatar_assets, avatar_config_yaml):
    """TestClient mit gemocktem Renderer für Hot-Reload-Tests."""
    from elder_berry.web.settings_dashboard import SettingsDashboard
    import elder_berry.web.avatar_editor as ae

    original_assets = ae._ASSETS_DIR
    original_config = ae.DEFAULT_CONFIG_PATH
    ae._ASSETS_DIR = avatar_assets
    ae.DEFAULT_CONFIG_PATH = avatar_config_yaml

    import elder_berry.avatar.avatar_config_loader as acl
    original_loader_path = acl.DEFAULT_CONFIG_PATH
    acl.DEFAULT_CONFIG_PATH = avatar_config_yaml

    mock_renderer = MagicMock()
    mock_renderer.reload_config.return_value = True

    router = AudioRouter(local_available=True)
    dashboard = SettingsDashboard(audio_router=router, avatar_renderer=mock_renderer)
    tc = TestClient(dashboard.app)

    yield tc, mock_renderer

    ae._ASSETS_DIR = original_assets
    ae.DEFAULT_CONFIG_PATH = original_config
    acl.DEFAULT_CONFIG_PATH = original_loader_path


# ---------------------------------------------------------------------------
# Editor-Seite
# ---------------------------------------------------------------------------

class TestEditorPage:
    def test_returns_html(self, client):
        r = client.get("/avatar/editor")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_contains_title(self, client):
        r = client.get("/avatar/editor")
        assert "Avatar-Editor" in r.text

    def test_contains_canvas(self, client):
        r = client.get("/avatar/editor")
        assert "avatar-canvas" in r.text


# ---------------------------------------------------------------------------
# Asset-Liste
# ---------------------------------------------------------------------------

class TestListAssets:
    def test_returns_all_categories(self, client):
        r = client.get("/api/avatar/assets")
        assert r.status_code == 200
        data = r.json()
        assert "body" in data
        assert "eye" in data
        assert "mouth" in data
        assert "effect" in data

    def test_body_assets(self, client):
        r = client.get("/api/avatar/assets")
        data = r.json()
        assert "idle" in data["body"]
        assert "relaxed" in data["body"]

    def test_effect_assets(self, client):
        r = client.get("/api/avatar/assets")
        data = r.json()
        assert "effect_tear" in data["effect"]


# ---------------------------------------------------------------------------
# Asset-Serving
# ---------------------------------------------------------------------------

class TestGetAsset:
    def test_serves_png(self, client):
        r = client.get("/api/avatar/assets/body/idle")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"

    def test_serves_eye(self, client):
        r = client.get("/api/avatar/assets/eye/eye_left_open")
        assert r.status_code == 200

    def test_invalid_category(self, client):
        r = client.get("/api/avatar/assets/invalid/test")
        assert r.status_code == 400
        assert "Ungültige Kategorie" in r.json()["error"]

    def test_not_found_asset(self, client):
        r = client.get("/api/avatar/assets/body/nonexistent")
        assert r.status_code == 404

    def test_path_traversal_blocked(self, client):
        r = client.get("/api/avatar/assets/body/..%2F..%2Fetc%2Fpasswd")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Config lesen
# ---------------------------------------------------------------------------

class TestGetConfig:
    def test_returns_config(self, client):
        r = client.get("/api/avatar/config")
        assert r.status_code == 200
        data = r.json()
        assert "config" in data
        assert "emotions" in data
        assert "reload_available" in data

    def test_emotions_list(self, client):
        r = client.get("/api/avatar/config")
        data = r.json()
        assert "neutral" in data["emotions"]
        assert "angry" in data["emotions"]

    def test_config_contains_emotions(self, client):
        r = client.get("/api/avatar/config")
        config = r.json()["config"]
        assert "neutral" in config["emotions"]
        assert config["emotions"]["neutral"]["body"] == "relaxed"

    def test_reload_not_available(self, client):
        """Ohne Renderer ist Hot-Reload deaktiviert."""
        r = client.get("/api/avatar/config")
        assert r.json()["reload_available"] is False

    def test_reload_available_with_renderer(self, client_with_renderer):
        tc, _ = client_with_renderer
        r = tc.get("/api/avatar/config")
        assert r.json()["reload_available"] is True


# ---------------------------------------------------------------------------
# Config speichern
# ---------------------------------------------------------------------------

class TestSaveConfig:
    def test_save_valid_config(self, client, avatar_config_yaml):
        config = {
            "version": 1,
            "emotions": {
                "neutral": {
                    "body": "idle",
                    "eye_left": "eye_left_open",
                    "eye_right": "eye_right_open",
                    "mouth": "mouth_neutral_close",
                    "can_blink": True,
                },
            },
            "lip_sync": {
                "frames": {"mouth_open": 1.0},
                "interval": 0.2,
                "jitter": 0.02,
            },
            "breathing": {"enabled": True, "speed": 1.0, "amplitude": 1.5},
        }
        r = client.put("/api/avatar/config", json={"config": config})
        assert r.status_code == 200
        assert r.json()["saved"] is True

        # Verify file was written
        with open(avatar_config_yaml, encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        assert saved["emotions"]["neutral"]["body"] == "idle"

    def test_save_missing_body(self, client):
        r = client.put("/api/avatar/config", json={
            "config": {
                "emotions": {
                    "neutral": {
                        "eye_left": "x",
                        "eye_right": "x",
                        "mouth": "x",
                    },
                },
            },
        })
        assert r.status_code == 400
        assert "body" in r.json()["error"]

    def test_save_unknown_emotion(self, client):
        r = client.put("/api/avatar/config", json={
            "config": {
                "emotions": {
                    "nonexistent": {
                        "body": "x",
                        "eye_left": "x",
                        "eye_right": "x",
                        "mouth": "x",
                    },
                },
            },
        })
        assert r.status_code == 400
        assert "Unbekannte Emotion" in r.json()["error"]

    def test_save_empty_body(self, client):
        r = client.put("/api/avatar/config", json={})
        assert r.status_code == 400

    def test_save_no_emotions(self, client):
        r = client.put("/api/avatar/config", json={
            "config": {"emotions": {}},
        })
        assert r.status_code == 400

    def test_save_with_effect(self, client, avatar_config_yaml):
        config = {
            "version": 1,
            "emotions": {
                "sad": {
                    "body": "relaxed",
                    "eye_left": "eye_left_open",
                    "eye_right": "eye_right_open",
                    "mouth": "mouth_open",
                    "effect": "effect_tear",
                    "can_blink": False,
                },
            },
            "lip_sync": {"frames": {"mouth_open": 1.0}, "interval": 0.2, "jitter": 0.02},
            "breathing": {"enabled": True, "speed": 1.0, "amplitude": 1.5},
        }
        r = client.put("/api/avatar/config", json={"config": config})
        assert r.status_code == 200

        with open(avatar_config_yaml, encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        assert saved["emotions"]["sad"]["effect"] == "effect_tear"


# ---------------------------------------------------------------------------
# Hot-Reload
# ---------------------------------------------------------------------------

class TestReload:
    def test_reload_without_renderer(self, client):
        r = client.post("/api/avatar/reload")
        assert r.status_code == 400
        assert "Kein Renderer" in r.json()["error"]

    def test_reload_with_renderer(self, client_with_renderer):
        tc, mock_renderer = client_with_renderer
        r = tc.post("/api/avatar/reload")
        assert r.status_code == 200
        assert r.json()["reloaded"] is True
        mock_renderer.reload_config.assert_called_once()

    def test_reload_failure(self, client_with_renderer):
        tc, mock_renderer = client_with_renderer
        mock_renderer.reload_config.return_value = False
        r = tc.post("/api/avatar/reload")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# Effekt-Layer im ConfigLoader
# ---------------------------------------------------------------------------

class TestEffectLayerConfig:
    def test_effect_field_in_emotion_layers(self):
        from elder_berry.avatar.avatar_config_loader import EmotionLayers
        layers = EmotionLayers(
            body="relaxed",
            eye_left="eye_left_open",
            eye_right="eye_right_open",
            mouth="mouth_neutral_close",
            can_blink=True,
            effect="effect_tear",
        )
        assert layers.effect == "effect_tear"

    def test_effect_field_default_none(self):
        from elder_berry.avatar.avatar_config_loader import EmotionLayers
        layers = EmotionLayers(
            body="relaxed",
            eye_left="eye_left_open",
            eye_right="eye_right_open",
            mouth="mouth_neutral_close",
            can_blink=True,
        )
        assert layers.effect is None

    def test_load_config_with_effect(self, tmp_path):
        """Config mit effect-Key wird korrekt geladen."""
        config = {
            "emotions": {
                "sad": {
                    "body": "relaxed",
                    "eye_left": "eye_left_open",
                    "eye_right": "eye_right_open",
                    "mouth": "mouth_open",
                    "effect": "effect_tear",
                    "can_blink": False,
                },
            },
            "lip_sync": {"frames": {}, "interval": 0.18, "jitter": 0.03},
            "breathing": {"enabled": True, "speed": 1.2, "amplitude": 2.0},
            "idle_actions": [],
        }
        config_path = tmp_path / "test_config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        from elder_berry.avatar.avatar_config_loader import load_avatar_config
        result = load_avatar_config(config_path)
        assert result is not None
        assert result.emotions[Emotion.SAD].effect == "effect_tear"

    def test_load_config_without_effect(self, tmp_path):
        """Config ohne effect-Key → effect ist None."""
        config = {
            "emotions": {
                "neutral": {
                    "body": "relaxed",
                    "eye_left": "eye_left_open",
                    "eye_right": "eye_right_open",
                    "mouth": "mouth_open",
                    "can_blink": True,
                },
            },
            "lip_sync": {"frames": {}, "interval": 0.18, "jitter": 0.03},
            "breathing": {"enabled": True, "speed": 1.2, "amplitude": 2.0},
            "idle_actions": [],
        }
        config_path = tmp_path / "test_config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        from elder_berry.avatar.avatar_config_loader import load_avatar_config
        result = load_avatar_config(config_path)
        assert result is not None
        assert result.emotions[Emotion.NEUTRAL].effect is None


# ---------------------------------------------------------------------------
# Effekt-Layer im Renderer
# ---------------------------------------------------------------------------

class TestEffectLayerRenderer:
    def test_emotion_layers_has_effect(self):
        from elder_berry.avatar.layered_renderer import EmotionLayers
        layers = EmotionLayers(
            body="relaxed",
            eye_left="eye_left_open",
            eye_right="eye_right_open",
            mouth="mouth_neutral_close",
            can_blink=True,
            effect="effect_sparkle",
        )
        assert layers.effect == "effect_sparkle"

    def test_emotion_layers_effect_default_none(self):
        from elder_berry.avatar.layered_renderer import EmotionLayers
        layers = EmotionLayers(
            body="relaxed",
            eye_left="eye_left_open",
            eye_right="eye_right_open",
            mouth="mouth_neutral_close",
            can_blink=True,
        )
        assert layers.effect is None
