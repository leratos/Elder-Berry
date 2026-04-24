"""RPi5 Avatar-Display – Echte Implementierung mit LayeredSpriteRenderer.

Brücke zwischen RobotServer (AvatarDisplay ABC) und dem PyGame-basierten
LayeredSpriteRenderer. Läuft als Background-Thread mit eigenem Render-Loop.

Plattformhinweis: Läuft auf RPi5 (Linux) mit DSI-Display.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer
from elder_berry.character.base import Emotion
from elder_berry.robot.server import AvatarDisplay

logger = logging.getLogger(__name__)

# Default Display-Auflösung (RPi Touch Display 2, Portrait)
DEFAULT_WIDTH = 720
DEFAULT_HEIGHT = 1280


class RPi5AvatarDisplay(AvatarDisplay):
    """
    Echte Avatar-Anzeige auf dem RPi5 DSI-Display.

    Wraps LayeredSpriteRenderer und betreibt den PyGame-Render-Loop
    in einem separaten Thread. Emotion und Speaking werden thread-safe
    über Locks gesetzt.

    Verwendung:
        avatar = RPi5AvatarDisplay()
        avatar.start()       # Startet Render-Thread
        avatar.set_emotion("cheerful")
        avatar.set_speaking(True)
        avatar.stop()        # Beendet Render-Thread
    """

    def __init__(
        self,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        fullscreen: bool = True,
        assets_dir: Path | None = None,
    ) -> None:
        self._width = width
        self._height = height
        self._fullscreen = fullscreen
        self._assets_dir = assets_dir

        self._renderer: LayeredSpriteRenderer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Thread-safe State (gelesen vom Render-Thread)
        self._emotion = "neutral"
        self._speaking = False
        self._emotion_changed = threading.Event()

    def start(self) -> None:
        """Startet den Render-Loop in einem Background-Thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Render-Thread läuft bereits")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._render_loop,
            name="rpi5-avatar-render",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "RPi5AvatarDisplay gestartet: %dx%d%s",
            self._width, self._height,
            " (fullscreen)" if self._fullscreen else "",
        )

    def stop(self) -> None:
        """Stoppt den Render-Loop und wartet auf Thread-Ende."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("Render-Thread reagiert nicht auf Stop")
            self._thread = None
        logger.info("RPi5AvatarDisplay gestoppt")

    # -- AvatarDisplay Interface -----------------------------------------------

    def set_emotion(self, emotion: str) -> None:
        with self._lock:
            if self._emotion != emotion:
                self._emotion = emotion
                self._emotion_changed.set()
                logger.debug("Emotion → %s", emotion)

    def set_speaking(self, is_speaking: bool) -> None:
        with self._lock:
            self._speaking = is_speaking

    def get_state(self) -> dict:
        with self._lock:
            return {
                "emotion": self._emotion,
                "speaking": self._speaking,
                "running": self._thread is not None and self._thread.is_alive(),
            }

    # -- Render-Loop (läuft im Thread) ----------------------------------------

    def _render_loop(self) -> None:
        """Hauptschleife: PyGame init → render @ 30 FPS → shutdown."""
        try:
            self._renderer = LayeredSpriteRenderer(assets_dir=self._assets_dir)
            self._renderer.initialize(
                width=self._width,
                height=self._height,
                fullscreen=self._fullscreen,
            )
            logger.info("Render-Loop gestartet")

            while not self._stop_event.is_set() and self._renderer.is_running():
                # State aus Lock lesen
                with self._lock:
                    emotion_str = self._emotion
                    speaking = self._speaking

                # Emotion → Enum konvertieren
                try:
                    emotion = Emotion(emotion_str)
                except ValueError:
                    emotion = Emotion.NEUTRAL

                self._renderer.show_emotion(emotion)
                self._renderer.show_speaking(speaking)
                self._renderer.update()

        except Exception:
            logger.exception("Fehler im Render-Loop")
        finally:
            if self._renderer is not None:
                self._renderer.shutdown()
                self._renderer = None
            logger.info("Render-Loop beendet")
