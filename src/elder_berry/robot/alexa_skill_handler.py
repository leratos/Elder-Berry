"""AlexaSkillHandler -- Alexa Custom Skill Endpoint fuer RPi5.

Empfaengt Intents von Amazon Alexa, extrahiert den Befehlstext,
dispatcht an HarmonyAdapter und gibt Alexa-Response zurueck.

Flow:
  Echo -> Amazon STT -> Rootserver (HTTPS) -> SSH-Tunnel -> RPi5:8000
  -> AlexaSkillHandler -> HarmonyAdapter -> Harmony Hub -> IR -> Geraet

Sicherheit:
  Alexa-Signatur-Validierung ist fuer Dev-Skills nicht zwingend.
  Kann spaeter per ask-sdk-core ergaenzt werden.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# -- Activity-Mapping (Kurzformen -> Harmony-Aktivitaetsnamen) ------------- #

_ACTIVITY_MAP: dict[str, str] = {
    "fernsehen": "Fernsehen",
    "tv": "Fernsehen",
    "fernseher": "Fernsehen",
    "musik": "Musik",
    "radio": "Musik",
    "gaming": "Gaming",
    "film": "Fernsehen",
    "kino": "Fernsehen",
}

# -- Geraet fuer Lautstaerke (Samsung TV steuert Denon via ARC/CEC) ------- #

_VOLUME_DEVICE = "Samsung TV"

# -- Patterns -------------------------------------------------------------- #

ACTIVITY_ON_PATTERN = re.compile(
    r"^(?:starte?\s+|mach\s+)?(?P<activity>fernsehen|fernseher|tv|musik|"
    r"radio|gaming|film|kino)\s+an$",
    re.IGNORECASE,
)
ALL_OFF_PATTERN = re.compile(
    r"^(?:alles?\s+aus|harmony\s+aus|schalte?\s+alles?\s+aus|aus)$",
    re.IGNORECASE,
)
VOLUME_UP_PATTERN = re.compile(
    r"^(?:mach\s+)?lauter$", re.IGNORECASE,
)
VOLUME_DOWN_PATTERN = re.compile(
    r"^(?:mach\s+)?leiser$", re.IGNORECASE,
)
MUTE_PATTERN = re.compile(
    r"^(?:stummschalten|stumm)$", re.IGNORECASE,
)
CURRENT_PATTERN = re.compile(
    r"^(?:was\s+(?:l[äa]uft|ist\s+an)|status)$",
    re.IGNORECASE,
)
SCENE_START_PATTERN = re.compile(
    r"^(?:starte?\s+)?szene\s+(?P<scene>.+)$", re.IGNORECASE,
)
LIGHT_ON_PATTERN = re.compile(
    r"^(?:licht|lampe)\s+an$", re.IGNORECASE,
)
LIGHT_OFF_PATTERN = re.compile(
    r"^(?:licht|lampe)\s+aus$", re.IGNORECASE,
)


@dataclass
class AlexaResult:
    """Ergebnis einer Alexa-Command-Verarbeitung."""

    text: str
    success: bool = True
    end_session: bool = True


class AlexaSkillHandler:
    """Verarbeitet Alexa-Requests und dispatcht an HarmonyAdapter.

    Parameters
    ----------
    harmony : HarmonyAdapter | None
        Adapter fuer Harmony-Hub-Steuerung (optional).
    harmony_scenes : HarmonySceneManager | None
        Szenen-Manager (optional).
    """

    def __init__(
        self,
        harmony: Any = None,
        harmony_scenes: Any = None,
    ) -> None:
        self._harmony = harmony
        self._harmony_scenes = harmony_scenes

    # -- Alexa Request Parsing --------------------------------------------- #

    def parse_alexa_request(self, body: dict) -> tuple[str, str]:
        """Extrahiert Request-Typ und Command-Text aus Alexa-JSON.

        Returns
        -------
        tuple[str, str]
            (request_type, command_text)
            request_type: "LaunchRequest", "IntentRequest", "SessionEndedRequest"
            command_text: extrahierter Slot-Text oder leerer String
        """
        request = body.get("request", {})
        request_type = request.get("type", "")

        if request_type != "IntentRequest":
            return request_type, ""

        intent = request.get("intent", {})
        slots = intent.get("slots", {})
        command_slot = slots.get("CommandText", {})
        command_text = command_slot.get("value", "").strip()

        return request_type, command_text

    # -- Alexa Response Building ------------------------------------------- #

    def build_alexa_response(self, result: AlexaResult) -> dict:
        """Baut Alexa-kompatible JSON-Response."""
        return {
            "version": "1.0",
            "response": {
                "outputSpeech": {
                    "type": "PlainText",
                    "text": result.text,
                },
                "shouldEndSession": result.end_session,
            },
        }

    # -- Command Dispatch -------------------------------------------------- #

    async def handle_request(self, body: dict) -> dict:
        """Verarbeitet einen kompletten Alexa-Request.

        Returns
        -------
        dict
            Alexa-Response-JSON.
        """
        request_type, command_text = self.parse_alexa_request(body)

        if request_type == "LaunchRequest":
            result = AlexaResult(
                text="Saleria hört. Was soll ich tun?",
                end_session=False,
            )
            return self.build_alexa_response(result)

        if request_type == "SessionEndedRequest":
            return self.build_alexa_response(AlexaResult(text=""))

        if request_type != "IntentRequest":
            result = AlexaResult(
                text="Das habe ich nicht verstanden.",
                success=False,
            )
            return self.build_alexa_response(result)

        if not command_text:
            result = AlexaResult(
                text="Ich habe keinen Befehl verstanden. "
                     "Sag zum Beispiel: Fernsehen an.",
                success=False,
                end_session=False,
            )
            return self.build_alexa_response(result)

        logger.info("Alexa-Befehl: '%s'", command_text)
        result = await self._dispatch_command(command_text)
        return self.build_alexa_response(result)

    async def _dispatch_command(self, text: str) -> AlexaResult:
        """Matcht Text gegen Patterns und fuehrt Command aus."""
        normalized = text.strip().lower()

        # Activity on
        match = ACTIVITY_ON_PATTERN.match(normalized)
        if match:
            return await self._cmd_activity_on(match.group("activity"))

        # All off
        if ALL_OFF_PATTERN.match(normalized):
            return await self._cmd_all_off()

        # Volume
        if VOLUME_UP_PATTERN.match(normalized):
            return await self._cmd_volume("VolumeUp", "Lauter")

        if VOLUME_DOWN_PATTERN.match(normalized):
            return await self._cmd_volume("VolumeDown", "Leiser")

        if MUTE_PATTERN.match(normalized):
            return await self._cmd_volume("Mute", "Stummgeschaltet")

        # Status
        if CURRENT_PATTERN.match(normalized):
            return await self._cmd_current()

        # Scene
        match = SCENE_START_PATTERN.match(text.strip())
        if match:
            return await self._cmd_scene_start(match.group("scene").strip())

        return AlexaResult(
            text=f"Befehl '{text}' nicht erkannt. "
                 "Versuch zum Beispiel: Fernsehen an, alles aus, oder lauter.",
            success=False,
        )

    # -- Harmony Commands -------------------------------------------------- #

    async def _cmd_activity_on(self, activity_key: str) -> AlexaResult:
        if not self._harmony:
            return AlexaResult(text="Harmony Hub nicht verfügbar.", success=False)

        activity_name = _ACTIVITY_MAP.get(activity_key.lower(), activity_key.title())
        try:
            success = await self._harmony.start_activity(activity_name)
            if success:
                return AlexaResult(text=f"{activity_name} wurde eingeschaltet.")
            return AlexaResult(
                text=f"{activity_name} konnte nicht gestartet werden.",
                success=False,
            )
        except Exception as e:
            logger.error("Alexa activity_on Fehler: %s", e)
            return AlexaResult(text="Fehler bei der Steuerung.", success=False)

    async def _cmd_all_off(self) -> AlexaResult:
        if not self._harmony:
            return AlexaResult(text="Harmony Hub nicht verfügbar.", success=False)

        try:
            success = await self._harmony.power_off()
            if success:
                return AlexaResult(text="Alles ausgeschaltet.")
            return AlexaResult(text="Ausschalten fehlgeschlagen.", success=False)
        except Exception as e:
            logger.error("Alexa all_off Fehler: %s", e)
            return AlexaResult(text="Fehler beim Ausschalten.", success=False)

    async def _cmd_volume(self, command: str, label: str) -> AlexaResult:
        if not self._harmony:
            return AlexaResult(text="Harmony Hub nicht verfügbar.", success=False)

        try:
            success = await self._harmony.send_command(
                device=_VOLUME_DEVICE, command=command,
            )
            if success:
                return AlexaResult(text=f"{label}.")
            return AlexaResult(text=f"{label} fehlgeschlagen.", success=False)
        except Exception as e:
            logger.error("Alexa volume Fehler: %s", e)
            return AlexaResult(text="Fehler bei der Lautstärke.", success=False)

    async def _cmd_current(self) -> AlexaResult:
        if not self._harmony:
            return AlexaResult(text="Harmony Hub nicht verfügbar.", success=False)

        try:
            activity = await self._harmony.get_current_activity()
            if activity:
                return AlexaResult(text=f"Gerade läuft: {activity}.")
            return AlexaResult(text="Nichts aktiv. Alles ist aus.")
        except Exception as e:
            logger.error("Alexa current Fehler: %s", e)
            return AlexaResult(text="Status konnte nicht abgefragt werden.", success=False)

    async def _cmd_scene_start(self, scene_name: str) -> AlexaResult:
        if not self._harmony_scenes:
            return AlexaResult(text="Szenen nicht verfügbar.", success=False)

        try:
            result = await self._harmony_scenes.start_scene(scene_name)
            ok = result.get("steps_ok", 0)
            total = result.get("steps_total", 0)
            return AlexaResult(
                text=f"Szene {scene_name} gestartet. {ok} von {total} Schritten erfolgreich.",
            )
        except Exception as e:
            logger.error("Alexa scene_start Fehler: %s", e)
            return AlexaResult(
                text=f"Szene {scene_name} konnte nicht gestartet werden.",
                success=False,
            )
