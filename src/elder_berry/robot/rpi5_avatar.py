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
from typing import Any

from elder_berry.avatar.attention import NoopAttentionProvider
from elder_berry.avatar.briefing_mode import CasualBriefingModeProvider
from elder_berry.avatar.controller import AvatarController
from elder_berry.avatar.idle_policy import IdleAction, IdleBehaviorPolicy
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
        # Confidence der zuletzt gesetzten Emotion (Phase 108). Vom REST-Thread
        # gesetzt, vom Render-Thread an den Controller/das StateMachine-Gate
        # gereicht. Default 1.0 → Legacy-/String-only-Pfad schaltet immer.
        self._emotion_confidence = 1.0
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

    def set_emotion(self, emotion: str, confidence: float = 1.0) -> None:
        with self._lock:
            # confidence immer aktualisieren (auch bei gleichem Emotion-String),
            # damit der Render-Thread beim nächsten Wechsel den aktuellen Wert
            # ans Confidence-Gate gibt.
            self._emotion_confidence = confidence
            if self._emotion != emotion:
                self._emotion = emotion
                self._emotion_changed.set()
                logger.debug("Emotion → %s (conf=%.2f)", emotion, confidence)

    def set_speaking(
        self, is_speaking: bool, audio_meta: AmplitudeTrack | None = None
    ) -> None:
        with self._lock:
            self._speaking = is_speaking
            # Track nur halten, solange gesprochen wird (83.4). Beim Stopp
            # verwerfen, damit eine Folge-Sitzung ohne Track sauber auf den
            # Inline-Random fällt.
            self._audio_meta = audio_meta if is_speaking else None

    def get_state(self) -> dict[str, Any]:
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
            # Phase 83.6: IdleBehaviorPolicy aus derselben geladenen Avatar-Config
            # (idle_actions + can_blink) + Default-Stubs (NoopAttention → UNKNOWN,
            # casual Briefing). Damit zieht nur die Idle/Blink-Logik um; das
            # sichtbare Verhalten bleibt identisch.
            idle_policy = IdleBehaviorPolicy(
                idle_actions=[
                    IdleAction(
                        name=name, eye_left=eye_l, eye_right=eye_r, mouth=mouth
                    )
                    for name, eye_l, eye_r, mouth in self._renderer.idle_actions
                ],
                can_blink={
                    emotion: layers.can_blink
                    for emotion, layers in self._renderer.emotion_map.items()
                },
                attention_provider=NoopAttentionProvider(),
                briefing_provider=CasualBriefingModeProvider(),
                available_components=self._renderer.component_keys,
            )
            controller = AvatarController(
                renderer=self._renderer,
                state_machine=AvatarStateMachine(
                    emotion_map=self._renderer.emotion_map
                ),
                idle_policy=idle_policy,
            )
            logger.info("Render-Loop gestartet")

            last_forwarded: tuple[str, float] | None = None
            while not self._stop_event.is_set() and self._renderer.is_running():
                # State aus Lock lesen (Snapshot vom REST-Thread)
                with self._lock:
                    emotion_str = self._emotion
                    emotion_conf = self._emotion_confidence
                    speaking = self._speaking
                    audio_meta = self._audio_meta

                # Controller statt direkter Renderer-Aufrufe. set_emotion nur bei
                # Änderung des (Emotion, Confidence)-Paares weiterreichen: ein
                # konstanter Zustand würde sonst den Fallback-Pfad pro Frame eine
                # Warnung loggen lassen (Spam @ 30 FPS). Phase 108: das Paar (statt
                # nur des Strings) ist nötig, damit eine zuvor confidence-gegatete
                # Emotion bei steigender Confidence (gleicher String, höherer Wert)
                # erneut ans Gate geht – das ändert sich nur pro REST-Update
                # (Turn-Takt), nicht pro Frame, bleibt also spam-frei. set_speaking
                # ist kantengetriggert und darf pro Frame aufgerufen werden; der
                # Track wird auf der steigenden Flanke einmal in den Lip-Sync-Driver
                # übernommen (83.4).
                if (emotion_str, emotion_conf) != last_forwarded:
                    controller.set_emotion(emotion_str, emotion_conf)
                    last_forwarded = (emotion_str, emotion_conf)
                controller.set_speaking(speaking, audio_meta=audio_meta)
                now = time.monotonic()
                # 83.3: Crossfade-Transition pro Frame (Lock-gewrappt) lesen und
                # an den Renderer reichen. Außerhalb einer Transition meldet sie
                # not in_transition → der Renderer rendert byte-identisch zu 83.2.
                transition = controller.current_transition(now)
                # 83.4: Amplitude-Mund (oder None → Inline-Random) pro Frame.
                speaking_mouth = controller.current_speaking_mouth(now)
                # 83.6: Idle/Blink-Overrides (Lock-gewrappt) pro Frame aus der
                # IdleBehaviorPolicy; ersetzt die ehem. Renderer-internen
                # _update_idle/_update_blink.
                idle_blink = controller.current_idle_blink(now)
                self._renderer.update(
                    transition=transition,
                    speaking_mouth=speaking_mouth,
                    idle_blink=idle_blink,
                )

        except Exception:
            logger.exception("Fehler im Render-Loop")
        finally:
            if self._renderer is not None:
                self._renderer.shutdown()
                self._renderer = None
            logger.info("Render-Loop beendet")
