"""Assistant – Orchestrierung: User-Input → LLM → Aktion → TTS → Avatar → Robot.

Phase 106 (Modul-Entflechtung): Die Implementierung ist in Mixins geschnitten:
- core/assistant_prompt.py   – PromptBuilderMixin (System-Prompt-Aufbau)
- core/assistant_parsing.py  – ResponseParserMixin (LLM-Output-Parsing)
- core/assistant_robot.py    – RobotActionMixin (Robot + TTS/Lip-Sync)
``Assistant`` erbt diese Mixins; ``process()`` bleibt der Orchestrator. Damit
bleiben die öffentliche API und die in Tests direkt aufgerufenen Methoden
(``Assistant._find_last_json_object`` etc.) sowie ``SYSTEM_PROMPT_TEMPLATE``
und ``elder_berry.core.assistant.Path`` (Patch-Target) am alten Importpfad.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from elder_berry.actions.base import ActionController
from elder_berry.actions.db import ActionsDB
from elder_berry.core.assistant_parsing import ResponseParserMixin
from elder_berry.core.assistant_prompt import PromptBuilderMixin
from elder_berry.core.assistant_robot import RobotActionMixin
from elder_berry.core.audio_analyzer import AudioAnalyzer
from elder_berry.core.prompts import SYSTEM_PROMPT_TEMPLATE
from elder_berry.llm.base import LLMClient
from elder_berry.tts.base import TTSEngine

if TYPE_CHECKING:
    from elder_berry.agent.client import AgentClient
    from elder_berry.avatar.base import AvatarRenderer
    from elder_berry.character.base import CharacterEngine
    from elder_berry.character.emotion_resolver import (
        EmotionDecision,
        EmotionResolver,
    )
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.core.smart_context import SmartContextProvider
    from elder_berry.memory.base import MemoryStore
    from elder_berry.robot.client import RobotClient
    from elder_berry.system.info import SystemMonitor
    from elder_berry.tools.proposal_store import ProposalStore

logger = logging.getLogger(__name__)

__all__ = ["Assistant", "AssistantResult", "SYSTEM_PROMPT_TEMPLATE"]


# SYSTEM_PROMPT_TEMPLATE → ausgelagert nach core/prompts.py, hier re-exportiert.


@dataclass
class AssistantResult:
    """Ergebnis einer Assistant.process()-Anfrage."""

    response: str
    action_executed: str | None
    action_success: bool
    emotion: str | None = None
    audio_path: Path | None = None
    action_params: dict[str, Any] | None = None
    plugin_candidate: dict[str, Any] | None = None
    """Phase 78: <plugin-candidate>-Block, wenn der LLM einen geliefert hat.

    Wird von der Bridge an den ProposalIntentAggregator weitergereicht.
    None wenn kein Block gefunden / Block kaputt war / keine Capability-
    Luecke erkannt wurde.
    """


class Assistant(PromptBuilderMixin, ResponseParserMixin, RobotActionMixin):
    """
    Orchestriert den Ablauf: User-Input → LLM → Aktion → TTS → Avatar.

    Alle Abhängigkeiten werden per Konstruktor übergeben (DI).
    Optional: CharacterEngine für Persönlichkeit/Emotionen,
    AvatarRenderer für visuelle Darstellung.

    Die Implementierung ist auf Mixins verteilt (Phase 106): Prompt-Aufbau,
    LLM-Output-Parsing und die Robot-/TTS-Brücke. ``process()`` und die
    PC-Aktions-Ausführung bleiben hier.
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
        proposal_store: ProposalStore | None = None,
        audio_analyzer: AudioAnalyzer | None = None,
        emotion_resolver: EmotionResolver | None = None,
        robot_battery_enabled: bool = False,
    ) -> None:
        self._llm = llm
        self._actions_db = actions_db
        self._controller = controller
        self._tts = tts
        # Phase 83.4: baut im Playback-Modus das Amplitude-Profil fürs Lip-Sync.
        # Default-Instanz ist billig + numpy-geguarded (liefert None ohne numpy),
        # daher kein Pflicht-Wiring; injizierbar für Tests.
        self._audio_analyzer = audio_analyzer or AudioAnalyzer()
        self._character = character
        # Phase 83.5: opt-in. Gesetzt → process() leitet die Emotion über den
        # EmotionResolver (resolve_from_llm) statt über character.extract_emotion
        # ab und reicht die EmotionDecision an Avatar + Robot. None → heutiges
        # Verhalten (extract_emotion-Adapter), bestehende Tests bleiben grün.
        self._emotion_resolver = emotion_resolver
        self._avatar = avatar
        self._robot = robot
        # Phase 102 (#739 Schritt 1): Akku ist eine optionale Sensor-Capability
        # (heute Sim). Default aus -> kein simulierter Akku-Stand im System-
        # Prompt. Pro-Sensor-Flag, KEIN globaler sim/real-Schalter.
        self._robot_battery_enabled = robot_battery_enabled
        self._agent = agent
        self._system_monitor = system_monitor
        self._memory = memory
        self._remote_commands = remote_commands
        self._smart_context = smart_context
        self._proposal_store = proposal_store
        self._session_id: str = memory.new_session() if memory else ""
        self._agent_online_cache = None

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

        # Phase 98: Bei einem Backend-Wechsel (Cloud-Störung → lokal) liefert
        # der Router einmalig einen Hinweis. Wird nur an die Chat-Antwort
        # angehängt – nicht an TTS/Memory (kein gesprochener Meta-Text, kein
        # Verschmutzen des Gedächtnisses).
        backend_notice = self._pop_backend_notice()

        # Phase 78: Plugin-Candidate VOR _parse_llm_response extrahieren.
        # Sonst greift der Parser-Fallback (rfind '}') ueber Action-JSON-
        # Envelope UND Candidate-JSON, was das Action-Routing zerstoert
        # (action_type wird None, response wird Roh-JSON inkl. Block).
        raw_response, plugin_candidate = self._extract_plugin_candidate(raw_response)

        parsed = self._parse_llm_response(raw_response)

        action_type = parsed.get("action")
        params = parsed.get("params", {})
        response_text = parsed.get("response", raw_response)

        # Emotion extrahieren und Text bereinigen (falls CharacterEngine vorhanden)
        emotion_str = None
        if self._character:
            # Phase 83.5: Resolver (opt-in) ersetzt extract_emotion. Beide lesen
            # das [tag] auf dem UN-bereinigten response_text; bei vorhandenem Tag
            # setzt der Resolver dasselbe set_mood + tracker.record wie heute
            # (B4 – aufgezeichnete Serie identisch). decision != None nur im
            # Resolver-Pfad → wird additiv an den RPi5 geloggt.
            decision: EmotionDecision | None = None
            if self._emotion_resolver is not None:
                decision = self._emotion_resolver.resolve_from_llm(response_text)
                emotion = decision.emotion
            else:
                emotion = self._character.extract_emotion(response_text)
                # Phase 110: auch ohne Resolver eine explizit schwache Tag-
                # Intensität an den RPi5 durchreichen, damit die mildere Mimik
                # (Blend) auch im Fallback-Pfad sichtbar wird. Modell B: ein Tag
                # schaltet immer (confidence 1.0); die Intensität steuert nur die
                # Anzeige-Tiefe. Volle Intensität (bare Tag) bleibt decision=None
                # → byte-identisch zum bisherigen Legacy-Verhalten.
                tag_intensity = self._character.parse_emotion_tag_with_intensity(
                    response_text
                )
                # Nur eine echt schwache (0 < int < 1) Intensität synthetisieren.
                # int == 0 ist „kein Signal" (sonst angry-State bei alpha-0-/
                # Neutral-Render); int == 1 ist voll → decision=None (1-armig).
                if tag_intensity is not None and 0.0 < tag_intensity[1] < 1.0:
                    from elder_berry.character.emotion_resolver import EmotionDecision

                    decision = EmotionDecision(
                        emotion,
                        1.0,  # getaggte Emotion schaltet immer (Modell B)
                        "legacy_intensity",
                        {},
                        tag_intensity[1],  # Phase 110: Anzeige-Tiefe
                    )
            emotion_str = emotion.value
            response_text = self._character.clean_response(response_text)

            # Avatar aktualisieren (lokal)
            if self._avatar:
                self._avatar.show_emotion(emotion)

            # Avatar aktualisieren (Robot/RPi5)
            self._robot_set_emotion(emotion_str, decision=decision)

        action_success = False
        if action_type:
            # remote_command / multi_step / list_pick (Phase 80) /
            # action_sequence (Phase 82) / propose_action (Phase 89):
            # Pass-through -- Bridge/MessageHandler fuehrt aus bzw. legt den
            # Vorschlag ab. Der Assistant fuehrt diese Typen NICHT lokal aus.
            if action_type in (
                "remote_command",
                "multi_step",
                "list_pick",
                "action_sequence",
                "propose_action",
            ):
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
                # Playback-Modus: Audio direkt abspielen (lokal oder via Agent).
                self._speak_with_lipsync(response_text, emotion_str)

        # Memory: Konversation speichern (ohne Backend-Hinweis)
        self._save_to_memory(user_input, response_text, emotion_str)

        chat_response = response_text
        if backend_notice:
            chat_response = (
                f"{response_text}\n\n{backend_notice}"
                if response_text
                else backend_notice
            )

        return AssistantResult(
            response=chat_response,
            action_executed=action_type,
            action_params=params if action_type else None,
            action_success=action_success,
            emotion=emotion_str,
            audio_path=generated_audio,
            plugin_candidate=plugin_candidate,
        )

    def _pop_backend_notice(self) -> str | None:
        """Holt einen einmaligen Backend-Wechsel-Hinweis vom LLM-Router.

        Defensiv: Nicht jedes ``LLMClient`` ist ein ``LLMRouter`` (z. B. ein
        direkter Client in Tests) – darum per ``getattr`` geprüft.
        """
        pop = getattr(self._llm, "pop_backend_notice", None)
        if not callable(pop):
            return None
        try:
            notice = pop()
        except Exception as exc:  # pragma: no cover - defensiv
            logger.debug("pop_backend_notice fehlgeschlagen: %s", exc)
            return None
        return notice if isinstance(notice, str) and notice else None

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

        Vorbedingung: ``_tts is not None`` -- gefiltert in
        ``process()`` (``if self._tts and response_text:``).

        Returns:
            Pfad zur generierten Datei oder None bei Fehler.
        """
        assert self._tts is not None
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

    def _execute_action(self, action_type: str, params: dict[str, Any]) -> bool:
        """Führt eine Aktion aus. Agent-Route wenn verbunden, sonst lokal."""
        # Robot-Aktionen immer direkt routen
        if action_type in ("robot_drive", "robot_stop"):
            return self._execute_robot_action(action_type, params)

        # PC-Aktionen: wenn Agent verbunden → remote, sonst lokal
        if self._agent and self._is_agent_online():
            return self._execute_via_agent(action_type, params)

        return self._execute_locally(action_type, params)

    def _execute_via_agent(self, action_type: str, params: dict[str, Any]) -> bool:
        """Führt eine PC-Aktion über den AgentClient (Laptop) aus.

        Vorbedingung: ``_agent is not None`` -- gefiltert in
        ``_execute_action`` (``if self._agent and self._is_agent_online()``).
        """
        assert self._agent is not None
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

    def _execute_locally(self, action_type: str, params: dict[str, Any]) -> bool:
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
