"""RPi5 Avatar-Display – Echte Implementierung mit LayeredSpriteRenderer.

Brücke zwischen RobotServer (AvatarDisplay ABC) und dem PyGame-basierten
LayeredSpriteRenderer. Läuft als Background-Thread mit eigenem Render-Loop.

Plattformhinweis: Läuft auf RPi5 (Linux) mit DSI-Display.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from elder_berry.avatar.controller import AvatarController
from elder_berry.avatar.layered_renderer import CrossfadeScope, LayeredSpriteRenderer
from elder_berry.avatar.state_machine import AvatarStateMachine
from elder_berry.core.audio_analyzer import AmplitudeTrack
from elder_berry.robot.server import AvatarDisplay

logger = logging.getLogger(__name__)

# Default Display-Auflösung (RPi Touch Display 2, Portrait)
DEFAULT_WIDTH = 720
DEFAULT_HEIGHT = 1280
# Default Display-Rotation: Saleria steht im Gehäuse baulich auf dem
# Kopf (DSI-Kabel-Führung). 180° dreht den Render so, dass die Figur
# aufrecht erscheint. Override per --rotation in start_rpi5.py.
DEFAULT_ROTATION = 180


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
        rotation: int = DEFAULT_ROTATION,
        crossfade_scope: CrossfadeScope = CrossfadeScope.FULL,
    ) -> None:
        self._width = width
        self._height = height
        self._fullscreen = fullscreen
        self._assets_dir = assets_dir
        self._rotation = rotation
        # Crossfade-Reichweite (83.3): FULL = alle Layer; MOUTH_ONLY ist der
        # §5/§6.1-Fallback, falls der volle Crossfade auf dem RPi5 < 30 FPS fällt.
        self._crossfade_scope = crossfade_scope

        self._renderer: LayeredSpriteRenderer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Thread-safe State (gelesen vom Render-Thread)
        self._emotion = "neutral"
        self._speaking = False
        # Amplitude-Profil der laufenden Sprech-Sitzung (83.4, nur Playback-
        # Modus). Vom REST-Thread gesetzt, vom Render-Thread konsumiert.
        self._audio_meta: AmplitudeTrack | None = None
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
            "RPi5AvatarDisplay gestartet: %dx%d%s rotation=%d\u00b0",
            self._width,
            self._height,
            " (fullscreen)" if self._fullscreen else "",
            self._rotation,
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

    def set_speaking(
        self, is_speaking: bool, audio_meta: AmplitudeTrack | None = None
    ) -> None:
        with self._lock:
            self._speaking = is_speaking
            # Track nur halten, solange gesprochen wird (83.4). Beim Stopp
            # verwerfen, damit eine Folge-Sitzung ohne Track sauber auf den
            # Inline-Random fällt.
            self._audio_meta = audio_meta if is_speaking else None

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
            self._renderer = LayeredSpriteRenderer(
                assets_dir=self._assets_dir,
                crossfade_scope=self._crossfade_scope,
            )
            self._renderer.initialize(
                width=self._width,
                height=self._height,
                fullscreen=self._fullscreen,
                rotation=self._rotation,
            )
            # Phase 83.2: Semantik-Layer zwischen Snapshot-State und Renderer.
            # Der Controller leitet weiterhin an den Renderer weiter (Verhalten
            # identisch); die StateMachine teilt sich die Emotion-Map des
            # Renderers, damit current_layers dieselben Keys auflöst.
            controller = AvatarController(
                renderer=self._renderer,
                state_machine=AvatarStateMachine(
                    emotion_map=self._renderer.emotion_map
                ),
            )
            logger.info("Render-Loop gestartet")

            last_emotion: str | None = None
            while not self._stop_event.is_set() and self._renderer.is_running():
                # State aus Lock lesen (Snapshot vom REST-Thread)
                with self._lock:
                    emotion_str = self._emotion
                    speaking = self._speaking
                    audio_meta = self._audio_meta

                # Controller statt direkter Renderer-Aufrufe. set_emotion nur
                # bei Änderung weiterreichen: bei einem ungültigen Emotion-String
                # würde der Fallback-Pfad sonst pro Frame eine Warnung loggen
                # (Spam @ 30 FPS). set_speaking ist kantengetriggert und darf
                # pro Frame aufgerufen werden; der Track wird auf der steigenden
                # Flanke einmal in den Lip-Sync-Driver übernommen (83.4).
                if emotion_str != last_emotion:
                    controller.set_emotion(emotion_str)
                    last_emotion = emotion_str
                controller.set_speaking(speaking, audio_meta=audio_meta)
                now = time.monotonic()
                # 83.3: Crossfade-Transition pro Frame (Lock-gewrappt) lesen und
                # an den Renderer reichen. Außerhalb einer Transition meldet sie
                # not in_transition → der Renderer rendert byte-identisch zu 83.2.
                transition = controller.current_transition(now)
                # 83.4: Amplitude-Mund (oder None → Inline-Random) pro Frame.
                speaking_mouth = controller.current_speaking_mouth(now)
                self._renderer.update(
                    transition=transition, speaking_mouth=speaking_mouth
                )

        except Exception:
            logger.exception("Fehler im Render-Loop")
        finally:
            if self._renderer is not None:
                self._renderer.shutdown()
                self._renderer = None
            logger.info("Render-Loop beendet")
