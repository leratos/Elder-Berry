"""MatrixChannel – Matrix-Implementierung des MessageChannel (via matrix-nio).

Verbindet sich zu einem Synapse-Server, empfängt Textnachrichten und
sendet Text + Audio (OGG/Opus Sprachnachrichten) zurück.

Verwendung:
    channel = MatrixChannel(
        homeserver="https://matrix.last-strawberry.com",
        user_id="@saleria:matrix.last-strawberry.com",
        password="geheim",
        allowed_rooms=["!roomid:matrix.last-strawberry.com"],
    )
    await channel.connect()
    channel.on_message(my_callback)
    await channel.sync_loop()
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import aiofiles
from nio import (
    AsyncClient,
    JoinError,
    LoginError,
    LoginResponse,
    RoomMessageText,
    RoomSendError,
    UploadError,
    UploadResponse,
)

from elder_berry.comms.message_channel import (
    IncomingMessage,
    MessageCallback,
    MessageChannel,
)

logger = logging.getLogger(__name__)

# Sync-Timeout in Millisekunden (30 Sekunden)
SYNC_TIMEOUT_MS = 30_000

# Retry-Delay bei Sync-Fehlern (Sekunden)
SYNC_RETRY_DELAY = 5


class MatrixChannelError(Exception):
    """Fehler bei der Matrix-Kommunikation."""


class MatrixChannel(MessageChannel):
    """Matrix-Implementierung des MessageChannel via matrix-nio.

    - Login via Passwort (kein E2EE in Phase 1)
    - Empfängt m.room.message (msgtype: m.text)
    - Sendet Text (m.text) und Audio (m.audio mit Voice-Flag)
    - Optionale Room-Whitelist
    """

    def __init__(
        self,
        homeserver: str,
        user_id: str,
        password: str | None = None,
        access_token: str | None = None,
        allowed_rooms: list[str] | None = None,
        store_path: str | None = None,
    ) -> None:
        if not password and not access_token:
            raise ValueError("Entweder password oder access_token muss angegeben werden")

        self._homeserver = homeserver
        self._user_id = user_id
        self._password = password
        self._access_token = access_token
        self._allowed_rooms = set(allowed_rooms) if allowed_rooms else None
        self._callbacks: list[MessageCallback] = []
        self._connected = False
        self._should_sync = False

        self._client = AsyncClient(
            homeserver=homeserver,
            user=user_id,
            store_path=store_path or "",
        )

    async def connect(self) -> None:
        """Login zum Matrix-Server (Passwort oder Access-Token)."""
        if self._connected:
            logger.debug("Bereits verbunden")
            return

        if self._access_token:
            self._client.access_token = self._access_token
            self._client.user_id = self._user_id
            logger.info("Matrix-Login via Access-Token für %s", self._user_id)
        else:
            response = await self._client.login(self._password)
            if isinstance(response, LoginError):
                raise MatrixChannelError(
                    f"Matrix-Login fehlgeschlagen: {response.message}"
                )
            logger.info(
                "Matrix-Login erfolgreich: %s (Device: %s)",
                self._user_id, response.device_id,
            )

        # Initialer Sync – markiert alles als gelesen, damit wir nur neue
        # Nachrichten verarbeiten
        await self._client.sync(timeout=SYNC_TIMEOUT_MS, full_state=True)
        logger.debug("Initialer Sync abgeschlossen")

        # Auto-Join: Einladungen in erlaubte Räume automatisch annehmen
        await self._auto_join_invited_rooms()

        # Message-Callback registrieren
        self._client.add_event_callback(self._on_room_message, RoomMessageText)

        self._connected = True

    async def disconnect(self) -> None:
        """Logout und Verbindung trennen."""
        self._should_sync = False
        self._connected = False

        try:
            await self._client.close()
        except Exception as e:
            logger.debug("Fehler beim Schließen: %s", e)

        logger.info("Matrix-Verbindung getrennt")

    async def send_text(self, room_id: str, text: str) -> None:
        """Sendet eine Textnachricht in den Raum."""
        if not self._connected:
            raise MatrixChannelError("Nicht verbunden")

        response = await self._client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": text,
            },
        )

        if isinstance(response, RoomSendError):
            raise MatrixChannelError(f"Senden fehlgeschlagen: {response.message}")

        logger.debug("Text gesendet an %s (%d Zeichen)", room_id, len(text))

    async def send_audio(self, room_id: str, audio_path: Path) -> None:
        """Sendet eine Audiodatei als Sprachnachricht.

        Die Datei sollte OGG/Opus sein für korrekte Darstellung in Element.
        Setzt den org.matrix.msc3245.voice Flag für Waveform-Player.
        """
        if not self._connected:
            raise MatrixChannelError("Nicht verbunden")

        if not audio_path.exists():
            raise FileNotFoundError(f"Audio-Datei nicht gefunden: {audio_path}")

        file_size = audio_path.stat().st_size
        mime_type = self._guess_mime_type(audio_path)
        filename = audio_path.name

        # Upload zum Matrix-Server (nio erwartet File-Objekt, nicht bytes)
        async with aiofiles.open(audio_path, "rb") as f:
            upload_response, _keys = await self._client.upload(
                f,
                content_type=mime_type,
                filename=filename,
                filesize=file_size,
            )

        if isinstance(upload_response, UploadError):
            raise MatrixChannelError(
                f"Audio-Upload fehlgeschlagen: {upload_response.message}"
            )

        content_uri = upload_response.content_uri

        # Audio-Event mit Voice-Flag senden
        content: dict[str, Any] = {
            "msgtype": "m.audio",
            "body": filename,
            "url": content_uri,
            "info": {
                "mimetype": mime_type,
                "size": file_size,
            },
            # Voice-Flag: Element zeigt Waveform-Player statt Download-Link
            "org.matrix.msc3245.voice": {},
        }

        response = await self._client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )

        if isinstance(response, RoomSendError):
            raise MatrixChannelError(
                f"Audio-Nachricht senden fehlgeschlagen: {response.message}"
            )

        logger.debug(
            "Audio gesendet an %s: %s (%d bytes)", room_id, filename, file_size,
        )

    def on_message(self, callback: MessageCallback) -> None:
        """Registriert einen Callback für eingehende Textnachrichten."""
        self._callbacks.append(callback)

    async def sync_loop(self) -> None:
        """Startet den Sync-Loop (blockierend).

        Nutzt sync_forever() von matrix-nio mit automatischem Reconnect.
        """
        if not self._connected:
            raise MatrixChannelError("Nicht verbunden – zuerst connect() aufrufen")

        self._should_sync = True
        logger.info("Sync-Loop gestartet")

        while self._should_sync:
            try:
                await self._client.sync(
                    timeout=SYNC_TIMEOUT_MS,
                    full_state=False,
                )
            except asyncio.CancelledError:
                logger.debug("Sync-Loop abgebrochen (CancelledError)")
                break
            except Exception as e:
                if not self._should_sync:
                    break
                logger.warning(
                    "Sync-Fehler: %s – Retry in %ds", e, SYNC_RETRY_DELAY,
                )
                await asyncio.sleep(SYNC_RETRY_DELAY)

        logger.info("Sync-Loop beendet")

    @property
    def is_connected(self) -> bool:
        """True wenn verbunden und bereit."""
        return self._connected

    @property
    def client(self) -> AsyncClient:
        """Zugriff auf den nio AsyncClient (für Tests/Debugging)."""
        return self._client

    # --- Interne Methoden ---

    async def _auto_join_invited_rooms(self) -> None:
        """Tritt automatisch allen eingeladenen Räumen bei (gefiltert durch Whitelist)."""
        invited = self._client.invited_rooms
        if not invited:
            return

        for room_id in invited:
            # Whitelist prüfen: nur erlaubte Räume joinen
            if self._allowed_rooms and room_id not in self._allowed_rooms:
                logger.debug("Einladung ignoriert (nicht in Whitelist): %s", room_id)
                continue

            response = await self._client.join(room_id)
            if isinstance(response, JoinError):
                logger.warning("Raum-Beitritt fehlgeschlagen %s: %s", room_id, response.message)
            else:
                logger.info("Raum beigetreten: %s", room_id)

    async def _on_room_message(self, room, event: RoomMessageText) -> None:
        """nio-Callback: wird für jede m.room.message (m.text) aufgerufen."""
        # Eigene Nachrichten ignorieren
        if event.sender == self._user_id:
            return

        # Room-Whitelist prüfen
        if self._allowed_rooms and room.room_id not in self._allowed_rooms:
            logger.debug(
                "Nachricht aus nicht erlaubtem Raum ignoriert: %s", room.room_id,
            )
            return

        msg = IncomingMessage(
            sender=event.sender,
            room_id=room.room_id,
            body=event.body,
            timestamp=event.server_timestamp / 1000.0,
            raw=event,
        )

        logger.debug("Nachricht empfangen: %s → %s", msg.sender, msg.body[:80])

        for callback in self._callbacks:
            try:
                await callback(msg)
            except Exception as e:
                logger.error(
                    "Callback-Fehler für Nachricht von %s: %s", msg.sender, e,
                )

    @staticmethod
    def _guess_mime_type(path: Path) -> str:
        """Ermittelt MIME-Type anhand der Dateiendung."""
        suffix = path.suffix.lower()
        mime_map = {
            ".ogg": "audio/ogg",
            ".opus": "audio/ogg",
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".flac": "audio/flac",
        }
        return mime_map.get(suffix, "application/octet-stream")
