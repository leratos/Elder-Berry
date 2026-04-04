"""TowerAgent – Proxy für Tower-Dienste (PC-Steuerung, Audio-Fallback).

Der Tower exponiert einen FastAPI-Server. Der Bot auf dem Rootserver
ruft Tower-Dienste per HTTP auf – wenn verfügbar.

Konnektivität: SSH Reverse Tunnel (Tower → Server), z.B. Port 12769.
Heartbeat prüft periodisch ob der Tower erreichbar ist.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=3.0, read=30.0, write=10.0, pool=5.0)


class TowerAgentError(Exception):
    """Fehler bei der Tower-Kommunikation."""


class TowerAgent:
    """Proxy für Tower-Dienste (TTS-Fallback, STT-Fallback, PC-Steuerung).

    Args:
        tower_host: Host:Port des Tower-FastAPI-Servers
            (z.B. "127.0.0.1:12769" via SSH-Tunnel).
        heartbeat_timeout: Timeout für Heartbeat-Checks in Sekunden.
    """

    def __init__(
        self,
        tower_host: str,
        heartbeat_timeout: float = 3.0,
    ) -> None:
        self._host = tower_host.rstrip("/")
        self._heartbeat_timeout = heartbeat_timeout
        self._online = False

    @property
    def is_online(self) -> bool:
        """True wenn der Tower beim letzten Heartbeat erreichbar war."""
        return self._online

    @property
    def host(self) -> str:
        """Tower-Host:Port."""
        return self._host

    async def heartbeat(self) -> bool:
        """Prüft ob der Tower erreichbar ist.

        Returns:
            True wenn Tower antwortet, False sonst.
        """
        try:
            timeout = httpx.Timeout(connect=self._heartbeat_timeout,
                                    read=self._heartbeat_timeout)
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(f"http://{self._host}/status")
                self._online = r.status_code == 200
        except Exception:
            self._online = False

        if self._online:
            logger.debug("Tower Heartbeat OK (%s)", self._host)
        else:
            logger.debug("Tower nicht erreichbar (%s)", self._host)
        return self._online

    async def tts(self, text: str, emotion: str | None = None) -> bytes:
        """XTTS v2 Synthese auf dem Tower.

        Args:
            text: Zu synthetisierender Text.
            emotion: Optionaler Emotions-Name.

        Returns:
            WAV-Bytes.

        Raises:
            TowerAgentError: Bei Verbindungs- oder Verarbeitungsfehlern.
        """
        payload = {"text": text}
        if emotion:
            payload["emotion"] = emotion

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                r = await client.post(
                    f"http://{self._host}/tts", json=payload,
                )
                r.raise_for_status()
                logger.debug(
                    "Tower TTS: %d Zeichen → %d bytes WAV",
                    len(text), len(r.content),
                )
                return r.content
        except httpx.HTTPError as e:
            raise TowerAgentError("Tower TTS fehlgeschlagen: %s" % e) from e

    async def stt(self, audio_bytes: bytes) -> str:
        """FasterWhisper Transkription auf dem Tower.

        Args:
            audio_bytes: Audio-Daten (OGG/WAV).

        Returns:
            Transkribierter Text.

        Raises:
            TowerAgentError: Bei Verbindungs- oder Verarbeitungsfehlern.
        """
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                files = {"file": ("audio.ogg", audio_bytes, "audio/ogg")}
                r = await client.post(
                    f"http://{self._host}/stt", files=files,
                )
                r.raise_for_status()
                text = r.json().get("text", "")
                logger.debug("Tower STT: %d bytes → '%s'", len(audio_bytes), text[:60])
                return text
        except httpx.HTTPError as e:
            raise TowerAgentError("Tower STT fehlgeschlagen: %s" % e) from e

    async def execute_action(self, action: str, params: dict | None = None) -> dict:
        """WindowsActionController / Computer Use auf dem Tower.

        Args:
            action: Aktionsname (z.B. "press_key", "open_url").
            params: Aktionsparameter.

        Returns:
            Ergebnis-Dict vom Tower.

        Raises:
            TowerAgentError: Bei Verbindungs- oder Verarbeitungsfehlern.
        """
        payload = {"action": action, "params": params or {}}
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                r = await client.post(
                    f"http://{self._host}/action", json=payload,
                )
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError as e:
            raise TowerAgentError("Tower Action fehlgeschlagen: %s" % e) from e

    async def screenshot(self) -> bytes:
        """Screenshot vom Tower-Desktop.

        Returns:
            PNG-Bytes.

        Raises:
            TowerAgentError: Bei Verbindungs- oder Verarbeitungsfehlern.
        """
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                r = await client.get(f"http://{self._host}/screenshot")
                r.raise_for_status()
                return r.content
        except httpx.HTTPError as e:
            raise TowerAgentError("Tower Screenshot fehlgeschlagen: %s" % e) from e
