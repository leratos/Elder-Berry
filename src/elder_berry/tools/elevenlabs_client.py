"""ElevenLabsClient – Text-to-Speech via ElevenLabs REST API.

Nutzt die ElevenLabs v1 API für hochwertige, mehrsprachige Sprachsynthese.
Rückgabe: MP3-Bytes, die über AudioConverter in OGG/Opus konvertiert werden.

Benötigt:
    - elevenlabs_api_key (SecretStore)
    - elevenlabs_voice_id (SecretStore)
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# Timeouts: 10s connect, 30s read (Synthese kann bei langen Texten dauern)
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


class ElevenLabsError(Exception):
    """Fehler bei der ElevenLabs API-Kommunikation."""


class ElevenLabsClient:
    """ElevenLabs TTS API Client.

    Args:
        api_key: ElevenLabs API Key.
        voice_id: ID der konfigurierten Voice (aus ElevenLabs Dashboard).
        model: TTS-Modell (default: eleven_multilingual_v2).
        stability: Stimm-Stabilität 0.0–1.0 (default: 0.5).
        similarity_boost: Ähnlichkeit zur Referenzstimme 0.0–1.0 (default: 0.75).
    """

    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model: str = "eleven_multilingual_v2",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
    ) -> None:
        if not api_key:
            raise ValueError("ElevenLabs API Key darf nicht leer sein")
        if not voice_id:
            raise ValueError("ElevenLabs Voice ID darf nicht leer sein")

        self._api_key = api_key
        self._voice_id = voice_id
        self._model = model
        self._stability = stability
        self._similarity_boost = similarity_boost

    async def synthesize(self, text: str) -> bytes:
        """Synthetisiert Text zu MP3-Audio.

        Args:
            text: Zu synthetisierender Text.

        Returns:
            MP3-Bytes.

        Raises:
            ElevenLabsError: Bei API-Fehlern oder Netzwerkproblemen.
        """
        if not text or not text.strip():
            raise ElevenLabsError("Text darf nicht leer sein")

        url = f"{self.BASE_URL}/text-to-speech/{self._voice_id}"
        headers = {
            "xi-api-key": self._api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": self._model,
            "voice_settings": {
                "stability": self._stability,
                "similarity_boost": self._similarity_boost,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 401:
                    raise ElevenLabsError("Ungültiger API Key")
                if response.status_code == 429:
                    raise ElevenLabsError("Rate Limit / Credits aufgebraucht")
                response.raise_for_status()

                audio_bytes = response.content
                if len(audio_bytes) < 100:
                    raise ElevenLabsError(
                        "API lieferte zu wenig Daten (%d bytes)" % len(audio_bytes),
                    )

                logger.debug(
                    "ElevenLabs TTS: %d Zeichen → %d bytes MP3",
                    len(text), len(audio_bytes),
                )
                return audio_bytes

        except httpx.TimeoutException as e:
            raise ElevenLabsError("ElevenLabs Timeout: %s" % e) from e
        except httpx.HTTPStatusError as e:
            raise ElevenLabsError(
                "ElevenLabs HTTP %d: %s" % (e.response.status_code, e.response.text[:200]),
            ) from e
        except ElevenLabsError:
            raise
        except httpx.HTTPError as e:
            raise ElevenLabsError("ElevenLabs Netzwerkfehler: %s" % e) from e

    async def get_usage(self) -> dict:
        """Fragt verbleibende Credits / Zeichenkontingent ab.

        Returns:
            Dict mit Feldern wie character_count, character_limit, etc.

        Raises:
            ElevenLabsError: Bei API-Fehlern.
        """
        url = f"{self.BASE_URL}/user/subscription"
        headers = {"xi-api-key": self._api_key}

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                logger.debug(
                    "ElevenLabs Usage: %s/%s Zeichen",
                    data.get("character_count", "?"),
                    data.get("character_limit", "?"),
                )
                return data
        except httpx.HTTPError as e:
            raise ElevenLabsError("Usage-Abfrage fehlgeschlagen: %s" % e) from e
