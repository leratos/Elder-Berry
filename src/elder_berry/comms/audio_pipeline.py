"""AudioPipeline – Audio-Verarbeitung für die MatrixBridge.

Verwaltet:
- STT: Audio-Nachrichten transkribieren (Whisper)
- TTS: WAV → OGG/Opus Konvertierung + Matrix-Upload
- Lokale Wiedergabe: sounddevice / AgentClient
- Datei-Nachrichten: PDF/TXT via DocumentReader + LLM-Zusammenfassung
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.comms.audio_converter import AudioConverter
    from elder_berry.comms.chat_history import ChatHistory
    from elder_berry.comms.message_channel import IncomingMessage, MessageChannel
    from elder_berry.core.assistant import Assistant, AssistantResult
    from elder_berry.core.audio_router import AudioRouter
    from elder_berry.stt.base import STTEngine
    from elder_berry.tools.document_reader import DocumentReader

MessageCallback = Callable[["IncomingMessage"], Awaitable[None]]

logger = logging.getLogger(__name__)


class AudioPipeline:
    """Audio-I/O-Pipeline für die MatrixBridge.

    Kapselt STT (Sprache→Text), TTS-Output (WAV→OGG→Matrix),
    lokale Wiedergabe und Datei-Verarbeitung.
    """

    def __init__(
        self,
        channel: MessageChannel,
        assistant: Assistant,
        chat_history: ChatHistory,
        stt: STTEngine | None = None,
        audio_converter: AudioConverter | None = None,
        audio_router: AudioRouter | None = None,
        document_reader: DocumentReader | None = None,
        stt_timeout: float = 120.0,
    ) -> None:
        self._channel = channel
        self._assistant = assistant
        self._chat_history = chat_history
        self._stt = stt
        self._audio_converter = audio_converter
        self._audio_router = audio_router
        self._document_reader = document_reader
        self._stt_timeout = stt_timeout
        # Callback für Re-Dispatch nach STT (wird von Bridge gesetzt)
        self._on_message_callback: MessageCallback | None = None

    @property
    def stt_timeout(self) -> float:
        """Aktueller STT-Timeout in Sekunden."""
        return self._stt_timeout

    @stt_timeout.setter
    def stt_timeout(self, value: float) -> None:
        self._stt_timeout = value

    @property
    def audio_to_matrix(self) -> bool:
        """True wenn TTS-Audio als Datei generiert werden soll (für Matrix)."""
        return (
            self._audio_converter is not None and self._audio_converter.ffmpeg_available
        )

    def set_message_callback(self, callback: MessageCallback) -> None:
        """Setzt den Callback für Re-Dispatch nach STT-Transkription."""
        self._on_message_callback = callback

    async def handle_audio_message(self, msg: IncomingMessage) -> None:
        """Transkribiert eine Audio-Nachricht via STT und dispatcht weiter."""
        if self._stt is None:
            logger.warning(
                "Audio-Nachricht empfangen, aber kein STT konfiguriert (msg von %s)",
                msg.sender,
            )
            try:
                await self._channel.send_text(
                    msg.room_id,
                    "Sprachnachrichten werden gerade nicht unterstützt "
                    "(STT nicht konfiguriert).",
                )
            except Exception:
                pass
            return

        # Bridge routet nur dann hierher, wenn das Event m.audio ist und
        # audio_data dadurch gesetzt wurde. Mypy sieht IncomingMessage.audio_data
        # als bytes | None (das Datenmodell erlaubt auch text/file-Events ohne
        # Audio).
        assert msg.audio_data is not None
        tmp_path: Path | None = None
        try:
            loop = asyncio.get_running_loop()

            suffix = ".ogg"
            if isinstance(msg.body, str) and "." in msg.body:
                suffix = Path(msg.body).suffix or suffix

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(msg.audio_data)
                tmp_path = Path(tmp.name)

            logger.debug(
                "Audio-Nachricht transkribieren: %s (%d bytes)",
                tmp_path.name,
                len(msg.audio_data),
            )

            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._stt.transcribe,
                    tmp_path,
                ),
                timeout=self._stt_timeout,
            )

            if result.is_empty():
                logger.info(
                    "STT: kein Text erkannt (Sender: %s)",
                    msg.sender,
                )
                await self._channel.send_text(
                    msg.room_id,
                    "Ich konnte die Sprachnachricht leider nicht verstehen. "
                    "Bitte deutlich sprechen oder als Text senden.",
                )
                return

            logger.info(
                "STT erkannt [%s, %.0f%%]: %s",
                result.language or "?",
                (result.confidence or 0.0) * 100,
                result.text[:80],
            )

            # Transkription als Text-Nachricht weiterverarbeiten
            from elder_berry.comms.message_channel import IncomingMessage as IM

            text_msg = IM(
                sender=msg.sender,
                room_id=msg.room_id,
                body=result.text,
                timestamp=msg.timestamp,
                raw=msg.raw,
            )
            if self._on_message_callback:
                await self._on_message_callback(text_msg)

        except Exception as e:
            logger.error(
                "Fehler bei Audio-Transkription: %s",
                e,
                extra={"sender": msg.sender, "handler": "stt"},
            )
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Fehler bei der Sprachverarbeitung: {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte STT-Fehlermeldung nicht senden")
        finally:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    async def handle_file_message(self, msg: IncomingMessage) -> None:
        """Verarbeitet eine Datei-Nachricht (PDF/TXT via Matrix-Upload)."""
        file_name = msg.file_name or msg.body or "unknown"
        tmp_file: Path | None = None

        if self._document_reader is None:
            logger.warning(
                "Datei empfangen (%s), aber kein DocumentReader konfiguriert",
                file_name,
            )
            try:
                await self._channel.send_text(
                    msg.room_id,
                    "Dokument-Verarbeitung nicht verfügbar.",
                )
            except Exception:
                # Best-effort: User-Notification ist nett-zu-haben, darf aber
                # die Document-Pipeline nicht crashen wenn der Channel kurz weg ist.
                pass
            return

        from elder_berry.tools.document_reader import DocumentReader

        if not DocumentReader.is_supported(Path(file_name)):
            logger.info("Nicht unterstütztes Dateiformat: %s", file_name)
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Dateiformat '{Path(file_name).suffix}' nicht unterstützt. "
                    f"Ich kann PDF und TXT verarbeiten.",
                )
            except Exception:
                pass
            return

        # Bridge routet nur dann hierher, wenn das Event m.file ist und
        # file_data gesetzt wurde -- analog handle_audio_message.
        assert msg.file_data is not None
        try:
            suffix = Path(file_name).suffix or ".tmp"
            # Phase 70 (H-2): NamedTemporaryFile ist TOCTOU-frei -- ein
            # Angreifer mit Schreibrechten in $TMP haette zwischen
            # mktemp() und write_bytes() einen Symlink auf eine Ziel-
            # datei legen koennen.
            with tempfile.NamedTemporaryFile(
                suffix=suffix,
                delete=False,
            ) as fh:
                fh.write(msg.file_data)
                tmp_file = Path(fh.name)

            logger.info(
                "Datei verarbeiten: %s (%d bytes)",
                file_name,
                len(msg.file_data),
            )

            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._document_reader.read_file,
                    tmp_file,
                ),
                timeout=30.0,
            )

            doc_context = (
                f"Dokument '{result.source}' ({result.pages} Seiten):\n\n{result.text}"
            )
            self._chat_history.add(msg.sender, "user", f"[Datei: {file_name}]")
            self._chat_history.add(msg.sender, "assistant", doc_context)

            summary_prompt = (
                f"Der Nutzer hat folgendes Dokument geschickt: {file_name}\n\n"
                f"Inhalt:\n{result.text}\n\n"
                f"Fasse den Inhalt zusammen."
            )

            chat_context = self._chat_history.format_for_prompt(msg.sender)
            # Phase 70 (H-2): leere WAV-Datei TOCTOU-frei anlegen.
            # Der Assistant schreibt das echte Audio-Material rein.
            tmp_wav: Path | None = None
            if self.audio_to_matrix:
                with tempfile.NamedTemporaryFile(
                    suffix=".wav",
                    delete=False,
                ) as fh:
                    tmp_wav = Path(fh.name)
            llm_result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._assistant.process,
                    summary_prompt,
                    tmp_wav,
                    chat_context,
                ),
                timeout=120.0,
            )

            if llm_result.response:
                header = f"📄 {result.source} ({result.pages} Seite(n))"
                if result.truncated:
                    header += " [gekürzt]"
                response = f"{header}\n\n{llm_result.response}"
                self._chat_history.add(msg.sender, "assistant", llm_result.response)
                await self._channel.send_text(msg.room_id, response)

            await self.send_audio_if_available(msg.room_id, llm_result, tmp_wav)

        except Exception as e:
            logger.error(
                "Datei-Verarbeitung fehlgeschlagen (%s): %s",
                file_name,
                e,
                extra={"sender": msg.sender, "handler": "document"},
            )
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Fehler beim Verarbeiten von '{file_name}': {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")
        finally:
            if tmp_file and tmp_file.exists():
                tmp_file.unlink(missing_ok=True)

    async def send_audio_if_available(
        self,
        room_id: str,
        result: AssistantResult,
        tmp_wav: Path | None,
    ) -> None:
        """Konvertiert WAV→OGG und sendet Audio an Matrix (wenn vorhanden)."""
        if not result.audio_path or not result.audio_path.exists():
            return
        if not self._audio_converter:
            return

        tmp_ogg: Path | None = None
        try:
            tmp_ogg = result.audio_path.with_suffix(".ogg")
            ogg_path, _duration = self._audio_converter.to_ogg_opus(
                result.audio_path,
                output_path=tmp_ogg,
            )
            await self._channel.send_audio(room_id, ogg_path)
            logger.debug("Sprachnachricht gesendet: %s", ogg_path.name)
        except Exception as e:
            logger.error("Audio-Senden fehlgeschlagen: %s", e)

        # Lokale Wiedergabe
        if (
            self._audio_router
            and self._audio_router.should_play_local()
            and result.audio_path.exists()
        ):
            self._play_audio_local(result.audio_path)

        # Cleanup
        try:
            if result.audio_path.exists():
                result.audio_path.unlink(missing_ok=True)
            if tmp_ogg and tmp_ogg.exists():
                tmp_ogg.unlink(missing_ok=True)
        except OSError as e:
            logger.debug("Audio-Cleanup Fehler: %s", e)

    def _play_audio_local(self, wav_path: Path) -> None:
        """Spielt eine WAV-Datei lokal ab (sounddevice oder AgentClient)."""
        agent = getattr(self._assistant, "_agent", None)
        if agent is not None:
            try:
                agent.play_audio_file(wav_path)
                logger.debug("Audio lokal via AgentClient abgespielt")
                return
            except Exception as e:
                logger.debug("AgentClient-Wiedergabe fehlgeschlagen: %s", e)

        try:
            import sounddevice as sd
            import wave

            with wave.open(str(wav_path), "rb") as wf:
                frames = wf.readframes(wf.getnframes())
                sd.play(
                    __import__("numpy").frombuffer(frames, dtype="int16"),
                    samplerate=wf.getframerate(),
                    blocksize=4096,
                )
                sd.wait()
            logger.debug("Audio lokal via sounddevice abgespielt")
        except Exception as e:
            logger.warning("Lokale Audio-Wiedergabe fehlgeschlagen: %s", e)
