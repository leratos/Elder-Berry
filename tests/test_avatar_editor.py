"""Tests für AvatarEditor – FastAPI-Endpoints für den Avatar-Editor."""

from unittest.mock import MagicMock

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
        (
            "eye",
            ["eye_left_open", "eye_right_open", "eye_left_close", "eye_right_close"],
        ),
        ("mouth", ["mouth_neutral_close", "mouth_open", "mouth_halfopen"]),
        ("effect", ["effect_tear"]),
    ]:
        d = tmp_path / subdir
        d.mkdir()
        for name in names:
            # Minimales PNG (Header reicht für FileResponse-Test)
            (d / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
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
def avatar_user_config_yaml(tmp_path):
    """Pfad fuer die USER-Override-Datei (`~/.elder-berry/avatar_config.yaml`).

    Existiert anfangs NICHT -- der Editor legt sie beim ersten Save an.
    Tests, die explizit den User-Pfad pruefen, schreiben/lesen daran.
    """
    return tmp_path / "user_avatar_config.yaml"


@pytest.fixture
def client(avatar_assets, avatar_config_yaml, avatar_user_config_yaml):
    """TestClient mit gemockten Asset- und Config-Pfaden (DEFAULT + USER)."""
    from elder_berry.web.settings_dashboard import SettingsDashboard
    import elder_berry.web.avatar_editor as ae
    import elder_berry.avatar.avatar_config_loader as acl

    # avatar_editor referenziert avatar_config_loader-Konstanten via Modul --
    # ein Patch am Loader reicht, beide Module sehen's.
    original_assets = ae._ASSETS_DIR
    original_default = acl.DEFAULT_CONFIG_PATH
    original_user = acl.USER_CONFIG_PATH
    ae._ASSETS_DIR = avatar_assets
    acl.DEFAULT_CONFIG_PATH = avatar_config_yaml
    acl.USER_CONFIG_PATH = avatar_user_config_yaml

    router = AudioRouter(local_available=True)
    dashboard = SettingsDashboard(audio_router=router)
    tc = TestClient(dashboard.app)

    yield tc

    # Restore
    ae._ASSETS_DIR = original_assets
    acl.DEFAULT_CONFIG_PATH = original_default
    acl.USER_CONFIG_PATH = original_user


@pytest.fixture
def client_with_renderer(avatar_assets, avatar_config_yaml, avatar_user_config_yaml):
    """TestClient mit gemocktem Renderer für Hot-Reload-Tests."""
    from elder_berry.web.settings_dashboard import SettingsDashboard
    import elder_berry.web.avatar_editor as ae
    import elder_berry.avatar.avatar_config_loader as acl

    original_assets = ae._ASSETS_DIR
    original_default = acl.DEFAULT_CONFIG_PATH
    original_user = acl.USER_CONFIG_PATH
    ae._ASSETS_DIR = avatar_assets
    acl.DEFAULT_CONFIG_PATH = avatar_config_yaml
    acl.USER_CONFIG_PATH = avatar_user_config_yaml

    mock_renderer = MagicMock()
    mock_renderer.reload_config.return_value = True

    router = AudioRouter(local_available=True)
    dashboard = SettingsDashboard(audio_router=router, avatar_renderer=mock_renderer)
    tc = TestClient(dashboard.app)

    yield tc, mock_renderer

    ae._ASSETS_DIR = original_assets
    acl.DEFAULT_CONFIG_PATH = original_default
    acl.USER_CONFIG_PATH = original_user


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

    def test_path_traversal_url_encoded_blocked(self, client):
        # URL-encoded "../../etc/passwd" -- TestClient/Starlette
        # normalisiert das auf URL-Ebene und gibt 404 (Route matcht
        # nicht mehr). Frueher Allowlist-Bypass-Versuch wird dadurch
        # auf zwei Ebenen geblockt: Routing UND Endpoint-Allowlist.
        r = client.get("/api/avatar/assets/body/..%2F..%2Fetc%2Fpasswd")
        assert r.status_code == 404

    def test_special_chars_blocked(self, client):
        # Punkte, Spaces, Sonderzeichen, ".." als Substring -- der
        # Allowlist-Regex r"^[A-Za-z0-9_-]+$" lehnt all das mit 400 ab
        # (CodeQL py/path-injection #304).
        for name in ("foo.bar", "foo bar", "foo$", "foo;rm", "*", "..foo", "foo.."):
            r = client.get(f"/api/avatar/assets/body/{name}")
            assert r.status_code == 400, f"name={name!r} sollte 400 geben"

    def test_empty_name_blocked(self, client):
        # Leerer Name (z.B. via trailing slash) -- FastAPI matcht
        # die Route gar nicht mehr -> 404. Leere Namen kommen also
        # nicht in get_asset() rein.
        r = client.get("/api/avatar/assets/body/")
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
    def test_save_valid_config(
        self, client, avatar_config_yaml, avatar_user_config_yaml
    ):
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
        default_before = avatar_config_yaml.read_text(encoding="utf-8")

        r = client.put("/api/avatar/config", json={"config": config})
        assert r.status_code == 200
        assert r.json()["saved"] is True

        # USER-Pfad wurde geschrieben.
        assert avatar_user_config_yaml.exists()
        with open(avatar_user_config_yaml, encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        assert saved["emotions"]["neutral"]["body"] == "idle"
        # DEFAULT-Pfad (= getrackte Datei) wurde NICHT angefasst -- sonst
        # kollidiert das mit ``git pull --ff-only`` bei ``update alles``.
        assert avatar_config_yaml.read_text(encoding="utf-8") == default_before

    def test_save_missing_body(self, client):
        r = client.put(
            "/api/avatar/config",
            json={
                "config": {
                    "emotions": {
                        "neutral": {
                            "eye_left": "x",
                            "eye_right": "x",
                            "mouth": "x",
                        },
                    },
                },
            },
        )
        assert r.status_code == 400
        assert "body" in r.json()["error"]

    def test_save_unknown_emotion(self, client):
        r = client.put(
            "/api/avatar/config",
            json={
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
            },
        )
        assert r.status_code == 400
        assert "Unbekannte Emotion" in r.json()["error"]

    def test_save_empty_body(self, client):
        r = client.put("/api/avatar/config", json={})
        assert r.status_code == 400

    def test_save_no_emotions(self, client):
        r = client.put(
            "/api/avatar/config",
            json={
                "config": {"emotions": {}},
            },
        )
        assert r.status_code == 400

    def test_save_with_effect(self, client, avatar_user_config_yaml):
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
            "lip_sync": {
                "frames": {"mouth_open": 1.0},
                "interval": 0.2,
                "jitter": 0.02,
            },
            "breathing": {"enabled": True, "speed": 1.0, "amplitude": 1.5},
        }
        r = client.put("/api/avatar/config", json={"config": config})
        assert r.status_code == 200

        # USER-Pfad enthaelt den geschriebenen Effect.
        with open(avatar_user_config_yaml, encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        assert saved["emotions"]["sad"]["effect"] == "effect_tear"

    # ------------------------------------------------------------------
    # User-Override-Pattern (Phase: avatar-config-user-override)
    # ------------------------------------------------------------------

    def test_save_writes_to_user_not_default(
        self, client, avatar_config_yaml, avatar_user_config_yaml
    ):
        """Save schreibt ausschliesslich in USER, DEFAULT bleibt unangetastet."""
        default_before = avatar_config_yaml.read_text(encoding="utf-8")
        config = {
            "emotions": {
                "neutral": {
                    "body": "idle",
                    "eye_left": "eye_left_open",
                    "eye_right": "eye_right_open",
                    "mouth": "mouth_neutral_close",
                },
            },
        }
        r = client.put("/api/avatar/config", json={"config": config})
        assert r.status_code == 200
        assert avatar_user_config_yaml.exists()
        assert avatar_config_yaml.read_text(encoding="utf-8") == default_before

    def test_save_creates_user_parent_dir(
        self, avatar_assets, avatar_config_yaml, tmp_path
    ):
        """USER-Parent-Verzeichnis fehlt -> Editor legt es an (mkdir parents=True)."""
        from elder_berry.web.settings_dashboard import SettingsDashboard
        import elder_berry.web.avatar_editor as ae
        import elder_berry.avatar.avatar_config_loader as acl

        nested_user = tmp_path / "subdir" / "doesnt" / "exist" / "user_avatar.yaml"
        assert not nested_user.parent.exists()

        original_assets = ae._ASSETS_DIR
        original_default = acl.DEFAULT_CONFIG_PATH
        original_user = acl.USER_CONFIG_PATH
        ae._ASSETS_DIR = avatar_assets
        acl.DEFAULT_CONFIG_PATH = avatar_config_yaml
        acl.USER_CONFIG_PATH = nested_user

        try:
            router = AudioRouter(local_available=True)
            dashboard = SettingsDashboard(audio_router=router)
            tc = TestClient(dashboard.app)

            config = {
                "emotions": {
                    "neutral": {
                        "body": "idle",
                        "eye_left": "eye_left_open",
                        "eye_right": "eye_right_open",
                        "mouth": "mouth_neutral_close",
                    },
                },
            }
            r = tc.put("/api/avatar/config", json={"config": config})
            assert r.status_code == 200
            assert nested_user.exists()
            assert nested_user.parent.is_dir()
        finally:
            ae._ASSETS_DIR = original_assets
            acl.DEFAULT_CONFIG_PATH = original_default
            acl.USER_CONFIG_PATH = original_user

    def test_get_reads_user_when_present(self, client, avatar_user_config_yaml):
        """USER existiert mit Override -> GET liefert USER-Content."""
        user_config = {
            "version": 1,
            "emotions": {
                "neutral": {
                    "body": "user_override_body",
                    "eye_left": "eye_left_open",
                    "eye_right": "eye_right_open",
                    "mouth": "mouth_neutral_close",
                    "can_blink": True,
                },
            },
            "lip_sync": {"frames": {}, "interval": 0.18, "jitter": 0.03},
            "breathing": {"enabled": True, "speed": 1.0, "amplitude": 1.0},
        }
        with open(avatar_user_config_yaml, "w", encoding="utf-8") as f:
            yaml.dump(user_config, f)

        r = client.get("/api/avatar/config")
        assert r.status_code == 200
        assert r.json()["config"]["emotions"]["neutral"]["body"] == "user_override_body"


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


# ---------------------------------------------------------------------------
# Stack-Trace-Exposure (CodeQL py/stack-trace-exposure)
# ---------------------------------------------------------------------------


class TestErrorResponsesDoNotLeak:
    """Sicherstellt, dass Exception-Pfade keine internen Details ausgeben."""

    def test_get_config_swallows_yaml_error(self, avatar_assets, tmp_path):
        """Korrupte YAML -> generic Fehlermeldung, kein yaml.YAMLError-Detail."""
        from elder_berry.web.settings_dashboard import SettingsDashboard
        import elder_berry.web.avatar_editor as ae
        import elder_berry.avatar.avatar_config_loader as acl

        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(
            "emotions:\n  neutral: {body: ['unclosed",
            encoding="utf-8",
        )
        # USER auf nicht-existenten tmp-Pfad, damit resolve_active_config_path
        # garantiert auf DEFAULT (bad_yaml) faellt -- sonst koennte ein echtes
        # ~/.elder-berry/avatar_config.yaml auf der Dev-Maschine reinpfuschen.
        nonexistent_user = tmp_path / "nonexistent_user.yaml"

        original_assets = ae._ASSETS_DIR
        original_default = acl.DEFAULT_CONFIG_PATH
        original_user = acl.USER_CONFIG_PATH
        ae._ASSETS_DIR = avatar_assets
        acl.DEFAULT_CONFIG_PATH = bad_yaml
        acl.USER_CONFIG_PATH = nonexistent_user

        try:
            router = AudioRouter(local_available=True)
            dashboard = SettingsDashboard(audio_router=router)
            tc = TestClient(dashboard.app)

            r = tc.get("/api/avatar/config")
            assert r.status_code == 500
            body = r.json()
            assert "error" in body
            # Generic-Message: ja
            assert "nicht gelesen" in body["error"].lower()
            # Pfad-Detail oder yaml-Detail: nein
            assert str(bad_yaml) not in body["error"]
            assert "yaml" not in body["error"].lower()
            assert "line" not in body["error"].lower()
            assert "column" not in body["error"].lower()
        finally:
            ae._ASSETS_DIR = original_assets
            acl.DEFAULT_CONFIG_PATH = original_default
            acl.USER_CONFIG_PATH = original_user

    def test_save_config_swallows_io_error(self, avatar_assets, tmp_path):
        """IO-Fehler beim Schreiben -> generic Message, kein OSError-Detail.

        Save schreibt jetzt nach USER_CONFIG_PATH -- also USER unwritable
        machen, nicht DEFAULT.
        """
        from elder_berry.web.settings_dashboard import SettingsDashboard
        import elder_berry.web.avatar_editor as ae
        import elder_berry.avatar.avatar_config_loader as acl

        # USER-Pfad zeigt auf ein Verzeichnis -> open(..., 'w') wirft
        # IsADirectoryError. Der Editor erstellt zwar parent.mkdir(), aber
        # der Pfad selbst IST ein Verzeichnis, das Schreiben schlaegt fehl.
        unwritable_user = tmp_path / "as_directory"
        unwritable_user.mkdir()

        original_assets = ae._ASSETS_DIR
        original_user = acl.USER_CONFIG_PATH
        ae._ASSETS_DIR = avatar_assets
        acl.USER_CONFIG_PATH = unwritable_user

        try:
            router = AudioRouter(local_available=True)
            dashboard = SettingsDashboard(audio_router=router)
            tc = TestClient(dashboard.app)

            valid_config = {
                "emotions": {
                    "neutral": {
                        "body": "relaxed",
                        "eye_left": "eye_left_open",
                        "eye_right": "eye_right_open",
                        "mouth": "mouth_neutral_close",
                    }
                }
            }
            r = tc.put("/api/avatar/config", json={"config": valid_config})
            assert r.status_code == 500
            body = r.json()
            # Generic-Message
            assert "nicht gespeichert" in body["error"].lower()
            # Pfad nicht in der Antwort
            assert str(unwritable_user) not in body["error"]
            assert "errno" not in body["error"].lower()
        finally:
            ae._ASSETS_DIR = original_assets
            acl.USER_CONFIG_PATH = original_user
