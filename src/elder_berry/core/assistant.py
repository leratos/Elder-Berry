"""Assistant – Orchestrierung: User-Input → LLM → Aktion → TTS → Avatar → Robot."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from elder_berry.actions.base import ActionController
from elder_berry.actions.db import ActionsDB
from elder_berry.llm.base import LLMClient
from elder_berry.tts.base import TTSEngine

if TYPE_CHECKING:
    from elder_berry.avatar.base import AvatarRenderer
    from elder_berry.character.base import CharacterEngine
    from elder_berry.robot.client import RobotClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """\
Du bist Elder-Berry, eine hilfreiche Assistentin.
Du kannst PC-Aktionen ausführen. Antworte IMMER im folgenden JSON-Format:

{{"action": "<action_type oder null>", "params": {{}}, "response": "<deine Antwort an den Nutzer>"}}

Verfügbare Aktionen:
- press_key: Taste drücken. params: {{"key": "enter"}}
- type_text: Text tippen. params: {{"text": "hello"}}
- hotkey: Tastenkombination. params: {{"keys": ["ctrl", "c"]}}
- set_volume: Lautstärke setzen (0.0-1.0). params: {{"level": 0.5}}
- mute: Stummschalten. params: {{"state": true}}
- focus_window: Fenster fokussieren. params: {{"title": "Notepad"}}
- minimize_window: Fenster minimieren. params: {{"title": "Notepad"}}
- maximize_window: Fenster maximieren. params: {{"title": "Notepad"}}
- robot_drive: Roboter fahren. params: {{"direction": "forward", "speed": 0.5}}
  Richtungen: forward, backward, left, right, rotate_left, rotate_right
- robot_stop: Roboter stoppen. params: {{"reason": "hindernis"}}

{action_list}

{robot_status}

Wenn keine Aktion nötig ist, setze "action" auf null.
Antworte immer auf Deutsch.
"""


@dataclass
class AssistantResult:
    """Ergebnis einer Assistant.process()-Anfrage."""
    response: str
    action_executed: str | None
    action_success: bool
    emotion: str | None = None


class Assistant:
    """
    Orchestriert den Ablauf: User-Input → LLM → Aktion → TTS → Avatar.

    Alle Abhängigkeiten werden per Konstruktor übergeben (DI).
    Optional: CharacterEngine für Persönlichkeit/Emotionen,
    AvatarRenderer für visuelle Darstellung.
    """

    def __init__(
        self,
        llm: LLMClient,
        actions_db: ActionsDB,
        controller: ActionController,
        tts: TTSEngine | None = None,
        character: CharacterEngine | None = None,
        avatar: AvatarRenderer | None = None,
        robot: RobotClient | None = None,
    ) -> None:
        self._llm = llm
        self._actions_db = actions_db
        self._controller = controller
        self._tts = tts
        self._character = character
        self._avatar = avatar
        self._robot = robot

    def process(self, user_input: str) -> AssistantResult:
        """
        Verarbeitet User-Input: LLM befragen → Aktion ausführen → TTS → Avatar.

        Args:
            user_input: Text-Eingabe des Nutzers.

        Returns:
            AssistantResult mit Antwort, ausgeführter Aktion, Erfolg und Emotion.
        """
        if not user_input.strip():
            return AssistantResult(
                response="Leere Eingabe.", action_executed=None, action_success=False
            )

        system_prompt = self._build_system_prompt()
        logger.debug("System-Prompt: %d Zeichen", len(system_prompt))

        raw_response = self._llm.generate(user_input, system=system_prompt)
        logger.debug("LLM-Antwort: %s", raw_response[:200])

        parsed = self._parse_llm_response(raw_response)

        action_type = parsed.get("action")
        params = parsed.get("params", {})
        response_text = parsed.get("response", raw_response)

        # Emotion extrahieren und Text bereinigen (falls CharacterEngine vorhanden)
        emotion_str = None
        if self._character:
            emotion = self._character.extract_emotion(response_text)
            emotion_str = emotion.value
            response_text = self._character.clean_response(response_text)

            # Avatar aktualisieren (lokal)
            if self._avatar:
                self._avatar.show_emotion(emotion)

            # Avatar aktualisieren (Robot/RPi5)
            self._robot_set_emotion(emotion_str)

        action_success = False
        if action_type:
            action_success = self._execute_action(action_type, params)
            db_action = self._actions_db.get(action_type)
            if db_action:
                self._actions_db.record_use(action_type)

        # TTS aussprechen
        if self._tts and response_text:
            if self._avatar:
                self._avatar.show_speaking(True)
            self._robot_set_speaking(True)
            try:
                if emotion_str:
                    self._tts.speak(response_text, emotion=emotion_str)
                else:
                    self._tts.speak(response_text)
            except Exception as e:
                logger.error("TTS fehlgeschlagen: %s", e)
            finally:
                if self._avatar:
                    self._avatar.show_speaking(False)
                self._robot_set_speaking(False)

        return AssistantResult(
            response=response_text,
            action_executed=action_type,
            action_success=action_success,
            emotion=emotion_str,
        )

    def _build_system_prompt(self) -> str:
        """Generiert System-Prompt – aus CharacterEngine oder Fallback-Template."""
        db_actions = self._actions_db.list_all()
        if db_actions:
            lines = ["Registrierte Aktionen in der Datenbank:"]
            for a in db_actions:
                lines.append(f"- Trigger: \"{a.trigger}\" → Typ: {a.action_type}")
            action_list = "\n".join(lines)
        else:
            action_list = "Keine zusätzlichen Aktionen in der Datenbank registriert."

        robot_status = self._build_robot_status()

        if self._character:
            prompt = self._character.build_system_prompt(
                available_actions=action_list,
            )
            if robot_status:
                prompt += f"\n\n{robot_status}"
            return prompt

        return SYSTEM_PROMPT_TEMPLATE.format(
            action_list=action_list,
            robot_status=robot_status,
        )

    def _parse_llm_response(self, raw: str) -> dict:
        """
        Parst JSON aus der LLM-Antwort.

        Versucht zuerst den gesamten String als JSON zu parsen.
        Fallback: sucht nach dem ersten { und letzten } im String.
        Letzter Fallback: gibt die rohe Antwort als response zurück.
        """
        # Versuch 1: Gesamter String
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Versuch 2: JSON-Block extrahieren
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass

        # Fallback: Rohe Antwort als Text
        logger.warning("LLM-Antwort konnte nicht als JSON geparst werden")
        return {"action": None, "params": {}, "response": raw}

    def _execute_action(self, action_type: str, params: dict) -> bool:
        """Führt eine Aktion über den ActionController aus."""
        try:
            match action_type:
                case "press_key":
                    self._controller.press_key(params["key"])
                case "type_text":
                    self._controller.type_text(params["text"])
                case "hotkey":
                    self._controller.hotkey(*params["keys"])
                case "set_volume":
                    self._controller.set_volume(params["level"])
                case "mute":
                    self._controller.mute(params.get("state", True))
                case "focus_window":
                    return self._controller.focus_window(params["title"])
                case "minimize_window":
                    return self._controller.minimize_window(params["title"])
                case "maximize_window":
                    return self._controller.maximize_window(params["title"])
                case "robot_drive":
                    return self._robot_drive(
                        params.get("direction", "forward"),
                        params.get("speed", 0.5),
                    )
                case "robot_stop":
                    return self._robot_stop(params.get("reason", "manual"))
                case _:
                    logger.warning("Unbekannte Aktion: %s", action_type)
                    return False
            return True
        except (KeyError, TypeError) as e:
            logger.error("Aktion '%s' fehlgeschlagen – fehlende Parameter: %s",
                         action_type, e)
            return False
        except Exception as e:
            logger.error("Aktion '%s' fehlgeschlagen: %s", action_type, e)
            return False

    # --- Robot-Integration ---

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

    def _robot_set_emotion(self, emotion: str | None) -> None:
        """Synchronisiert Emotion zum RPi5-Display (fire-and-forget)."""
        if not self._robot or not emotion:
            return
        try:
            self._robot.set_emotion(emotion)
        except Exception as e:
            logger.debug("Robot Emotion-Sync fehlgeschlagen: %s", e)

    def _robot_set_speaking(self, is_speaking: bool) -> None:
        """Synchronisiert Sprechzustand zum RPi5-Display (fire-and-forget)."""
        if not self._robot:
            return
        try:
            self._robot.set_speaking(is_speaking)
        except Exception as e:
            logger.debug("Robot Speaking-Sync fehlgeschlagen: %s", e)

    def _build_robot_status(self) -> str:
        """Baut Robot-Status-Info für den System-Prompt. Leer wenn kein Robot."""
        if not self._robot:
            return ""
        try:
            if not self._robot.is_online():
                return "Roboter-Status: OFFLINE (nicht erreichbar)"
            battery = self._robot.get_battery()
            parts = [
                "Roboter-Status: ONLINE",
                f"  Akku: {battery.percentage}% ({battery.voltage}V)",
            ]
            if battery.is_low:
                parts.append("  WARNUNG: Akku niedrig! Zur Ladestation fahren.")
            if battery.is_charging:
                parts.append("  Akku wird geladen.")
            return "\n".join(parts)
        except Exception as e:
            logger.debug("Robot-Status Abfrage fehlgeschlagen: %s", e)
            return "Roboter-Status: OFFLINE (Abfrage fehlgeschlagen)"
