"""AlexaSkillHandler -- Alexa Custom Skill Endpoint fuer RPi5.

Empfaengt Intents von Amazon Alexa, dispatcht an HarmonyAdapter
und gibt Alexa-Response zurueck.

Flow:
  Echo -> Amazon STT -> Rootserver (HTTPS) -> SSH-Tunnel -> RPi5:8000
  -> AlexaSkillHandler -> HarmonyAdapter -> Harmony Hub -> IR -> Geraet

Routing: Alexa sendet Intent-Namen (TVAnIntent, AllesAusIntent, etc.),
kein Freitext-Slot. Dadurch keine Carrier-Phrase noetig.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# -- Geraet fuer Lautstaerke (Samsung TV steuert Denon via ARC/CEC) ------- #

_VOLUME_DEVICE = "Samsung TV"

# -- Intent -> Activity Mapping -------------------------------------------- #

_INTENT_ACTIVITY_MAP: dict[str, str] = {
    "TVAnIntent": "Fernsehen",
    "MusikAnIntent": "Musik",
    "GamingAnIntent": "Gaming",
}


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
        """Extrahiert Request-Typ und Intent-Name aus Alexa-JSON.

        Returns
        -------
        tuple[str, str]
            (request_type, intent_name)
            request_type: "LaunchRequest", "IntentRequest", "SessionEndedRequest"
            intent_name: z.B. "TVAnIntent" oder leerer String
        """
        request = body.get("request", {})
        request_type = request.get("type", "")

        if request_type != "IntentRequest":
            return request_type, ""

        intent = request.get("intent", {})
        intent_name = intent.get("name", "")

        return request_type, intent_name

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
        request_type, intent_name = self.parse_alexa_request(body)

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

        # Amazon Built-in Intents
        if intent_name in ("AMAZON.CancelIntent", "AMAZON.StopIntent"):
            return self.build_alexa_response(AlexaResult(text="Tschüss."))

        if intent_name == "AMAZON.HelpIntent":
            result = AlexaResult(
                text="Du kannst sagen: Fernsehen an, Musik an, "
                     "alles aus, lauter, leiser, stumm, oder was läuft.",
                end_session=False,
            )
            return self.build_alexa_response(result)

        if intent_name == "AMAZON.FallbackIntent":
            result = AlexaResult(
                text="Das habe ich nicht verstanden. "
                     "Sag zum Beispiel: Fernsehen an.",
                success=False,
                end_session=False,
            )
            return self.build_alexa_response(result)

        logger.info("Alexa-Intent: '%s'", intent_name)
        result = await self._dispatch_intent(intent_name)
        return self.build_alexa_response(result)

    async def _dispatch_intent(self, intent_name: str) -> AlexaResult:
        """Dispatcht Intent an passenden Handler."""

        # Activity on (TV, Musik, Gaming)
        if intent_name in _INTENT_ACTIVITY_MAP:
            activity = _INTENT_ACTIVITY_MAP[intent_name]
            return await self._cmd_activity_on(activity)

        # All off
        if intent_name == "AllesAusIntent":
            return await self._cmd_all_off()

        # Volume
        if intent_name == "LauterIntent":
            return await self._cmd_volume("VolumeUp", "Lauter")

        if intent_name == "LeiserIntent":
            return await self._cmd_volume("VolumeDown", "Leiser")

        if intent_name == "StummIntent":
            return await self._cmd_volume("Mute", "Stummgeschaltet")

        # Status
        if intent_name == "StatusIntent":
            return await self._cmd_current()

        return AlexaResult(
            text="Diesen Befehl kenne ich noch nicht.",
            success=False,
        )

    # -- Harmony Commands -------------------------------------------------- #

    async def _cmd_activity_on(self, activity_name: str) -> AlexaResult:
        if not self._harmony:
            return AlexaResult(text="Harmony Hub nicht verfügbar.", success=False)

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
