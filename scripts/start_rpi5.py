#!/usr/bin/env python3
"""RPi5 Start-Script – Avatar-Display + RobotServer.

Startet den LayeredSpriteRenderer im Fullscreen (720x1280 DSI)
und den FastAPI RobotServer auf Port 8000.

Verwendung:
    python scripts/start_rpi5.py                    # Fullscreen (Default)
    python scripts/start_rpi5.py --windowed         # Fenster-Modus (Debug)
    python scripts/start_rpi5.py --width 512 --height 1024  # Custom Resolution

Plattformhinweis: Für RPi5 (Linux, Python 3.13).
Kann zum Testen auch auf Windows laufen (--windowed).
"""
from __future__ import annotations

import argparse
import ipaddress
import logging
import os
import signal
import sys
import threading
from pathlib import Path

logger = logging.getLogger("elder_berry.rpi5")


# Phase 59.1: Token-Auslesen ist eine eigene Funktion, damit der Regression-
# Test verhindert, dass sie still wegfällt (davor wurde der Token nie gelesen
# und die RobotTokenMiddleware blieb dauerhaft im Bypass).
def _resolve_robot_token() -> str | None:
    """Liest ``ELDER_BERRY_ROBOT_TOKEN`` aus der Env.

    Returns:
        Token-String wenn gesetzt und nicht-leer, sonst None.
    """
    token = os.environ.get("ELDER_BERRY_ROBOT_TOKEN")
    if token and token.strip():
        return token.strip()
    return None


# Phase 64 (H-2): Policy-Enforcement. Der Warning-Only-Ansatz aus Phase 59
# hat in der Praxis mehr als einmal dazu gefuehrt, dass RPi5 im LAN ohne
# Token lief (Warning im Systemd-Log wurde uebersehen). Jetzt: Hard-Fail,
# wenn der Server auf einem nicht-Loopback-Interface binden soll UND kein
# Token gesetzt ist.
_LOOPBACK_NAMES = frozenset({"localhost"})


def _is_loopback_host(host: str) -> bool:
    """True wenn ``host`` nur ueber Loopback erreichbar ist.

    Akzeptiert ``localhost``, ``127.0.0.0/8``, ``::1``. ``0.0.0.0`` und
    ``::`` gelten NICHT als Loopback (binden auf alle Interfaces).
    """
    stripped = host.strip().lower().strip("[]")
    if stripped in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(stripped).is_loopback
    except ValueError:
        return False


def _enforce_robot_token_policy(token: str | None, host: str) -> None:
    """Bricht den Start ab, wenn Token fehlt UND Bind nicht Loopback ist.

    Raises:
        SystemExit(2): wenn kein Token gesetzt UND Host auf nicht-Loopback-
        Interface bindet. Exit-Code 2, damit systemd den Unterschied zu
        regulaeren Fehlern (1) sieht.
    """
    if token:
        return
    if _is_loopback_host(host):
        logger.warning(
            "Robot-Token NICHT konfiguriert -- Server bindet nur auf "
            "Loopback (%s). Fuer Dev/Tests OK, fuer Produktion bitte "
            "ELDER_BERRY_ROBOT_TOKEN setzen.",
            host,
        )
        return
    logger.error(
        "Robot-Token NICHT konfiguriert, aber Server soll auf %s "
        "(nicht-Loopback) binden.",
        host,
    )
    logger.error(
        "Alle Endpoints (inkl. /system/update = RCE, /harmony/*, "
        "/drive) waeren im LAN ungeprueft erreichbar. Abbruch.",
    )
    logger.error(
        "Fix: ELDER_BERRY_ROBOT_TOKEN in der systemd-Unit setzen, oder "
        "explizit mit '--host 127.0.0.1' starten.",
    )
    sys.exit(2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Elder-Berry RPi5 – Avatar-Display + Robot-API",
    )
    parser.add_argument(
        "--windowed", action="store_true",
        help="Fenster-Modus statt Fullscreen (für Debugging)",
    )
    parser.add_argument(
        "--width", type=int, default=720,
        help="Display-Breite in Pixeln (default: 720)",
    )
    parser.add_argument(
        "--height", type=int, default=1280,
        help="Display-Höhe in Pixeln (default: 1280)",
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="API-Port (default: 8000)",
    )
    parser.add_argument(
        "--host", type=str, default="0.0.0.0",
        help="API-Host (default: 0.0.0.0)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # -- Imports (nach Logging-Setup) ------------------------------------------
    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn nicht installiert: pip install uvicorn")
        sys.exit(1)

    try:
        from elder_berry.robot.rpi5_avatar import RPi5AvatarDisplay
    except ImportError as e:
        logger.error("Import fehlgeschlagen: %s", e)
        logger.error("pygame installiert? pip install pygame")
        sys.exit(1)

    from elder_berry.robot.server import RobotServer
    from elder_berry.robot.simulator import SimulatedMotors, SimulatedSensors

    # -- Avatar-Display --------------------------------------------------------
    fullscreen = not args.windowed
    avatar = RPi5AvatarDisplay(
        width=args.width,
        height=args.height,
        fullscreen=fullscreen,
    )

    # -- Motoren + Sensoren (erstmal Simulator, echte Hardware kommt später) ----
    motors = SimulatedMotors()
    sensors = SimulatedSensors()

    # -- Kamera (optional) -----------------------------------------------------
    camera = None
    try:
        from elder_berry.robot.camera_controller import RPi5Camera
        camera = RPi5Camera(resolution=(1920, 1080))
        if camera.is_available():
            logger.info("Kamera erkannt: RPi Camera Module 3")
        else:
            logger.warning("Kamera nicht erkannt – Capture deaktiviert")
            camera = None
    except Exception as e:
        logger.warning("Kamera-Init fehlgeschlagen: %s", e)

    # -- Drehteller (optional) -------------------------------------------------
    turntable = None
    try:
        from elder_berry.robot.turntable_controller import RPi5TurntableController
        turntable = RPi5TurntableController(step_delay_ms=2.0)
        logger.info("Drehteller initialisiert (Homing manuell via API)")
    except ImportError:
        logger.info("Drehteller: lgpio nicht verfügbar (kein RPi5?)")
    except Exception as e:
        logger.warning("Drehteller-Init fehlgeschlagen: %s", e)

    # -- Harmony Hub (optional) ------------------------------------------------
    # Nur instanziieren, connect() passiert im uvicorn Event-Loop (startup)
    harmony = None
    try:
        from elder_berry.robot.harmony_adapter import HarmonyAdapter
        harmony = HarmonyAdapter(hub_ip="192.168.50.133")
        logger.info("HarmonyAdapter initialisiert (IP: 192.168.50.133)")
    except ImportError:
        logger.info("Harmony: aioharmony nicht installiert – deaktiviert")
    except Exception as e:
        logger.warning("Harmony-Init fehlgeschlagen: %s", e)

    # -- Alexa Request-Verifikation (optional) ---------------------------------
    alexa_verifier = None
    try:
        from elder_berry.robot.alexa_skill_handler import AlexaRequestVerifier
        from elder_berry.core.secret_store import SecretStore
        _skill_id = SecretStore().get_or_none("alexa_skill_id")
        if _skill_id:
            alexa_verifier = AlexaRequestVerifier(application_id=_skill_id)
            logger.info("Alexa-Verifikation aktiviert (Skill-ID konfiguriert)")
        else:
            logger.info("Alexa-Verifikation deaktiviert (kein alexa_skill_id)")
    except Exception as e:
        logger.warning("Alexa-Verifier-Init fehlgeschlagen: %s", e)

    # -- RobotServer -----------------------------------------------------------
    # Projekt-Root ermitteln (scripts/ ist ein Unterverzeichnis)
    project_root = Path(__file__).resolve().parent.parent

    # Phase 59.1: Token muss hier gelesen und durchgereicht werden, sonst ist
    # die RobotTokenMiddleware dauerhaft ein No-Op (Endpoints 0.0.0.0:8000
    # wären im LAN ungeprüft – inkl. /system/update = RCE).
    robot_token = _resolve_robot_token()
    # Phase 64 (H-2): Hard-Fail, wenn Token fehlt UND Bind non-loopback.
    # Wirft SystemExit(2), bevor ueberhaupt Hardware initialisiert wird.
    _enforce_robot_token_policy(robot_token, args.host)
    if robot_token:
        logger.info("Robot-Token aktiv – Requests erfordern X-Saleria-Robot-Token")

    server = RobotServer(
        motors=motors,
        avatar=avatar,
        sensors=sensors,
        camera=camera,
        turntable=turntable,
        harmony=harmony,
        hostname="elder-berry-rpi5",
        project_root=project_root,
        service_name="elder-berry",
        alexa_verifier=alexa_verifier,
        robot_token=robot_token,
    )

    # -- Graceful Shutdown -----------------------------------------------------
    shutdown_event = threading.Event()

    def signal_handler(sig: int, frame: object) -> None:
        logger.info("Signal %d empfangen, fahre herunter...", sig)
        shutdown_event.set()
        avatar.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # -- Start -----------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("Elder-Berry RPi5")
    logger.info("Display: %dx%d %s", args.width, args.height,
                "fullscreen" if fullscreen else "windowed")
    logger.info("API: http://%s:%d", args.host, args.port)
    logger.info("=" * 60)

    # Avatar-Render-Thread starten
    avatar.start()

    # Uvicorn im Main-Thread (blockiert bis Shutdown)
    try:
        uvicorn.run(
            server.app,
            host=args.host,
            port=args.port,
            log_level="info",
        )
    except KeyboardInterrupt:
        pass
    finally:
        avatar.stop()
        if turntable:
            turntable.close()
        logger.info("RPi5 beendet")


if __name__ == "__main__":
    main()
