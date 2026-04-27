"""HarmonyMockServer -- Lokal gehosteter Ersatz fuer Logitech-Konfigurations-Server.

Antwortet auf Harmony-Hub-Anfragen mit dem gespeicherten Backup-JSON.
Ermoeglicht Konfigurationsaenderungen ohne Logitech-Cloud.

Deployment: Rootserver, Port 8765, hinter Nginx mit SSL.
Config-Datei: /etc/elder-berry/harmony_config.json (auf Rootserver)

Endpunkte (aus Reverse-Engineering des Logitech-Protokolls):
  POST /account/getConfig     → gibt harmony_config_backup.json zurueck
  POST /account/saveConfig    → speichert neue Konfiguration lokal
  POST /account/getDeviceInfo → IR-Code-Lookup (aus gespeicherter DB)

Plattformhinweis: Laeuft auf dem Rootserver (Linux), nicht auf RPi5 oder Tower.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("/etc/elder-berry/harmony_config.json")


def create_app(config_path: Path = DEFAULT_CONFIG_PATH) -> FastAPI:
    """Erstellt die FastAPI-App mit konfigurierbarem Config-Pfad."""

    app = FastAPI(title="Harmony Mock Server", version="0.1.0")

    @app.post("/account/getConfig")
    async def get_config(request: Request) -> JSONResponse:
        """Liefert gespeicherte Hub-Konfiguration."""
        if not config_path.exists():
            return JSONResponse(
                {"error": "Config not found"},
                status_code=404,
            )
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return JSONResponse(data)
        except json.JSONDecodeError as e:
            logger.error("Config malformed: %s", e)
            return JSONResponse(
                {"error": "Config malformed"},
                status_code=500,
            )

    @app.post("/account/saveConfig")
    async def save_config(request: Request) -> JSONResponse:
        """Speichert geaenderte Konfiguration lokal."""
        try:
            body = await request.body()
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return JSONResponse(
                {"error": "Invalid JSON"},
                status_code=400,
            )

        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Config gespeichert: %s", config_path)
            return JSONResponse({"status": "ok"})
        except Exception:
            logger.exception("Config speichern fehlgeschlagen: %s", config_path)
            return JSONResponse(
                {"error": "Speichern fehlgeschlagen."},
                status_code=500,
            )

    @app.post("/account/getDeviceInfo")
    async def get_device_info(request: Request) -> JSONResponse:
        """IR-Code-Lookup aus lokaler Datenbank."""
        if not config_path.exists():
            return JSONResponse(
                {"error": "Config not found"},
                status_code=404,
            )

        try:
            body = await request.body()
            query = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            return JSONResponse(
                {"error": "Invalid JSON"},
                status_code=400,
            )

        device_name = query.get("device", "").lower()
        if not device_name:
            return JSONResponse(
                {"error": "Missing 'device' field"},
                status_code=400,
            )

        config_data = json.loads(config_path.read_text(encoding="utf-8"))
        devices = config_data.get("device", [])

        for dev in devices:
            if dev.get("label", "").lower() == device_name:
                return JSONResponse(dev)

        return JSONResponse(
            {"error": f"Device '{device_name}' not found"},
            status_code=404,
        )

    return app


# Standalone-Start
app = create_app()
