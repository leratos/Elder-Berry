"""AvatarEditor – FastAPI-Endpoints für den Avatar-Editor.

Stellt Endpoints bereit für:
- GET  /avatar/editor                       → HTML-Editor-UI
- GET  /api/avatar/assets                   → Liste aller Sprites pro Kategorie
- GET  /api/avatar/assets/{category}/{name} → Sprite-PNG servieren
- GET  /api/avatar/config                   → aktuelle YAML-Config als JSON
- PUT  /api/avatar/config                   → Config speichern (validiert)
- POST /api/avatar/reload                   → Hot-Reload triggern
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.responses import Response

if TYPE_CHECKING:
    from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

from elder_berry.avatar import avatar_config_loader
from elder_berry.character.base import Emotion

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_ASSETS_DIR = Path(__file__).parent.parent / "avatar" / "assets"

# Erlaubte Asset-Kategorien → Unterordner
_CATEGORIES = {"body", "eye", "mouth", "effect"}

# Erlaubte Asset-Namen: ASCII-Bezeichner ohne Punkte/Slashes/Sonderzeichen.
# Strikter Allowlist-Check vor dem Path-Build -- Defense-in-Depth zusaetzlich
# zu Path(name).name in get_asset(). Behebt CodeQL py/path-injection durch
# Allowlist statt Sanitizer.
_VALID_ASSET_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Alle Emotion-Namen
_EMOTION_NAMES = [e.value for e in Emotion]


def register_avatar_editor_routes(
    app: FastAPI,
    renderer: LayeredSpriteRenderer | None = None,
) -> None:
    """Registriert alle Avatar-Editor-Routen auf der gegebenen FastAPI-App.

    Parameters
    ----------
    app : FastAPI
        Die FastAPI-Instanz (z.B. SettingsDashboard.app).
    renderer : LayeredSpriteRenderer | None
        Optionaler Renderer für Hot-Reload. Ohne Renderer ist
        der Reload-Button deaktiviert.
    """

    @app.get("/avatar/editor", response_class=HTMLResponse)
    async def avatar_editor() -> HTMLResponse:
        template_path = _TEMPLATE_DIR / "avatar_editor.html"
        if template_path.exists():
            return HTMLResponse(template_path.read_text(encoding="utf-8"))
        return HTMLResponse(
            "<h1>Avatar-Editor Template nicht gefunden</h1>", status_code=500
        )

    @app.get("/api/avatar/assets")
    async def list_assets() -> JSONResponse:
        """Gibt alle verfügbaren Sprites pro Kategorie zurück."""
        result: dict[str, list[str]] = {}
        for category in sorted(_CATEGORIES):
            subdir = _ASSETS_DIR / category
            if not subdir.exists():
                result[category] = []
                continue
            result[category] = sorted(p.stem for p in subdir.glob("*.png"))
        return JSONResponse(result)

    @app.get("/api/avatar/assets/{category}/{name}")
    async def get_asset(category: str, name: str) -> Response:
        """Serviert eine Sprite-PNG-Datei."""
        if category not in _CATEGORIES:
            return JSONResponse(
                {"error": f"Ungültige Kategorie: {category}"},
                status_code=400,
            )

        # Layer 1 -- Allowlist-Check: nur ASCII-Bezeichner. Wirft Punkte,
        # Slashes, Sonderzeichen direkt mit 400 raus.
        if not _VALID_ASSET_NAME_RE.match(name):
            return JSONResponse(
                {"error": f"Ungültiger Asset-Name: {name}"},
                status_code=400,
            )

        # Layer 2 -- Resolve + is_relative_to(): finaler Pfad muss unter
        # _ASSETS_DIR liegen, nachdem Symlinks aufgeloest wurden. Behebt
        # CodeQL py/path-injection (#304); Layer 1 alleine wurde von der
        # Query nicht als Sanitizer erkannt.
        assets_root = _ASSETS_DIR.resolve()
        candidate = (_ASSETS_DIR / category / f"{name}.png").resolve()
        if not candidate.is_relative_to(assets_root):
            logger.warning(
                "Path-Traversal-Versuch geblockt: category=%s name=%s",
                category,
                name,
            )
            return JSONResponse(
                {"error": f"Ungültiger Asset-Name: {name}"},
                status_code=400,
            )
        file_path = candidate

        if not file_path.exists() or not file_path.is_file():
            return JSONResponse(
                {"error": f"Asset nicht gefunden: {category}/{name}"},
                status_code=404,
            )

        return FileResponse(
            path=str(file_path),
            media_type="image/png",
        )

    @app.get("/api/avatar/config")
    async def get_config() -> JSONResponse:
        """Gibt die aktuelle YAML-Config als JSON zurück."""
        if not avatar_config_loader.DEFAULT_CONFIG_PATH.exists():
            return JSONResponse(
                {"error": "avatar_config.yaml nicht gefunden"},
                status_code=404,
            )

        try:
            with open(avatar_config_loader.DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            logger.exception(
                "Avatar-Config konnte nicht gelesen werden: %s",
                avatar_config_loader.DEFAULT_CONFIG_PATH,
            )
            return JSONResponse(
                {"error": "Avatar-Config konnte nicht gelesen werden."},
                status_code=500,
            )

        return JSONResponse(
            {
                "config": data,
                "emotions": _EMOTION_NAMES,
                "reload_available": renderer is not None,
            }
        )

    @app.put("/api/avatar/config")
    async def save_config(body: dict[str, Any] | None = None) -> JSONResponse:
        """Speichert die Config nach Validierung als YAML."""
        if not body or "config" not in body:
            return JSONResponse(
                {"error": "Request-Body muss 'config'-Feld enthalten."},
                status_code=400,
            )

        config_data = body["config"]

        # Validierung: emotions müssen vorhanden sein
        validation_error = _validate_config(config_data)
        if validation_error:
            return JSONResponse(
                {"error": validation_error},
                status_code=400,
            )

        # YAML schreiben
        try:
            with open(
                avatar_config_loader.DEFAULT_CONFIG_PATH, "w", encoding="utf-8"
            ) as f:
                yaml.dump(
                    config_data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
        except Exception:
            logger.exception(
                "Avatar-Config konnte nicht gespeichert werden: %s",
                avatar_config_loader.DEFAULT_CONFIG_PATH,
            )
            return JSONResponse(
                {"error": "Avatar-Config konnte nicht gespeichert werden."},
                status_code=500,
            )

        logger.info("Avatar-Config gespeichert via Web-Editor")
        return JSONResponse({"saved": True})

    @app.post("/api/avatar/reload")
    async def reload_config() -> JSONResponse:
        """Triggert Hot-Reload der Config im Renderer."""
        if renderer is None:
            return JSONResponse(
                {"error": "Kein Renderer verfügbar – Hot-Reload nicht möglich."},
                status_code=400,
            )

        success = renderer.reload_config()
        if success:
            return JSONResponse({"reloaded": True})
        return JSONResponse(
            {"error": "Fehler beim Reload – siehe Server-Log."},
            status_code=500,
        )


def _validate_config(data: Any) -> str | None:
    """Validiert die Config-Daten. Gibt Fehlertext oder None zurück.

    Akzeptiert Any, weil yaml.safe_load() beliebige Typen zurueckliefern
    kann (incl. None bei leerem File). Der erste Check enge das ein.
    """
    if not isinstance(data, dict):
        return "Config muss ein Dictionary sein."

    # emotions prüfen
    emotions = data.get("emotions")
    if not isinstance(emotions, dict) or not emotions:
        return "Config muss mindestens eine Emotion enthalten."

    valid_emotions = {e.value for e in Emotion}
    for emotion_name, layers in emotions.items():
        if emotion_name not in valid_emotions:
            return f"Unbekannte Emotion: {emotion_name}"
        if not isinstance(layers, dict):
            return f"Emotion '{emotion_name}' muss ein Dictionary sein."
        for required_key in ("body", "eye_left", "eye_right", "mouth"):
            if required_key not in layers:
                return f"Emotion '{emotion_name}': Feld '{required_key}' fehlt."

    # lip_sync prüfen
    lip_sync = data.get("lip_sync")
    if lip_sync:
        if not isinstance(lip_sync, dict):
            return "lip_sync muss ein Dictionary sein."
        frames = lip_sync.get("frames")
        if frames and not isinstance(frames, dict):
            return "lip_sync.frames muss ein Dictionary sein."

    # breathing prüfen
    breathing = data.get("breathing")
    if breathing and not isinstance(breathing, dict):
        return "breathing muss ein Dictionary sein."

    return None
