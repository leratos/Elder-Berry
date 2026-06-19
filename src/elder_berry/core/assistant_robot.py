"""Assistant-Mixin: Robot-Aktionen + TTS/Lip-Sync-Brücke (Phase 106).

Phase 106 (Modul-Entflechtung): aus ``assistant.py`` ausgelagert. Bündelt die
geräteseitige Auslieferung: Robot-Fahrbefehle/Emotion/Speaking, der
Playback-Pfad mit Amplitude-Lip-Sync (Phase 83.4) und die Agent-Online-Probe.

``Path`` wird bewusst aus ``pathlib`` importiert (dasselbe globale Klassen-
objekt wie in ``assistant.py``), damit ``patch("…assistant.Path.unlink")`` aus
``test_assistant_agent`` weiter greift.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from elder_berry.core._assistant_base import AssistantMixinBase
from elder_berry.core.audio_analyzer import AmplitudeTrack

if TYPE_CHECKING:
    from elder_berry.character.emotion_resolver import EmotionDecision

logger = logging.getLogger(__name__)


class RobotActionMixin(AssistantMixinBase):
    """Robot-Fahrbefehle, Emotion/Speaking-Sync, TTS-Playback + Lip-Sync."""

    def _execute_robot_action(self, action_type: str, params: dict[str, Any]) -> bool:
        """Führt Robot-spezifische Aktionen aus."""
        match action_type:
            case "robot_drive":
                return self._robot_drive(
                    params.get("direction", "forward"),
                    params.get("speed", 0.5),
                )
            case "robot_stop":
                return self._robot_stop(params.get("reason", "manual"))
        return False

    def _robot_drive(self, direction: str, speed: float) -> bool:
        """Sendet Fahrbefehl an den Roboter. Gibt False zurück wenn nicht verbunden."""
        if not self._robot:
            logger.warning("robot_drive: Kein RobotClient verbunden")
            return False
        try:
            resp = self._robot.drive(direction, speed)
            return resp.success
        except Exception as e:
            logger.error("robot_drive fehlgeschlagen: %s", e)
            return False

    def _robot_stop(self, reason: str) -> bool:
        """Stoppt den Roboter. Gibt False zurück wenn nicht verbunden."""
        if not self._robot:
            logger.warning("robot_stop: Kein RobotClient verbunden")
            return False
        try:
            resp = self._robot.stop(reason)
            return resp.success
        except Exception as e:
            logger.error("robot_stop fehlgeschlagen: %s", e)
            return False

    def _robot_set_emotion(
        self, emotion: str | None, decision: EmotionDecision | None = None
    ) -> None:
        """Synchronisiert Emotion zum RPi5-Display (fire-and-forget).

        Phase 83.5: ``decision`` (nur im Resolver-Pfad gesetzt) wird additiv
        mitgesendet – rein fürs Server-Logging/Debug (§6.3). Ohne ``decision``
        bleibt der Aufruf 1-armig (``set_emotion(emotion)``), damit der
        Legacy-/extract_emotion-Pfad und dessen Tests unverändert bleiben.
        """
        if not self._robot or not emotion:
            return
        try:
            if decision is not None:
                self._robot.set_emotion(emotion, decision=decision)
            else:
                self._robot.set_emotion(emotion)
        except Exception as e:
            logger.debug("Robot Emotion-Sync fehlgeschlagen: %s", e)

    def _robot_set_speaking(
        self, is_speaking: bool, audio_meta: AmplitudeTrack | None = None
    ) -> None:
        """Synchronisiert Sprechzustand zum RPi5-Display (fire-and-forget).

        Phase 83.4: ``audio_meta`` (nur Playback-Modus) wird additiv mitgesendet
        → AmplitudeLipSyncDriver auf dem RPi5; ohne Track → RandomLipSync (§4.4).
        """
        if not self._robot:
            return
        try:
            self._robot.set_speaking(is_speaking, audio_meta=audio_meta)
        except Exception as e:
            logger.debug("Robot Speaking-Sync fehlgeschlagen: %s", e)

    def _is_agent_online(self) -> bool:
        """Prüft ob der Laptop-Agent erreichbar ist (cached pro Request)."""
        if not self._agent:
            return False
        if self._agent_online_cache is not None:
            return self._agent_online_cache
        try:
            self._agent_online_cache = self._agent.is_online()
            return self._agent_online_cache
        except Exception:
            self._agent_online_cache = False
            return False

    def _speak_with_lipsync(self, text: str, emotion: str | None) -> None:
        """Playback-Pfad mit optionalem Amplitude-Lip-Sync (Phase 83.4).

        Nur hier (lokaler Playback-Modus) wird ein Speaking-Signal gesendet
        (§0.2/B1). Spielt der Laptop-Agent ab, generiert der Bot das Audio
        **einmal** als WAV, baut daraus den AmplitudeTrack (sofern der
        AudioAnalyzer verfügbar ist) und sendet ihn additiv per
        ``set_speaking(True, audio_meta=...)`` an den RPi5. Ohne Agent / ohne WAV
        / ohne Analyzer → kein Track → RandomLipSyncDriver (§4.4). Die Speaking-
        Flanken (show_speaking / robot.set_speaking) bleiben wie bisher um die
        TTS-Wiedergabe gewickelt (inkl. ``finally``-Reset bei Fehlern).

        Vorbedingung: ``_tts is not None`` – gefiltert in ``process()``.
        """
        assert self._tts is not None
        use_agent = bool(self._agent and self._is_agent_online())
        audio_path = self._generate_tts_wav(text, emotion) if use_agent else None
        # Der Laptop-Agent kann NUR WAV abspielen (AgentClient lädt als audio/wav
        # hoch, AgentServer dekodiert via wave.open). Ein Nicht-WAV (z.B. eine
        # ElevenLabs-.mp3 vom TTSRouter) darf nicht an den Agent gehen → dann
        # lokal via speak() abspielen (Engine ist mp3-fähig), ohne Amplitude.
        play_wav = (
            audio_path
            if audio_path is not None and audio_path.suffix.lower() == ".wav"
            else None
        )
        track = self._build_amplitude_track(play_wav) if play_wav else None

        if self._avatar:
            self._avatar.show_speaking(True)
        self._robot_set_speaking(True, track)
        try:
            if play_wav is not None and self._agent is not None:
                self._agent.play_audio_file(play_wav, emotion=emotion or "neutral")
            elif emotion:
                self._tts.speak(text, emotion=emotion)
            else:
                self._tts.speak(text)
        except Exception as e:
            logger.error("TTS fehlgeschlagen: %s", e)
        finally:
            if self._avatar:
                self._avatar.show_speaking(False)
            self._robot_set_speaking(False)
            if audio_path is not None:
                audio_path.unlink(missing_ok=True)

    def _generate_tts_wav(self, text: str, emotion: str | None) -> Path | None:
        """Generiert das TTS-Audio einmal als Datei (für Agent-Playback + Analyse).

        Gibt den **tatsächlich geschriebenen** Pfad zurück: ``generate_audio``
        kann einen anderen Pfad liefern als den Platzhalter (z.B. schreibt der
        ``TTSRouter``/ElevenLabs eine ``.mp3`` und gibt deren Pfad zurück). In
        dem Fall wird der leere ``.wav``-Platzhalter aufgeräumt und der echte
        Pfad genutzt – sonst spielte der Agent die leere Datei ab (Codex P2).

        Returns ``None``, wenn die Engine keine Dateigenerierung unterstützt
        (``NotImplementedError``) oder die Generierung scheitert → der Aufrufer
        spielt dann lokal via ``speak()`` ab (ohne Amplitude-Track).
        """
        assert self._tts is not None
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            actual = self._tts.generate_audio(text, tmp_path, emotion=emotion)
            result = actual if actual else tmp_path
            if result != tmp_path:
                # Engine schrieb woanders (z.B. .mp3) → Platzhalter aufräumen.
                tmp_path.unlink(missing_ok=True)
            return result
        except NotImplementedError:
            logger.debug("TTS generate_audio nicht verfügbar, lokaler Fallback")
            tmp_path.unlink(missing_ok=True)
            return None
        except Exception as e:
            logger.error("TTS-Audio-Generierung fehlgeschlagen: %s", e)
            tmp_path.unlink(missing_ok=True)
            return None

    def _build_amplitude_track(self, wav_path: Path) -> AmplitudeTrack | None:
        """Baut aus der WAV das Amplitude-Profil (83.4); ``None`` bei Problemen.

        ``None`` (→ RandomLipSyncDriver, §4.4), wenn die Datei kein lesbares WAV
        ist (z.B. eine ElevenLabs-.mp3) oder die Analyse scheitert.
        """
        try:
            return self._audio_analyzer.profile(wav_path)
        except Exception as e:
            logger.debug("Amplitude-Analyse fehlgeschlagen: %s", e)
            return None
