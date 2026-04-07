"""AudioDashboard – Web-UI für Systemeinstellungen und Avatar-Editor.

Stellt eine FastAPI-App bereit mit:
- GET /             → HTML-Seite mit Audio-Toggle + Monitor-Dropdown + Sicherheit
- GET /api/audio    → aktueller Modus (JSON)
- POST /api/audio   → Modus setzen oder togglen (JSON)
- GET /api/monitors → verfügbare Monitore (JSON)
- POST /api/monitor → Monitor für Computer Use setzen (JSON)
- GET /api/allowed-senders  → Status (configured, count) – keine Klartext-IDs
- POST /api/allowed-senders → Sender setzen oder entfernen (JSON)
- GET /health               → Tower Health-Check (für Dashboard PWA)
- GET /avatar/editor        → Avatar-Editor Web-UI
- GET/PUT /api/avatar/*     → Avatar-Config CRUD + Asset-Serving
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

if TYPE_CHECKING:
    from elder_berry.actions.computer_use import ComputerUseController
    from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer
    from elder_berry.comms.audio_pipeline import AudioPipeline
    from elder_berry.core.audio_router import AudioRouter
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SettingDefinition:
    """Metadaten für ein Dashboard-Setting."""

    key: str
    label: str
    category: str
    type: Literal["text", "textarea", "select", "number", "secret"]
    source: Literal["secret_store", "derived"] = "secret_store"
    required: bool = False
    restart_required: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"
    placeholder: str | None = None
    help_text: str | None = None
    options: tuple[dict[str, str], ...] = ()
    secret: bool = False
    min_value: float | None = None
    max_value: float | None = None


_TEMPLATE_DIR = Path(__file__).parent / "templates"


class AudioDashboard:
    """Web-Dashboard für Audio-Routing und Computer-Use-Monitor-Auswahl.

    Parameters
    ----------
    audio_router : AudioRouter
        Der gemeinsame AudioRouter (thread-safe).
    computer_use : ComputerUseController | None
        Optionaler ComputerUseController für Monitor-Auswahl.
    host : str
        Bind-Adresse (Default: 0.0.0.0).
    port : int
        Port (Default: 8090).
    """

    ALLOWED_SENDERS_KEY = "matrix_allowed_senders"
    TIMEZONE_KEY = "user_timezone"
    STT_TIMEOUT_KEY = "stt_timeout"
    DEFAULT_STT_TIMEOUT = 120.0
    LLM_MODE_KEY = "llm_mode"
    DEFAULT_LLM_MODE = "api_preferred"
    DEFAULT_TIMEZONE = "Europe/Berlin"

    # Gängige Zeitzonen für das Dashboard-Dropdown
    AVAILABLE_TIMEZONES = [
        "Europe/Berlin",
        "Europe/Vienna",
        "Europe/Zurich",
        "Europe/London",
        "Europe/Paris",
        "Europe/Amsterdam",
        "Europe/Rome",
        "Europe/Madrid",
        "Europe/Warsaw",
        "Europe/Prague",
        "Europe/Istanbul",
        "Europe/Moscow",
        "US/Eastern",
        "US/Central",
        "US/Pacific",
        "Asia/Tokyo",
        "UTC",
    ]

    def __init__(
        self,
        audio_router: AudioRouter,
        computer_use: ComputerUseController | None = None,
        secret_store: SecretStore | None = None,
        avatar_renderer: LayeredSpriteRenderer | None = None,
        audio_pipeline: AudioPipeline | None = None,
        host: str = "0.0.0.0",
        port: int = 8090,
    ) -> None:
        self._router = audio_router
        self._computer_use = computer_use
        self._secret_store = secret_store
        self._audio_pipeline = audio_pipeline
        self._host = host
        self._port = port
        self._app = FastAPI(title="Elder-Berry Settings Dashboard")
        from fastapi.middleware.cors import CORSMiddleware
        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self._thread = None
        self._register_routes()

        # Avatar-Editor-Routen registrieren
        from elder_berry.web.avatar_editor import register_avatar_editor_routes
        register_avatar_editor_routes(self._app, renderer=avatar_renderer)

    @property
    def app(self) -> FastAPI:
        """FastAPI-App-Instanz (für Tests oder externe Einbindung)."""
        return self._app

    def _setting_definitions(self) -> list[SettingDefinition]:
        """Definiert die erste Registry für Phase 45."""
        timezone_options = tuple(
            {"value": tz, "label": tz} for tz in sorted(self.AVAILABLE_TIMEZONES)
        )
        llm_mode_options = (
            {"value": "api_preferred", "label": "API bevorzugt"},
            {"value": "local_preferred", "label": "Lokal bevorzugt"},
            {"value": "fallback_only", "label": "Nur Fallback/Lokal"},
        )
        return [
            SettingDefinition(
                key=self.ALLOWED_SENDERS_KEY,
                label="Erlaubte Sender",
                category="Matrix",
                type="textarea",
                restart_required=True,
                risk_level="high",
                placeholder="@lera:matrix.example.com\n@kollege:matrix.example.com",
                help_text="Eine Matrix-ID pro Zeile. Nur diese Sender dürfen Saleria steuern.",
            ),
            SettingDefinition(
                key=self.TIMEZONE_KEY,
                label="Zeitzone",
                category="Verhalten",
                type="select",
                required=True,
                options=timezone_options,
                help_text="Standard-Zeitzone für Erinnerungen, Briefings und zeitbezogene Antworten.",
            ),
            SettingDefinition(
                key=self.STT_TIMEOUT_KEY,
                label="STT-Timeout (Sekunden)",
                category="Audio",
                type="number",
                required=True,
                risk_level="medium",
                min_value=5,
                max_value=600,
                help_text="Wie lange auf Spracheingabe gewartet wird, bevor abgebrochen wird.",
            ),
            SettingDefinition(
                key=self.LLM_MODE_KEY,
                label="LLM-Modus",
                category="LLM",
                type="select",
                required=True,
                restart_required=True,
                risk_level="medium",
                options=llm_mode_options,
                help_text="Steuert, ob API-Modelle oder lokale Modelle bevorzugt verwendet werden.",
            ),
        ]

    def _setting_definition_map(self) -> dict[str, SettingDefinition]:
        return {
            definition.key: definition for definition in self._setting_definitions()
        }

    def _serialize_setting_definition(
        self, definition: SettingDefinition,
    ) -> dict[str, Any]:
        return {
            "key": definition.key,
            "label": definition.label,
            "category": definition.category,
            "type": definition.type,
            "source": definition.source,
            "required": definition.required,
            "restartRequired": definition.restart_required,
            "riskLevel": definition.risk_level,
            "placeholder": definition.placeholder,
            "helpText": definition.help_text,
            "options": list(definition.options),
            "secret": definition.secret,
            "minValue": definition.min_value,
            "maxValue": definition.max_value,
        }

    def _get_setting_value(self, key: str) -> str | float:
        if key == self.ALLOWED_SENDERS_KEY:
            raw = self._secret_store.get_or_none(key) if self._secret_store else None
            if not raw:
                return ""
            senders = [sender.strip() for sender in raw.split(",") if sender.strip()]
            return "\n".join(senders)
        if key == self.TIMEZONE_KEY:
            return self.get_timezone()
        if key == self.STT_TIMEOUT_KEY:
            return self._get_stt_timeout()
        if key == self.LLM_MODE_KEY:
            if self._secret_store:
                stored = self._secret_store.get_or_none(key)
                if stored in {"api_preferred", "local_preferred", "fallback_only"}:
                    return stored
            return self.DEFAULT_LLM_MODE
        raise KeyError(key)

    def _validate_setting_value(self, definition: SettingDefinition, value: Any) -> str | float:
        if definition.key == self.ALLOWED_SENDERS_KEY:
            if not isinstance(value, str):
                raise ValueError("Erlaubte Sender müssen Text sein.")
            senders = [line.strip() for line in value.replace(",", "\n").splitlines() if line.strip()]
            if any(not sender.startswith("@") for sender in senders):
                raise ValueError("Jeder Sender muss mit @ beginnen.")
            return "\n".join(senders)
        if definition.key == self.TIMEZONE_KEY:
            if not isinstance(value, str) or value not in self.AVAILABLE_TIMEZONES:
                raise ValueError("Ungültige Zeitzone.")
            return value
        if definition.key == self.STT_TIMEOUT_KEY:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                raise ValueError("STT-Timeout muss eine Zahl sein.") from None
            if definition.min_value is not None and numeric < definition.min_value:
                raise ValueError(f"STT-Timeout muss >= {definition.min_value} sein.")
            if definition.max_value is not None and numeric > definition.max_value:
                raise ValueError(f"STT-Timeout muss <= {definition.max_value} sein.")
            return numeric
        if definition.key == self.LLM_MODE_KEY:
            if value not in {"api_preferred", "local_preferred", "fallback_only"}:
                raise ValueError("Ungültiger LLM-Modus.")
            return str(value)
        raise ValueError("Unbekanntes Setting.")

    def _store_setting_value(self, definition: SettingDefinition, value: str | float) -> None:
        if not self._secret_store:
            raise RuntimeError("SecretStore nicht verfügbar")
        if definition.key == self.ALLOWED_SENDERS_KEY:
            senders = [line.strip() for line in str(value).splitlines() if line.strip()]
            self._secret_store.set(definition.key, ",".join(senders))
            return
        self._secret_store.set(definition.key, str(value))

    def _get_monitor_status(self) -> dict[str, Any]:
        if not self._computer_use:
            return {
                "available": False,
                "selected": None,
                "monitorCount": 0,
                "monitors": [],
            }
        monitors = self._computer_use.get_available_monitors()
        return {
            "available": True,
            "selected": self._computer_use.monitor_index,
            "monitorCount": len(monitors),
            "monitors": monitors,
        }

    def _register_routes(self) -> None:
        """Routen registrieren."""

        @self._app.get("/", response_class=HTMLResponse)
        async def dashboard():
            template_path = _TEMPLATE_DIR / "audio_dashboard.html"
            if template_path.exists():
                return HTMLResponse(template_path.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>Template nicht gefunden</h1>", status_code=500)

        @self._app.get("/api/audio")
        async def get_audio_mode():
            return JSONResponse({
                "mode": self._router.mode.value,
                "local_available": self._router.local_available,
                "play_local": self._router.should_play_local(),
            })

        @self._app.post("/api/audio")
        async def set_audio_mode(body: dict | None = None):
            if body and "mode" in body:
                from elder_berry.core.audio_router import AudioOutputMode
                try:
                    mode = AudioOutputMode(body["mode"])
                except ValueError:
                    return JSONResponse(
                        {"error": f"Ungültiger Modus: {body['mode']}"},
                        status_code=400,
                    )
                new_mode = self._router.set_mode(mode)
            else:
                new_mode = self._router.toggle()

            logger.info("Audio-Modus geändert: %s", new_mode.value)
            return JSONResponse({
                "mode": new_mode.value,
                "local_available": self._router.local_available,
                "play_local": self._router.should_play_local(),
            })

        # ----------------------------------------------------------
        # Monitor-Auswahl (Computer Use)
        # ----------------------------------------------------------

        @self._app.get("/api/monitors")
        async def get_monitors():
            if not self._computer_use:
                return JSONResponse({
                    "available": False,
                    "monitors": [],
                    "selected": 1,
                })
            monitors = self._computer_use.get_available_monitors()
            return JSONResponse({
                "available": True,
                "monitors": monitors,
                "selected": self._computer_use.monitor_index,
            })

        @self._app.post("/api/monitor")
        async def set_monitor(body: dict | None = None):
            if not self._computer_use:
                return JSONResponse(
                    {"error": "Computer Use nicht verfügbar."},
                    status_code=400,
                )
            if not body or "index" not in body:
                return JSONResponse(
                    {"error": "Parameter 'index' fehlt."},
                    status_code=400,
                )
            try:
                index = int(body["index"])
            except (ValueError, TypeError):
                return JSONResponse(
                    {"error": "Ungültiger Monitor-Index."},
                    status_code=400,
                )

            monitors = self._computer_use.get_available_monitors()
            valid_indices = {m["index"] for m in monitors}
            if index not in valid_indices:
                return JSONResponse(
                    {"error": f"Monitor {index} nicht verfügbar. "
                              f"Gültig: {sorted(valid_indices)}"},
                    status_code=400,
                )

            self._computer_use.monitor_index = index
            logger.info("Computer Use Monitor geändert: %d", index)
            return JSONResponse({
                "selected": index,
                "monitors": monitors,
            })

        # ----------------------------------------------------------
        # Allowed Senders (Matrix-Sicherheit)
        # ----------------------------------------------------------

        @self._app.get("/api/allowed-senders")
        async def get_allowed_senders():
            if not self._secret_store:
                return JSONResponse({
                    "available": False,
                    "configured": False,
                    "count": 0,
                })
            raw = self._secret_store.get_or_none(self.ALLOWED_SENDERS_KEY)
            if not raw:
                return JSONResponse({
                    "available": True,
                    "configured": False,
                    "count": 0,
                })
            senders = [s.strip() for s in raw.split(",") if s.strip()]
            return JSONResponse({
                "available": True,
                "configured": bool(senders),
                "count": len(senders),
            })

        @self._app.post("/api/allowed-senders")
        async def set_allowed_senders(body: dict | None = None):
            if not self._secret_store:
                return JSONResponse(
                    {"error": "SecretStore nicht verfügbar."},
                    status_code=400,
                )
            if not body:
                return JSONResponse(
                    {"error": "Request-Body fehlt."},
                    status_code=400,
                )

            # Entfernen-Aktion
            if body.get("action") == "remove":
                try:
                    self._secret_store.delete(self.ALLOWED_SENDERS_KEY)
                except Exception:
                    pass  # Key existiert nicht – OK
                logger.info("Allowed-Senders entfernt")
                return JSONResponse({
                    "configured": False,
                    "count": 0,
                })

            # Setzen-Aktion
            senders_raw = body.get("senders", "")
            if not isinstance(senders_raw, str) or not senders_raw.strip():
                return JSONResponse(
                    {"error": "Parameter 'senders' fehlt oder leer."},
                    status_code=400,
                )

            # Validierung: jede ID muss mit @ beginnen und : enthalten
            senders = [s.strip() for s in senders_raw.split(",") if s.strip()]
            invalid = [s for s in senders if not s.startswith("@") or ":" not in s]
            if invalid:
                return JSONResponse(
                    {"error": f"Ungültige Matrix-ID(s): {', '.join(invalid)}. "
                              "Format: @user:domain.com"},
                    status_code=400,
                )

            self._secret_store.set(
                self.ALLOWED_SENDERS_KEY,
                ",".join(senders),
            )
            logger.info("Allowed-Senders gesetzt: %d Sender", len(senders))
            return JSONResponse({
                "configured": True,
                "count": len(senders),
            })

        # ----------------------------------------------------------
        # Timezone
        # ----------------------------------------------------------

        @self._app.get("/api/timezone")
        async def get_timezone():
            tz = self.get_timezone()
            return JSONResponse({
                "timezone": tz,
                "available": sorted(self.AVAILABLE_TIMEZONES),
            })

        @self._app.post("/api/timezone")
        async def set_timezone(body: dict | None = None):
            if not self._secret_store:
                return JSONResponse(
                    {"error": "SecretStore nicht verfügbar."},
                    status_code=400,
                )
            if not body or "timezone" not in body:
                return JSONResponse(
                    {"error": "Parameter 'timezone' fehlt."},
                    status_code=400,
                )
            tz_name = body["timezone"]

            # Validierung: muss eine gültige IANA-Timezone sein
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(tz_name)
            except (KeyError, Exception):
                return JSONResponse(
                    {"error": f"Ungültige Zeitzone: {tz_name}"},
                    status_code=400,
                )

            self._secret_store.set(self.TIMEZONE_KEY, tz_name)
            logger.info("Zeitzone geändert: %s", tz_name)
            return JSONResponse({
                "timezone": tz_name,
                "available": sorted(self.AVAILABLE_TIMEZONES),
            })

        # ----------------------------------------------------------
        # STT-Timeout
        # ----------------------------------------------------------

        @self._app.get("/api/stt-timeout")
        async def get_stt_timeout():
            timeout = self._get_stt_timeout()
            return JSONResponse({
                "timeout": timeout,
                "available": self._audio_pipeline is not None,
            })

        @self._app.post("/api/stt-timeout")
        async def set_stt_timeout(body: dict | None = None):
            if not body or "timeout" not in body:
                return JSONResponse(
                    {"error": "Parameter 'timeout' fehlt."},
                    status_code=400,
                )
            try:
                timeout = float(body["timeout"])
                if not (5.0 <= timeout <= 600.0):
                    raise ValueError("Out of range")
            except (ValueError, TypeError):
                return JSONResponse(
                    {"error": f"Ungültiger Timeout: {body['timeout']}. "
                              "Erlaubt: 5–600 Sekunden."},
                    status_code=400,
                )

            # Live-Update auf AudioPipeline
            if self._audio_pipeline is not None:
                self._audio_pipeline.stt_timeout = timeout

            # Persistent speichern
            if self._secret_store:
                self._secret_store.set(self.STT_TIMEOUT_KEY, str(timeout))

            logger.info("STT-Timeout geändert: %.0fs", timeout)
            return JSONResponse({
                "timeout": timeout,
                "available": self._audio_pipeline is not None,
            })

        @self._app.get("/api/settings/schema")
        async def settings_schema():
            definitions = [
                self._serialize_setting_definition(definition)
                for definition in self._setting_definitions()
            ]
            return JSONResponse({"settings": definitions})

        @self._app.get("/api/settings/values")
        async def settings_values():
            values = {
                definition.key: self._get_setting_value(definition.key)
                for definition in self._setting_definitions()
            }
            return JSONResponse({"values": values})

        @self._app.get("/api/settings/status")
        async def settings_status():
            settings = self._setting_definitions()
            categories: dict[str, int] = {}
            configured = 0
            restart_required = []
            for definition in settings:
                categories[definition.category] = categories.get(definition.category, 0) + 1
                value = self._get_setting_value(definition.key)
                is_set = bool(str(value).strip()) if isinstance(value, str) else True
                if is_set:
                    configured += 1
                if definition.restart_required:
                    restart_required.append(definition.key)
            return JSONResponse({
                "configured": configured,
                "total": len(settings),
                "categories": categories,
                "llmMode": self._get_setting_value(self.LLM_MODE_KEY),
                "timezone": self._get_setting_value(self.TIMEZONE_KEY),
                "restartRequiredSettings": restart_required,
                "monitor": self._get_monitor_status(),
                "towerTopology": {
                    "dashboardRemote": True,
                    "towerLocal": True,
                },
            })

        @self._app.post("/api/settings/update")
        async def settings_update(body: dict = Body(...)):
            if not self._secret_store:
                return JSONResponse({"error": "SecretStore nicht verfügbar"}, status_code=503)
            if not isinstance(body, dict):
                return JSONResponse({"error": "JSON-Objekt erwartet"}, status_code=400)

            key = body.get("key")
            value = body.get("value")
            definition = self._setting_definition_map().get(str(key)) if key else None
            if not definition:
                return JSONResponse({"error": "Unbekanntes Setting"}, status_code=400)

            try:
                validated = self._validate_setting_value(definition, value)
                self._store_setting_value(definition, validated)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            except Exception as exc:
                logger.error("Settings-Update fehlgeschlagen (%s): %s", key, exc)
                return JSONResponse({"error": "Setting konnte nicht gespeichert werden"}, status_code=500)

            return JSONResponse({
                "status": "ok",
                "key": definition.key,
                "value": self._get_setting_value(definition.key),
                "restartRequired": definition.restart_required,
                "riskLevel": definition.risk_level,
            })

        @self._app.get("/health")
        async def health():
            import time
            import platform
            return JSONResponse({
                "status": "ok",
                "hostname": platform.node(),
                "saleria_running": True,
            })

    def _get_stt_timeout(self) -> float:
        """Gibt den konfigurierten STT-Timeout zurück."""
        if self._secret_store:
            raw = self._secret_store.get_or_none(self.STT_TIMEOUT_KEY)
            if raw:
                try:
                    return float(raw)
                except ValueError:
                    pass
        if self._audio_pipeline is not None:
            return self._audio_pipeline.stt_timeout
        return self.DEFAULT_STT_TIMEOUT

    def get_timezone(self) -> str:
        """Gibt die konfigurierte Zeitzone zurück (für externe Nutzung)."""
        if self._secret_store:
            tz = self._secret_store.get_or_none(self.TIMEZONE_KEY)
            if tz:
                return tz
        return self.DEFAULT_TIMEZONE

    def _is_port_free(self) -> bool:
        """Prüft ob der Port frei ist."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((self._host, self._port))
                return True
            except OSError:
                return False

    def start(self, retries: int = 5, retry_delay: float = 2.0) -> None:
        """Startet den Dashboard-Server in einem Hintergrund-Thread.

        Bei Update/Neustart kann der alte Prozess den Port noch kurz
        halten. Daher wird bis zu ``retries``-mal gewartet.
        """
        import threading
        import time
        import uvicorn

        for attempt in range(1, retries + 1):
            if self._is_port_free():
                break
            if attempt < retries:
                logger.info(
                    "Settings-Dashboard: Port %d belegt, Retry %d/%d in %.0fs …",
                    self._port, attempt, retries, retry_delay,
                )
                time.sleep(retry_delay)
        else:
            logger.warning(
                "Settings-Dashboard: Port %d nach %d Versuchen belegt – übersprungen.",
                self._port, retries,
            )
            return

        def _run():
            uvicorn.run(
                self._app,
                host=self._host,
                port=self._port,
                log_level="warning",
            )

        self._thread = threading.Thread(
            target=_run,
            name="settings-dashboard",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Settings-Dashboard gestartet: http://%s:%d", self._host, self._port,
        )

    def stop(self) -> None:
        """Stoppt den Server (Daemon-Thread endet mit Hauptprozess)."""
        self._thread = None
