"""Tests: AudioPipeline – Audio-Verarbeitung für die MatrixBridge."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from elder_berry.comms.audio_pipeline import AudioPipeline


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_async(coro):
    """Führt eine Coroutine synchron aus (für Tests ohne pytest-asyncio)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def channel():
    ch = AsyncMock()
    return ch


@pytest.fixture
def assistant():
    return MagicMock()


@pytest.fixture
def chat_history():
    return MagicMock()


@pytest.fixture
def stt():
    engine = MagicMock()
    result = MagicMock()
    result.text = "Hallo Welt"
    result.is_empty.return_value = False
    result.language = "de"
    result.confidence = 0.95
    engine.transcribe.return_value = result
    return engine


@pytest.fixture
def audio_converter():
    conv = MagicMock()
    conv.ffmpeg_available = True
    conv.to_ogg_opus.return_value = (Path("/tmp/out.ogg"), 2.5)
    return conv


@pytest.fixture
def audio_router():
    router = MagicMock()
    router.should_play_local.return_value = False
    return router


@pytest.fixture
def document_reader():
    reader = MagicMock()
    result = MagicMock()
    result.source = "doc.pdf"
    result.pages = 3
    result.truncated = False
    result.text = "Document text..."
    reader.read_file.return_value = result
    return reader


@pytest.fixture
def pipeline(channel, assistant, chat_history, stt, audio_converter, audio_router):
    return AudioPipeline(
        channel=channel,
        assistant=assistant,
        chat_history=chat_history,
        stt=stt,
        audio_converter=audio_converter,
        audio_router=audio_router,
    )


@pytest.fixture
def pipeline_no_stt(channel, assistant, chat_history):
    return AudioPipeline(
        channel=channel,
        assistant=assistant,
        chat_history=chat_history,
        stt=None,
    )


@pytest.fixture
def pipeline_with_doc(channel, assistant, chat_history, document_reader):
    return AudioPipeline(
        channel=channel,
        assistant=assistant,
        chat_history=chat_history,
        document_reader=document_reader,
    )


def _make_audio_msg(audio_data=b"fake_audio", body="voice.ogg"):
    msg = MagicMock()
    msg.sender = "@user:matrix.org"
    msg.room_id = "!room:matrix.org"
    msg.body = body
    msg.audio_data = audio_data
    msg.timestamp = 1711500000.0
    msg.raw = {}
    return msg


def _make_file_msg(file_data=b"fake_pdf", file_name="doc.pdf"):
    msg = MagicMock()
    msg.sender = "@user:matrix.org"
    msg.room_id = "!room:matrix.org"
    msg.body = file_name
    msg.file_name = file_name
    msg.file_data = file_data
    msg.timestamp = 1711500000.0
    msg.raw = {}
    return msg


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestAudioPipelineProperties:
    def test_audio_to_matrix_true(self, pipeline):
        assert pipeline.audio_to_matrix is True

    def test_audio_to_matrix_false_no_converter(self, pipeline_no_stt):
        assert pipeline_no_stt.audio_to_matrix is False

    def test_set_message_callback(self, pipeline):
        cb = AsyncMock()
        pipeline.set_message_callback(cb)
        assert pipeline._on_message_callback is cb


# ---------------------------------------------------------------------------
# Audio Message Handling
# ---------------------------------------------------------------------------

class TestHandleAudioMessage:
    def test_no_stt_sends_warning(self, pipeline_no_stt, channel):
        async def _test():
            msg = _make_audio_msg()
            await pipeline_no_stt.handle_audio_message(msg)
            channel.send_text.assert_called_once()
            text = channel.send_text.call_args[0][1]
            assert "nicht unterstützt" in text.lower() or "STT" in text
        run_async(_test())

    def test_stt_transcribe_and_callback(self, pipeline, stt):
        async def _test():
            msg = _make_audio_msg()
            cb = AsyncMock()
            pipeline.set_message_callback(cb)

            await pipeline.handle_audio_message(msg)

            stt.transcribe.assert_called_once()
            cb.assert_called_once()
            # Callback should receive a text message with transcribed text
            text_msg = cb.call_args[0][0]
            assert text_msg.body == "Hallo Welt"
        run_async(_test())

    def test_stt_empty_result(self, pipeline, stt, channel):
        async def _test():
            stt_result = MagicMock()
            stt_result.is_empty.return_value = True
            stt.transcribe.return_value = stt_result

            msg = _make_audio_msg()
            await pipeline.handle_audio_message(msg)

            channel.send_text.assert_called_once()
            text = channel.send_text.call_args[0][1]
            assert "nicht verstehen" in text.lower()
        run_async(_test())

    def test_stt_exception(self, pipeline, stt, channel):
        async def _test():
            stt.transcribe.side_effect = RuntimeError("STT crash")
            msg = _make_audio_msg()
            await pipeline.handle_audio_message(msg)

            channel.send_text.assert_called_once()
            text = channel.send_text.call_args[0][1]
            assert "RuntimeError" in text
        run_async(_test())


# ---------------------------------------------------------------------------
# File Message Handling
# ---------------------------------------------------------------------------

class TestHandleFileMessage:
    def test_no_document_reader(self, pipeline_no_stt, channel):
        async def _test():
            msg = _make_file_msg()
            await pipeline_no_stt.handle_file_message(msg)
            channel.send_text.assert_called_once()
            text = channel.send_text.call_args[0][1]
            assert "nicht verfügbar" in text.lower()
        run_async(_test())

    def test_unsupported_format(self, pipeline_with_doc, channel):
        async def _test():
            msg = _make_file_msg(file_name="image.jpg")
            await pipeline_with_doc.handle_file_message(msg)
            channel.send_text.assert_called_once()
            text = channel.send_text.call_args[0][1]
            assert "nicht unterstützt" in text.lower()
        run_async(_test())


# ---------------------------------------------------------------------------
# send_audio_if_available
# ---------------------------------------------------------------------------

class TestSendAudioIfAvailable:
    def test_no_audio_path(self, pipeline, channel):
        async def _test():
            result = MagicMock()
            result.audio_path = None
            await pipeline.send_audio_if_available("!room", result, None)
            channel.send_audio.assert_not_called()
        run_async(_test())

    def test_audio_path_nonexistent(self, pipeline, channel):
        async def _test():
            result = MagicMock()
            # Use a MagicMock for audio_path to avoid Path.exists being read-only
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            result.audio_path = mock_path
            await pipeline.send_audio_if_available("!room", result, None)
            channel.send_audio.assert_not_called()
        run_async(_test())

    def test_sends_ogg_to_channel(self, pipeline, channel, audio_converter, tmp_path):
        async def _test():
            wav_file = tmp_path / "audio.wav"
            wav_file.write_bytes(b"RIFF")
            result = MagicMock()
            result.audio_path = wav_file

            await pipeline.send_audio_if_available("!room", result, wav_file)
            audio_converter.to_ogg_opus.assert_called_once()
            channel.send_audio.assert_called_once()
        run_async(_test())
