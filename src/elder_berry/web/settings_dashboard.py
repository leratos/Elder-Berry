"""SettingsDashboard – Web-UI für Systemeinstellungen und Avatar-Editor.

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

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict

from fastapi import Body, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

if TYPE_CHECKING:
    from elder_berry.actions.computer_use import ComputerUseController
    from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer
    from elder_berry.comms.audio_pipeline import AudioPipeline
    from elder_berry.core.audio_router import AudioRouter
    from elder_berry.core.tower_agent import TowerAgent
    from elder_berry.core.secret_store import SecretStore
    from elder_berry.llm.router import LLMRouter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Secret Registry – vollständige Key-Definition für das Dashboard
# ---------------------------------------------------------------------------

_VALID_KEY_RE = re.compile(r"^[a-z0-9_]{1,128}$")
_MAX_VALUE_LENGTH = 4096


class SecretRegistryEntry(TypedDict):
    """Schema für einen Registry-Eintrag."""

    key: str
    label: str
    category: str
    sensitive: NotRequired[bool]            # Default: True
    requires_restart: NotRequired[bool]     # Default: False
    type: NotRequired[str]                  # "str" | "int" | "float" | "url"
    min: NotRequired[float | int]
    max: NotRequired[float | int]
    pattern: NotRequired[str]
    description: NotRequired[str]
    link: NotRequired[str]


SECRET_REGISTRY: list[SecretRegistryEntry] = [
    # --- KI & Sprache ---
    {
        "key": "anthropic_api_key", "label": "Claude API", "category": "KI & Sprache",
        "sensitive": True, "requires_restart": True,
        "description": "API Key für Anthropic Claude.",
        "link": "https://console.anthropic.com/",
    },
    {
        "key": "groq_api_key", "label": "Groq", "category": "KI & Sprache",
        "sensitive": True, "requires_restart": True,
        "description": "API Key für Groq (optional).",
        "link": "https://console.groq.com/",
    },
    {
        "key": "elevenlabs_api_key", "label": "ElevenLabs API", "category": "KI & Sprache",
        "sensitive": True, "requires_restart": True,
        "description": "API Key für ElevenLabs TTS.",
        "link": "https://elevenlabs.io/app/speech-synthesis",
    },
    {
        "key": "elevenlabs_voice_id", "label": "ElevenLabs Voice", "category": "KI & Sprache",
        "sensitive": False, "requires_restart": True,
        "description": "Voice-ID für ElevenLabs TTS.",
    },
    # --- Suche & Karten ---
    {
        "key": "brave_api_key", "label": "Brave Search", "category": "Suche & Karten",
        "sensitive": True, "requires_restart": True,
        "description": "API Key für Brave Web Search.",
        "link": "https://brave.com/search/api/",
    },
    {
        "key": "google_maps_api_key", "label": "Google Maps", "category": "Suche & Karten",
        "sensitive": True, "requires_restart": True,
        "description": "Google Directions API Key.",
        "link": "https://console.cloud.google.com/",
    },
    {
        "key": "google_oauth_tokens", "label": "Google OAuth", "category": "Suche & Karten",
        "sensitive": True, "requires_restart": True,
        "description": "Google Calendar OAuth Tokens (Legacy-Fallback).",
    },
    # --- Matrix ---
    {
        "key": "matrix_homeserver", "label": "Homeserver", "category": "Matrix",
        "sensitive": False, "requires_restart": True, "type": "url",
        "description": "URL des Matrix-Homeservers (z.B. https://matrix.example.com).",
    },
    {
        "key": "matrix_user_id", "label": "User ID", "category": "Matrix",
        "sensitive": False, "requires_restart": True,
        "description": "Matrix User-ID (z.B. @bot:example.com).",
    },
    {
        "key": "matrix_password", "label": "Passwort", "category": "Matrix",
        "sensitive": True, "requires_restart": True,
    },
    {
        "key": "matrix_access_token", "label": "Access Token", "category": "Matrix",
        "sensitive": True, "requires_restart": True,
    },
    {
        "key": "matrix_room_id", "label": "Room ID", "category": "Matrix",
        "sensitive": False, "requires_restart": True,
        "description": "Matrix-Raum-ID (z.B. !abc:example.com).",
    },
    {
        "key": "matrix_allowed_senders", "label": "Erlaubte Sender", "category": "Matrix",
        "sensitive": False, "requires_restart": True,
        "description": "Komma-getrennte Liste erlaubter Matrix-IDs.",
    },
    # --- E-Mail ---
    {
        "key": "email_user", "label": "Benutzer", "category": "E-Mail",
        "sensitive": False, "requires_restart": True,
    },
    {
        "key": "email_password", "label": "Passwort", "category": "E-Mail",
        "sensitive": True, "requires_restart": True,
    },
    {
        "key": "email_imap_host", "label": "IMAP Host", "category": "E-Mail",
        "sensitive": False, "requires_restart": True,
    },
    {
        "key": "email_imap_port", "label": "IMAP Port", "category": "E-Mail",
        "sensitive": False, "requires_restart": True,
        "type": "int", "min": 1, "max": 65535,
    },
    {
        "key": "smtp_host", "label": "SMTP Host", "category": "E-Mail",
        "sensitive": False, "requires_restart": True,
    },
    {
        "key": "smtp_port", "label": "SMTP Port", "category": "E-Mail",
        "sensitive": False, "requires_restart": True,
        "type": "int", "min": 1, "max": 65535,
    },
    # --- Nextcloud ---
    {
        "key": "nextcloud_url", "label": "URL", "category": "Nextcloud",
        "sensitive": False, "requires_restart": True, "type": "url",
    },
    {
        "key": "nextcloud_user", "label": "Benutzer", "category": "Nextcloud",
        "sensitive": False, "requires_restart": True,
    },
    {
        "key": "nextcloud_app_password", "label": "App-Passwort", "category": "Nextcloud",
        "sensitive": True, "requires_restart": True,
    },
    # --- Dienste ---
    {
        "key": "berry_gym_api_token", "label": "API Token", "category": "Dienste",
        "sensitive": True, "requires_restart": False,
        "description": "Fitness-Tracker API Token.",
    },
    {
        "key": "stirling_pdf_url", "label": "URL", "category": "Dienste",
        "sensitive": False, "requires_restart": False, "type": "url",
        "description": "Stirling PDF Service URL.",
    },
    {
        "key": "stirling_pdf_api_key", "label": "API Key", "category": "Dienste",
        "sensitive": True, "requires_restart": False,
    },
    # --- Infrastruktur ---
    {
        "key": "robot_host", "label": "RPi5 Host", "category": "Infrastruktur",
        "sensitive": False, "requires_restart": False,
        "description": "IP/Hostname des RPi5.",
    },
    {
        "key": "tower_host", "label": "Tower Host", "category": "Infrastruktur",
        "sensitive": False, "requires_restart": False,
        "description": "IP/Hostname des Towers.",
    },
    # --- Wetter & Standort ---
    {
        "key": "weather_city", "label": "Stadt", "category": "Wetter & Standort",
        "sensitive": False, "requires_restart": False,
    },
    {
        "key": "weather_latitude", "label": "Breitengrad", "category": "Wetter & Standort",
        "sensitive": False, "requires_restart": False,
        "type": "float", "min": -90.0, "max": 90.0,
    },
    {
        "key": "weather_longitude", "label": "Längengrad", "category": "Wetter & Standort",
        "sensitive": False, "requires_restart": False,
        "type": "float", "min": -180.0, "max": 180.0,
    },
]

# Schnellzugriff: key → Entry
_REGISTRY_BY_KEY: dict[str, SecretRegistryEntry] = {e["key"]: e for e in SECRET_REGISTRY}


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


class SettingsDashboard:
    """Web-Dashboard für Systemeinstellungen, Audio-Routing und Computer-Use.

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
        tower_agent: TowerAgent | None = None,
        llm_router: LLMRouter | None = None,
        host: str = "0.0.0.0",
        port: int = 8090,
    ) -> None:
        self._router = audio_router
        self._computer_use = computer_use
        self._secret_store = secret_store
        self._audio_pipeline = audio_pipeline
        self._tower_agent = tower_agent
        self._llm_router = llm_router
        self._host = host
        self._port = port
        self._app = FastAPI(title="Elder-Berry Settings Dashboard")

        # --- CORS: Origins aus SecretStore oder nur localhost ---
        from fastapi.middleware.cors import CORSMiddleware
        allowed_origins = [
            f"http://localhost:{port}",
            f"http://127.0.0.1:{port}",
        ]
        if secret_store:
            dashboard_origin = secret_store.get_or_none("dashboard_origin")
            if dashboard_origin:
                allowed_origins.append(dashboard_origin)
        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type"],
            allow_credentials=False,
        )

        # --- Security Response Headers ---
        from starlette.middleware.base import BaseHTTPMiddleware

        class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                response = await call_next(request)
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["X-Frame-Options"] = "DENY"
                response.headers["Referrer-Policy"] = "no-referrer"
                response.headers["Content-Security-Policy"] = (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline';"
                )
                return response

        self._app.add_middleware(_SecurityHeadersMiddleware)

        # --- Globaler Exception-Handler für Fehler-Isolation ---
        @self._app.exception_handler(Exception)
        async def _global_exception_handler(request: Request, exc: Exception):
            logger.exception("Unbehandelte Ausnahme in %s", request.url.path)
            return JSONResponse(
                {"error": "Interner Fehler – Details im Log."},
                status_code=500,
            )

        self._write_lock = asyncio.Lock()
        self._change_callbacks: dict[str, list[Any]] = {}
        self._secrets_meta: dict[str, dict[str, str]] = {}
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

    @staticmethod
    def _validate_secret(key: str, value: str) -> None:
        """Zentrale Validierung für Secret-Keys und -Werte.

        Raises
        ------
        ValueError
            Bei ungültigem Key oder Wert.
        """
        # Key-Format
        if not _VALID_KEY_RE.match(key):
            raise ValueError(
                "Key darf nur Kleinbuchstaben, Ziffern und Unterstriche enthalten "
                "(max. 128 Zeichen)."
            )
        # Value leer
        if not value or not value.strip():
            raise ValueError("Wert darf nicht leer sein.")
        # Value zu lang
        if len(value) > _MAX_VALUE_LENGTH:
            raise ValueError(
                f"Wert zu lang (max. {_MAX_VALUE_LENGTH} Zeichen)."
            )
        # Typ-spezifische Validierung anhand Registry
        entry = _REGISTRY_BY_KEY.get(key)
        if not entry:
            return  # Unbekannter Key – keine Typ-Validierung
        entry_type = entry.get("type", "str")
        if entry_type == "int":
            try:
                num = int(value)
            except ValueError:
                raise ValueError(f"Wert für '{key}' muss eine Ganzzahl sein.") from None
            if "min" in entry and num < entry["min"]:
                raise ValueError(f"Wert für '{key}' muss >= {entry['min']} sein.")
            if "max" in entry and num > entry["max"]:
                raise ValueError(f"Wert für '{key}' muss <= {entry['max']} sein.")
        elif entry_type == "float":
            try:
                num_f = float(value)
            except ValueError:
                raise ValueError(f"Wert für '{key}' muss eine Zahl sein.") from None
            if "min" in entry and num_f < entry["min"]:
                raise ValueError(f"Wert für '{key}' muss >= {entry['min']} sein.")
            if "max" in entry and num_f > entry["max"]:
                raise ValueError(f"Wert für '{key}' muss <= {entry['max']} sein.")
        elif entry_type == "url":
            if not value.startswith(("http://", "https://")):
                raise ValueError(
                    f"Wert für '{key}' muss mit http:// oder https:// beginnen."
                )
        if "pattern" in entry:
            if not re.match(entry["pattern"], value):
                raise ValueError(f"Wert für '{key}' entspricht nicht dem erwarteten Format.")

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

    async def _get_monitor_status(self) -> dict[str, Any]:
        # Remote: Tower via SSH-Tunnel abfragen
        if self._tower_agent:
            try:
                data = await self._tower_agent.get_monitors()
                data["source"] = "tower"
                return data
            except Exception as e:
                logger.debug("Tower Monitor-Status nicht abrufbar: %s", e)
                return {
                    "available": False,
                    "selected": None,
                    "monitorCount": 0,
                    "monitors": [],
                    "source": "tower",
                    "error": str(e),
                }
        # Lokal: ComputerUseController direkt abfragen
        if self._computer_use:
            monitors = self._computer_use.get_available_monitors()
            return {
                "available": True,
                "selected": self._computer_use.monitor_index,
                "monitorCount": len(monitors),
                "monitors": monitors,
                "source": "local",
            }
        return {
            "available": False,
            "selected": None,
            "monitorCount": 0,
            "monitors": [],
            "source": "none",
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
            # Remote: Tower via SSH-Tunnel abfragen
            if self._tower_agent:
                try:
                    data = await self._tower_agent.get_monitors()
                    return JSONResponse(data)
                except Exception as e:
                    logger.warning("Tower Monitor-Abfrage fehlgeschlagen: %s", e)
                    return JSONResponse({
                        "available": False,
                        "monitors": [],
                        "selected": 1,
                        "error": "Tower nicht erreichbar",
                    })

            # Lokal: ComputerUseController direkt
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

            # Remote: an Tower weiterleiten
            if self._tower_agent:
                try:
                    data = await self._tower_agent.set_monitor(index)
                    logger.info("Tower Monitor geändert: %d", index)
                    return JSONResponse(data)
                except Exception as e:
                    logger.warning("Tower Monitor-Setzen fehlgeschlagen: %s", e)
                    return JSONResponse(
                        {"error": f"Tower nicht erreichbar: {e}"},
                        status_code=502,
                    )

            # Lokal
            if not self._computer_use:
                return JSONResponse(
                    {"error": "Computer Use nicht verfügbar."},
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
                "monitor": await self._get_monitor_status(),
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
                async with self._write_lock:
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

        @self._app.get("/api/settings/export")
        async def settings_export():
            """Exportiert alle nicht-sensitiven Werte + Namen gesetzter sensitiver Keys."""
            from datetime import datetime, timezone
            non_sensitive: dict[str, str] = {}
            sensitive_keys_set: list[str] = []
            for entry in SECRET_REGISTRY:
                key = entry["key"]
                is_sensitive = entry.get("sensitive", True)
                value = self._secret_store.get_or_none(key) if self._secret_store else None
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

        # ----------------------------------------------------------
        # Secrets-API (Registry-basiert)
        # ----------------------------------------------------------

        @self._app.get("/api/secrets/status")
        async def secrets_status():
            if not self._secret_store:
                return JSONResponse({"available": False, "categories": []})
            categories: dict[str, list[dict[str, Any]]] = {}
            for entry in SECRET_REGISTRY:
                cat = entry["category"]
                is_set = self._secret_store.get_or_none(entry["key"]) is not None
                item = {
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
                meta = self._secrets_meta.get(entry["key"])
                if meta and "updated_at" in meta:
                    item["updated_at"] = meta["updated_at"]
                categories.setdefault(cat, []).append(item)
            result = [
                {"name": name, "keys": keys}
                for name, keys in categories.items()
            ]
            return JSONResponse({"available": True, "categories": result})

        @self._app.post("/api/secrets/set")
        async def secrets_set(request: Request, body: dict = Body(...)):
            if not self._secret_store:
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
                self._validate_secret(key, value)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)

            entry = _REGISTRY_BY_KEY.get(key)
            async with self._write_lock:
                self._secret_store.set(key, value)
            self._record_meta(key)
            self._notify_change(key, value)
            client_host = request.client.host if request.client else "unbekannt"
            logger.info("AUDIT: secret '%s' gesetzt von %s", key, client_host)
            return JSONResponse({
                "success": True,
                "key": key,
                "requires_restart": entry.get("requires_restart", False) if entry else False,
            })

        @self._app.post("/api/secrets/delete")
        async def secrets_delete(request: Request, body: dict = Body(...)):
            if not self._secret_store:
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
            # Prüfen ob Key existiert
            if self._secret_store.get_or_none(key) is None:
                return JSONResponse(
                    {"error": f"Key '{key}' nicht vorhanden."},
                    status_code=404,
                )
            async with self._write_lock:
                self._secret_store.delete(key)
            client_host = request.client.host if request.client else "unbekannt"
            logger.info("AUDIT: secret '%s' gelöscht von %s", key, client_host)
            return JSONResponse({"success": True, "key": key})

        # ----------------------------------------------------------
        # LLM-API (Status + Mode-Umschalter)
        # ----------------------------------------------------------

        @self._app.get("/api/llm/status")
        async def llm_status():
            if not self._llm_router:
                return JSONResponse({
                    "available": False,
                    "mode": None,
                    "active_backend": "none",
                    "primary": {"name": None, "available": False},
                    "fallback": {"name": None, "available": False},
                })
            return JSONResponse({
                "available": True,
                "mode": self._llm_router.mode,
                "active_backend": self._llm_router.active_backend,
                "primary": {
                    "name": self._llm_router.primary_name,
                    "available": self._llm_router.primary_available,
                },
                "fallback": {
                    "name": self._llm_router.fallback_name,
                    "available": self._llm_router.fallback_available,
                },
            })

        @self._app.post("/api/llm/mode")
        async def llm_mode(request: Request, body: dict = Body(...)):
            if not self._llm_router:
                return JSONResponse(
                    {"error": "LLMRouter nicht verfügbar."},
                    status_code=503,
                )
            new_mode = body.get("mode")
            if new_mode not in ("api_preferred", "local_only"):
                return JSONResponse(
                    {"error": f"Ungültiger Modus: {new_mode}. "
                              "Erlaubt: api_preferred, local_only"},
                    status_code=400,
                )
            self._llm_router.mode = new_mode
            # Persistieren im SecretStore
            if self._secret_store:
                async with self._write_lock:
                    self._secret_store.set(self.LLM_MODE_KEY, new_mode)
            client_host = request.client.host if request.client else "unbekannt"
            logger.info(
                "AUDIT: LLM-Modus auf '%s' gesetzt von %s", new_mode, client_host,
            )
            return JSONResponse({
                "mode": self._llm_router.mode,
                "active_backend": self._llm_router.active_backend,
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

    def on_change(self, key: str, callback: Any) -> None:
        """Registriert einen Callback für Änderungen an einem Key.

        Callback-Signatur: callback(new_value: str) -> None
        """
        self._change_callbacks.setdefault(key, []).append(callback)

    def _notify_change(self, key: str, new_value: str) -> None:
        """Ruft alle registrierten Callbacks für einen Key auf."""
        for cb in self._change_callbacks.get(key, []):
            try:
                cb(new_value)
            except Exception as exc:
                logger.error("Callback-Fehler für '%s': %s", key, exc)

    def _record_meta(self, key: str) -> None:
        """Speichert den Änderungs-Timestamp für einen Key."""
        from datetime import datetime, timezone
        self._secrets_meta[key] = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _is_port_free(self) -> bool:
        """Prüft ob der Port frei ist."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((self._host, self._port))
                return True
            except OSError:
                return False

    def start(self, retries: int = 10, retry_delay: float = 3.0) -> None:
        """Startet den Dashboard-Server in einem Hintergrund-Thread.

        Bei Update/Neustart kann der alte Prozess den Port noch kurz
        halten (TIME_WAIT). Daher wird bis zu ``retries``-mal gewartet.
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
            import asyncio
            import socket as _sock

            # Socket mit SO_REUSEADDR: Port sofort wiederverwendbar nach Prozess-Ende
            sock = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            sock.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
            sock.bind((self._host, self._port))

            config = uvicorn.Config(
                self._app,
                host=self._host,
                port=self._port,
                log_level="warning",
            )
            server = uvicorn.Server(config)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server.serve(sockets=[sock]))

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
