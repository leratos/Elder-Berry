"""Tests: MatrixChannel – Matrix-Implementierung des MessageChannel."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

nio = pytest.importorskip("nio", reason="matrix-nio nicht installiert")

from nio import (  # noqa: E402
    DownloadError,
    DownloadResponse,
    JoinError,
    JoinResponse,
    LoginError,
    LoginResponse,
    RoomSendError,
    RoomSendResponse,
    UploadError,
    UploadResponse,
)

from elder_berry.comms.matrix_channel import MatrixChannel, MatrixChannelError  # noqa: E402
from elder_berry.comms.message_channel import IncomingMessage, MessageChannel  # noqa: E402


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def run_async(coro):
    """Führt Coroutine synchron aus (kein pytest-asyncio nötig)."""
    return asyncio.run(coro)


def make_channel(**kwargs) -> MatrixChannel:
    """Erstellt einen MatrixChannel mit Test-Defaults."""
    defaults = {
        "homeserver": "https://matrix.test.com",
        "user_id": "@bot:test.com",
        "password": "geheim",
    }
    defaults.update(kwargs)
    return MatrixChannel(**defaults)


def make_login_response() -> LoginResponse:
    """Erstellt eine erfolgreiche LoginResponse."""
    resp = MagicMock(spec=LoginResponse)
    resp.device_id = "TESTDEVICE"
    resp.user_id = "@bot:test.com"
    resp.access_token = "syt_test_token"
    return resp


def make_send_response() -> RoomSendResponse:
    """Erstellt eine erfolgreiche RoomSendResponse."""
    resp = MagicMock(spec=RoomSendResponse)
    resp.event_id = "$test_event_id"
    return resp


def make_upload_response() -> UploadResponse:
    """Erstellt eine erfolgreiche UploadResponse."""
    resp = MagicMock(spec=UploadResponse)
    resp.content_uri = "mxc://test.com/audio123"
    return resp


# ---------------------------------------------------------------------------
# Konstruktor
# ---------------------------------------------------------------------------


class TestMatrixChannelInit:
    def test_implements_interface(self):
        channel = make_channel()
        assert isinstance(channel, MessageChannel)

    def test_requires_password_or_token(self):
        with pytest.raises(ValueError, match="password oder access_token"):
            MatrixChannel(
                homeserver="https://test.com",
                user_id="@bot:test.com",
            )

    def test_accepts_password(self):
        channel = make_channel(password="pw")
        assert not channel.is_connected

    def test_accepts_access_token(self):
        channel = MatrixChannel(
            homeserver="https://test.com",
            user_id="@bot:test.com",
            access_token="syt_token",
        )
        assert not channel.is_connected

    def test_not_connected_initially(self):
        assert not make_channel().is_connected


# ---------------------------------------------------------------------------
# Connect
# ---------------------------------------------------------------------------


class TestConnect:
    def test_login_success(self):
        async def _test():
            channel = make_channel()
            channel._client.login = AsyncMock(return_value=make_login_response())
            channel._client.sync = AsyncMock(return_value=MagicMock())

            await channel.connect()

            assert channel.is_connected
            channel._client.login.assert_called_once_with("geheim")

        run_async(_test())

    def test_login_failure(self):
        async def _test():
            channel = make_channel()
            error = MagicMock(spec=LoginError)
            error.message = "Invalid password"
            channel._client.login = AsyncMock(return_value=error)

            with pytest.raises(MatrixChannelError, match="Login fehlgeschlagen"):
                await channel.connect()

            assert not channel.is_connected

        run_async(_test())

    def test_access_token_login(self):
        async def _test():
            channel = MatrixChannel(
                homeserver="https://test.com",
                user_id="@bot:test.com",
                access_token="syt_existing_token",
            )
            channel._client.sync = AsyncMock(return_value=MagicMock())

            await channel.connect()

            assert channel.is_connected
            assert channel._client.access_token == "syt_existing_token"

        run_async(_test())

    def test_double_connect_no_crash(self):
        async def _test():
            channel = make_channel()
            channel._client.login = AsyncMock(return_value=make_login_response())
            channel._client.sync = AsyncMock(return_value=MagicMock())

            await channel.connect()
            await channel.connect()  # Darf nicht crashen

            # Login nur einmal aufgerufen
            channel._client.login.assert_called_once()

        run_async(_test())


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    def test_disconnect(self):
        async def _test():
            channel = make_channel()
            channel._client.login = AsyncMock(return_value=make_login_response())
            channel._client.sync = AsyncMock(return_value=MagicMock())
            channel._client.close = AsyncMock()

            await channel.connect()
            assert channel.is_connected

            await channel.disconnect()
            assert not channel.is_connected
            channel._client.close.assert_called_once()

        run_async(_test())

    def test_disconnect_when_not_connected(self):
        async def _test():
            channel = make_channel()
            channel._client.close = AsyncMock()
            await channel.disconnect()  # Darf nicht crashen

        run_async(_test())


# ---------------------------------------------------------------------------
# Send Text
# ---------------------------------------------------------------------------


class TestSendText:
    def test_send_text_success(self):
        async def _test():
            channel = make_channel()
            channel._connected = True
            channel._client.room_send = AsyncMock(return_value=make_send_response())

            await channel.send_text("!room:test.com", "Hallo Welt!")

            channel._client.room_send.assert_called_once()
            call_kwargs = channel._client.room_send.call_args.kwargs
            assert call_kwargs["room_id"] == "!room:test.com"
            assert call_kwargs["content"]["body"] == "Hallo Welt!"
            assert call_kwargs["content"]["msgtype"] == "m.text"

        run_async(_test())

    def test_send_text_not_connected(self):
        async def _test():
            channel = make_channel()
            with pytest.raises(MatrixChannelError, match="Nicht verbunden"):
                await channel.send_text("!room:test.com", "test")

        run_async(_test())

    def test_send_text_error(self):
        async def _test():
            channel = make_channel()
            channel._connected = True
            error = MagicMock(spec=RoomSendError)
            error.message = "Permission denied"
            channel._client.room_send = AsyncMock(return_value=error)

            with pytest.raises(MatrixChannelError, match="Senden fehlgeschlagen"):
                await channel.send_text("!room:test.com", "test")

        run_async(_test())


# ---------------------------------------------------------------------------
# Send Audio
# ---------------------------------------------------------------------------


class TestSendAudio:
    def test_send_audio_success(self, tmp_path):
        async def _test():
            channel = make_channel()
            channel._connected = True

            audio_file = tmp_path / "voice.ogg"
            audio_file.write_bytes(b"fake ogg data")

            channel._client.upload = AsyncMock(
                return_value=(make_upload_response(), None),
            )
            channel._client.room_send = AsyncMock(return_value=make_send_response())

            await channel.send_audio("!room:test.com", audio_file)

            # Upload wurde aufgerufen
            channel._client.upload.assert_called_once()
            upload_kwargs = channel._client.upload.call_args.kwargs
            assert upload_kwargs["content_type"] == "audio/ogg"
            assert upload_kwargs["filename"] == "voice.ogg"

            # room_send mit Voice-Flag
            send_kwargs = channel._client.room_send.call_args.kwargs
            content = send_kwargs["content"]
            assert content["msgtype"] == "m.audio"
            assert content["url"] == "mxc://test.com/audio123"
            assert "org.matrix.msc3245.voice" in content

        run_async(_test())

    def test_send_audio_not_connected(self, tmp_path):
        async def _test():
            channel = make_channel()
            audio_file = tmp_path / "voice.ogg"
            audio_file.write_bytes(b"data")

            with pytest.raises(MatrixChannelError, match="Nicht verbunden"):
                await channel.send_audio("!room:test.com", audio_file)

        run_async(_test())

    def test_send_audio_file_not_found(self):
        async def _test():
            channel = make_channel()
            channel._connected = True

            with pytest.raises(FileNotFoundError):
                await channel.send_audio("!room:test.com", Path("/nope.ogg"))

        run_async(_test())

    def test_send_audio_upload_error(self, tmp_path):
        async def _test():
            channel = make_channel()
            channel._connected = True

            audio_file = tmp_path / "voice.ogg"
            audio_file.write_bytes(b"data")

            error = MagicMock(spec=UploadError)
            error.message = "Too large"
            channel._client.upload = AsyncMock(return_value=(error, None))

            with pytest.raises(MatrixChannelError, match="Upload fehlgeschlagen"):
                await channel.send_audio("!room:test.com", audio_file)

        run_async(_test())


# ---------------------------------------------------------------------------
# On Message + Callback
# ---------------------------------------------------------------------------


class TestOnMessage:
    def test_register_callback(self):
        channel = make_channel()
        cb = AsyncMock()
        channel.on_message(cb)
        assert len(channel._callbacks) == 1

    def test_multiple_callbacks(self):
        channel = make_channel()
        channel.on_message(AsyncMock())
        channel.on_message(AsyncMock())
        assert len(channel._callbacks) == 2

    def test_own_messages_ignored(self):
        async def _test():
            channel = make_channel(user_id="@bot:test.com")
            received = []
            channel.on_message(lambda msg: received.append(msg))

            # Simuliere Event von sich selbst
            room = MagicMock()
            room.room_id = "!room:test.com"
            event = MagicMock()
            event.sender = "@bot:test.com"
            event.body = "Echo"
            event.server_timestamp = 1710000000000

            await channel._on_room_message(room, event)
            assert len(received) == 0

        run_async(_test())

    def test_message_from_other_user(self):
        async def _test():
            channel = make_channel(user_id="@bot:test.com")
            received = []

            async def cb(msg):
                received.append(msg)

            channel.on_message(cb)

            room = MagicMock()
            room.room_id = "!room:test.com"
            event = MagicMock()
            event.sender = "@user:test.com"
            event.body = "Hallo Saleria!"
            event.server_timestamp = 1710000000000

            await channel._on_room_message(room, event)

            assert len(received) == 1
            assert received[0].body == "Hallo Saleria!"
            assert received[0].sender == "@user:test.com"
            assert received[0].room_id == "!room:test.com"
            assert isinstance(received[0], IncomingMessage)

        run_async(_test())

    def test_room_whitelist_allowed(self):
        async def _test():
            channel = make_channel(
                allowed_rooms=["!allowed:test.com"],
            )
            received = []

            async def cb(msg):
                received.append(msg)

            channel.on_message(cb)

            room = MagicMock()
            room.room_id = "!allowed:test.com"
            event = MagicMock()
            event.sender = "@user:test.com"
            event.body = "Erlaubt"
            event.server_timestamp = 1710000000000

            await channel._on_room_message(room, event)
            assert len(received) == 1

        run_async(_test())

    def test_room_whitelist_blocked(self):
        async def _test():
            channel = make_channel(
                allowed_rooms=["!allowed:test.com"],
            )
            received = []

            async def cb(msg):
                received.append(msg)

            channel.on_message(cb)

            room = MagicMock()
            room.room_id = "!other:test.com"
            event = MagicMock()
            event.sender = "@user:test.com"
            event.body = "Geblockt"
            event.server_timestamp = 1710000000000

            await channel._on_room_message(room, event)
            assert len(received) == 0

        run_async(_test())

    def test_no_whitelist_allows_all(self):
        async def _test():
            channel = make_channel(allowed_rooms=None)
            received = []

            async def cb(msg):
                received.append(msg)

            channel.on_message(cb)

            room = MagicMock()
            room.room_id = "!any:test.com"
            event = MagicMock()
            event.sender = "@user:test.com"
            event.body = "Egal welcher Raum"
            event.server_timestamp = 1710000000000

            await channel._on_room_message(room, event)
            assert len(received) == 1

        run_async(_test())

    def test_callback_error_no_crash(self):
        async def _test():
            channel = make_channel()

            async def bad_cb(msg):
                raise RuntimeError("Callback kaputt")

            channel.on_message(bad_cb)

            room = MagicMock()
            room.room_id = "!room:test.com"
            event = MagicMock()
            event.sender = "@user:test.com"
            event.body = "Test"
            event.server_timestamp = 1710000000000

            # Darf nicht crashen
            await channel._on_room_message(room, event)

        run_async(_test())

    def test_timestamp_conversion(self):
        async def _test():
            channel = make_channel()
            received = []

            async def cb(msg):
                received.append(msg)

            channel.on_message(cb)

            room = MagicMock()
            room.room_id = "!room:test.com"
            event = MagicMock()
            event.sender = "@user:test.com"
            event.body = "Test"
            event.server_timestamp = 1710000000000  # Millisekunden

            await channel._on_room_message(room, event)

            # server_timestamp ist in ms, IncomingMessage in Sekunden
            assert received[0].timestamp == 1710000000.0

        run_async(_test())


# ---------------------------------------------------------------------------
# Sync-Loop
# ---------------------------------------------------------------------------


class TestSyncLoop:
    def test_sync_loop_not_connected(self):
        async def _test():
            channel = make_channel()
            with pytest.raises(MatrixChannelError, match="Nicht verbunden"):
                await channel.sync_loop()

        run_async(_test())

    def test_sync_loop_stops_on_disconnect(self):
        async def _test():
            channel = make_channel()
            channel._connected = True

            call_count = 0

            async def fake_sync(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count >= 3:
                    channel._should_sync = False
                return MagicMock()

            channel._client.sync = fake_sync

            await channel.sync_loop()
            assert call_count == 3

        run_async(_test())

    def test_sync_loop_retries_on_error(self):
        async def _test():
            channel = make_channel()
            channel._connected = True

            call_count = 0

            async def flaky_sync(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ConnectionError("Netzwerk weg")
                channel._should_sync = False
                return MagicMock()

            channel._client.sync = flaky_sync

            # Patch sleep damit der Test schnell läuft
            with patch(
                "elder_berry.comms.matrix_channel.asyncio.sleep", new_callable=AsyncMock
            ):
                await channel.sync_loop()

            assert call_count == 2

        run_async(_test())


# ---------------------------------------------------------------------------
# MIME-Type
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Send Image
# ---------------------------------------------------------------------------


class TestSendImage:
    def test_send_image_success(self, tmp_path):
        async def _test():
            channel = make_channel()
            channel._connected = True

            img_file = tmp_path / "screenshot.png"
            img_file.write_bytes(b"\x89PNG" + b"\x00" * 100)

            channel._client.upload = AsyncMock(
                return_value=(make_upload_response(), None),
            )
            channel._client.room_send = AsyncMock(return_value=make_send_response())

            await channel.send_image("!room:test.com", img_file)

            # Upload wurde aufgerufen
            channel._client.upload.assert_called_once()
            upload_kwargs = channel._client.upload.call_args.kwargs
            assert upload_kwargs["content_type"] == "image/png"
            assert upload_kwargs["filename"] == "screenshot.png"

            # room_send mit m.image
            send_kwargs = channel._client.room_send.call_args.kwargs
            content = send_kwargs["content"]
            assert content["msgtype"] == "m.image"
            assert content["url"] == "mxc://test.com/audio123"

        run_async(_test())

    def test_send_image_not_connected(self, tmp_path):
        async def _test():
            channel = make_channel()
            img_file = tmp_path / "screen.png"
            img_file.write_bytes(b"data")

            with pytest.raises(MatrixChannelError, match="Nicht verbunden"):
                await channel.send_image("!room:test.com", img_file)

        run_async(_test())

    def test_send_image_file_not_found(self):
        async def _test():
            channel = make_channel()
            channel._connected = True

            with pytest.raises(FileNotFoundError):
                await channel.send_image("!room:test.com", Path("/nope.png"))

        run_async(_test())

    def test_send_image_upload_error(self, tmp_path):
        async def _test():
            channel = make_channel()
            channel._connected = True

            img_file = tmp_path / "screen.png"
            img_file.write_bytes(b"data")

            error = MagicMock(spec=UploadError)
            error.message = "Too large"
            channel._client.upload = AsyncMock(return_value=(error, None))

            with pytest.raises(MatrixChannelError, match="Bild-Upload fehlgeschlagen"):
                await channel.send_image("!room:test.com", img_file)

        run_async(_test())

    def test_send_image_jpeg(self, tmp_path):
        async def _test():
            channel = make_channel()
            channel._connected = True

            img_file = tmp_path / "photo.jpg"
            img_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 50)

            channel._client.upload = AsyncMock(
                return_value=(make_upload_response(), None),
            )
            channel._client.room_send = AsyncMock(return_value=make_send_response())

            await channel.send_image("!room:test.com", img_file)

            upload_kwargs = channel._client.upload.call_args.kwargs
            assert upload_kwargs["content_type"] == "image/jpeg"

        run_async(_test())


class TestMimeType:
    def test_ogg(self):
        assert MatrixChannel._guess_mime_type(Path("voice.ogg")) == "audio/ogg"

    def test_wav(self):
        assert MatrixChannel._guess_mime_type(Path("audio.wav")) == "audio/wav"

    def test_mp3(self):
        assert MatrixChannel._guess_mime_type(Path("song.mp3")) == "audio/mpeg"

    def test_unknown(self):
        assert (
            MatrixChannel._guess_mime_type(Path("file.xyz"))
            == "application/octet-stream"
        )

    def test_opus(self):
        assert MatrixChannel._guess_mime_type(Path("voice.opus")) == "audio/ogg"


# ---------------------------------------------------------------------------
# Auto-Join
# ---------------------------------------------------------------------------


class TestAutoJoin:
    def test_auto_join_invited_room(self):
        async def _test():
            channel = make_channel(allowed_rooms=["!room:test.com"])

            # Simuliere invited_rooms
            channel._client.invited_rooms = {"!room:test.com": MagicMock()}
            join_resp = MagicMock(spec=JoinResponse)
            channel._client.join = AsyncMock(return_value=join_resp)

            await channel._auto_join_invited_rooms()

            channel._client.join.assert_called_once_with("!room:test.com")

        run_async(_test())

    def test_auto_join_skips_non_whitelisted(self):
        async def _test():
            channel = make_channel(allowed_rooms=["!allowed:test.com"])

            channel._client.invited_rooms = {"!other:test.com": MagicMock()}
            channel._client.join = AsyncMock()

            await channel._auto_join_invited_rooms()

            channel._client.join.assert_not_called()

        run_async(_test())

    def test_auto_join_no_whitelist_joins_all(self):
        async def _test():
            channel = make_channel(allowed_rooms=None)

            channel._client.invited_rooms = {
                "!a:test.com": MagicMock(),
                "!b:test.com": MagicMock(),
            }
            join_resp = MagicMock(spec=JoinResponse)
            channel._client.join = AsyncMock(return_value=join_resp)

            await channel._auto_join_invited_rooms()

            assert channel._client.join.call_count == 2

        run_async(_test())

    def test_auto_join_handles_error(self):
        async def _test():
            channel = make_channel(allowed_rooms=["!room:test.com"])

            channel._client.invited_rooms = {"!room:test.com": MagicMock()}
            error = MagicMock(spec=JoinError)
            error.message = "Forbidden"
            channel._client.join = AsyncMock(return_value=error)

            # Darf nicht crashen
            await channel._auto_join_invited_rooms()

        run_async(_test())

    def test_auto_join_no_invites(self):
        async def _test():
            channel = make_channel()
            channel._client.invited_rooms = {}
            channel._client.join = AsyncMock()

            await channel._auto_join_invited_rooms()

            channel._client.join.assert_not_called()

        run_async(_test())


# ---------------------------------------------------------------------------
# Image MIME-Type
# ---------------------------------------------------------------------------


class TestImageMimeType:
    def test_png(self):
        assert MatrixChannel._guess_image_mime_type(Path("screen.png")) == "image/png"

    def test_jpg(self):
        assert MatrixChannel._guess_image_mime_type(Path("photo.jpg")) == "image/jpeg"

    def test_jpeg(self):
        assert MatrixChannel._guess_image_mime_type(Path("photo.jpeg")) == "image/jpeg"

    def test_gif(self):
        assert MatrixChannel._guess_image_mime_type(Path("anim.gif")) == "image/gif"

    def test_webp(self):
        assert MatrixChannel._guess_image_mime_type(Path("img.webp")) == "image/webp"

    def test_unknown(self):
        assert (
            MatrixChannel._guess_image_mime_type(Path("file.xyz"))
            == "application/octet-stream"
        )


# ---------------------------------------------------------------------------
# _on_room_audio – Eingehende Sprachnachrichten
# ---------------------------------------------------------------------------


def make_audio_event(
    sender: str = "@user:test.com",
    body: str = "voice-message.ogg",
    url: str = "mxc://matrix.test.com/audioabc123",
    timestamp_ms: int = 1710000000000,
) -> MagicMock:
    """Erstellt ein Mock-RoomMessageAudio-Event."""
    event = MagicMock()
    event.sender = sender
    event.body = body
    event.url = url
    event.server_timestamp = timestamp_ms
    return event


class TestOnRoomAudio:
    def test_audio_own_message_ignored(self):
        """Eigene Audio-Nachrichten werden ignoriert."""

        async def _test():
            channel = make_channel(user_id="@bot:test.com")
            received = []
            channel.on_message(lambda msg: received.append(msg))

            room = MagicMock()
            room.room_id = "!room:test.com"
            event = make_audio_event(sender="@bot:test.com")

            await channel._on_room_audio(room, event)
            assert len(received) == 0

        run_async(_test())

    def test_audio_room_whitelist_blocked(self):
        """Nachrichten aus nicht erlaubten Räumen werden ignoriert."""

        async def _test():
            channel = make_channel(allowed_rooms=["!allowed:test.com"])
            received = []
            channel.on_message(lambda msg: received.append(msg))

            room = MagicMock()
            room.room_id = "!other:test.com"
            event = make_audio_event()

            await channel._on_room_audio(room, event)
            assert len(received) == 0

        run_async(_test())

    def test_audio_invalid_mxc_url_ignored(self):
        """Event ohne gültige mxc://-URL wird ignoriert."""

        async def _test():
            channel = make_channel()
            received = []
            channel.on_message(lambda msg: received.append(msg))

            room = MagicMock()
            room.room_id = "!room:test.com"
            event = make_audio_event(url="https://example.com/file.ogg")

            await channel._on_room_audio(room, event)
            assert len(received) == 0

        run_async(_test())

    def test_audio_download_error_no_callback(self):
        """Download-Fehler verhindert Callback (kein Crash)."""

        async def _test():
            channel = make_channel()
            received = []
            channel.on_message(lambda msg: received.append(msg))

            room = MagicMock()
            room.room_id = "!room:test.com"
            event = make_audio_event()

            error = MagicMock(spec=DownloadError)
            error.message = "Not found"
            channel._client.download = AsyncMock(return_value=error)

            await channel._on_room_audio(room, event)
            assert len(received) == 0

        run_async(_test())

    def test_audio_download_success_fires_callback(self):
        """Erfolgreicher Download: Callback mit audio_data wird aufgerufen."""

        async def _test():
            channel = make_channel()
            received = []

            async def cb(msg):
                received.append(msg)

            channel.on_message(cb)

            room = MagicMock()
            room.room_id = "!room:test.com"
            event = make_audio_event(
                sender="@user:test.com",
                body="voice.ogg",
                url="mxc://matrix.test.com/abc123",
            )

            audio_bytes = b"\x00\x01\x02\x03" * 100
            download_resp = MagicMock(spec=DownloadResponse)
            download_resp.body = audio_bytes
            channel._client.download = AsyncMock(return_value=download_resp)

            await channel._on_room_audio(room, event)

            assert len(received) == 1
            msg = received[0]
            assert isinstance(msg, IncomingMessage)
            assert msg.sender == "@user:test.com"
            assert msg.room_id == "!room:test.com"
            assert msg.body == "voice.ogg"
            assert msg.audio_data == audio_bytes
            assert msg.timestamp == 1710000000.0

        run_async(_test())

    def test_audio_download_calls_correct_server_and_media_id(self):
        """Download-Aufruf nutzt Server-Name und Media-ID aus MXC-URL."""

        async def _test():
            channel = make_channel()

            room = MagicMock()
            room.room_id = "!room:test.com"
            event = make_audio_event(url="mxc://matrix.example.org/XYZ987")

            download_resp = MagicMock(spec=DownloadResponse)
            download_resp.body = b"audio"
            channel._client.download = AsyncMock(return_value=download_resp)

            channel.on_message(AsyncMock())
            await channel._on_room_audio(room, event)

            channel._client.download.assert_called_once_with(
                "matrix.example.org",
                "XYZ987",
            )

        run_async(_test())

    def test_audio_callback_error_no_crash(self):
        """Fehlerhafter Callback darf nicht crashen."""

        async def _test():
            channel = make_channel()

            async def bad_cb(msg):
                raise RuntimeError("Callback-Fehler")

            channel.on_message(bad_cb)

            room = MagicMock()
            room.room_id = "!room:test.com"
            event = make_audio_event()

            download_resp = MagicMock(spec=DownloadResponse)
            download_resp.body = b"audio"
            channel._client.download = AsyncMock(return_value=download_resp)

            # Darf nicht crashen
            await channel._on_room_audio(room, event)

        run_async(_test())

    def test_audio_registered_in_connect(self):
        """_on_room_audio wird in connect() als Callback registriert."""

        async def _test():
            from nio import RoomMessageAudio

            channel = make_channel()
            login_resp = make_login_response()

            channel._client.login = AsyncMock(return_value=login_resp)
            channel._client.sync = AsyncMock(return_value=MagicMock())
            channel._client.invited_rooms = {}

            registered_callbacks = {}

            def fake_add_callback(cb, event_type):
                registered_callbacks[event_type] = cb

            channel._client.add_event_callback = fake_add_callback

            await channel.connect()

            assert RoomMessageAudio in registered_callbacks
            assert registered_callbacks[RoomMessageAudio] == channel._on_room_audio

        run_async(_test())
