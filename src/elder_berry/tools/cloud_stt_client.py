"""CloudSTTClient – Speech-to-Text via Groq Whisper API.

Nutzt die Groq-kompatible OpenAI Whisper API (whisper-large-v3).
Groq Free Tier: kostenlos, schnell, ~500 Requests/Tag.

Benötigt:
    - groq_api_key (SecretStore)
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)


class CloudSTTError(Exception):
    """Fehler bei der Cloud-STT API-Kommunikation."""


class CloudSTTClient:
    """Groq Whisper API Client für Speech-to-Text.

    Nutzt die OpenAI-kompatible Groq API mit whisper-large-v3.
    Erkennt Sprache automatisch, kann aber mit language-Hint gesteuert werden.

    Args:
        api_key: Groq API Key.
        model: Whisper-Modell (default: whisper-large-v3).
        language: Sprach-Hint (default: "de"). None für automatische Erkennung.
    """

    GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-large-v3",
        language: str | None = "de",
    ) -> None:
        if not api_key:
            raise ValueError("Groq API Key darf nicht leer sein")
        self._api_key = api_key
        self._model = model
        self._language = language

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str | None = None,
        filename: str = "audio.ogg",
    ) -> str:
        """Transkribiert Audio-Bytes zu Text.

        Args:
            audio_bytes: Audio-Daten (OGG/Opus, MP3, WAV, etc.).
            language: Optionaler Sprach-Hint (überschreibt Default).
            filename: Dateiname für MIME-Type-Erkennung.

        Returns:
            Transkribierter Text.

        Raises:
            CloudSTTError: Bei API-Fehlern oder Netzwerkproblemen.
        """
        if not audio_bytes:
            raise CloudSTTError("Audio-Daten dürfen nicht leer sein")

        lang = language or self._language
        headers = {"Authorization": f"Bearer {self._api_key}"}

        # Multipart-Form: file + model + optional language
        mime = _guess_mime(filename)
        files = {"file": (filename, audio_bytes, mime)}
        data = {"model": self._model}
        if lang:
            data["language"] = lang

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                response = await client.post(
                    self.GROQ_URL,
                    headers=headers,
                    files=files,
                    data=data,
                )
                if response.status_code == 401:
                    raise CloudSTTError("Ungültiger Groq API Key")
                if response.status_code == 429:
                    raise CloudSTTError("Groq Rate Limit erreicht")
                response.raise_for_status()

                result = response.json()
                text = result.get("text", "").strip()
                logger.debug(
                    "Cloud-STT: %d bytes → '%s' (%s)",
                    len(audio_bytes),
                    text[:60],
                    lang or "auto",
                )
                return text

        except httpx.TimeoutException as e:
            raise CloudSTTError("Groq STT Timeout: %s" % e) from e
        except httpx.HTTPStatusError as e:
            raise CloudSTTError(
                "Groq STT HTTP %d: %s"
                % (
                    e.response.status_code,
                    e.response.text[:200],
                ),
            ) from e
        except CloudSTTError:
            raise
        except httpx.HTTPError as e:
            raise CloudSTTError("Groq STT Netzwerkfehler: %s" % e) from e


def _guess_mime(filename: str) -> str:
    """Errät den MIME-Type anhand der Dateiendung."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "ogg": "audio/ogg",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "flac": "audio/flac",
        "m4a": "audio/mp4",
        "webm": "audio/webm",
    }.get(ext, "application/octet-stream")
