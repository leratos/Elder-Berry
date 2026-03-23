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
import logging
import signal
import sys
import threading
from pathlib import Path

logger = logging.getLogger("elder_berry.rpi5")


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

    # -- RobotServer -----------------------------------------------------------
    # Projekt-Root ermitteln (scripts/ ist ein Unterverzeichnis)
    project_root = Path(__file__).resolve().parent.parent

    server = RobotServer(
        motors=motors,
        avatar=avatar,
        sensors=sensors,
        camera=camera,
        turntable=turntable,
        hostname="elder-berry-rpi5",
        project_root=project_root,
        service_name="elder-berry",
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
