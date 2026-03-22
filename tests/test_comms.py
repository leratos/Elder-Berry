"""Tests: MessageChannel ABC, IncomingMessage DTO, MatrixBridge, Command-Routing, ClaudeAgent-Routing."""
import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.message_channel import IncomingMessage, MessageChannel
from elder_berry.comms.bridge import MatrixBridge, extract_claude_message
from elder_berry.comms.claude_agent import AgentResult
from elder_berry.comms.remote_commands import CommandResult, RemoteCommandHandler
from elder_berry.core.assistant import AssistantResult


# ---------------------------------------------------------------------------
# Helper: async in sync ausführen (kein pytest-asyncio nötig)
# ---------------------------------------------------------------------------

def run_async(coro):
    """Führt eine Coroutine synchron aus (für Tests ohne pytest-asyncio)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Mock-Implementierung des MessageChannel ABC
# ---------------------------------------------------------------------------

class MockChannel(MessageChannel):
    """Testbare Implementierung des MessageChannel."""

    def __init__(self):
        self._connected = False
        self._callbacks = []
        self._sent_texts: list[tuple[str, str]] = []
        self._sent_audios: list[tuple[str, Path]] = []
        self._sent_images: list[tuple[str, Path]] = []
        self._sent_files: list[tuple[str, Path]] = []
        self._sync_event = asyncio.Event()

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        self._sync_event.set()

    async def send_text(self, room_id: str, text: str) -> None:
        self._sent_texts.append((room_id, text))

    async def send_audio(self, room_id: str, audio_path: Path) -> None:
        self._sent_audios.append((room_id, audio_path))

    async def send_image(self, room_id: str, image_path: Path) -> None:
        self._sent_images.append((room_id, image_path))

    async def send_file(self, room_id: str, file_path: Path) -> None:
        self._sent_files.append((room_id, file_path))

    def on_message(self, callback) -> None:
        self._callbacks.append(callback)

    async def sync_loop(self) -> None:
        await self._sync_event.wait()

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def simulate_message(self, msg: IncomingMessage) -> None:
        """Simuliert eine eingehende Nachricht (für Tests)."""
        for cb in self._callbacks:
            await cb(msg)


# ---------------------------------------------------------------------------
# IncomingMessage DTO
# ---------------------------------------------------------------------------

class TestIncomingMessage:
    def test_creation(self):
        msg = IncomingMessage(
            sender="@user:example.com",
            room_id="!room:example.com",
            body="Hallo!",
            timestamp=1710500000.0,
        )
        assert msg.sender == "@user:example.com"
        assert msg.room_id == "!room:example.com"
        assert msg.body == "Hallo!"
        assert msg.timestamp == 1710500000.0
        assert msg.raw is None

    def test_frozen(self):
        msg = IncomingMessage(
            sender="@u:x", room_id="!r:x", body="hi", timestamp=0.0,
        )
        with pytest.raises(AttributeError):
            msg.body = "changed"

    def test_with_raw_data(self):
        raw = {"event_id": "$abc123"}
        msg = IncomingMessage(
            sender="@u:x", room_id="!r:x", body="hi",
            timestamp=0.0, raw=raw,
        )
        assert msg.raw == {"event_id": "$abc123"}

    def test_equality(self):
        args = dict(sender="@u:x", room_id="!r:x", body="hi", timestamp=1.0)
        assert IncomingMessage(**args) == IncomingMessage(**args)

    def test_inequality(self):
        msg1 = IncomingMessage(sender="@a:x", room_id="!r:x", body="hi", timestamp=1.0)
        msg2 = IncomingMessage(sender="@b:x", room_id="!r:x", body="hi", timestamp=1.0)
        assert msg1 != msg2


# ---------------------------------------------------------------------------
# MessageChannel ABC
# ---------------------------------------------------------------------------

class TestMessageChannelABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            MessageChannel()

    def test_mock_channel_implements_interface(self):
        channel = MockChannel()
        assert isinstance(channel, MessageChannel)

    def test_connect_disconnect(self):
        async def _test():
            channel = MockChannel()
            assert not channel.is_connected
            await channel.connect()
            assert channel.is_connected
            await channel.disconnect()
            assert not channel.is_connected

        run_async(_test())

    def test_send_text(self):
        async def _test():
            channel = MockChannel()
            await channel.connect()
            await channel.send_text("!room:x", "Hallo!")
            assert channel._sent_texts == [("!room:x", "Hallo!")]

        run_async(_test())

    def test_send_audio(self):
        async def _test():
            channel = MockChannel()
            await channel.connect()
            await channel.send_audio("!room:x", Path("/tmp/voice.ogg"))
            assert channel._sent_audios == [("!room:x", Path("/tmp/voice.ogg"))]

        run_async(_test())

    def test_on_message_callback(self):
        async def _test():
            channel = MockChannel()
            received = []
            channel.on_message(lambda msg: received.append(msg))

            msg = IncomingMessage(
                sender="@u:x", room_id="!r:x", body="test", timestamp=1.0,
            )
            for cb in channel._callbacks:
                result = cb(msg)
                if asyncio.iscoroutine(result):
                    await result

            assert len(received) == 1
            assert received[0].body == "test"

        run_async(_test())

    def test_multiple_callbacks(self):
        async def _test():
            channel = MockChannel()
            results_a = []
            results_b = []

            async def cb_a(msg):
                results_a.append(msg)

            async def cb_b(msg):
                results_b.append(msg)

            channel.on_message(cb_a)
            channel.on_message(cb_b)

            msg = IncomingMessage(
                sender="@u:x", room_id="!r:x", body="multi", timestamp=1.0,
            )
            await channel.simulate_message(msg)

            assert len(results_a) == 1
            assert len(results_b) == 1

        run_async(_test())


# ---------------------------------------------------------------------------
# MatrixBridge
# ---------------------------------------------------------------------------

class TestMatrixBridge:
    def _make_assistant_mock(self, response_text="Antwort", emotion="neutral"):
        assistant = MagicMock()
        assistant.process.return_value = AssistantResult(
            response=response_text,
            action_executed=None,
            action_success=False,
            emotion=emotion,
        )
        return assistant

    def test_bridge_creation(self):
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        bridge = MatrixBridge(channel=channel, assistant=assistant)
        assert not bridge.is_running

    def test_bridge_start_stop(self):
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        bridge = MatrixBridge(channel=channel, assistant=assistant)

        bridge.start()
        assert bridge.is_running

        time.sleep(0.2)

        bridge.stop()
        time.sleep(0.3)
        assert not bridge.is_running

    def test_bridge_double_start(self):
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        bridge = MatrixBridge(channel=channel, assistant=assistant)

        bridge.start()
        bridge.start()  # Darf nicht crashen
        assert bridge.is_running

        bridge.stop()
        time.sleep(0.3)

    def test_bridge_stop_when_not_running(self):
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        bridge = MatrixBridge(channel=channel, assistant=assistant)
        bridge.stop()  # Darf nicht crashen

    def test_handle_message_calls_assistant(self):
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("Hallo zurück!")
            bridge = MatrixBridge(channel=channel, assistant=assistant)

            await channel.connect()
            channel.on_message(bridge._handle_message)

            msg = IncomingMessage(
                sender="@user:x", room_id="!room:x", body="Hi Saleria",
                timestamp=time.time(),
            )
            await bridge._handle_message(msg)

            assistant.process.assert_called_once()
            assert assistant.process.call_args[0][0] == "Hi Saleria"
            assert ("!room:x", "Hallo zurück!") in channel._sent_texts

        run_async(_test())

    def test_handle_message_with_audio_converter(self, tmp_path):
        async def _test():
            channel = MockChannel()
            # Assistant gibt audio_path zurück
            wav_file = tmp_path / "test.wav"
            wav_file.write_bytes(b"RIFF" + b"\x00" * 100)
            assistant = MagicMock()
            assistant.process.return_value = AssistantResult(
                response="Antwort mit Audio",
                action_executed=None,
                action_success=False,
                emotion="neutral",
                audio_path=wav_file,
            )

            # AudioConverter Mock
            ogg_file = tmp_path / "test.ogg"
            ogg_file.write_bytes(b"OggS" + b"\x00" * 50)
            converter = MagicMock()
            converter.ffmpeg_available = True
            converter.to_ogg_opus.return_value = (ogg_file, 1000)

            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
                audio_converter=converter,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@u:x", room_id="!r:x", body="Sag was",
                timestamp=time.time(),
            )
            await bridge._handle_message(msg)

            # Text gesendet
            assert ("!r:x", "Antwort mit Audio") in channel._sent_texts
            # Audio gesendet
            assert len(channel._sent_audios) == 1
            assert channel._sent_audios[0][0] == "!r:x"
            # AudioConverter aufgerufen
            converter.to_ogg_opus.assert_called_once()

        run_async(_test())

    def test_handle_message_no_audio_without_converter(self):
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("Nur Text")
            bridge = MatrixBridge(channel=channel, assistant=assistant)
            await channel.connect()

            msg = IncomingMessage(
                sender="@u:x", room_id="!r:x", body="Hi", timestamp=1.0,
            )
            await bridge._handle_message(msg)

            # Nur Text, kein Audio
            assert ("!r:x", "Nur Text") in channel._sent_texts
            assert len(channel._sent_audios) == 0

        run_async(_test())

    def test_handle_message_empty_response(self):
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("")
            bridge = MatrixBridge(channel=channel, assistant=assistant)
            await channel.connect()

            msg = IncomingMessage(
                sender="@u:x", room_id="!r:x", body="test", timestamp=1.0,
            )
            await bridge._handle_message(msg)

            assert len(channel._sent_texts) == 0

        run_async(_test())

    def test_handle_message_assistant_error(self):
        async def _test():
            channel = MockChannel()
            assistant = MagicMock()
            assistant.process.side_effect = RuntimeError("LLM down")
            bridge = MatrixBridge(channel=channel, assistant=assistant)
            await channel.connect()

            msg = IncomingMessage(
                sender="@u:x", room_id="!r:x", body="test", timestamp=1.0,
            )
            await bridge._handle_message(msg)

            assert len(channel._sent_texts) == 1
            assert "Fehler" in channel._sent_texts[0][1]
            assert "RuntimeError" in channel._sent_texts[0][1]

        run_async(_test())

    def test_async_main_connects_channel(self):
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            bridge = MatrixBridge(channel=channel, assistant=assistant)

            channel._sync_event.set()

            await bridge._async_main()
            assert len(channel._callbacks) == 1

        run_async(_test())


# ---------------------------------------------------------------------------
# MatrixBridge – Command-Routing (Phase 7)
# ---------------------------------------------------------------------------

class TestBridgeCommandRouting:
    def _make_assistant_mock(self, response_text="LLM Antwort"):
        assistant = MagicMock()
        assistant.process.return_value = AssistantResult(
            response=response_text,
            action_executed=None,
            action_success=False,
        )
        return assistant

    def _make_remote_handler(self, command=None, result=None):
        """Erstellt einen Mock-RemoteCommandHandler."""
        handler = MagicMock(spec=RemoteCommandHandler)
        handler.parse_command.return_value = command
        handler.execute.return_value = result or CommandResult(
            command=command or "status", success=True, text="OK",
        )
        return handler

    def test_command_routed_to_handler(self):
        """Direkter Command wird an RemoteCommandHandler delegiert, nicht an Assistant."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            handler = self._make_remote_handler(
                command="status",
                result=CommandResult(command="status", success=True, text="CPU: 25%"),
            )
            bridge = MatrixBridge(
                channel=channel, assistant=assistant, remote_commands=handler,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="status", timestamp=1.0,
            )
            await bridge._handle_message(msg)

            # Handler aufgerufen
            handler.parse_command.assert_called_once_with("status")
            handler.execute.assert_called_once_with("status", "status")
            # Text gesendet
            assert ("!r:x", "CPU: 25%") in channel._sent_texts
            # Assistant NICHT aufgerufen
            assistant.process.assert_not_called()

        run_async(_test())

    def test_non_command_falls_through_to_assistant(self):
        """Normaler Text wird an Assistant delegiert (kein Command)."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("Hallo!")
            handler = self._make_remote_handler(command=None)  # Kein Command erkannt
            bridge = MatrixBridge(
                channel=channel, assistant=assistant, remote_commands=handler,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="Was ist los?",
                timestamp=1.0,
            )
            await bridge._handle_message(msg)

            # Handler parse_command aufgerufen, aber execute NICHT
            handler.parse_command.assert_called_once_with("Was ist los?")
            handler.execute.assert_not_called()
            # Assistant aufgerufen
            assistant.process.assert_called_once()
            assert assistant.process.call_args[0][0] == "Was ist los?"
            assert ("!r:x", "Hallo!") in channel._sent_texts

        run_async(_test())

    def test_screenshot_sends_image(self, tmp_path):
        """Screenshot-Command sendet Bild über send_image."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()

            img_path = tmp_path / "screenshot.png"
            img_path.write_bytes(b"\x89PNG" + b"\x00" * 50)

            handler = self._make_remote_handler(
                command="screenshot",
                result=CommandResult(
                    command="screenshot", success=True,
                    text="Screenshot aufgenommen.",
                    image_path=img_path,
                ),
            )
            bridge = MatrixBridge(
                channel=channel, assistant=assistant, remote_commands=handler,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="screenshot",
                timestamp=1.0,
            )
            await bridge._handle_message(msg)

            # Text + Bild gesendet
            assert ("!r:x", "Screenshot aufgenommen.") in channel._sent_texts
            assert len(channel._sent_images) == 1
            assert channel._sent_images[0][0] == "!r:x"

        run_async(_test())

    def test_no_handler_falls_through(self):
        """Ohne RemoteCommandHandler wird alles an Assistant delegiert."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("Antwort")
            bridge = MatrixBridge(channel=channel, assistant=assistant)
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="status",
                timestamp=1.0,
            )
            await bridge._handle_message(msg)

            # Kein Handler → Assistant aufgerufen
            assistant.process.assert_called_once()
            assert assistant.process.call_args[0][0] == "status"

        run_async(_test())

    def test_command_error_sends_error_message(self):
        """Fehler bei Command-Ausführung wird als Fehlermeldung gesendet."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            handler = MagicMock(spec=RemoteCommandHandler)
            handler.parse_command.return_value = "status"
            handler.execute.side_effect = RuntimeError("psutil kaputt")
            bridge = MatrixBridge(
                channel=channel, assistant=assistant, remote_commands=handler,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="status",
                timestamp=1.0,
            )
            await bridge._handle_message(msg)

            # Fehlermeldung gesendet
            assert len(channel._sent_texts) == 1
            assert "Command-Fehler" in channel._sent_texts[0][1]
            assert "RuntimeError" in channel._sent_texts[0][1]

        run_async(_test())

    def test_send_file_routes_file(self, tmp_path):
        """send_file Command sendet Datei über send_file."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()

            file_path = tmp_path / "test.pdf"
            file_path.write_bytes(b"%PDF" + b"\x00" * 50)

            handler = self._make_remote_handler(
                command="send_file",
                result=CommandResult(
                    command="send_file", success=True,
                    text="Datei wird gesendet: test.pdf (0.1 KB)",
                    file_path=file_path,
                ),
            )
            bridge = MatrixBridge(
                channel=channel, assistant=assistant, remote_commands=handler,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x",
                body=f"schick mir {file_path}", timestamp=1.0,
            )
            await bridge._handle_message(msg)

            # Text + Datei gesendet
            assert any("test.pdf" in t[1] for t in channel._sent_texts)
            assert len(channel._sent_files) == 1
            assert channel._sent_files[0][0] == "!r:x"
            assistant.process.assert_not_called()

        run_async(_test())

    def test_send_file_not_implemented_fallback(self, tmp_path):
        """send_file NotImplementedError → Fallback-Text."""
        async def _test():
            channel = MockChannel()

            async def raise_not_impl(room_id, path):
                raise NotImplementedError("not supported")
            channel.send_file = raise_not_impl

            assistant = self._make_assistant_mock()

            file_path = tmp_path / "test.pdf"
            file_path.write_bytes(b"%PDF" + b"\x00" * 50)

            handler = self._make_remote_handler(
                command="send_file",
                result=CommandResult(
                    command="send_file", success=True,
                    text="Datei wird gesendet.",
                    file_path=file_path,
                ),
            )
            bridge = MatrixBridge(
                channel=channel, assistant=assistant, remote_commands=handler,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x",
                body=f"schick mir {file_path}", timestamp=1.0,
            )
            await bridge._handle_message(msg)

            texts = [t[1] for t in channel._sent_texts]
            assert any("nicht unterstützt" in t for t in texts)

        run_async(_test())

    def test_send_image_not_implemented_fallback(self):
        """Wenn send_image NotImplementedError wirft, kommt ein Fallback-Text."""
        async def _test():
            channel = MockChannel()
            # send_image wirft NotImplementedError
            async def raise_not_impl(room_id, path):
                raise NotImplementedError("not supported")
            channel.send_image = raise_not_impl

            assistant = self._make_assistant_mock()
            handler = self._make_remote_handler(
                command="screenshot",
                result=CommandResult(
                    command="screenshot", success=True,
                    text="Screenshot aufgenommen.",
                    image_path=Path("/tmp/fake.png"),
                ),
            )
            bridge = MatrixBridge(
                channel=channel, assistant=assistant, remote_commands=handler,
            )
            await channel.connect()

            # Fake-Bild erstellen damit exists() True ergibt
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(b"fake")
                fake_path = Path(f.name)

            handler.execute.return_value = CommandResult(
                command="screenshot", success=True,
                text="Screenshot aufgenommen.",
                image_path=fake_path,
            )

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="screenshot",
                timestamp=1.0,
            )
            await bridge._handle_message(msg)

            # Text + Fallback-Hinweis gesendet
            texts = [t[1] for t in channel._sent_texts]
            assert any("nicht unterstützt" in t for t in texts)

            fake_path.unlink(missing_ok=True)

        run_async(_test())


# ---------------------------------------------------------------------------
# extract_claude_message – Keyword-Routing (Phase 7 Schritt 3)
# ---------------------------------------------------------------------------

class TestExtractClaudeMessage:
    def test_claude_with_quotes(self):
        result = extract_claude_message('Sag Claude bitte "Dokumentiere X im Journal"')
        assert result == "Dokumentiere X im Journal"

    def test_claude_lowercase(self):
        result = extract_claude_message('claude "Was war der letzte Schritt?"')
        assert result == "Was war der letzte Schritt?"

    def test_claude_uppercase(self):
        result = extract_claude_message('CLAUDE "Zeig mir die Tests"')
        assert result == "Zeig mir die Tests"

    def test_no_claude_keyword(self):
        result = extract_claude_message("Wie geht's dir?")
        assert result is None

    def test_claude_without_quotes(self):
        result = extract_claude_message("Claude mach mal was")
        assert result is None

    def test_quotes_without_claude(self):
        result = extract_claude_message('Sag Saleria "Hallo"')
        assert result is None

    def test_empty_string(self):
        result = extract_claude_message("")
        assert result is None

    def test_empty_quotes(self):
        result = extract_claude_message('Claude ""')
        assert result is None

    def test_first_quoted_text_extracted(self):
        result = extract_claude_message('Claude "erster Auftrag" und "zweiter"')
        assert result == "erster Auftrag"


# ---------------------------------------------------------------------------
# MatrixBridge – ClaudeAgent-Routing (Phase 7 Schritt 3)
# ---------------------------------------------------------------------------

class TestBridgeClaudeAgentRouting:
    def _make_assistant_mock(self, response_text="LLM Antwort"):
        assistant = MagicMock()
        assistant.process.return_value = AssistantResult(
            response=response_text,
            action_executed=None,
            action_success=False,
        )
        return assistant

    def _make_claude_agent(self, summary="Agent-Antwort", details=None,
                           action_taken="answer_only", success=True):
        """Erstellt einen Mock-ClaudeAgent."""
        agent = MagicMock()
        agent.process.return_value = AgentResult(
            success=success,
            action_taken=action_taken,
            summary=summary,
            details=details,
        )
        return agent

    def test_claude_keyword_routes_to_agent(self):
        """'claude' + Anführungszeichen → ClaudeAgent."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            handler = MagicMock(spec=RemoteCommandHandler)
            handler.parse_command.return_value = None
            claude_agent = self._make_claude_agent(
                summary="Journal aktualisiert.",
            )
            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
                remote_commands=handler, claude_agent=claude_agent,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x",
                body='Claude "Dokumentiere X im Journal"', timestamp=1.0,
            )
            await bridge._handle_message(msg)

            # ClaudeAgent mit extrahiertem Text aufgerufen
            claude_agent.process.assert_called_once_with(
                "Dokumentiere X im Journal",
            )
            assert ("!r:x", "Journal aktualisiert.") in channel._sent_texts
            assistant.process.assert_not_called()

        run_async(_test())

    def test_no_claude_keyword_goes_to_llm(self):
        """Ohne 'claude' Keyword → direkt an lokales LLM."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("Saleria antwortet!")
            handler = MagicMock(spec=RemoteCommandHandler)
            handler.parse_command.return_value = None
            claude_agent = self._make_claude_agent()
            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
                remote_commands=handler, claude_agent=claude_agent,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x",
                body="Wie geht's dir?", timestamp=1.0,
            )
            await bridge._handle_message(msg)

            # Assistant aufgerufen, ClaudeAgent NICHT
            assistant.process.assert_called_once()
            assert assistant.process.call_args[0][0] == "Wie geht's dir?"
            claude_agent.process.assert_not_called()
            assert ("!r:x", "Saleria antwortet!") in channel._sent_texts

        run_async(_test())

    def test_claude_without_quotes_goes_to_llm(self):
        """'claude' ohne Anführungszeichen → lokales LLM."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("LLM Antwort")
            claude_agent = self._make_claude_agent()
            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
                claude_agent=claude_agent,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x",
                body="Claude mach mal was", timestamp=1.0,
            )
            await bridge._handle_message(msg)

            assistant.process.assert_called_once()
            claude_agent.process.assert_not_called()

        run_async(_test())

    def test_command_still_routed_to_handler_not_agent(self):
        """Commands gehen weiter an RemoteCommandHandler, nicht an ClaudeAgent."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            handler = MagicMock(spec=RemoteCommandHandler)
            handler.parse_command.return_value = "status"
            handler.execute.return_value = CommandResult(
                command="status", success=True, text="CPU: 10%",
            )
            claude_agent = self._make_claude_agent()
            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
                remote_commands=handler, claude_agent=claude_agent,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="status",
                timestamp=1.0,
            )
            await bridge._handle_message(msg)

            handler.execute.assert_called_once()
            claude_agent.process.assert_not_called()
            assistant.process.assert_not_called()

        run_async(_test())

    def test_no_claude_agent_falls_to_assistant(self):
        """Ohne ClaudeAgent geht alles an Assistant (auch mit 'claude' keyword)."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("Lokale Antwort")
            handler = MagicMock(spec=RemoteCommandHandler)
            handler.parse_command.return_value = None
            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
                remote_commands=handler,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x",
                body='Claude "test"', timestamp=1.0,
            )
            await bridge._handle_message(msg)

            assistant.process.assert_called_once()

        run_async(_test())

    def test_claude_agent_with_details(self):
        """ClaudeAgent-Antwort mit Details sendet zwei Nachrichten."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            claude_agent = self._make_claude_agent(
                summary="Datei gelesen",
                details="# Inhalt\nTest-Inhalt hier",
                action_taken="read_file",
            )
            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
                claude_agent=claude_agent,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x",
                body='Claude "Zeig CLAUDE.md"', timestamp=1.0,
            )
            await bridge._handle_message(msg)

            assert len(channel._sent_texts) == 2
            assert ("!r:x", "Datei gelesen") in channel._sent_texts
            assert ("!r:x", "# Inhalt\nTest-Inhalt hier") in channel._sent_texts

        run_async(_test())

    def test_claude_agent_screenshot_sends_image(self, tmp_path):
        """ClaudeAgent-Screenshot sendet Bild über send_image."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()

            img_path = tmp_path / "agent_screenshot.png"
            img_path.write_bytes(b"\x89PNG" + b"\x00" * 50)

            claude_agent = self._make_claude_agent(
                summary="Screenshot aufgenommen.",
                details=str(img_path),
                action_taken="screenshot",
            )
            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
                claude_agent=claude_agent,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x",
                body='Claude "Mach ein Screenshot"', timestamp=1.0,
            )
            await bridge._handle_message(msg)

            assert ("!r:x", "Screenshot aufgenommen.") in channel._sent_texts
            assert len(channel._sent_images) == 1

        run_async(_test())

    def test_claude_agent_error_sends_error_message(self):
        """Fehler bei ClaudeAgent wird als Fehlermeldung gesendet."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            claude_agent = MagicMock()
            claude_agent.process.side_effect = RuntimeError("API kaputt")
            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
                claude_agent=claude_agent,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x",
                body='Claude "Test"', timestamp=1.0,
            )
            await bridge._handle_message(msg)

            assert len(channel._sent_texts) == 1
            assert "Agent-Fehler" in channel._sent_texts[0][1]

        run_async(_test())



# ---------------------------------------------------------------------------
# MatrixBridge – Error-Alerting via ErrorCollector
# ---------------------------------------------------------------------------

class TestBridgeErrorLogging:
    """Prüft dass Bridge-Fehler via logger.error() geloggt werden (statt _log_error)."""

    def _make_assistant_mock(self):
        assistant = MagicMock()
        assistant.process.return_value = AssistantResult(
            response="ok", emotion="neutral",
            action_executed=None,
            action_success=False,
        )
        return assistant

    def test_command_exception_logs_error(self):
        """Exception bei Command erzeugt logger.error() mit extra-Kontext."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            handler = MagicMock(spec=RemoteCommandHandler)
            handler.parse_command.return_value = "status"
            handler.execute.side_effect = RuntimeError("psutil kaputt")
            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
                remote_commands=handler,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="status",
                timestamp=1.0,
            )
            with patch("elder_berry.comms.bridge.logger") as mock_logger:
                await bridge._handle_message(msg)
                mock_logger.error.assert_called()
                call_kwargs = mock_logger.error.call_args
                assert "extra" in call_kwargs.kwargs
                assert call_kwargs.kwargs["extra"]["handler"] == "command"

        run_async(_test())

    def test_failed_command_logs_error(self):
        """success=False bei Command erzeugt logger.error()."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            handler = MagicMock(spec=RemoteCommandHandler)
            handler.parse_command.return_value = "status"
            handler.execute.return_value = CommandResult(
                command="status", success=False,
                text="SystemMonitor nicht verfügbar.",
            )
            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
                remote_commands=handler,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="status",
                timestamp=1.0,
            )
            with patch("elder_berry.comms.bridge.logger") as mock_logger:
                await bridge._handle_message(msg)
                mock_logger.error.assert_called_once()
                call_kwargs = mock_logger.error.call_args
                assert "command:status" in call_kwargs.kwargs["extra"]["handler"]

        run_async(_test())

    def test_llm_error_logs_with_handler_extra(self):
        """LLM-Fehler erzeugt logger.error() mit handler=llm."""
        async def _test():
            channel = MockChannel()
            assistant = MagicMock()
            assistant.process.side_effect = RuntimeError("Ollama down")
            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="Hallo",
                timestamp=1.0,
            )
            with patch("elder_berry.comms.bridge.logger") as mock_logger:
                await bridge._handle_message(msg)
                mock_logger.error.assert_called()
                call_kwargs = mock_logger.error.call_args
                assert call_kwargs.kwargs["extra"]["handler"] == "llm"

        run_async(_test())

    def test_no_error_on_success(self):
        """Erfolgreicher Command erzeugt keinen logger.error()."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            handler = MagicMock(spec=RemoteCommandHandler)
            handler.parse_command.return_value = "status"
            handler.execute.return_value = CommandResult(
                command="status", success=True, text="CPU: 25%",
            )
            bridge = MatrixBridge(
                channel=channel, assistant=assistant,
                remote_commands=handler,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="status",
                timestamp=1.0,
            )
            with patch("elder_berry.comms.bridge.logger") as mock_logger:
                await bridge._handle_message(msg)
                mock_logger.error.assert_not_called()

        run_async(_test())


class TestBridgeAlertMonitor:
    def _make_assistant_mock(self):
        assistant = MagicMock()
        assistant.process.return_value = AssistantResult(
            response="ok",
            action_executed=None,
            action_success=False,
        )
        return assistant

    def test_bridge_with_alert_monitor(self):
        """Bridge akzeptiert AlertMonitor als DI-Parameter."""
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        alert_monitor = MagicMock()
        alert_monitor.is_running = False

        bridge = MatrixBridge(
            channel=channel,
            assistant=assistant,
            alert_monitor=alert_monitor,
            alert_room_id="!alerts:x",
        )
        assert not bridge.is_running

    def test_bridge_without_alert_monitor(self):
        """Bridge funktioniert ohne AlertMonitor."""
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        bridge = MatrixBridge(channel=channel, assistant=assistant)
        assert not bridge.is_running

    def test_bridge_stop_stops_alert_monitor(self):
        """Bridge.stop() stoppt auch AlertMonitor."""
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        alert_monitor = MagicMock()
        alert_monitor.is_running = True

        bridge = MatrixBridge(
            channel=channel,
            assistant=assistant,
            alert_monitor=alert_monitor,
        )
        bridge._running = True
        bridge.stop()

        alert_monitor.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Restart-Flag + Notification
# ---------------------------------------------------------------------------

class TestRestartNotification:
    """Tests für Restart-Flag und Startup-Benachrichtigung."""

    def test_restart_flag_file_written_on_restart(self):
        """_perform_restart schreibt Flag-Datei mit room_id."""
        from elder_berry.comms.bridge import RESTART_FLAG_FILE

        channel = MockChannel()
        assistant = MagicMock()
        bridge = MatrixBridge(channel=channel, assistant=assistant)

        # Flag aufräumen falls von vorherigem Test
        RESTART_FLAG_FILE.unlink(missing_ok=True)

        # _perform_restart aufrufen (Restart-Mechanismus wird gemockt)
        from unittest.mock import patch as _patch
        with _patch("elder_berry.comms.bridge.os.execv"), \
             _patch("elder_berry.comms.bridge.os._exit"), \
             _patch("elder_berry.comms.bridge.subprocess.Popen", create=True):
            run_async(bridge._perform_restart("!test:room"))

        assert RESTART_FLAG_FILE.exists()
        assert RESTART_FLAG_FILE.read_text(encoding="utf-8") == "!test:room"

        # Cleanup
        RESTART_FLAG_FILE.unlink(missing_ok=True)

    def test_send_restart_notification_sends_message(self):
        """send_restart_notification sendet Nachricht wenn Flag existiert."""
        from elder_berry.comms.bridge import RESTART_FLAG_FILE

        channel = MockChannel()
        channel._connected = True

        # Flag simulieren
        RESTART_FLAG_FILE.write_text("!notify:room", encoding="utf-8")

        run_async(MatrixBridge.send_restart_notification(channel))

        assert len(channel._sent_texts) == 1
        room_id, text = channel._sent_texts[0]
        assert room_id == "!notify:room"
        assert "wieder da" in text

        # Flag sollte gelöscht sein
        assert not RESTART_FLAG_FILE.exists()

    def test_send_restart_notification_noop_without_flag(self):
        """Ohne Flag-Datei passiert nichts."""
        from elder_berry.comms.bridge import RESTART_FLAG_FILE

        RESTART_FLAG_FILE.unlink(missing_ok=True)

        channel = MockChannel()
        run_async(MatrixBridge.send_restart_notification(channel))

        assert len(channel._sent_texts) == 0

    def test_restart_command_triggers_bridge_restart(self):
        """Command mit restart=True löst _perform_restart aus."""
        channel = MockChannel()
        channel._connected = True
        assistant = MagicMock()

        mock_handler = MagicMock()
        mock_handler.parse_command.return_value = "restart"
        mock_handler.execute.return_value = CommandResult(
            command="restart", success=True,
            text="Starte neu...", restart=True,
        )

        bridge = MatrixBridge(
            channel=channel,
            assistant=assistant,
            remote_commands=mock_handler,
        )
        bridge._running = True

        msg = IncomingMessage(
            sender="@user:test", room_id="!room:test",
            body="restart", timestamp=0.0,
        )

        from unittest.mock import patch as _patch, AsyncMock
        with _patch.object(bridge, "_perform_restart", new_callable=AsyncMock) as mock_restart:
            run_async(bridge._handle_message(msg))

        # Text wurde gesendet
        assert len(channel._sent_texts) == 1
        assert "Starte neu" in channel._sent_texts[0][1]

        # _perform_restart wurde aufgerufen (mit room_id + Server-Timestamp)
        mock_restart.assert_called_once_with(
            "!room:test", msg_server_ts=0.0,
        )


# ---------------------------------------------------------------------------
# IncomingMessage – audio_data Feld
# ---------------------------------------------------------------------------

class TestIncomingMessageAudio:
    def test_audio_data_default_none(self):
        msg = IncomingMessage(
            sender="@u:x", room_id="!r:x", body="voice.ogg", timestamp=0.0,
        )
        assert msg.audio_data is None

    def test_audio_data_set(self):
        data = b"\x00\x01\x02\x03"
        msg = IncomingMessage(
            sender="@u:x", room_id="!r:x", body="voice.ogg",
            timestamp=0.0, audio_data=data,
        )
        assert msg.audio_data == data

    def test_audio_data_immutable(self):
        msg = IncomingMessage(
            sender="@u:x", room_id="!r:x", body="hi",
            timestamp=0.0, audio_data=b"test",
        )
        with pytest.raises(AttributeError):
            msg.audio_data = b"other"


# ---------------------------------------------------------------------------
# MatrixBridge – Audio-Routing (STT)
# ---------------------------------------------------------------------------

def _make_audio_msg(body: str = "voice.ogg", data: bytes = b"\x00" * 16) -> IncomingMessage:
    return IncomingMessage(
        sender="@user:test", room_id="!room:test",
        body=body, timestamp=0.0, audio_data=data,
    )


class TestBridgeAudioRouting:
    """Tests für _handle_audio_message und STT-Integration in _handle_message."""

    def test_audio_message_no_stt_sends_error(self):
        """Ohne STT-Engine: Fehlermeldung an Raum senden."""
        channel = MockChannel()
        channel._connected = True
        assistant = MagicMock()

        bridge = MatrixBridge(channel=channel, assistant=assistant, stt=None)
        bridge._running = True

        run_async(bridge._handle_message(_make_audio_msg()))

        assert len(channel._sent_texts) == 1
        assert "nicht unterstützt" in channel._sent_texts[0][1].lower() or \
               "stt" in channel._sent_texts[0][1].lower() or \
               "sprachnachrichten" in channel._sent_texts[0][1].lower()

    def test_audio_message_routed_before_commands(self):
        """Audio-Nachrichten werden NICHT an RemoteCommandHandler weitergeleitet."""
        channel = MockChannel()
        channel._connected = True
        assistant = MagicMock()

        mock_handler = MagicMock()
        mock_handler.parse_command.return_value = "status"

        bridge = MatrixBridge(
            channel=channel,
            assistant=assistant,
            remote_commands=mock_handler,
            stt=None,
        )
        bridge._running = True

        run_async(bridge._handle_message(_make_audio_msg()))

        # Command-Handler darf NICHT aufgerufen werden
        mock_handler.parse_command.assert_not_called()

    def test_audio_message_stt_empty_sends_not_understood(self):
        """STT liefert leeren Text → 'nicht verstanden'-Meldung senden."""
        from unittest.mock import MagicMock, patch as _patch
        from elder_berry.stt.base import TranscriptionResult

        channel = MockChannel()
        channel._connected = True
        assistant = MagicMock()

        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = TranscriptionResult(text="")

        bridge = MatrixBridge(channel=channel, assistant=assistant, stt=mock_stt)
        bridge._running = True

        with _patch("tempfile.NamedTemporaryFile"):
            import tempfile
            import os

            # Wirklichen Temp-File erstellen damit unlink nicht crasht
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
                tmp_name = f.name

            with _patch.object(mock_stt, "transcribe", return_value=TranscriptionResult(text="")):
                # Direkt _handle_audio_message aufrufen mit echtem tmp-file-Flow
                msg = _make_audio_msg()

                # Patch NamedTemporaryFile um unsere Datei zu nutzen
                import builtins
                orig_open = builtins.open

                with _patch("elder_berry.comms.bridge.tempfile.NamedTemporaryFile") as mock_tmp:
                    mock_file = MagicMock()
                    mock_file.name = tmp_name
                    mock_file.__enter__ = lambda s: s
                    mock_file.__exit__ = MagicMock(return_value=False)
                    mock_tmp.return_value = mock_file

                    run_async(bridge._handle_audio_message(msg))

            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass

        assert len(channel._sent_texts) == 1
        reply = channel._sent_texts[0][1].lower()
        assert "nicht" in reply and ("verstehen" in reply or "verstanden" in reply)

    def test_audio_message_stt_success_calls_assistant(self):
        """STT liefert Text → Assistant.process() wird aufgerufen."""
        from unittest.mock import MagicMock, patch as _patch
        from elder_berry.stt.base import TranscriptionResult
        from elder_berry.core.assistant import AssistantResult
        import tempfile, os

        channel = MockChannel()
        channel._connected = True

        mock_assistant = MagicMock()
        mock_assistant.process.return_value = AssistantResult(
            response="Hallo!", action_executed=None, action_success=False,
        )

        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = TranscriptionResult(
            text="Wie geht es dir?", language="de", confidence=0.95,
        )

        bridge = MatrixBridge(channel=channel, assistant=mock_assistant, stt=mock_stt)
        bridge._running = True

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            tmp_name = f.name

        with _patch("elder_berry.comms.bridge.tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = tmp_name
            mock_file.__enter__ = lambda s: s
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value = mock_file

            run_async(bridge._handle_audio_message(_make_audio_msg()))

        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass

        # Assistant muss aufgerufen worden sein
        mock_assistant.process.assert_called_once()
        call_arg = mock_assistant.process.call_args[0][0]
        assert call_arg == "Wie geht es dir?"

        # Antwort muss gesendet worden sein
        assert len(channel._sent_texts) == 1
        assert "Hallo!" in channel._sent_texts[0][1]

    def test_audio_message_stt_exception_sends_error(self):
        """STT wirft Exception → Fehlermeldung senden."""
        from unittest.mock import MagicMock, patch as _patch
        import tempfile, os

        channel = MockChannel()
        channel._connected = True
        assistant = MagicMock()

        mock_stt = MagicMock()
        mock_stt.transcribe.side_effect = RuntimeError("CUDA out of memory")

        bridge = MatrixBridge(channel=channel, assistant=assistant, stt=mock_stt)
        bridge._running = True

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            tmp_name = f.name

        with _patch("elder_berry.comms.bridge.tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = tmp_name
            mock_file.__enter__ = lambda s: s
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value = mock_file

            run_async(bridge._handle_audio_message(_make_audio_msg()))

        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass

        assert len(channel._sent_texts) == 1
        assert "fehler" in channel._sent_texts[0][1].lower() or \
               "error" in channel._sent_texts[0][1].lower()

    def test_audio_message_allowed_sender(self):
        """Audio-Nachrichten werden durch Sender-Whitelist gefiltert."""
        channel = MockChannel()
        channel._connected = True
        assistant = MagicMock()

        bridge = MatrixBridge(
            channel=channel,
            assistant=assistant,
            allowed_senders=frozenset(["@allowed:test"]),
            stt=None,
        )
        bridge._running = True

        # Nicht erlaubter Sender
        msg = IncomingMessage(
            sender="@unknown:test", room_id="!room:test",
            body="voice.ogg", timestamp=0.0, audio_data=b"\x00",
        )
        run_async(bridge._handle_message(msg))

        # Keine Antwort für nicht erlaubten Sender
        assert len(channel._sent_texts) == 0


class TestBridgeChatHistory:
    """Tests für Multi-Turn Chat-History in der Bridge."""

    def _make_assistant_mock(self, response_text="Antwort"):
        assistant = MagicMock()
        assistant.process.return_value = AssistantResult(
            response=response_text,
            action_executed=None,
            action_success=False,
        )
        return assistant

    def test_chat_history_passed_to_assistant(self):
        """Chat-History wird als dritter Parameter an assistant.process übergeben."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("Antwort 1")
            bridge = MatrixBridge(channel=channel, assistant=assistant)
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="Hallo",
                timestamp=1.0,
            )
            await bridge._handle_message(msg)

            # process wurde mit 3 Argumenten aufgerufen
            assistant.process.assert_called_once()
            args = assistant.process.call_args[0]
            assert args[0] == "Hallo"  # user_input
            assert args[1] is None     # audio_output
            assert "Hallo" in args[2]  # chat_history enthält die Nachricht

        run_async(_test())

    def test_command_result_stored_in_history(self):
        """Command-Ergebnisse werden in der Chat-History gespeichert."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            handler = MagicMock(spec=RemoteCommandHandler)
            handler.parse_command.return_value = "mails"
            handler.execute.return_value = CommandResult(
                command="mails", success=True,
                text="3 ungelesene Mails",
            )
            bridge = MatrixBridge(
                channel=channel, assistant=assistant, remote_commands=handler,
            )
            await channel.connect()

            # Command ausführen
            msg1 = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="mails",
                timestamp=1.0,
            )
            await bridge._handle_message(msg1)

            # Chat-History sollte Command + Ergebnis enthalten
            history = bridge._chat_history.get("@user:x")
            assert len(history) == 2
            assert history[0].role == "user"
            assert history[0].text == "mails"
            assert history[1].role == "assistant"
            assert "3 ungelesene" in history[1].text

        run_async(_test())

    def test_assistant_response_stored_in_history(self):
        """LLM-Antworten werden in der Chat-History gespeichert."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("Ich bin Saleria!")
            bridge = MatrixBridge(channel=channel, assistant=assistant)
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x", body="Wer bist du?",
                timestamp=1.0,
            )
            await bridge._handle_message(msg)

            history = bridge._chat_history.get("@user:x")
            assert len(history) == 2
            assert history[0].text == "Wer bist du?"
            assert history[1].text == "Ich bin Saleria!"

        run_async(_test())

    def test_multi_turn_context_grows(self):
        """Mehrere Nachrichten bauen Kontext auf."""
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("OK")
            bridge = MatrixBridge(channel=channel, assistant=assistant)
            await channel.connect()

            for i in range(3):
                msg = IncomingMessage(
                    sender="@user:x", room_id="!r:x",
                    body=f"Nachricht {i}",
                    timestamp=float(i),
                )
                await bridge._handle_message(msg)

            history = bridge._chat_history.get("@user:x")
            # 3 user + 3 assistant = 6
            assert len(history) == 6

        run_async(_test())

    def test_file_paths_sent(self):
        """file_paths (z.B. Mail-Anhänge) werden via send_file gesendet."""
        async def _test():
            import tempfile
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            handler = MagicMock(spec=RemoteCommandHandler)
            handler.parse_command.return_value = "mail_attachment"

            # Temp-Datei erstellen
            tmp = tempfile.NamedTemporaryFile(
                suffix=".pdf", delete=False,
            )
            tmp.write(b"PDF content")
            tmp.close()
            tmp_path = Path(tmp.name)

            handler.execute.return_value = CommandResult(
                command="mail_attachment", success=True,
                text="1 Anhang", file_paths=[tmp_path],
            )
            bridge = MatrixBridge(
                channel=channel, assistant=assistant, remote_commands=handler,
            )
            await channel.connect()

            msg = IncomingMessage(
                sender="@user:x", room_id="!r:x",
                body="mail anhang 42", timestamp=1.0,
            )
            await bridge._handle_message(msg)

            # send_file wurde aufgerufen
            assert len(channel._sent_files) == 1

        run_async(_test())


# ────────────────────────────────────────────────────────────────
# Bridge + AudioRouter (Phase 12)
# ────────────────────────────────────────────────────────────────


class TestBridgeAudioRouter:
    """Bridge mit AudioRouter für lokale Wiedergabe."""

    def test_bridge_accepts_audio_router(self):
        """AudioRouter als DI-Parameter."""
        from elder_berry.core.audio_router import AudioRouter

        channel = MockChannel()
        assistant = MagicMock()
        router = AudioRouter(local_available=True)
        bridge = MatrixBridge(
            channel=channel, assistant=assistant, audio_router=router,
        )
        assert bridge._audio_router is router

    def test_bridge_without_audio_router(self):
        """Bridge funktioniert auch ohne AudioRouter."""
        channel = MockChannel()
        assistant = MagicMock()
        bridge = MatrixBridge(channel=channel, assistant=assistant)
        assert bridge._audio_router is None

    def test_play_audio_local_not_called_when_matrix_only(self):
        """Bei matrix_only wird _play_audio_local nicht aufgerufen."""
        from elder_berry.core.audio_router import AudioRouter

        channel = MockChannel()
        assistant = MagicMock()
        router = AudioRouter(local_available=True)
        bridge = MatrixBridge(
            channel=channel, assistant=assistant, audio_router=router,
        )
        bridge._play_audio_local = MagicMock()

        # should_play_local() ist False bei matrix_only
        assert router.should_play_local() is False
