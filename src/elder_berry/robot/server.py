"""RobotServer – FastAPI-Server für den RPi5 (oder Simulator).

Stellt REST-Endpoints bereit über die der Tower den Roboter steuert:
- Avatar (Emotion, Lip-Sync)
- Motoren (Fahrbefehle, Stopp)
- Sensoren (Akku, Temperatur)
- Drehteller (Rotation, Homing)
- System (Update, Health)

Plattformhinweis: Läuft auf RPi5 (Linux) und Windows (Simulator).
"""
from __future__ import annotations

import logging
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from elder_berry.robot.alexa_skill_handler import AlexaResult, AlexaSkillHandler
from elder_berry.robot.camera_controller import CameraController
from elder_berry.robot.harmony_adapter import HarmonyAdapter
from elder_berry.robot.harmony_layout_manager import HarmonyLayoutManager
from elder_berry.robot.harmony_scene_manager import (
    HarmonySceneManager,
    SceneExecutionError,
    SceneNotFoundError,
)
from elder_berry.robot.turntable_controller import TurntableController
from elder_berry.robot.protocol import (
    ApiResponse,
    BatteryStatus,
    HealthResponse,
    RobotStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Models (für FastAPI Request-Validierung)
# ---------------------------------------------------------------------------

class AvatarRequest(BaseModel):
    """Request: Emotion und/oder Sprechzustand setzen."""
    emotion: str | None = None
    is_speaking: bool | None = None


class DriveRequest(BaseModel):
    """Request: Fahrbefehl."""
    direction: str
    speed: float = 0.5
    duration: float | None = None


class StopRequest(BaseModel):
    """Request: Notfall-Stopp."""
    reason: str = "manual"


class TurntableRotateRequest(BaseModel):
    """Request: Drehteller rotieren."""
    target_degrees: float | None = None    # Absolute Position
    relative_degrees: float | None = None  # Relative Rotation


class HarmonyActivityRequest(BaseModel):
    """Request: Harmony-Aktivitaet starten."""
    activity: str  # z.B. "Fernsehen"


class HarmonyCommandRequest(BaseModel):
    """Request: Harmony-Geraetebefehl senden."""
    device: str    # z.B. "Receiver"
    command: str   # z.B. "VolumeUp"
    repeat: int = 1


class HarmonySceneStartRequest(BaseModel):
    """Request: Szene starten."""
    name: str  # z.B. "Gaming"


# ---------------------------------------------------------------------------
# Hardware-Abstraktionen (werden vom Simulator oder echten RPi implementiert)
# ---------------------------------------------------------------------------

class MotorController(ABC):
    """ABC für Motorsteuerung."""

    @abstractmethod
    def drive(self, direction: str, speed: float) -> None:
        """Fährt in die angegebene Richtung."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stoppt alle Motoren."""
        ...

    @abstractmethod
    def get_state(self) -> dict:
        """Gibt aktuellen Motor-Zustand zurück."""
        ...


class AvatarDisplay(ABC):
    """ABC für Avatar-Anzeige auf dem RPi5-Display."""

    @abstractmethod
    def set_emotion(self, emotion: str) -> None:
        """Setzt die angezeigte Emotion."""
        ...

    @abstractmethod
    def set_speaking(self, is_speaking: bool) -> None:
        """Aktiviert/deaktiviert Lip-Sync."""
        ...

    @abstractmethod
    def get_state(self) -> dict:
        """Gibt aktuellen Avatar-Zustand zurück."""
        ...


class SensorManager(ABC):
    """ABC für Sensor-Abfragen."""

    @abstractmethod
    def get_battery(self) -> BatteryStatus:
        """Liest Akku-Status."""
        ...

    @abstractmethod
    def get_all(self) -> dict:
        """Liest alle Sensoren."""
        ...


# ---------------------------------------------------------------------------
# Server-Klasse
# ---------------------------------------------------------------------------

class RobotServer:
    """
    FastAPI-basierter Server für die Tower ↔ RPi5 Kommunikation.

    Alle Hardware-Abhängigkeiten werden per DI übergeben (Konstruktor).
    Im Simulator: Mock-Implementierungen.
    Auf dem RPi5: Echte Hardware-Klassen.
    """

    def __init__(
        self,
        motors: MotorController,
        avatar: AvatarDisplay,
        sensors: SensorManager,
        camera: CameraController | None = None,
        turntable: TurntableController | None = None,
        harmony: HarmonyAdapter | None = None,
        harmony_layouts: HarmonyLayoutManager | None = None,
        harmony_scenes: HarmonySceneManager | None = None,
        hostname: str = "elder-berry-rpi",
        project_root: Path | None = None,
        service_name: str = "elder-berry-rpi",
    ) -> None:
        self._motors = motors
        self._avatar = avatar
        self._sensors = sensors
        self._camera = camera
        self._turntable = turntable
        self._harmony = harmony
        self._harmony_layouts = harmony_layouts
        self._harmony_scenes = harmony_scenes
        self._hostname = hostname
        self._project_root = project_root
        self._service_name = service_name
        self._alexa = AlexaSkillHandler(
            harmony=harmony,
            harmony_scenes=harmony_scenes,
        )
        self._start_time = time.monotonic()

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
            # Startup
            if self._harmony is not None:
                connected = await self._harmony.connect()
                if connected:
                    logger.info("HarmonyAdapter verbunden beim Startup")
                    if self._harmony_layouts is not None:
                        config = self._harmony.get_detailed_config()
                        self._harmony_layouts.ensure_defaults(config)
                else:
                    logger.warning("Harmony Hub nicht erreichbar beim Startup")
            yield
            # Shutdown
            if self._harmony is not None:
                await self._harmony.disconnect()
                logger.info("HarmonyAdapter getrennt beim Shutdown")

        self.app = FastAPI(
            title="Elder-Berry Robot API", version="0.1.0",
            lifespan=lifespan,
        )
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self._register_routes()

        logger.info("RobotServer initialisiert: %s", hostname)

    def _register_routes(self) -> None:
        """Registriert alle API-Endpoints."""

        @self.app.get("/health")
        def health() -> dict:
            uptime = time.monotonic() - self._start_time
            resp = HealthResponse(
                status="ok",
                hostname=self._hostname,
                uptime=round(uptime, 1),
            )
            return asdict(resp)

        @self.app.get("/status")
        def status() -> dict:
            motor_state = self._motors.get_state()
            avatar_state = self._avatar.get_state()
            battery = self._sensors.get_battery()

            robot_status = RobotStatus(
                online=True,
                battery=battery,
                motors_active=motor_state.get("active", False),
                current_direction=motor_state.get("direction", "stop"),
                current_speed=motor_state.get("speed", 0.0),
                avatar_emotion=avatar_state.get("emotion", "neutral"),
                avatar_speaking=avatar_state.get("speaking", False),
                sensors=self._sensors.get_all(),
            )
            return asdict(robot_status)

        @self.app.post("/avatar/emotion")
        def set_avatar(request: AvatarRequest) -> dict:
            if request.emotion is not None:
                self._avatar.set_emotion(request.emotion)
                logger.info("Avatar Emotion: %s", request.emotion)

            if request.is_speaking is not None:
                self._avatar.set_speaking(request.is_speaking)
                logger.info("Avatar Speaking: %s", request.is_speaking)

            resp = ApiResponse(success=True, message="Avatar aktualisiert")
            return asdict(resp)

        @self.app.post("/motor/drive")
        def drive(request: DriveRequest) -> dict:
            self._motors.drive(request.direction, request.speed)
            logger.info(
                "Motor: %s @ %.0f%%", request.direction, request.speed * 100,
            )
            resp = ApiResponse(
                success=True,
                message=f"Fahre {request.direction}",
            )
            return asdict(resp)

        @self.app.post("/motor/stop")
        def stop(request: StopRequest | None = None) -> dict:
            reason = request.reason if request else "manual"
            self._motors.stop()
            logger.info("Motor STOP: %s", reason)
            resp = ApiResponse(success=True, message=f"Gestoppt: {reason}")
            return asdict(resp)

        @self.app.get("/sensor/battery")
        def battery() -> dict:
            return asdict(self._sensors.get_battery())

        @self.app.get("/sensor/all")
        def sensors() -> dict:
            return self._sensors.get_all()

        # --- Kamera ---

        @self.app.get("/camera/capture")
        def camera_capture(quality: int = 85) -> dict:
            """Nimmt ein Bild auf und gibt JPEG als Base64 zurück."""
            if not self._camera:
                return asdict(ApiResponse(
                    success=False,
                    message="Keine Kamera verfügbar",
                ))
            if not self._camera.is_available():
                return asdict(ApiResponse(
                    success=False,
                    message="Kamera nicht erkannt",
                ))
            try:
                import base64
                jpeg_bytes = self._camera.capture_jpeg(quality=quality)
                b64 = base64.b64encode(jpeg_bytes).decode("ascii")
                width, height = self._camera.get_resolution()
                return {
                    "success": True,
                    "image_base64": b64,
                    "format": "jpeg",
                    "width": width,
                    "height": height,
                    "size_bytes": len(jpeg_bytes),
                }
            except Exception as e:
                logger.error("Kamera-Capture fehlgeschlagen: %s", e)
                return asdict(ApiResponse(
                    success=False,
                    message=f"Capture fehlgeschlagen: {e}",
                ))

        @self.app.get("/camera/status")
        def camera_status() -> dict:
            """Gibt den Kamera-Status zurück."""
            if not self._camera:
                return {"available": False, "reason": "Keine Kamera konfiguriert"}
            available = self._camera.is_available()
            resolution = self._camera.get_resolution() if available else None
            return {
                "available": available,
                "resolution": resolution,
            }

        # --- Drehteller ---

        @self.app.post("/turntable/rotate")
        def turntable_rotate(request: TurntableRotateRequest) -> dict:
            if not self._turntable:
                return asdict(ApiResponse(
                    success=False, message="Kein Drehteller",
                ))
            if request.target_degrees is None and request.relative_degrees is None:
                return asdict(ApiResponse(
                    success=False,
                    message="target_degrees oder relative_degrees erforderlich",
                ))
            try:
                if request.target_degrees is not None:
                    self._turntable.rotate_to(request.target_degrees)
                    msg = f"Rotation zu {request.target_degrees} Grad gestartet"
                else:
                    self._turntable.rotate_by(request.relative_degrees)
                    msg = f"Rotation um {request.relative_degrees} Grad gestartet"
                return asdict(ApiResponse(success=True, message=msg))
            except RuntimeError as e:
                return asdict(ApiResponse(success=False, message=str(e)))

        @self.app.post("/turntable/home")
        def turntable_home() -> dict:
            if not self._turntable:
                return asdict(ApiResponse(
                    success=False, message="Kein Drehteller",
                ))
            try:
                self._turntable.home()
                return asdict(ApiResponse(
                    success=True, message="Homing gestartet",
                ))
            except RuntimeError as e:
                return asdict(ApiResponse(success=False, message=str(e)))

        @self.app.post("/turntable/stop")
        def turntable_stop() -> dict:
            if not self._turntable:
                return asdict(ApiResponse(
                    success=False, message="Kein Drehteller",
                ))
            self._turntable.stop()
            return asdict(ApiResponse(
                success=True, message="Rotation gestoppt",
            ))

        @self.app.get("/turntable/status")
        def turntable_status() -> dict:
            if not self._turntable:
                return {
                    "available": False,
                    "reason": "Kein Drehteller konfiguriert",
                }
            return {
                "available": True,
                "is_homed": self._turntable.is_homed,
                "is_moving": self._turntable.is_moving,
                "position_degrees": self._turntable.get_position(),
            }

        # --- System ---

        @self.app.post("/system/update")
        def system_update() -> dict:
            """Git pull + pip install + systemctl restart."""
            if not self._project_root:
                return asdict(ApiResponse(
                    success=False,
                    message="Projekt-Root nicht konfiguriert",
                ))

            cwd = str(self._project_root)
            steps: list[str] = []

            # 1. git fetch
            try:
                r = subprocess.run(
                    ["git", "fetch", "origin"],
                    capture_output=True, text=True,
                    timeout=30, cwd=cwd,
                )
                if r.returncode != 0:
                    return asdict(ApiResponse(
                        success=False,
                        message=f"Git Fetch fehlgeschlagen: {r.stderr}",
                    ))
            except Exception as e:
                return asdict(ApiResponse(
                    success=False, message=f"Git Fetch Fehler: {e}",
                ))

            # 2. Commits behind?
            try:
                r = subprocess.run(
                    ["git", "rev-list", "--count", "HEAD..@{u}"],
                    capture_output=True, text=True,
                    timeout=10, cwd=cwd,
                )
                behind = int(r.stdout.strip()) if r.returncode == 0 else 0
            except Exception:
                behind = 0

            if behind == 0:
                return asdict(ApiResponse(
                    success=True,
                    message="Alles aktuell -- kein Update noetig.",
                ))

            steps.append(f"{behind} neue(r) Commit(s)")

            # 3. git pull --ff-only
            try:
                r = subprocess.run(
                    ["git", "pull", "--ff-only"],
                    capture_output=True, text=True,
                    timeout=60, cwd=cwd,
                )
                if r.returncode != 0:
                    return asdict(ApiResponse(
                        success=False,
                        message=f"Git Pull fehlgeschlagen: {r.stderr}",
                    ))
                steps.append("Code aktualisiert")
            except Exception as e:
                return asdict(ApiResponse(
                    success=False, message=f"Git Pull Fehler: {e}",
                ))

            # 4. pip install (immer, RPi hat weniger extras)
            try:
                r = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-e", ".",
                     "--quiet"],
                    capture_output=True, text=True,
                    timeout=300, cwd=cwd,
                )
                if r.returncode == 0:
                    steps.append("Dependencies installiert")
                else:
                    steps.append(f"pip Warnung: {r.stderr[:200]}")
            except Exception as e:
                steps.append(f"pip Fehler: {e}")

            # 5. systemctl restart
            try:
                subprocess.Popen(
                    ["sudo", "systemctl", "restart", self._service_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                steps.append(f"Neustart via systemctl ({self._service_name})")
            except Exception as e:
                steps.append(f"Neustart fehlgeschlagen: {e}")

            return asdict(ApiResponse(
                success=True,
                message=" | ".join(steps),
            ))

        # --- Harmony Hub ---

        @self.app.get("/harmony/status")
        async def harmony_status() -> dict:
            """Harmony-Hub Status: Verbindung und aktuelle Aktivitaet."""
            if not self._harmony:
                return JSONResponse(
                    {"error": "Harmony nicht konfiguriert"},
                    status_code=503,
                )
            current = await self._harmony.get_current_activity()
            return {
                "connected": self._harmony.is_connected,
                "current_activity": current,
            }

        @self.app.get("/harmony/config")
        async def harmony_config() -> dict:
            """Harmony-Hub Konfiguration: Aktivitaeten und Geraete."""
            if not self._harmony:
                return JSONResponse(
                    {"error": "Harmony nicht konfiguriert"},
                    status_code=503,
                )
            activities = await self._harmony.list_activities()
            devices = await self._harmony.list_devices()
            return {
                "activities": activities,
                "devices": devices,
            }

        @self.app.post("/harmony/activity")
        async def harmony_activity(request: HarmonyActivityRequest) -> dict:
            """Startet eine Harmony-Aktivitaet."""
            if not self._harmony:
                return JSONResponse(
                    {"error": "Harmony nicht konfiguriert"},
                    status_code=503,
                )
            success = await self._harmony.start_activity(request.activity)
            return {"success": success, "activity": request.activity}

        @self.app.post("/harmony/command")
        async def harmony_command(request: HarmonyCommandRequest) -> dict:
            """Sendet einen Geraetebefehl ueber den Harmony Hub."""
            if not self._harmony:
                return JSONResponse(
                    {"error": "Harmony nicht konfiguriert"},
                    status_code=503,
                )
            success = await self._harmony.send_command(
                device=request.device,
                command=request.command,
                repeat=request.repeat,
            )
            return {"success": success}

        @self.app.get("/harmony/config/detailed")
        async def harmony_config_detailed() -> dict:
            """Vollstaendige Device-Config mit ControlGroups und Commands."""
            if not self._harmony:
                return JSONResponse(
                    {"error": "Harmony nicht konfiguriert"},
                    status_code=503,
                )
            return self._harmony.get_detailed_config()

        @self.app.get("/harmony/layouts")
        async def harmony_layouts() -> dict:
            """Aktuelle Fernbedienungs-Layouts."""
            if not self._harmony_layouts:
                return JSONResponse(
                    {"error": "Layouts nicht konfiguriert"},
                    status_code=503,
                )
            return self._harmony_layouts.get_layouts()

        @self.app.post("/harmony/layouts")
        async def harmony_save_layouts(request: dict) -> dict:
            """Layouts speichern (ueberschreibt komplett)."""
            if not self._harmony_layouts:
                return JSONResponse(
                    {"error": "Layouts nicht konfiguriert"},
                    status_code=503,
                )
            self._harmony_layouts.save_layouts(request)
            return {"success": True}

        # --- Harmony Szenen ---

        @self.app.get("/harmony/scenes")
        async def harmony_scenes() -> dict:
            """Alle Szenen auflisten."""
            if not self._harmony_scenes:
                return JSONResponse(
                    {"error": "Szenen nicht konfiguriert"},
                    status_code=503,
                )
            return {"scenes": self._harmony_scenes.list_scenes()}

        @self.app.post("/harmony/scenes")
        async def harmony_save_scene(request: dict) -> dict:
            """Szene erstellen oder aktualisieren."""
            if not self._harmony_scenes:
                return JSONResponse(
                    {"error": "Szenen nicht konfiguriert"},
                    status_code=503,
                )
            try:
                self._harmony_scenes.save_scene(request)
                return {"success": True}
            except ValueError as e:
                return JSONResponse(
                    {"error": str(e)}, status_code=400,
                )

        @self.app.post("/harmony/scene/start")
        async def harmony_start_scene(
            request: HarmonySceneStartRequest,
        ) -> dict:
            """Szene starten (sequenzielle Ausfuehrung)."""
            if not self._harmony_scenes:
                return JSONResponse(
                    {"error": "Szenen nicht konfiguriert"},
                    status_code=503,
                )
            try:
                result = await self._harmony_scenes.start_scene(request.name)
                return {"success": True, **result}
            except SceneNotFoundError:
                return JSONResponse(
                    {"error": f"Szene '{request.name}' nicht gefunden"},
                    status_code=404,
                )
            except SceneExecutionError as e:
                return JSONResponse(
                    {"error": str(e)}, status_code=503,
                )

        @self.app.delete("/harmony/scene/{name}")
        async def harmony_delete_scene(name: str) -> dict:
            """Szene loeschen."""
            if not self._harmony_scenes:
                return JSONResponse(
                    {"error": "Szenen nicht konfiguriert"},
                    status_code=503,
                )
            try:
                self._harmony_scenes.delete_scene(name)
                return {"success": True}
            except SceneNotFoundError:
                return JSONResponse(
                    {"error": f"Szene '{name}' nicht gefunden"},
                    status_code=404,
                )

        @self.app.post("/harmony/off")
        async def harmony_off() -> dict:
            """Schaltet alle Geraete aus (PowerOff)."""
            if not self._harmony:
                return JSONResponse(
                    {"error": "Harmony nicht konfiguriert"},
                    status_code=503,
                )
            success = await self._harmony.power_off()
            return {"success": success}

        # --- Alexa Skill Endpoint ---

        @self.app.post("/saleria")
        async def alexa_saleria(request: Request) -> dict:
            """Alexa Custom Skill Endpoint.

            Empfaengt Alexa-JSON, extrahiert Befehlstext,
            dispatcht an HarmonyAdapter, gibt Alexa-Response zurueck.
            """
            try:
                body = await request.json()
            except Exception:
                return self._alexa.build_alexa_response(
                    AlexaResult(text="Ungültige Anfrage.", success=False),
                )
            return await self._alexa.handle_request(body)
