"""Secrets-API – FastAPI-Endpoints für SecretStore-Keys.

Wird von SettingsDashboard eingebunden via ``register_secrets_routes()``.

Die Registry-Daten (``SECRET_REGISTRY``, ``SecretRegistryEntry``,
``_REGISTRY_BY_KEY``, ``validate_secret``) leben in
``elder_berry.web.secrets_registry`` und werden hier nur re-exportiert,
damit Tests, die historisch aus ``secrets_api`` importieren, weiter
funktionieren. Die Auslagerung bricht den ehemaligen Modul-Zyklus
zwischen ``secrets_api`` und ``settings_dashboard``
(CodeQL ``py/unsafe-cyclic-import``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import Body, Request
from fastapi.responses import JSONResponse

from elder_berry.core.log_sanitize import safe_log
from elder_berry.web.secrets_registry import (
    SECRET_REGISTRY,
    SecretRegistryEntry,
    _MAX_VALUE_LENGTH,
    _REGISTRY_BY_KEY,
    _VALID_KEY_RE,
    validate_secret,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


class _DashboardLike(Protocol):
    """Strukturelles Subset von ``SettingsDashboard``, das die Secrets-Routen
    benötigen. Vermeidet einen Modul-Zyklus mit ``settings_dashboard``
    (CodeQL ``py/cyclic-import``).
    """

    _secret_store: Any
    _secrets_meta: dict[str, dict[str, str]]
    _write_lock: asyncio.Lock

    def _record_meta(self, key: str) -> None: ...
    def _notify_change(self, key: str, new_value: str) -> None: ...

__all__ = [
    "SECRET_REGISTRY",
    "SecretRegistryEntry",
    "_MAX_VALUE_LENGTH",
    "_REGISTRY_BY_KEY",
    "_VALID_KEY_RE",
    "register_secrets_routes",
    "validate_secret",
]


def register_secrets_routes(app: FastAPI, dashboard: _DashboardLike) -> None:
    """Registriert die Secrets-API-Endpoints auf der FastAPI-App."""

    @app.get("/api/secrets/status")
    async def secrets_status():
        if not dashboard._secret_store:
            return JSONResponse({"available": False, "categories": []})
        categories: dict[str, list[dict[str, Any]]] = {}
        for entry in SECRET_REGISTRY:
            cat = entry["category"]
            is_set = dashboard._secret_store.get_or_none(entry["key"]) is not None
            item: dict[str, Any] = {
                "key": entry["key"],
                "label": entry["label"],
                "is_set": is_set,
                "sensitive": entry.get("sensitive", True),
                "requires_restart": entry.get("requires_restart", False),
            }
            if entry.get("description"):
                item["description"] = entry["description"]
            if entry.get("link"):
                item["link"] = entry["link"]
            meta = dashboard._secrets_meta.get(entry["key"])
            if meta and "updated_at" in meta:
                item["updated_at"] = meta["updated_at"]
            categories.setdefault(cat, []).append(item)
        result = [
            {"name": name, "keys": keys}
            for name, keys in categories.items()
        ]
        return JSONResponse({"available": True, "categories": result})

    @app.post("/api/secrets/set")
    async def secrets_set(request: Request, body: dict = Body(...)):
        if not dashboard._secret_store:
            return JSONResponse(
                {"error": "SecretStore nicht verfügbar."},
                status_code=503,
            )
        key = body.get("key")
        value = body.get("value")
        if not key or not isinstance(key, str):
            return JSONResponse(
                {"error": "Parameter 'key' fehlt."},
                status_code=400,
            )
        if value is None or not isinstance(value, str):
            return JSONResponse(
                {"error": "Parameter 'value' fehlt oder ist kein String."},
                status_code=400,
            )
        try:
            validate_secret(key, value)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        entry = _REGISTRY_BY_KEY.get(key)
        async with dashboard._write_lock:
            dashboard._secret_store.set(key, value)
        dashboard._record_meta(key)
        dashboard._notify_change(key, value)
        client_host = request.client.host if request.client else "unbekannt"
        logger.info(
            "AUDIT: secret '%s' gesetzt von %s",
            safe_log(key), safe_log(client_host),
        )
        return JSONResponse({
            "success": True,
            "key": key,
            "requires_restart": entry.get("requires_restart", False) if entry else False,
        })

    @app.post("/api/secrets/delete")
    async def secrets_delete(request: Request, body: dict = Body(...)):
        if not dashboard._secret_store:
            return JSONResponse(
                {"error": "SecretStore nicht verfügbar."},
                status_code=503,
            )
        key = body.get("key")
        if not key or not isinstance(key, str):
            return JSONResponse(
                {"error": "Parameter 'key' fehlt."},
                status_code=400,
            )
        if dashboard._secret_store.get_or_none(key) is None:
            return JSONResponse(
                {"error": f"Key '{key}' nicht vorhanden."},
                status_code=404,
            )
        async with dashboard._write_lock:
            dashboard._secret_store.delete(key)
        client_host = request.client.host if request.client else "unbekannt"
        logger.info(
            "AUDIT: secret '%s' gelöscht von %s",
            safe_log(key), safe_log(client_host),
        )
        return JSONResponse({"success": True, "key": key})

    @app.get("/api/settings/export")
    async def settings_export():
        """Exportiert alle nicht-sensitiven Werte + Namen gesetzter sensitiver Keys."""
        from datetime import datetime, timezone
        non_sensitive: dict[str, str] = {}
        sensitive_keys_set: list[str] = []
        for entry in SECRET_REGISTRY:
            key = entry["key"]
            is_sensitive = entry.get("sensitive", True)
            value = dashboard._secret_store.get_or_none(key) if dashboard._secret_store else None
            if is_sensitive:
                if value is not None:
                    sensitive_keys_set.append(key)
            else:
                if value is not None:
                    non_sensitive[key] = value
        return JSONResponse({
            "export_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "non_sensitive": non_sensitive,
            "sensitive_keys_set": sensitive_keys_set,
        })
