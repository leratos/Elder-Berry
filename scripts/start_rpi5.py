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
import os
import signal
import sys
import threading
from pathlib import Path

from elder_berry.core import bind_policy

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
#
# Phase 103 (S1): Die Policy lebt jetzt zentral in
# ``elder_berry.core.bind_policy`` (damit auch Simulator + AgentServer sie
# wiederverwenden). Diese duennen Wrapper bleiben erhalten, weil
# ``tests/test_start_rpi5_token.py`` sie als Modul-Attribute laedt und die
# caplog-Assertions am Logger ``elder_berry.rpi5`` haengen -- der wird hier
# in den geteilten Helper injiziert.
def _is_loopback_host(host: str) -> bool:
    """Re-Export von :func:`elder_berry.core.bind_policy.is_loopback_host`."""
    return bind_policy.is_loopback_host(host)


def _enforce_robot_token_policy(token: str | None, host: str) -> None:
    """Re-Export der Robot-Token-Policy (Logger ``elder_berry.rpi5``)."""
    bind_policy.enforce_token_policy(
        token,
        host,
        token_env_name="ELDER_BERRY_ROBOT_TOKEN",
        server_label="Robot",
        logger=logger,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Elder-Berry RPi5 – Avatar-Display + Robot-API",
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Fenster-Modus statt Fullscreen (für Debugging)",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=720,
        help="Display-Breite in Pixeln (default: 720)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=1280,
        help="Display-Höhe in Pixeln (default: 1280)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="API-Port (default: 8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        # Phase 96-E (D3): Loopback-Default. Der RobotServer wird nur ueber den
        # SSH-Reverse-Tunnel (Bot 127.0.0.1:12800 -> RPi 127.0.0.1:8000)
        # erreicht; kein LAN-Direktzugriff noetig. Fuer LAN-Betrieb explizit
        # --host 0.0.0.0 setzen (dann ist ein Robot-Token Pflicht, s.
        # _enforce_robot_token_policy).
        default="127.0.0.1",
        help="API-Host (default: 127.0.0.1, Loopback/Tunnel)",
    )
    parser.add_argument(
        "--rotation",
        type=int,
        choices=[0, 180],
        default=180,
        help=(
            "Display-Rotation in Grad (0 oder 180). Default: 180 -- "
            "Saleria steht im Geh\u00e4use baulich auf dem Kopf, daher "
            "180\u00b0 Drehung im Render. RPi5 ignoriert "
            "display_lcd_rotate= im KMS-Modus."
        ),
    )
    parser.add_argument(
        "--crossfade-scope",
        choices=["full", "mouth_only"],
        default="full",
        help=(
            "Crossfade-Reichweite (Phase 83.3). 'full' = alle Layer (Default); "
            "'mouth_only' = \u00a75/\u00a76.1-Fallback, falls der volle Crossfade "
            "auf dem RPi5 unter 30 FPS f\u00e4llt (Body/Augen schneiden hart)."
        ),
    )
    parser.add_argument(
        "--benchmark-crossfade",
        action="store_true",
        help=(
            "Misst die Crossfade-Kompositionszeit MIT rotation (\u00a70.6) und "
            "beendet sich danach -- kein Display-/API-Start. Verbindlicher "
            "30-FPS-Nachweis auf dem RPi5. Exit 0 = h\u00e4lt 30 FPS, sonst 1."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from elder_berry.avatar.layered_renderer import CrossfadeScope

    crossfade_scope = CrossfadeScope(args.crossfade_scope)

    # -- Crossfade-FPS-Messung (§0.6): misst und beendet, kein Display/API. -----
    if args.benchmark_crossfade:
        from elder_berry.avatar.crossfade_benchmark import (
            format_result,
            result_for,
            sweep_crossfade_fps,
        )

        # Sweep: FULL/MOUTH_ONLY x nativ/540x960 MIT rotation (§0.6), damit auf
        # dem RPi5 in einem Lauf ablesbar ist, welche Kombination 30 FPS haelt.
        results = sweep_crossfade_fps(
            width=args.width,
            height=args.height,
            rotation=args.rotation,
        )
        logger.info("Crossfade-FPS-Sweep (rotation=%d):", args.rotation)
        for result in results:
            logger.info("  %s", format_result(result))

        # Empfehlung (informativ): schnellste Variante, die 30 FPS haelt.
        holds = [r for r in results if r.holds_30fps]
        if holds:
            best = max(holds, key=lambda r: r.effective_fps)
            logger.info(
                "Empfehlung: scope=%s @ %dx%d haelt 30 FPS (~%.1f FPS).",
                best.scope.value,
                best.width,
                best.height,
                best.effective_fps,
            )
        else:
            logger.warning(
                "Keine Variante haelt 30 FPS -- weitere Massnahme noetig "
                "(niedrigere Aufloesung / weniger Layer / HW-Beschleunigung)."
            )

        # Exit-Code = GATE fuer die tatsaechlich laufende Produktions-Konfig
        # (gewaehlter Scope @ nativer Aufloesung), NICHT "irgendeine Variante".
        # Sonst meldet das Gate gruen, obwohl z.B. FULL@720 unter 30 bleibt und
        # der 540x960-Fallback im Normalstart nicht automatisch greift.
        production = result_for(
            results, crossfade_scope, args.width, args.height
        )
        production_holds = production is not None and production.holds_30fps
        if production_holds:
            logger.info(
                "Produktions-Konfig (scope=%s @ %dx%d) haelt 30 FPS.",
                crossfade_scope.value,
                args.width,
                args.height,
            )
        else:
            logger.warning(
                "Produktions-Konfig (scope=%s @ %dx%d) haelt 30 FPS NICHT "
                "-- Scope/Aufloesung anpassen (siehe Empfehlung oben).",
                crossfade_scope.value,
                args.width,
                args.height,
            )
        sys.exit(0 if production_holds else 1)

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
        rotation=args.rotation,
        crossfade_scope=crossfade_scope,
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
    logger.info(
        "Display: %dx%d %s rotation=%d\u00b0",
        args.width,
        args.height,
        "fullscreen" if fullscreen else "windowed",
        args.rotation,
    )
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
