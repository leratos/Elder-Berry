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
    DownloadError,
    DownloadResponse,
    JoinError,
    LoginError,
    LoginResponse,
    RoomMessageAudio,
    RoomMessageFile,
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

        # Message-Callbacks registrieren
        self._client.add_event_callback(self._on_room_message, RoomMessageText)
        self._client.add_event_callback(self._on_room_audio, RoomMessageAudio)
        self._client.add_event_callback(self._on_room_file, RoomMessageFile)

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

    async def send_image(self, room_id: str, image_path: Path) -> None:
        """Sendet ein Bild (z.B. Screenshot) als m.image Nachricht.

        Unterstützt PNG, JPEG und weitere gängige Bildformate.
        """
        if not self._connected:
            raise MatrixChannelError("Nicht verbunden")

        if not image_path.exists():
            raise FileNotFoundError(f"Bilddatei nicht gefunden: {image_path}")

        file_size = image_path.stat().st_size
        mime_type = self._guess_image_mime_type(image_path)
        filename = image_path.name

        async with aiofiles.open(image_path, "rb") as f:
            upload_response, _keys = await self._client.upload(
                f,
                content_type=mime_type,
                filename=filename,
                filesize=file_size,
            )

        if isinstance(upload_response, UploadError):
            raise MatrixChannelError(
                f"Bild-Upload fehlgeschlagen: {upload_response.message}"
            )

        content_uri = upload_response.content_uri

        content: dict[str, Any] = {
            "msgtype": "m.image",
            "body": filename,
            "url": content_uri,
            "info": {
                "mimetype": mime_type,
                "size": file_size,
            },
        }

        response = await self._client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )

        if isinstance(response, RoomSendError):
            raise MatrixChannelError(
                f"Bild-Nachricht senden fehlgeschlagen: {response.message}"
            )

        logger.debug(
            "Bild gesendet an %s: %s (%d bytes)", room_id, filename, file_size,
        )

    async def send_file(self, room_id: str, file_path: Path) -> None:
        """Sendet eine beliebige Datei als m.file Nachricht.

        Unterstützt alle Dateitypen. MIME-Type wird anhand der Endung ermittelt.
        """
        if not self._connected:
            raise MatrixChannelError("Nicht verbunden")

        if not file_path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")

        file_size = file_path.stat().st_size
        mime_type = self._guess_file_mime_type(file_path)
        filename = file_path.name

        async with aiofiles.open(file_path, "rb") as f:
            upload_response, _keys = await self._client.upload(
                f,
                content_type=mime_type,
                filename=filename,
                filesize=file_size,
            )

        if isinstance(upload_response, UploadError):
            raise MatrixChannelError(
                f"Datei-Upload fehlgeschlagen: {upload_response.message}"
            )

        content_uri = upload_response.content_uri

        content: dict[str, Any] = {
            "msgtype": "m.file",
            "body": filename,
            "url": content_uri,
            "info": {
                "mimetype": mime_type,
                "size": file_size,
            },
        }

        response = await self._client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )

        if isinstance(response, RoomSendError):
            raise MatrixChannelError(
                f"Datei-Nachricht senden fehlgeschlagen: {response.message}"
            )

        logger.debug(
            "Datei gesendet an %s: %s (%d bytes)", room_id, filename, file_size,
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

    async def _on_room_audio(self, room, event: RoomMessageAudio) -> None:
        """nio-Callback: wird für jede m.room.message (m.audio) aufgerufen.

        Lädt die Audio-Datei vom Matrix-Server herunter und leitet sie
        als IncomingMessage mit audio_data an alle registrierten Callbacks weiter.
        """
        # Eigene Nachrichten ignorieren
        if event.sender == self._user_id:
            return

        # Room-Whitelist prüfen
        if self._allowed_rooms and room.room_id not in self._allowed_rooms:
            logger.debug(
                "Audio-Nachricht aus nicht erlaubtem Raum ignoriert: %s", room.room_id,
            )
            return

        # MXC-URL parsen: mxc://server/mediaid
        mxc_url: str = getattr(event, "url", "") or ""
        if not mxc_url.startswith("mxc://"):
            logger.warning("Audio-Nachricht ohne gültige MXC-URL ignoriert: %s", mxc_url)
            return

        mxc_path = mxc_url[len("mxc://"):]
        if "/" not in mxc_path:
            logger.warning("Ungültige MXC-URL (kein Slash): %s", mxc_url)
            return

        server_name, media_id = mxc_path.split("/", 1)

        # Audio herunterladen (authentifiziert – Synapse 1.94+ erfordert das)
        audio_bytes = await self._authenticated_download(server_name, media_id)
        if audio_bytes is None:
            return
        filename: str = event.body or "voice.ogg"

        logger.debug(
            "Audio empfangen von %s: %s (%d bytes)",
            event.sender, filename, len(audio_bytes),
        )

        msg = IncomingMessage(
            sender=event.sender,
            room_id=room.room_id,
            body=filename,
            timestamp=event.server_timestamp / 1000.0,
            raw=event,
            audio_data=audio_bytes,
        )

        for callback in self._callbacks:
            try:
                await callback(msg)
            except Exception as e:
                logger.error(
                    "Callback-Fehler für Audio-Nachricht von %s: %s", msg.sender, e,
                )

    async def _on_room_file(self, room, event: RoomMessageFile) -> None:
        """nio-Callback: wird für jede m.room.message (m.file) aufgerufen.

        Lädt die Datei vom Matrix-Server herunter und leitet sie
        als IncomingMessage mit file_data an alle registrierten Callbacks weiter.
        """
        # Eigene Nachrichten ignorieren
        if event.sender == self._user_id:
            return

        # Room-Whitelist prüfen
        if self._allowed_rooms and room.room_id not in self._allowed_rooms:
            logger.debug(
                "Datei-Nachricht aus nicht erlaubtem Raum ignoriert: %s", room.room_id,
            )
            return

        # MXC-URL parsen: mxc://server/mediaid
        mxc_url: str = getattr(event, "url", "") or ""
        if not mxc_url.startswith("mxc://"):
            logger.warning("Datei-Nachricht ohne gültige MXC-URL ignoriert: %s", mxc_url)
            return

        mxc_path = mxc_url[len("mxc://"):]
        if "/" not in mxc_path:
            logger.warning("Ungültige MXC-URL (kein Slash): %s", mxc_url)
            return

        server_name, media_id = mxc_path.split("/", 1)

        # Datei herunterladen (authentifiziert)
        file_bytes = await self._authenticated_download(server_name, media_id)
        if file_bytes is None:
            return

        filename: str = event.body or "unknown"

        logger.debug(
            "Datei empfangen von %s: %s (%d bytes)",
            event.sender, filename, len(file_bytes),
        )

        msg = IncomingMessage(
            sender=event.sender,
            room_id=room.room_id,
            body=filename,
            timestamp=event.server_timestamp / 1000.0,
            raw=event,
            file_data=file_bytes,
            file_name=filename,
        )

        for callback in self._callbacks:
            try:
                await callback(msg)
            except Exception as e:
                logger.error(
                    "Callback-Fehler für Datei-Nachricht von %s: %s", msg.sender, e,
                )

    async def _authenticated_download(
        self, server_name: str, media_id: str,
    ) -> bytes | None:
        """Lädt eine Datei vom Matrix-Server (authentifiziert).

        Synapse 1.94+ erfordert authentifizierte Media-Downloads über
        /_matrix/client/v1/media/download statt der alten
        /_matrix/media/v3/download Route.

        Fallback: Wenn die neue API fehlschlägt, wird die alte nio-API probiert.

        Returns:
            Audio-Bytes oder None bei Fehler.
        """
        import aiohttp

        # Neue authentifizierte API (Synapse 1.94+)
        url = (
            f"{self._homeserver}/_matrix/client/v1/media/download"
            f"/{server_name}/{media_id}"
        )
        headers = {"Authorization": f"Bearer {self._client.access_token}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    logger.debug(
                        "Authentifizierter Download HTTP %d, Fallback auf nio",
                        resp.status,
                    )
        except Exception as e:
            logger.debug("Authentifizierter Download fehlgeschlagen: %s", e)

        # Fallback: alte nio-API (unauthentifiziert, für ältere Server)
        try:
            download_resp = await self._client.download(server_name, media_id)
        except Exception as e:
            logger.error("Audio-Download Fehler: %s", e)
            return None

        if isinstance(download_resp, DownloadError):
            logger.error(
                "Audio-Download fehlgeschlagen: %s", download_resp.message,
            )
            return None

        return download_resp.body

    @staticmethod
    def _guess_mime_type(path: Path) -> str:
        """Ermittelt Audio-MIME-Type anhand der Dateiendung."""
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

    @staticmethod
    def _guess_image_mime_type(path: Path) -> str:
        """Ermittelt Bild-MIME-Type anhand der Dateiendung."""
        suffix = path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        return mime_map.get(suffix, "application/octet-stream")

    @staticmethod
    def _guess_file_mime_type(path: Path) -> str:
        """Ermittelt MIME-Type für beliebige Dateien anhand der Dateiendung."""
        suffix = path.suffix.lower()
        mime_map = {
            # Dokumente
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".txt": "text/plain",
            ".csv": "text/csv",
            ".json": "application/json",
            ".xml": "application/xml",
            ".md": "text/markdown",
            ".yaml": "application/x-yaml",
            ".yml": "application/x-yaml",
            # Archive
            ".zip": "application/zip",
            ".tar": "application/x-tar",
            ".gz": "application/gzip",
            ".7z": "application/x-7z-compressed",
            ".rar": "application/vnd.rar",
            # Bilder (Fallback)
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            # Code
            ".py": "text/x-python",
            ".js": "text/javascript",
            ".html": "text/html",
            ".css": "text/css",
            # Audio/Video
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".mp4": "video/mp4",
            ".mkv": "video/x-matroska",
        }
        return mime_map.get(suffix, "application/octet-stream")
