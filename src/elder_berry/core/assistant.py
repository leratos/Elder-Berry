"""Assistant – Orchestrierung: User-Input → LLM → Aktion → TTS → Avatar → Robot."""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.actions.base import ActionController
from elder_berry.actions.db import ActionsDB
from elder_berry.core.prompts import SYSTEM_PROMPT_TEMPLATE
from elder_berry.llm.base import LLMClient
from elder_berry.tts.base import TTSEngine

if TYPE_CHECKING:
    from elder_berry.agent.client import AgentClient
    from elder_berry.avatar.base import AvatarRenderer
    from elder_berry.character.base import CharacterEngine
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.core.smart_context import SmartContextProvider
    from elder_berry.memory.base import MemoryStore
    from elder_berry.robot.client import RobotClient
    from elder_berry.system.info import SystemMonitor

logger = logging.getLogger(__name__)


# SYSTEM_PROMPT_TEMPLATE → ausgelagert nach core/prompts.py


@dataclass
class AssistantResult:
    """Ergebnis einer Assistant.process()-Anfrage."""

    response: str
    action_executed: str | None
    action_success: bool
    emotion: str | None = None
    audio_path: Path | None = None
    action_params: dict | None = None


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
        agent: AgentClient | None = None,
        system_monitor: SystemMonitor | None = None,
        memory: MemoryStore | None = None,
        remote_commands: RemoteCommandHandler | None = None,
        smart_context: SmartContextProvider | None = None,
    ) -> None:
        self._llm = llm
        self._actions_db = actions_db
        self._controller = controller
        self._tts = tts
        self._character = character
        self._avatar = avatar
        self._robot = robot
        self._agent = agent
        self._system_monitor = system_monitor
        self._memory = memory
        self._remote_commands = remote_commands
        self._smart_context = smart_context
        self._session_id: str = memory.new_session() if memory else ""
        self._agent_online_cache: bool | None = None

    def process(
        self,
        user_input: str,
        audio_output: Path | None = None,
        chat_history: str = "",
    ) -> AssistantResult:
        """
        Verarbeitet User-Input: LLM befragen → Aktion ausführen → TTS → Avatar.

        Args:
            user_input: Text-Eingabe des Nutzers.
            audio_output: Wenn gesetzt, wird TTS-Audio als Datei generiert
                statt abgespielt. Der Pfad wird in AssistantResult.audio_path
                zurückgegeben.
            chat_history: Formatierter Chat-Verlauf als Kontext für das LLM
                (Kurzzeit-Gedächtnis, getrennt von RAG-Memory).

        Returns:
            AssistantResult mit Antwort, ausgeführter Aktion, Erfolg und Emotion.
        """
        if not user_input.strip():
            return AssistantResult(
                response="Leere Eingabe.", action_executed=None, action_success=False
            )

        # Reset request-scoped cache
        self._agent_online_cache = None

        memory_context = self._get_memory_context(user_input)
        smart_context = self._get_smart_context(user_input)
        system_prompt = self._build_system_prompt(
            memory_context=memory_context,
            chat_history=chat_history,
            smart_context=smart_context,
        )
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
            # remote_command / multi_step: Pass-through – Bridge führt aus
            if action_type in ("remote_command", "multi_step"):
                action_success = True
            # system_status: Daten abrufen und Response erweitern
            elif action_type == "system_status":
                status_text = self._get_system_status()
                if status_text:
                    response_text = f"{response_text}\n\n{status_text}"
                    action_success = True
                else:
                    action_success = False
            else:
                action_success = self._execute_action(action_type, params)
            db_action = self._actions_db.get(action_type)
            if db_action:
                self._actions_db.record_use(action_type)

        # TTS: Audio generieren oder aussprechen
        generated_audio: Path | None = None
        if self._tts and response_text:
            if audio_output:
                # Datei-Modus: Audio generieren, nicht abspielen
                generated_audio = self._tts_to_file(
                    response_text,
                    audio_output,
                    emotion_str,
                )
            else:
                # Playback-Modus: Audio direkt abspielen
                if self._avatar:
                    self._avatar.show_speaking(True)
                self._robot_set_speaking(True)
                try:
                    if self._agent and self._is_agent_online():
                        self._tts_via_agent(response_text, emotion_str)
                    elif emotion_str:
                        self._tts.speak(response_text, emotion=emotion_str)
                    else:
                        self._tts.speak(response_text)
                except Exception as e:
                    logger.error("TTS fehlgeschlagen: %s", e)
                finally:
                    if self._avatar:
                        self._avatar.show_speaking(False)
                    self._robot_set_speaking(False)

        # Memory: Konversation speichern
        self._save_to_memory(user_input, response_text, emotion_str)

        return AssistantResult(
            response=response_text,
            action_executed=action_type,
            action_params=params if action_type else None,
            action_success=action_success,
            emotion=emotion_str,
            audio_path=generated_audio,
        )

    def _get_system_status(self) -> str | None:
        """Ruft Systemdaten ab und formatiert sie als lesbaren Text.

        Returns:
            Formatierter Status-String oder None wenn kein SystemMonitor.
        """
        if not self._system_monitor:
            logger.warning("system_status: Kein SystemMonitor verfügbar")
            return None

        try:
            info = self._system_monitor.get_info(top_processes=5)
            lines = [
                f"CPU: {info.cpu.usage_percent}% "
                f"({info.cpu.core_count} Kerne, {info.cpu.thread_count} Threads"
                + (f", {info.cpu.freq_mhz:.0f} MHz" if info.cpu.freq_mhz else "")
                + ")",
                f"RAM: {info.ram.used_mb:.0f} / {info.ram.total_mb:.0f} MB "
                f"({info.ram.usage_percent}% belegt)",
            ]

            for gpu in info.gpus:
                lines.append(
                    f"GPU: {gpu.name} – {gpu.gpu_util_percent}% Auslastung, "
                    f"VRAM {gpu.vram_used_mb:.0f}/{gpu.vram_total_mb:.0f} MB, "
                    f"{gpu.temperature_c}°C"
                )

            if info.top_processes:
                lines.append("Top-Prozesse (CPU):")
                for p in info.top_processes:
                    lines.append(
                        f"  {p['name']}: CPU {p['cpu_percent']}%, "
                        f"RAM {p['memory_percent']}%"
                    )

            return "\n".join(lines)
        except Exception as e:
            logger.error("SystemMonitor Abfrage fehlgeschlagen: %s", e)
            return None

    def _tts_to_file(
        self,
        text: str,
        output_path: Path,
        emotion: str | None,
    ) -> Path | None:
        """Generiert TTS-Audio als Datei (ohne Playback).

        Returns:
            Pfad zur generierten Datei oder None bei Fehler.
        """
        try:
            actual_path = self._tts.generate_audio(
                text,
                output_path,
                emotion=emotion,
            )
            # generate_audio() kann einen anderen Pfad zurückgeben
            # (z.B. .mp3 statt .wav bei ElevenLabs/TTSRouter)
            check_path = actual_path if actual_path else output_path
            if check_path.exists() and check_path.stat().st_size > 0:
                logger.debug("TTS-Audio generiert: %s", check_path)
                return check_path
            logger.warning("TTS-Audio leer oder nicht erstellt: %s", check_path)
            return None
        except NotImplementedError:
            logger.debug("TTS generate_audio nicht verfügbar")
            return None
        except Exception as e:
            logger.error("TTS-Audio-Generierung fehlgeschlagen: %s", e)
            return None

    def _build_system_prompt(
        self,
        memory_context: str = "",
        chat_history: str = "",
        smart_context: str = "",
    ) -> str:
        """Generiert System-Prompt – aus CharacterEngine oder Fallback-Template."""
        db_actions = self._actions_db.list_all()
        if db_actions:
            lines = ["Registrierte Aktionen in der Datenbank:"]
            for a in db_actions:
                lines.append(f'- Trigger: "{a.trigger}" → Typ: {a.action_type}')
            action_list = "\n".join(lines)
        else:
            action_list = "Keine zusätzlichen Aktionen in der Datenbank registriert."

        robot_status = self._build_robot_status()
        current_dt = datetime.now().strftime("%A, %d.%m.%Y %H:%M Uhr")

        # Dynamischer Command-Block aus den Handler-Definitionen
        remote_commands = ""
        if self._remote_commands:
            remote_commands = self._remote_commands.get_command_summary()

        if self._character:
            prompt = self._character.build_system_prompt(
                available_actions=action_list,
                memory_context=memory_context,
                remote_commands=remote_commands,
            )
            prompt = f"Aktuelles Datum und Uhrzeit: {current_dt}\n\n{prompt}"
            mood_context = self._character.get_mood_context()
            if mood_context:
                prompt += f"\n\n{mood_context}"
            if robot_status:
                prompt += f"\n\n{robot_status}"
            if smart_context:
                prompt += f"\n\n{smart_context}"
            if chat_history:
                prompt += f"\n\n{chat_history}"
            return prompt

        full_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            action_list=action_list,
            robot_status=robot_status,
            current_datetime=current_dt,
            memory_context=memory_context,
            remote_commands=remote_commands,
            smart_context=smart_context,
        )
        if chat_history:
            full_prompt += f"\n\n{chat_history}"
        return full_prompt

    def _get_memory_context(self, user_input: str) -> str:
        """Ruft relevante Erinnerungen aus dem Memory ab und formatiert sie."""
        if not self._memory:
            return ""
        try:
            ctx = self._memory.get_context(
                query=user_input,
                recent_n=6,
                relevant_k=3,
                current_session_id=self._session_id,
            )
            return ctx.to_prompt_text() if not ctx.is_empty() else ""
        except Exception as e:
            logger.warning("Memory-Abruf fehlgeschlagen: %s", e)
            return ""

    def _get_smart_context(self, user_input: str) -> str:
        """Ruft kontextuelle Informationen aus Stores ab (keyword-basiert)."""
        if not self._smart_context:
            return ""
        try:
            return self._smart_context.get_context(user_input)
        except Exception as e:
            logger.warning("SmartContext-Abruf fehlgeschlagen: %s", e)
            return ""

    def _save_to_memory(
        self, user_input: str, response: str, emotion: str | None
    ) -> None:
        """Speichert User-Input und Assistant-Antwort im Memory."""
        if not self._memory:
            return
        try:
            from elder_berry.memory.base import MemoryEntry

            self._memory.add(
                MemoryEntry.create(
                    role="user",
                    content=user_input,
                    session_id=self._session_id,
                )
            )
            meta = {"emotion": emotion} if emotion else {}
            self._memory.add(
                MemoryEntry.create(
                    role="assistant",
                    content=response,
                    session_id=self._session_id,
                    metadata=meta,
                )
            )
        except Exception as e:
            logger.warning("Memory-Speicherung fehlgeschlagen: %s", e)

    def generate_raw(
        self,
        user_input: str,
        system: str = "",
        chat_history: str = "",
    ) -> str:
        """Ruft nur das LLM auf, ohne SmartContext, Memory, TTS oder Emotion.

        Nützlich für interne Retry-Logik die keine Seiteneffekte braucht.

        Args:
            user_input: Text-Eingabe.
            system: Optionaler System-Prompt (wenn leer → kein System-Prompt).
            chat_history: Optionaler Chat-Verlauf als Kontext.

        Returns:
            Rohe LLM-Antwort als String.
        """
        prompt = system
        if chat_history:
            prompt = f"{prompt}\n\n{chat_history}" if prompt else chat_history
        return self._llm.generate(user_input, system=prompt)

    def new_session(self) -> None:
        """Startet eine neue Konversations-Session (setzt Session-ID zurück)."""
        if self._memory:
            self._session_id = self._memory.new_session()
        logger.info("Neue Session gestartet: %s", self._session_id)

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
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass

        # Fallback: Rohe Antwort als Text
        logger.warning("LLM-Antwort konnte nicht als JSON geparst werden")
        return {"action": None, "params": {}, "response": raw}

    def _execute_action(self, action_type: str, params: dict) -> bool:
        """Führt eine Aktion aus. Agent-Route wenn verbunden, sonst lokal."""
        # Robot-Aktionen immer direkt routen
        if action_type in ("robot_drive", "robot_stop"):
            return self._execute_robot_action(action_type, params)

        # PC-Aktionen: wenn Agent verbunden → remote, sonst lokal
        if self._agent and self._is_agent_online():
            return self._execute_via_agent(action_type, params)

        return self._execute_locally(action_type, params)

    def _execute_via_agent(self, action_type: str, params: dict) -> bool:
        """Führt eine PC-Aktion über den AgentClient (Laptop) aus."""
        try:
            result = self._agent.execute_action(action_type, params)
            if not result.success:
                logger.warning(
                    "Agent-Aktion '%s' fehlgeschlagen: %s", action_type, result.message
                )
            return result.success
        except Exception as e:
            logger.error("Agent-Aktion '%s' fehlgeschlagen: %s", action_type, e)
            # Fallback auf lokale Ausführung
            logger.info("Fallback auf lokale Ausführung für '%s'", action_type)
            return self._execute_locally(action_type, params)

    def _execute_locally(self, action_type: str, params: dict) -> bool:
        """Führt eine PC-Aktion über den lokalen ActionController aus."""
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
                case _:
                    logger.warning("Unbekannte Aktion: %s", action_type)
                    return False
            return True
        except (KeyError, TypeError) as e:
            logger.error(
                "Aktion '%s' fehlgeschlagen – fehlende Parameter: %s", action_type, e
            )
            return False
        except Exception as e:
            logger.error("Aktion '%s' fehlgeschlagen: %s", action_type, e)
            return False

    def _execute_robot_action(self, action_type: str, params: dict) -> bool:
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

    # --- Agent-Integration (Laptop) ---

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

    def _tts_via_agent(self, text: str, emotion: str | None) -> None:
        """Generiert Audio auf dem Tower und sendet es an den Laptop-Agent."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            self._tts.generate_audio(text, tmp_path, emotion=emotion)
            self._agent.play_audio_file(tmp_path, emotion=emotion or "neutral")
        except NotImplementedError:
            # TTS-Engine hat kein generate_audio → Fallback auf lokale Wiedergabe
            logger.debug("TTS generate_audio nicht verfügbar, lokaler Fallback")
            if emotion:
                self._tts.speak(text, emotion=emotion)
            else:
                self._tts.speak(text)
        finally:
            tmp_path.unlink(missing_ok=True)
