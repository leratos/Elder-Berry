"""frame_profile -- Wiring des Geraeteprofils "frame" (Phase 111, §4.1, Ae9).

``scripts/start_rpi5.py --profile frame`` ruft :func:`run_frame` direkt nach
dem Logging-Setup auf; der Stamm-Pfad danach wird nicht betreten.

Bewusst NICHT gestartet: RobotServer (kein Port 8000), Avatar-Display,
Harmony, Drehteller, Tunnel; ``ELDER_BERRY_ROBOT_TOKEN`` wird nicht gelesen.

In E2/E3 laeuft als einziger Inhalt der Diagnosemodus (M3/M4' bzw. M5
mit ``--frame-view naeherung``, M6/D2 mit ``--frame-view kamera``). Der
Portrait-Modus folgt in E5. Die
Temperaturueberwachung (E3) laeuft in jedem Modus mit.

Overrides (nur fuer dieses Profil; ``--width``, ``--height`` und
``--rotation`` des Stamms werden ignoriert):
``--frame-config``, ``--frame-rotation``, ``--frame-fps``,
``--frame-video-driver``, ``--frame-view``, ``--frame-windowed``.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
from types import FrameType
from typing import Any

from elder_berry.room_display.frame_config import (
    FrameConfig,
    FrameConfigError,
    apply_overrides,
    load_frame_config,
)

logger = logging.getLogger(__name__)

#: Werte ignorierter Stamm-Argumente, damit wir nur bei echter Abweichung warnen.
_STAMM_DEFAULTS = {"width": 720, "height": 1280, "rotation": 180}


def config_from_args(args: argparse.Namespace) -> FrameConfig:
    """Konfiguration laden und CLI-Overrides anwenden.

    Raises:
        FrameConfigError: bei ungueltiger Datei oder ungueltigem Override.
    """
    config = load_frame_config(getattr(args, "frame_config", None))
    config = apply_overrides(
        config,
        rotation=getattr(args, "frame_rotation", None),
        fps=getattr(args, "frame_fps", None),
        video_driver=getattr(args, "frame_video_driver", None),
        view=getattr(args, "frame_view", None),
    )
    for name, default in _STAMM_DEFAULTS.items():
        value = getattr(args, name, default)
        if value != default:
            logger.warning(
                "--%s gilt nur fuer das Profil stamm und wird ignoriert "
                "(frame nutzt frame_config.yaml bzw. --frame-*).",
                name,
            )
    return config


def run_frame(args: argparse.Namespace) -> int:
    """Startet das Raumdisplay. Rueckgabe ist der Exit-Code."""
    try:
        config = config_from_args(args)
    except FrameConfigError as exc:
        logger.error("Konfiguration ungueltig: %s", exc)
        return 2
    windowed = bool(getattr(args, "frame_windowed", False))
    return run_with_config(config, windowed=windowed)


def run_with_config(config: FrameConfig, *, windowed: bool = False) -> int:
    """Display oeffnen, Modus bauen, Schleife laufen lassen, aufraeumen."""
    if config.display.video_driver:
        os.environ["SDL_VIDEODRIVER"] = config.display.video_driver
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    # Lazy: Das Profil stamm soll pygame hierueber nie importieren.
    import pygame

    from elder_berry.room_display.content_mode import ContentMode
    from elder_berry.room_display.diagnostic_mode import DiagnosticMode
    from elder_berry.room_display.frame_rate_meter import FrameRateMeter
    from elder_berry.room_display.frame_sensors import (
        ProximitySetup,
        ThermalSetup,
        build_proximity,
        build_thermal,
    )
    from elder_berry.room_display.oriented_display import OrientedDisplay
    from elder_berry.room_display.room_display_app import RoomDisplayApp

    logger.info(
        "Raumdisplay 'frame': Treiber=%s Rotation=%d FPS=%d Modus=%s/%s (Quelle: %s)",
        os.environ.get("SDL_VIDEODRIVER", "<SDL-Default>"),
        config.display.rotation,
        config.display.fps,
        config.mode,
        config.diagnostic.view,
        config.source,
    )
    try:
        pygame.display.init()
    except pygame.error as exc:
        logger.error(
            "Display-Init fehlgeschlagen (%s). pygame-ce installiert, Treiber "
            "'%s' verfuegbar, Benutzer in video/render?",
            exc,
            os.environ.get("SDL_VIDEODRIVER", "<SDL-Default>"),
        )
        return 1
    previous: dict[signal.Signals, Any] = {}
    proximity: ProximitySetup | None = None
    thermal: ThermalSetup | None = None
    camera: Any = None
    try:
        thermal = build_thermal(config.thermal)
        if thermal is not None:
            thermal.monitor.start()
        desktop_sizes = [tuple(size) for size in pygame.display.get_desktop_sizes()]
        logger.info("Physische Displaygroesse (get_desktop_sizes): %s", desktop_sizes)
        screen = _open_screen(
            pygame,
            config,
            desktop_sizes,
            windowed=windowed or not config.display.fullscreen,
        )
        display = OrientedDisplay(screen, config.display.rotation)
        meter = FrameRateMeter()
        mode: ContentMode
        if config.diagnostic.view == "naeherung":
            from elder_berry.room_display.proximity_diagnostic_mode import (
                ProximityDiagnosticMode,
            )

            proximity = build_proximity(config.proximity)
            mode = ProximityDiagnosticMode(
                proximity.provider if proximity is not None else None
            )
        elif config.diagnostic.view == "kamera":
            from elder_berry.room_display.camera_diagnostic_mode import (
                CameraDiagnosticMode,
            )
            from elder_berry.room_display.frame_camera import (
                af_status,
                build_camera,
                build_pipeline,
            )

            camera = build_camera(config.camera, start_now=True)
            if camera is None:
                mode = CameraDiagnosticMode(None)
            else:
                cam = camera
                mode = CameraDiagnosticMode(
                    build_pipeline(
                        cam, config.camera, config.face, preview_without_face=True
                    ),
                    interval_s=config.camera.diagnostic_interval_s,
                    af_status=lambda: af_status(cam),
                )
        else:
            mode = DiagnosticMode(
                config.diagnostic.view,
                desktop_sizes=[(int(w), int(h)) for w, h in desktop_sizes],
                meter=meter,
                transition_s=config.display.transition_s,
                hold_s=config.diagnostic.hold_s,
                transitions=config.diagnostic.transitions,
            )
        app = RoomDisplayApp(display, mode, fps=config.display.fps, meter=meter)

        def _stop(signum: int, _frame: FrameType | None) -> None:
            logger.info("Signal %d empfangen -- Raumdisplay beendet sich.", signum)
            app.request_stop()

        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, _stop)
        return app.run()
    finally:
        for restored, handler in previous.items():
            signal.signal(restored, handler)
        if thermal is not None:
            thermal.monitor.stop()
            if thermal.bme280 is not None:
                thermal.bme280.close()
        if proximity is not None:
            proximity.driver.close()
        if camera is not None:
            camera.close()
        pygame.quit()
        logger.info("Raumdisplay beendet.")


def _open_screen(
    pygame: Any,
    config: FrameConfig,
    desktop_sizes: list[tuple[int, ...]],
    *,
    windowed: bool,
) -> Any:
    """Vollbild in nativer Groesse oder Fenster (Debug)."""
    if windowed:
        size = (1280, 720) if config.display.rotation in (0, 180) else (720, 1280)
        return pygame.display.set_mode(size)
    native = desktop_sizes[0] if desktop_sizes else (0, 0)
    return pygame.display.set_mode(
        (int(native[0]), int(native[1])), pygame.FULLSCREEN | pygame.NOFRAME
    )
