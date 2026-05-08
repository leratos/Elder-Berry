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

Secrets-API, LLM-API und Security-Middleware sind in eigene Module ausgelagert:
- web/secrets_api.py
- web/llm_api.py
- web/security_middleware.py
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.responses import Response
from fastapi.staticfiles import StaticFiles

# Registry-Daten kommen aus dem Leaf-Modul secrets_registry, nicht mehr
# aus secrets_api. Damit ist der frühere Modul-Zyklus zwischen
# settings_dashboard und secrets_api aufgelöst (CodeQL
# py/cyclic-import). secrets_api/llm_api nutzen ein lokales Protocol
# statt eines TYPE_CHECKING-Imports, damit der Zyklus auch in den
# Annotationen aufgebrochen ist.
from elder_berry.core.log_sanitize import safe_log
from elder_berry.core.secret_store import SecretNotFoundError
from elder_berry.web.llm_api import register_llm_routes
from elder_berry.web.plugins_api import register_plugins_routes
from elder_berry.web.secrets_api import register_secrets_routes
from elder_berry.web.secrets_registry import (
    SecretRegistryEntry,
    _REGISTRY_BY_KEY,
)
from elder_berry.web.security_middleware import setup_security

__all__ = [
    "SettingsDashboard",
    "SettingDefinition",
    "SecretRegistryEntry",
    "_REGISTRY_BY_KEY",
    "register_secrets_routes",
]

if TYPE_CHECKING:
    import threading

    from elder_berry.actions.computer_use import ComputerUseController
    from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer
    from elder_berry.comms.audio_pipeline import AudioPipeline
    from elder_berry.core.audio_router import AudioRouter
    from elder_berry.core.tower_agent import TowerAgent
    from elder_berry.core.secret_store import SecretStore
    from elder_berry.llm.router import LLMRouter
    from elder_berry.tools.proposal_store import ProposalStore

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
_STATIC_DIR = Path(__file__).parent / "static"


class SettingsDashboard:
    """Web-Dashboard für Systemeinstellungen, Audio-Routing und Computer-Use.

    Parameters
    ----------
    audio_router : AudioRouter
        Der gemeinsame AudioRouter (thread-safe).
    computer_use : ComputerUseController | None
        Optionaler ComputerUseController für Monitor-Auswahl.
    host : str
        Bind-Adresse (Default Phase 52: 127.0.0.1 – Loopback-Only).
        Wer Remote-Zugriff will, setzt explizit ``ELDER_BERRY_SETTINGS_BIND``
        oder übergibt einen anderen Wert.
    port : int
        Port (Default: 8090).
    require_settings_token : bool
        Wenn True (Phase 52.1a), wird die SettingsTokenMiddleware
        installiert und schreibende API-Aufrufe verlangen einen gültigen
        ``X-Saleria-Settings-Token``-Header. Default False für
        Test-Kompatibilität – ``start_saleria.py`` aktiviert es explizit.
    settings_token_path : Path | None
        Pfad zur Token-Datei. Default: ``ELDER_BERRY_HOME/settings_token``.
    require_dashboard_login : bool
        Wenn True (Phase 58), wird die DashboardAuthMiddleware installiert
        und alle Settings-/Avatar-Endpoints verlangen ein gültiges
        Login-Cookie. Erfordert einen ``secret_store``. Aktiviert
        zusätzlich Cookie-OR-Token in der SettingsTokenMiddleware.
    dashboard_session_hours : int
        TTL der Login-Sessions in Stunden (Default 12, Range 1–168).
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
        host: str = "127.0.0.1",
        port: int = 8090,
        require_settings_token: bool = False,
        settings_token_path: Path | None = None,
        require_dashboard_login: bool = False,
        dashboard_session_hours: int = 12,
        proposal_store: ProposalStore | None = None,
    ) -> None:
        self._router = audio_router
        self._computer_use = computer_use
        self._secret_store = secret_store
        self._audio_pipeline = audio_pipeline
        self._tower_agent = tower_agent
        self._llm_router = llm_router
        self._proposal_store = proposal_store
        self._host = host
        self._port = port
        self._app = FastAPI(title="Elder-Berry Settings Dashboard")

        # Phase 63: Static-Files fuer CSP-Hardening (externe CSS/JS statt inline).
        # Mount vor den Auth-Middlewares -- /static/* bleibt oeffentlich, damit
        # CSS/JS auch fuer Login- und Setup-Wizard-Seiten verfuegbar sind.
        self._app.mount(
            "/static",
            StaticFiles(directory=_STATIC_DIR),
            name="static",
        )

        # Security: CORS, Headers, Exception-Handler
        setup_security(self._app, port, secret_store)

        # Phase 58: DashboardAuthManager (opt-in, vor Token-Middleware
        # initialisieren weil Cookie-OR-Token sie als Dependency braucht)
        self._auth_manager = None
        self._session_revocations = None
        if require_dashboard_login:
            if secret_store is None:
                raise ValueError("require_dashboard_login=True benötigt secret_store")
            from elder_berry.web.dashboard_auth import DashboardAuthManager
            from elder_berry.web.session_revocation_list import (
                SessionRevocationList,
            )

            # Phase 70 (H-1): SessionRevocationList persistiert neben
            # secrets.enc. So ueberlebt eine Logout-Revocation einen
            # Tower-Restart -- sonst koennte ein gestohlener Cookie nach
            # einem Bounce wieder benutzt werden.
            revocation_path = (
                secret_store.secrets_path.parent / "session_revocations.json"
            )
            self._session_revocations = SessionRevocationList(
                persist_path=revocation_path,
            )
            self._auth_manager = DashboardAuthManager(
                secret_store,
                ttl_hours=dashboard_session_hours,
                revocation_list=self._session_revocations,
            )

        # Phase 52.1a: Token-Middleware (opt-in)
        self._token_manager = None
        if require_settings_token:
            from elder_berry.web.settings_token import SettingsTokenManager
            from elder_berry.web.settings_token_middleware import (
                SettingsTokenMiddleware,
            )

            if settings_token_path is None:
                home = Path(
                    os.environ.get(
                        "ELDER_BERRY_HOME",
                        Path(__file__).parent.parent.parent.parent,
                    )
                ).resolve()
                settings_token_path = home / "settings_token"
            self._token_manager = SettingsTokenManager(settings_token_path)
            self._token_manager.load_or_create()
            # Phase 57.2: SecretStore durchreichen, damit die Middleware
            # den First-Run-Marker auswerten und die /api/setup-Exemption
            # nach dem Setup-Abschluss aufheben kann. Ohne Store fällt
            # die Middleware auf Phase-52.1a-Verhalten (permanente
            # Exemption) zurück – relevant für Tests.
            # Phase 58: auth_manager durchreichen → Cookie-OR-Token.
            self._app.add_middleware(
                SettingsTokenMiddleware,
                token_manager=self._token_manager,
                secret_store=secret_store,
                auth_manager=self._auth_manager,
            )

        # Phase 58: DashboardAuthMiddleware NACH der Token-Middleware
        # zufügen → Starlette baut den Stack rückwärts auf, d.h. die
        # zuletzt hinzugefügte Middleware wird ZUERST ausgeführt. Damit
        # läuft der Login-Check vor dem Token-Check.
        if self._auth_manager is not None:
            from elder_berry.web.dashboard_auth_middleware import (
                DashboardAuthMiddleware,
            )
            from elder_berry.web.dashboard_auth_routes import (
                register_dashboard_auth_routes,
            )

            self._app.add_middleware(
                DashboardAuthMiddleware,
                auth_manager=self._auth_manager,
                secret_store=secret_store,
            )
            register_dashboard_auth_routes(self._app, self._auth_manager)

        self._write_lock = asyncio.Lock()
        self._change_callbacks: dict[str, list[Any]] = {}
        self._secrets_meta: dict[str, dict[str, str]] = {}
        # Lazy-Init §10.11: Thread wird erst in start() erzeugt.
        self._thread: threading.Thread | None = None

        # Routen registrieren
        self._register_routes()
        register_secrets_routes(self._app, self)
        register_llm_routes(self._app, self)
        # Phase 77.5: Plugin-Inspector liegt hinter der gleichen
        # Auth-Middleware wie alle /api/-Routen mit Settings-Bezug.
        register_plugins_routes(self._app)

        # Phase 78 Etappe 3: Plugin-Vorschlaege-API. Nur registrieren,
        # wenn ein Store gesetzt ist -- in Tests/Standalone-Setups ohne
        # Bridge bleibt /api/proposals 404.
        if self._proposal_store is not None:
            from elder_berry.web.proposals_api import register_proposals_routes

            register_proposals_routes(self._app, self._proposal_store)

        # Avatar-Editor-Routen
        from elder_berry.web.avatar_editor import register_avatar_editor_routes

        register_avatar_editor_routes(self._app, renderer=avatar_renderer)

        # Setup-Wizard-Routen (Re-Konfiguration auch nach Ersteinrichtung möglich)
        if self._secret_store:
            from elder_berry.web.setup_wizard import register_setup_wizard_routes

            register_setup_wizard_routes(self._app, self._secret_store)

        # Phase 66: Reverse-Proxy /api/robot/* zum RPi5 (durch SSH-Tunnel),
        # damit der Browser auf der Dashboard-Domain nicht direkt die
        # LAN-IP ansprechen muss (Mixed-Content + LAN-Routing-Probleme).
        if self._secret_store:
            from elder_berry.web.robot_proxy import register_robot_proxy_routes

            register_robot_proxy_routes(self._app, self._secret_store)

    @property
    def app(self) -> FastAPI:
        """FastAPI-App-Instanz (für Tests oder externe Einbindung)."""
        return self._app

    # ------------------------------------------------------------------
    # Settings-Definitionen (Phase 45)
    # ------------------------------------------------------------------

    # Phase 52: Welche Registry-Keys werden im Settings-Dashboard angezeigt.
    # Reihenfolge bestimmt die Anzeige-Reihenfolge.
    DASHBOARD_SETTING_KEYS: tuple[str, ...] = (
        "matrix_allowed_senders",
        "user_timezone",
        "stt_timeout",
        "llm_mode",
    )

    def _setting_definitions(self) -> list[SettingDefinition]:
        """Leitet SettingDefinitions aus SECRET_REGISTRY ab (Phase 52).

        Quelle: ``DASHBOARD_SETTING_KEYS`` in der Reihenfolge der Anzeige.
        Für ``user_timezone`` werden die Zeitzonen-Optionen aus
        ``AVAILABLE_TIMEZONES`` injiziert (UI-spezifisch, nicht in der
        Registry hinterlegt).
        """
        definitions: list[SettingDefinition] = []
        for key in self.DASHBOARD_SETTING_KEYS:
            entry = _REGISTRY_BY_KEY.get(key)
            if entry is None:
                logger.warning("Dashboard-Key '%s' nicht in SECRET_REGISTRY", key)
                continue
            definitions.append(self._registry_to_setting_definition(entry))
        return definitions

    def _registry_to_setting_definition(
        self,
        entry: SecretRegistryEntry,
    ) -> SettingDefinition:
        """Konvertiert einen Registry-Eintrag in eine SettingDefinition."""
        key = entry["key"]
        registry_type = entry.get("type", "str")

        ui_type: Literal["text", "textarea", "select", "number", "secret"]
        if registry_type == "textarea":
            ui_type = "textarea"
        elif registry_type == "select":
            ui_type = "select"
        elif registry_type in ("int", "float"):
            ui_type = "number"
        elif entry.get("sensitive", True) and not entry.get("behavior", False):
            ui_type = "secret"
        else:
            ui_type = "text"

        if key == self.TIMEZONE_KEY:
            options: tuple[dict[str, str], ...] = tuple(
                {"value": tz, "label": tz} for tz in sorted(self.AVAILABLE_TIMEZONES)
            )
        else:
            options = tuple(entry.get("select_options", []))

        risk_raw = entry.get("risk_level", "low")
        # Narrow auf Literal: ternary returnt str (aus dict.get()) | "low"-
        # Literal -- das letzte else "low" macht das Whole zu str. Fix: cast.
        risk_level: Literal["low", "medium", "high"] = cast(
            'Literal["low", "medium", "high"]',
            risk_raw if risk_raw in ("low", "medium", "high") else "low",
        )

        min_value = entry.get("min")
        max_value = entry.get("max")

        return SettingDefinition(
            key=key,
            label=entry["label"],
            category=entry["category"],
            type=ui_type,
            source="secret_store",
            required=entry.get("behavior", False),
            restart_required=entry.get("requires_restart", False),
            risk_level=risk_level,
            placeholder=entry.get("placeholder"),
            help_text=entry.get("description"),
            options=options,
            secret=entry.get("sensitive", True) and not entry.get("behavior", False),
            min_value=float(min_value) if min_value is not None else None,
            max_value=float(max_value) if max_value is not None else None,
        )

    def _setting_definition_map(self) -> dict[str, SettingDefinition]:
        return {
            definition.key: definition for definition in self._setting_definitions()
        }

    def _serialize_setting_definition(
        self,
        definition: SettingDefinition,
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

    def _validate_setting_value(
        self, definition: SettingDefinition, value: Any
    ) -> str | float:
        if definition.key == self.ALLOWED_SENDERS_KEY:
            if not isinstance(value, str):
                raise ValueError("Erlaubte Sender müssen Text sein.")
            senders = [
                line.strip()
                for line in value.replace(",", "\n").splitlines()
                if line.strip()
            ]
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

    def _store_setting_value(
        self, definition: SettingDefinition, value: str | float
    ) -> None:
        if not self._secret_store:
            raise RuntimeError("SecretStore nicht verfügbar")
        if definition.key == self.ALLOWED_SENDERS_KEY:
            senders = [line.strip() for line in str(value).splitlines() if line.strip()]
            self._secret_store.set(definition.key, ",".join(senders))
            return
        self._secret_store.set(definition.key, str(value))

    # ------------------------------------------------------------------
    # Monitor-Status
    # ------------------------------------------------------------------

    async def _get_monitor_status(self) -> dict[str, Any]:
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
                }
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

    # ------------------------------------------------------------------
    # Core-Routen (Audio, Monitor, Senders, Timezone, STT, Settings)
    # ------------------------------------------------------------------

    def _register_routes(self) -> None:
        """Routen registrieren (Core-Endpoints)."""

        @self._app.get("/", response_class=HTMLResponse)
        async def dashboard() -> Response:
            # Redirect zum Setup-Wizard wenn Setup nicht abgeschlossen
            if self._secret_store and not self._secret_store.has(
                "setup_wizard_completed"
            ):
                from fastapi.responses import RedirectResponse

                return RedirectResponse(url="/setup", status_code=302)
            template_path = _TEMPLATE_DIR / "audio_dashboard.html"
            if template_path.exists():
                return HTMLResponse(template_path.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>Template nicht gefunden</h1>", status_code=500)

        @self._app.get("/settings", response_class=HTMLResponse)
        async def settings_panel() -> HTMLResponse:
            """Phase 52.1b: Unified Settings-Panel."""
            template_path = _TEMPLATE_DIR / "settings_panel.html"
            if template_path.exists():
                return HTMLResponse(template_path.read_text(encoding="utf-8"))
            return HTMLResponse(
                "<h1>settings_panel.html nicht gefunden</h1>", status_code=500
            )

        @self._app.get("/api/audio")
        async def get_audio_mode() -> JSONResponse:
            return JSONResponse(
                {
                    "mode": self._router.mode.value,
                    "local_available": self._router.local_available,
                    "play_local": self._router.should_play_local(),
                }
            )

        @self._app.post("/api/audio")
        async def set_audio_mode(body: dict[str, Any] | None = None) -> JSONResponse:
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
            return JSONResponse(
                {
                    "mode": new_mode.value,
                    "local_available": self._router.local_available,
                    "play_local": self._router.should_play_local(),
                }
            )

        # --- Monitor-Auswahl (Computer Use) ---

        @self._app.get("/api/monitors")
        async def get_monitors() -> JSONResponse:
            if self._tower_agent:
                try:
                    data = await self._tower_agent.get_monitors()
                    return JSONResponse(data)
                except Exception as e:
                    logger.warning("Tower Monitor-Abfrage fehlgeschlagen: %s", e)
                    return JSONResponse(
                        {
                            "available": False,
                            "monitors": [],
                            "selected": 1,
                            "error": "Tower nicht erreichbar",
                        }
                    )
            if not self._computer_use:
                return JSONResponse(
                    {
                        "available": False,
                        "monitors": [],
                        "selected": 1,
                    }
                )
            monitors = self._computer_use.get_available_monitors()
            return JSONResponse(
                {
                    "available": True,
                    "monitors": monitors,
                    "selected": self._computer_use.monitor_index,
                }
            )

        @self._app.post("/api/monitor")
        async def set_monitor(body: dict[str, Any] | None = None) -> JSONResponse:
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

            if self._tower_agent:
                try:
                    data = await self._tower_agent.set_monitor(index)
                    logger.info("Tower Monitor geändert: %d", index)
                    return JSONResponse(data)
                except Exception:
                    logger.exception("Tower Monitor-Setzen fehlgeschlagen")
                    return JSONResponse(
                        {"error": "Tower nicht erreichbar."},
                        status_code=502,
                    )

            if not self._computer_use:
                return JSONResponse(
                    {"error": "Computer Use nicht verfügbar."},
                    status_code=400,
                )

            monitors = self._computer_use.get_available_monitors()
            valid_indices = {m["index"] for m in monitors}
            if index not in valid_indices:
                return JSONResponse(
                    {
                        "error": f"Monitor {index} nicht verfügbar. "
                        f"Gültig: {sorted(valid_indices)}"
                    },
                    status_code=400,
                )

            self._computer_use.monitor_index = index
            logger.info("Computer Use Monitor geändert: %d", index)
            return JSONResponse(
                {
                    "selected": index,
                    "monitors": monitors,
                }
            )

        # --- Allowed Senders (Matrix-Sicherheit) ---

        @self._app.get("/api/allowed-senders")
        async def get_allowed_senders() -> JSONResponse:
            if not self._secret_store:
                return JSONResponse(
                    {
                        "available": False,
                        "configured": False,
                        "count": 0,
                    }
                )
            raw = self._secret_store.get_or_none(self.ALLOWED_SENDERS_KEY)
            if not raw:
                return JSONResponse(
                    {
                        "available": True,
                        "configured": False,
                        "count": 0,
                    }
                )
            senders = [s.strip() for s in raw.split(",") if s.strip()]
            return JSONResponse(
                {
                    "available": True,
                    "configured": bool(senders),
                    "count": len(senders),
                }
            )

        @self._app.post("/api/allowed-senders")
        async def set_allowed_senders(
            body: dict[str, Any] | None = None,
        ) -> JSONResponse:
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

            if body.get("action") == "remove":
                try:
                    self._secret_store.delete(self.ALLOWED_SENDERS_KEY)
                except SecretNotFoundError:
                    # Idempotent: Allowed-Senders-Key kann bereits fehlen.
                    pass
                logger.info("Allowed-Senders entfernt")
                return JSONResponse(
                    {
                        "configured": False,
                        "count": 0,
                    }
                )

            senders_raw = body.get("senders", "")
            if not isinstance(senders_raw, str) or not senders_raw.strip():
                return JSONResponse(
                    {"error": "Parameter 'senders' fehlt oder leer."},
                    status_code=400,
                )

            senders = [s.strip() for s in senders_raw.split(",") if s.strip()]
            invalid = [s for s in senders if not s.startswith("@") or ":" not in s]
            if invalid:
                return JSONResponse(
                    {
                        "error": f"Ungültige Matrix-ID(s): {', '.join(invalid)}. "
                        "Format: @user:domain.com"
                    },
                    status_code=400,
                )

            self._secret_store.set(
                self.ALLOWED_SENDERS_KEY,
                ",".join(senders),
            )
            logger.info("Allowed-Senders gesetzt: %d Sender", len(senders))
            return JSONResponse(
                {
                    "configured": True,
                    "count": len(senders),
                }
            )

        # --- Timezone ---

        @self._app.get("/api/timezone")
        async def get_timezone() -> JSONResponse:
            tz = self.get_timezone()
            return JSONResponse(
                {
                    "timezone": tz,
                    "available": sorted(self.AVAILABLE_TIMEZONES),
                }
            )

        @self._app.post("/api/timezone")
        async def set_timezone(body: dict[str, Any] | None = None) -> JSONResponse:
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

            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(tz_name)
            except (KeyError, Exception):
                return JSONResponse(
                    {"error": f"Ungültige Zeitzone: {tz_name}"},
                    status_code=400,
                )

            self._secret_store.set(self.TIMEZONE_KEY, tz_name)
            logger.info("Zeitzone geändert: %s", safe_log(tz_name))
            return JSONResponse(
                {
                    "timezone": tz_name,
                    "available": sorted(self.AVAILABLE_TIMEZONES),
                }
            )

        # --- STT-Timeout ---

        @self._app.get("/api/stt-timeout")
        async def get_stt_timeout() -> JSONResponse:
            timeout = self._get_stt_timeout()
            return JSONResponse(
                {
                    "timeout": timeout,
                    "available": self._audio_pipeline is not None,
                }
            )

        @self._app.post("/api/stt-timeout")
        async def set_stt_timeout(body: dict[str, Any] | None = None) -> JSONResponse:
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
                    {
                        "error": f"Ungültiger Timeout: {body['timeout']}. "
                        "Erlaubt: 5–600 Sekunden."
                    },
                    status_code=400,
                )

            if self._audio_pipeline is not None:
                self._audio_pipeline.stt_timeout = timeout

            if self._secret_store:
                self._secret_store.set(self.STT_TIMEOUT_KEY, str(timeout))

            logger.info("STT-Timeout geändert: %.0fs", timeout)
            return JSONResponse(
                {
                    "timeout": timeout,
                    "available": self._audio_pipeline is not None,
                }
            )

        # --- Settings-API (Schema, Values, Status, Update) ---

        @self._app.get("/api/settings/schema")
        async def settings_schema() -> JSONResponse:
            definitions = [
                self._serialize_setting_definition(definition)
                for definition in self._setting_definitions()
            ]
            return JSONResponse({"settings": definitions})

        @self._app.get("/api/settings/values")
        async def settings_values() -> JSONResponse:
            values = {
                definition.key: self._get_setting_value(definition.key)
                for definition in self._setting_definitions()
            }
            return JSONResponse({"values": values})

        @self._app.get("/api/settings/status")
        async def settings_status() -> JSONResponse:
            settings = self._setting_definitions()
            categories: dict[str, int] = {}
            configured = 0
            restart_required = []
            for definition in settings:
                categories[definition.category] = (
                    categories.get(definition.category, 0) + 1
                )
                value = self._get_setting_value(definition.key)
                is_set = bool(str(value).strip()) if isinstance(value, str) else True
                if is_set:
                    configured += 1
                if definition.restart_required:
                    restart_required.append(definition.key)
            return JSONResponse(
                {
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
                }
            )

        @self._app.post("/api/settings/update")
        async def settings_update(body: Any = Body(...)) -> JSONResponse:
            # body als Any (statt dict[str, Any]), damit der isinstance-
            # Check unten als Defense-in-Depth gegen non-dict-Bodies
            # erhalten bleibt (FastAPI-Body parst zwar dict, aber der
            # Schutz ist beabsichtigt -- gleicher Trick wie avatar_editor
            # _validate_config gegen yaml.safe_load).
            if not self._secret_store:
                return JSONResponse(
                    {"error": "SecretStore nicht verfügbar"}, status_code=503
                )
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
            except Exception:
                logger.exception(
                    "Settings-Update fehlgeschlagen (%s)",
                    safe_log(key),
                )
                return JSONResponse(
                    {"error": "Setting konnte nicht gespeichert werden"},
                    status_code=500,
                )

            return JSONResponse(
                {
                    "status": "ok",
                    "key": definition.key,
                    "value": self._get_setting_value(definition.key),
                    "restartRequired": definition.restart_required,
                    "riskLevel": definition.risk_level,
                }
            )

        # --- Health ---

        @self._app.get("/health")
        async def health() -> JSONResponse:
            import platform

            return JSONResponse(
                {
                    "status": "ok",
                    "hostname": platform.node(),
                    "saleria_running": True,
                }
            )

    # ------------------------------------------------------------------
    # Helper-Methoden
    # ------------------------------------------------------------------

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
                    self._port,
                    attempt,
                    retries,
                    retry_delay,
                )
                time.sleep(retry_delay)
        else:
            logger.warning(
                "Settings-Dashboard: Port %d nach %d Versuchen belegt – übersprungen.",
                self._port,
                retries,
            )
            return

        def _run() -> None:
            import socket as _sock

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
            "Settings-Dashboard gestartet: http://%s:%d",
            self._host,
            self._port,
        )

    def stop(self) -> None:
        """Stoppt den Server (Daemon-Thread endet mit Hauptprozess)."""
        self._thread = None
