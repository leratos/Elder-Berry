"""MatrixBridge – Async-Bridge zwischen MessageChannel und synchronem Assistant.

Das Problem: MatrixChannel (matrix-nio) ist async, aber Assistant.process() ist
synchron. Die Bridge löst das mit einem dedizierten Thread für den sync-Loop
und einem Thread-Pool für die blockierenden Assistant-Aufrufe.

Architektur:
    ┌─────────────────────┐     ┌──────────────────┐
    │  Async Event-Loop   │     │  Worker-Thread    │
    │  (MatrixChannel)    │────>│  (Assistant)      │
    │  sync_loop()        │     │  process()        │
    │  on_message(cb)     │<────│  → result         │
    └─────────────────────┘     └──────────────────┘

Command-Router (Phase 7):
    Nachricht rein → RemoteCommandHandler.parse_command()
      ├─ Command erkannt → execute() → send result (text/image)
      └─ Kein Command → "claude" + "..." → ClaudeAgent → sonst lokales LLM

Audio-Pipeline (wenn AudioConverter vorhanden):
    Assistant.process(audio_output=tmp.wav) → WAV → AudioConverter → OGG/Opus → Matrix

Verwendung:
    bridge = MatrixBridge(channel=matrix_channel, assistant=assistant)
    bridge.start()   # Startet async Loop + Message-Handler
    ...
    bridge.stop()    # Stoppt sauber
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.chat_history import ChatHistory
from elder_berry.comms.message_channel import IncomingMessage, MessageChannel

if TYPE_CHECKING:
    from elder_berry.comms.alert_monitor import AlertMonitor
    from elder_berry.comms.audio_converter import AudioConverter
    from elder_berry.comms.claude_agent import ClaudeAgent
    from elder_berry.comms.briefing_scheduler import BriefingScheduler
    from elder_berry.comms.reminder_scheduler import ReminderScheduler
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.core.assistant import Assistant
    from elder_berry.core.audio_router import AudioRouter
    from elder_berry.stt.base import STTEngine
    from elder_berry.tools.document_reader import DocumentReader

logger = logging.getLogger(__name__)

# Restart-Flag: wird vor os.execv geschrieben, beim Start geprüft
RESTART_FLAG_FILE = Path(tempfile.gettempdir()) / "elder_berry_restart.flag"

# Regex: Text in Anführungszeichen extrahieren (erste Fundstelle)
_QUOTED_TEXT_PATTERN = re.compile(r'"([^"]+)"')


def extract_claude_message(text: str) -> str | None:
    """Prüft ob eine Nachricht an den ClaudeAgent gerichtet ist.

    Erkennung: Das Wort "claude" muss im Text vorkommen UND der eigentliche
    Auftrag muss in Anführungszeichen stehen.

    Beispiele:
        "Sag Claude bitte \"Dokumentiere X im Journal\""  → "Dokumentiere X im Journal"
        "Claude \"Was war der letzte Schritt?\""           → "Was war der letzte Schritt?"
        "Wie geht's dir?"                                  → None (kein "claude")
        "Claude mach mal was"                              → None (keine Anführungszeichen)

    Returns:
        Der extrahierte Text in Anführungszeichen oder None.
    """
    if "claude" not in text.lower():
        return None

    match = _QUOTED_TEXT_PATTERN.search(text)
    if not match:
        return None

    return match.group(1)


class MatrixBridge:
    """Verbindet einen async MessageChannel mit dem synchronen Assistant.

    - Startet den MessageChannel sync_loop in einem eigenen Thread mit eigenem Event-Loop.
    - Empfangene Nachrichten werden an Assistant.process() delegiert (in Thread-Pool).
    - Antworten (Text + optional Audio) werden über den Kanal zurückgesendet.
    - Optional: AudioConverter für WAV→OGG/Opus Konvertierung (Sprachnachrichten).
    """

    def __init__(
        self,
        channel: MessageChannel,
        assistant: Assistant,
        audio_converter: AudioConverter | None = None,
        remote_commands: RemoteCommandHandler | None = None,
        claude_agent: ClaudeAgent | None = None,
        alert_monitor: AlertMonitor | None = None,
        alert_room_id: str | None = None,
        error_log_dir: Path | None = None,
        allowed_senders: frozenset[str] | None = None,
        stt: STTEngine | None = None,
        reminder_scheduler: ReminderScheduler | None = None,
        briefing_scheduler: BriefingScheduler | None = None,
        document_reader: DocumentReader | None = None,
        audio_router: AudioRouter | None = None,
    ) -> None:
        self._channel = channel
        self._assistant = assistant
        self._audio_converter = audio_converter
        self._remote_commands = remote_commands
        self._claude_agent = claude_agent
        self._alert_monitor = alert_monitor
        self._alert_room_id = alert_room_id
        self._error_log_dir = error_log_dir
        self._allowed_senders = allowed_senders
        self._stt = stt
        self._reminder_scheduler = reminder_scheduler
        self._briefing_scheduler = briefing_scheduler
        self._document_reader = document_reader
        self._audio_router = audio_router
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        # Multi-Turn Chat-History pro User (Sliding Window)
        self._chat_history = ChatHistory(max_messages=10)

    @property
    def _audio_to_matrix(self) -> bool:
        """True wenn TTS-Audio als Datei generiert werden soll (für Matrix)."""
        return (
            self._audio_converter is not None
            and self._audio_converter.ffmpeg_available
        )

    @property
    def is_running(self) -> bool:
        """True wenn die Bridge aktiv ist."""
        return self._running

    def start(self) -> None:
        """Startet die Bridge in einem Hintergrund-Thread.

        Nicht-blockierend – kehrt sofort zurück.
        """
        if self._running:
            logger.warning("Bridge läuft bereits")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="matrix-bridge",
            daemon=True,
        )
        self._thread.start()
        logger.info("MatrixBridge gestartet")

    def stop(self) -> None:
        """Stoppt die Bridge und wartet auf Thread-Ende."""
        if not self._running:
            return

        # AlertMonitor stoppen
        if self._alert_monitor and self._alert_monitor.is_running:
            self._alert_monitor.stop()

        # ReminderScheduler stoppen
        if self._reminder_scheduler and self._reminder_scheduler.is_running:
            self._reminder_scheduler.stop()

        # BriefingScheduler stoppen
        if self._briefing_scheduler and self._briefing_scheduler.is_running:
            self._briefing_scheduler.stop()

        self._running = False

        if self._loop and self._loop.is_running():
            # Schedule disconnect im async Loop
            asyncio.run_coroutine_threadsafe(
                self._shutdown(), self._loop,
            )

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                logger.warning("Bridge-Thread konnte nicht sauber beendet werden")

        self._loop = None
        self._thread = None
        logger.info("MatrixBridge gestoppt")

    def _run_loop(self) -> None:
        """Thread-Einstiegspunkt: Erstellt Event-Loop und startet async Code."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception as e:
            logger.error("Bridge-Loop Fehler: %s", e)
        finally:
            self._loop.close()
            self._running = False

    async def _async_main(self) -> None:
        """Async Hauptroutine: Connect, Callback registrieren, Sync-Loop starten."""
        await self._channel.connect()

        # Restart-Benachrichtigung senden (wenn Flag existiert)
        await self.send_restart_notification(self._channel)

        self._channel.on_message(self._handle_message)
        logger.info("Bridge verbunden, warte auf Nachrichten...")

        # AlertMonitor starten (wenn vorhanden)
        if self._alert_monitor and self._alert_room_id:
            self._start_alert_monitor()

        # ReminderScheduler starten (wenn vorhanden)
        if self._reminder_scheduler:
            self._start_reminder_scheduler()

        # BriefingScheduler starten (wenn vorhanden)
        if self._briefing_scheduler:
            self._start_briefing_scheduler()

        try:
            await self._channel.sync_loop()
        except asyncio.CancelledError:
            logger.debug("Sync-Loop abgebrochen")
        except Exception as e:
            logger.error("Sync-Loop Fehler: %s", e)

    async def _handle_message(self, msg: IncomingMessage) -> None:
        """Callback für eingehende Nachrichten.

        Command-Router (Phase 7):
        1. Prüft ob die Nachricht ein direkter Command ist (RemoteCommandHandler)
        2. Wenn ja: execute → send result (text/image)
        3. Wenn nein: weiter an Assistant (bestehender Flow)

        Audio-Pipeline (wenn AudioConverter vorhanden):
        1. Assistant generiert WAV in Temp-Datei (audio_output Parameter)
        2. AudioConverter konvertiert WAV → OGG/Opus
        3. OGG wird als Sprachnachricht via Channel gesendet
        """
        logger.info("Nachricht von %s: %s", msg.sender, msg.body[:100])

        # --- Sender-Whitelist: Nachrichten von unbekannten Absendern ignorieren ---
        if self._allowed_senders and msg.sender not in self._allowed_senders:
            logger.warning("Nachricht von unbekanntem Sender ignoriert: %s", msg.sender)
            return

        # --- Audio-Nachricht: STT → Text → Assistant ---
        if msg.audio_data is not None:
            await self._handle_audio_message(msg)
            return

        # --- Datei-Nachricht: PDF/TXT → DocumentReader → LLM ---
        if msg.file_data is not None:
            await self._handle_file_message(msg)
            return

        # --- Command-Router: direkte Commands vor LLM ---
        if self._remote_commands:
            command = self._remote_commands.parse_command(msg.body)
            if command:
                await self._handle_remote_command(msg, command)
                return

        # --- Claude Agent: nur bei explizitem "claude" + "..." ---
        if self._claude_agent:
            claude_text = extract_claude_message(msg.body)
            if claude_text:
                await self._handle_claude_agent(msg, claude_text)
                return

        # --- LLM-Fallback: bestehender Assistant-Flow ---
        await self._handle_assistant_message(msg)

    async def _handle_remote_command(
        self, msg: IncomingMessage, command: str,
    ) -> None:
        """Führt einen direkten Remote-Command aus und sendet das Ergebnis."""
        logger.info("Remote-Command erkannt: %s", command)

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self._remote_commands.execute, command, msg.body,
            )

            # Dokument-Zusammenfassung: Rohtext ans LLM schicken
            if (
                result.command == "document_summary"
                and result.success
                and result.history_text
            ):
                await self._handle_document_summary(msg, result)
                return

            # Text-Antwort senden
            if result.text:
                await self._channel.send_text(msg.room_id, result.text)

            # Command-Ergebnis in Chat-History speichern
            # history_text bevorzugen (z.B. Mail-Body für LLM-Kontext)
            if result.success and result.text:
                history_content = result.history_text or result.text
                self._chat_history.add(msg.sender, "user", msg.body)
                self._chat_history.add(msg.sender, "assistant", history_content)

            # Fehlgeschlagene Commands loggen (kein Crash, aber success=False)
            if not result.success:
                self._log_error(
                    msg.sender, msg.body,
                    RuntimeError(result.text or "Command fehlgeschlagen"),
                    handler=f"command:{command}",
                )

            # Bild senden (z.B. Screenshot)
            if result.image_path and result.image_path.exists():
                try:
                    await self._channel.send_image(
                        msg.room_id, result.image_path,
                    )
                except NotImplementedError:
                    await self._channel.send_text(
                        msg.room_id,
                        "Screenshot aufgenommen, aber Bild-Upload nicht unterstützt.",
                    )
                finally:
                    result.image_path.unlink(missing_ok=True)

            # Datei senden (z.B. PDF)
            if result.file_path and result.file_path.exists():
                try:
                    await self._channel.send_file(
                        msg.room_id, result.file_path,
                    )
                except NotImplementedError:
                    await self._channel.send_text(
                        msg.room_id,
                        "Datei-Upload nicht unterstützt.",
                    )

            # Mehrere Dateien senden (z.B. Mail-Anhänge)
            for fpath in (result.file_paths or []):
                if fpath.exists():
                    try:
                        await self._channel.send_file(msg.room_id, fpath)
                    except NotImplementedError:
                        await self._channel.send_text(
                            msg.room_id,
                            "Datei-Upload nicht unterstützt.",
                        )
                    finally:
                        fpath.unlink(missing_ok=True)

            # Restart: Flag schreiben + Prozess ersetzen
            if result.restart:
                await self._perform_restart(msg.room_id)

        except Exception as e:
            logger.error("Remote-Command '%s' fehlgeschlagen: %s", command, e)
            self._log_error(msg.sender, msg.body, e, handler="command")
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Command-Fehler: {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")

    async def _handle_claude_agent(
        self, msg: IncomingMessage, claude_text: str,
    ) -> None:
        """Delegiert an ClaudeAgent.process() für komplexe Anfragen.

        Args:
            msg: Original-Nachricht (für room_id).
            claude_text: Extrahierter Text aus Anführungszeichen.
        """
        logger.info("ClaudeAgent verarbeitet: %s", claude_text[:100])

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self._claude_agent.process, claude_text,
            )

            # Zusammenfassung senden
            if result.summary:
                await self._channel.send_text(msg.room_id, result.summary)

            # Details senden (z.B. Dateiinhalt, Testergebnis)
            if result.details:
                # Screenshot: Bild senden statt Pfad-Text
                if result.action_taken == "screenshot" and result.success:
                    image_path = Path(result.details)
                    if image_path.exists():
                        try:
                            await self._channel.send_image(
                                msg.room_id, image_path,
                            )
                        except NotImplementedError:
                            await self._channel.send_text(
                                msg.room_id,
                                "Screenshot aufgenommen, aber Bild-Upload "
                                "nicht unterstützt.",
                            )
                        finally:
                            image_path.unlink(missing_ok=True)
                else:
                    # Lange Details kürzen für Matrix
                    details = result.details
                    if len(details) > 4000:
                        details = details[:4000] + "\n... (gekürzt)"
                    await self._channel.send_text(msg.room_id, details)

        except Exception as e:
            logger.error("ClaudeAgent Fehler: %s", e)
            self._log_error(msg.sender, msg.body, e, handler="agent")
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Agent-Fehler: {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")

    async def _handle_document_summary(self, msg: IncomingMessage, result) -> None:
        """Schickt extrahierten Dokumenttext ans LLM für eine Zusammenfassung.

        Der Remote Command liefert den Rohtext in result.history_text.
        Hier wird der Text ans LLM geschickt, die Zusammenfassung an den User
        gesendet und der Rohtext in die Chat-History geschrieben (für Rückfragen).
        """
        try:
            loop = asyncio.get_running_loop()

            # Rohtext in Chat-History für Rückfragen
            self._chat_history.add(msg.sender, "user", msg.body)
            self._chat_history.add(msg.sender, "assistant", result.history_text)

            # LLM-Zusammenfassung
            summary_prompt = (
                f"Der Nutzer möchte folgendes Dokument zusammengefasst haben.\n\n"
                f"{result.history_text}\n\n"
                f"Fasse den Inhalt zusammen."
            )
            chat_context = self._chat_history.format_for_prompt(msg.sender)

            # Audio-Datei generieren wenn AudioConverter verfügbar
            tmp_wav = Path(tempfile.mktemp(suffix=".wav")) if self._audio_to_matrix else None
            llm_result = await loop.run_in_executor(
                None, self._assistant.process, summary_prompt, tmp_wav, chat_context,
            )

            # Header + LLM-Zusammenfassung senden
            if llm_result.response:
                response = f"{result.text}\n\n{llm_result.response}"
                self._chat_history.add(msg.sender, "assistant", llm_result.response)
                await self._channel.send_text(msg.room_id, response)
            else:
                # Fallback: Header senden wenn LLM keine Antwort liefert
                await self._channel.send_text(msg.room_id, result.text)

            # Audio senden (WAV → OGG → Matrix)
            await self._send_audio_if_available(msg.room_id, llm_result, tmp_wav)

        except Exception as e:
            logger.error("Dokument-Zusammenfassung LLM fehlgeschlagen: %s", e)
            # Fallback: zumindest den Header senden
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"{result.text}\n\n(LLM-Zusammenfassung fehlgeschlagen: {type(e).__name__})",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")

    async def _handle_audio_message(self, msg: IncomingMessage) -> None:
        """Transkribiert eine Audio-Nachricht via STT und delegiert an den Assistant.

        Flow:
            1. audio_data in temp-Datei schreiben
            2. STTEngine.transcribe() → TranscriptionResult
            3. Erkannter Text → _handle_assistant_message()
            4. Kein Text erkannt → Fehlermeldung an Raum senden

        Ohne STT-Engine: Fehlermeldung mit Hinweis senden.
        """
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

        tmp_path: Path | None = None
        try:
            loop = asyncio.get_running_loop()

            # Audio-Bytes in temp-Datei schreiben (.ogg – Endung für ffmpeg/whisper)
            suffix = ".ogg"
            if isinstance(msg.body, str) and "." in msg.body:
                suffix = Path(msg.body).suffix or suffix

            import tempfile
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(msg.audio_data)
                tmp_path = Path(tmp.name)

            logger.debug(
                "Audio-Nachricht transkribieren: %s (%d bytes)",
                tmp_path.name, len(msg.audio_data),
            )

            result = await loop.run_in_executor(
                None, self._stt.transcribe, tmp_path,
            )

            if result.is_empty():
                logger.info(
                    "STT: kein Text erkannt (Sender: %s)", msg.sender,
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
            # Geht durch den vollen Router (Commands, Claude, LLM)
            text_msg = IncomingMessage(
                sender=msg.sender,
                room_id=msg.room_id,
                body=result.text,
                timestamp=msg.timestamp,
                raw=msg.raw,
            )
            await self._handle_message(text_msg)

        except Exception as e:
            logger.error("Fehler bei Audio-Transkription: %s", e)
            self._log_error(msg.sender, msg.body, e, handler="stt")
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

    async def _handle_file_message(self, msg: IncomingMessage) -> None:
        """Verarbeitet eine Datei-Nachricht (PDF/TXT via Matrix-Upload).

        Flow:
            1. Datei-Bytes in temp-Datei schreiben
            2. DocumentReader.read_file() → Text extrahieren
            3. Text in Chat-History speichern (für Rückfragen)
            4. Text an LLM mit "Fasse zusammen"-Prompt senden
        """
        file_name = msg.file_name or msg.body or "unknown"
        tmp_file: Path | None = None

        # Prüfe ob DocumentReader verfügbar
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
                pass
            return

        # Prüfe ob Dateiformat unterstützt wird
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

        try:
            # Datei in temp-Verzeichnis schreiben
            suffix = Path(file_name).suffix or ".tmp"
            tmp_file = Path(tempfile.mktemp(suffix=suffix))
            tmp_file.write_bytes(msg.file_data)

            logger.info(
                "Datei verarbeiten: %s (%d bytes)",
                file_name, len(msg.file_data),
            )

            # Text extrahieren
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self._document_reader.read_file, tmp_file,
            )

            # Extrahierten Text in Chat-History speichern (für Rückfragen)
            doc_context = (
                f"Dokument '{result.source}' ({result.pages} Seiten):\n\n"
                f"{result.text}"
            )
            self._chat_history.add(msg.sender, "user", f"[Datei: {file_name}]")
            self._chat_history.add(msg.sender, "assistant", doc_context)

            # Text an LLM senden mit Zusammenfassungs-Prompt
            summary_prompt = (
                f"Der Nutzer hat folgendes Dokument geschickt: {file_name}\n\n"
                f"Inhalt:\n{result.text}\n\n"
                f"Fasse den Inhalt zusammen."
            )

            chat_context = self._chat_history.format_for_prompt(msg.sender)

            # Audio-Datei generieren wenn AudioConverter verfügbar
            tmp_wav = Path(tempfile.mktemp(suffix=".wav")) if self._audio_to_matrix else None
            llm_result = await loop.run_in_executor(
                None, self._assistant.process, summary_prompt, tmp_wav, chat_context,
            )

            # Antwort senden
            if llm_result.response:
                header = f"📄 {result.source} ({result.pages} Seite(n))"
                if result.truncated:
                    header += " [gekürzt]"
                response = f"{header}\n\n{llm_result.response}"
                self._chat_history.add(msg.sender, "assistant", llm_result.response)
                await self._channel.send_text(msg.room_id, response)

            # Audio senden (WAV → OGG → Matrix)
            await self._send_audio_if_available(msg.room_id, llm_result, tmp_wav)

        except Exception as e:
            logger.error("Datei-Verarbeitung fehlgeschlagen (%s): %s", file_name, e)
            self._log_error(msg.sender, file_name, e, handler="document")
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

    async def _handle_assistant_message(self, msg: IncomingMessage) -> None:
        """Delegiert an Assistant.process() (bestehender Flow)."""
        tmp_wav: Path | None = None

        try:
            loop = asyncio.get_running_loop()

            # User-Nachricht in Chat-History speichern
            self._chat_history.add(msg.sender, "user", msg.body)

            # Chat-History als Kontext für das LLM
            user_input = msg.body
            chat_context = self._chat_history.format_for_prompt(msg.sender)

            # Audio immer als Datei generieren (→ Matrix), nie lokal abspielen
            tmp_wav = Path(tempfile.mktemp(suffix=".wav")) if self._audio_to_matrix else None
            result = await loop.run_in_executor(
                None, self._assistant.process, user_input,
                tmp_wav, chat_context,
            )

            # LLM hat remote_command als Aktion gewählt → an CommandHandler weiterleiten
            if (
                result.action_executed == "remote_command"
                and result.action_success
                and self._remote_commands
            ):
                await self._handle_llm_remote_command(msg, result)
                return

            # Antwort in Chat-History speichern
            if result.response:
                self._chat_history.add(msg.sender, "assistant", result.response)

            # Textantwort senden
            if result.response:
                await self._channel.send_text(msg.room_id, result.response)

            # Audio senden (WAV → OGG → Matrix)
            await self._send_audio_if_available(msg.room_id, result, tmp_wav)

        except Exception as e:
            logger.error("Fehler bei Nachrichtenverarbeitung: %s", e)
            self._log_error(msg.sender, msg.body, e, handler="llm")
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Fehler bei der Verarbeitung: {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")
        finally:
            # Temp-Dateien aufräumen
            if tmp_wav and tmp_wav.exists():
                tmp_wav.unlink(missing_ok=True)

    async def _send_audio_if_available(
        self, room_id: str, result, tmp_wav: Path | None,
    ) -> None:
        """Konvertiert WAV→OGG und sendet Audio an Matrix (wenn vorhanden).

        Wenn AudioRouter auf matrix_and_local steht, wird das WAV zusätzlich
        lokal abgespielt (sounddevice oder AgentClient).
        """
        if not result.audio_path or not result.audio_path.exists():
            return
        if not self._audio_converter:
            return

        tmp_ogg: Path | None = None
        try:
            tmp_ogg = result.audio_path.with_suffix(".ogg")
            ogg_path, _duration = self._audio_converter.to_ogg_opus(
                result.audio_path, output_path=tmp_ogg,
            )
            await self._channel.send_audio(room_id, ogg_path)
            logger.debug("Sprachnachricht gesendet: %s", ogg_path.name)
        except Exception as e:
            logger.error("Audio-Senden fehlgeschlagen: %s", e)

        # Lokale Wiedergabe (wenn AudioRouter das will und WAV noch existiert)
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
        # Versuch 1: AgentClient (Laptop-Wiedergabe)
        agent = getattr(self._assistant, "_agent", None)
        if agent is not None:
            try:
                agent.play_audio_file(wav_path)
                logger.debug("Audio lokal via AgentClient abgespielt")
                return
            except Exception as e:
                logger.debug("AgentClient-Wiedergabe fehlgeschlagen: %s", e)

        # Versuch 2: sounddevice (Tower-Wiedergabe)
        try:
            import sounddevice as sd  # noqa: F811
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

    async def _handle_llm_remote_command(
        self, msg: IncomingMessage, llm_result,
    ) -> None:
        """LLM hat remote_command Aktion gewählt → Command ausführen.

        Sendet die LLM-Antwort (z.B. "Ich suche nach der Rechnung...") als Text,
        dann führt den eigentlichen Command aus und sendet dessen Ergebnis.
        """
        # LLM-Antwort senden und in History speichern
        if llm_result.response:
            self._chat_history.add(msg.sender, "assistant", llm_result.response)
            await self._channel.send_text(msg.room_id, llm_result.response)

        # Audio der LLM-Antwort senden (wenn vorhanden)
        await self._send_audio_if_available(msg.room_id, llm_result, None)

        # Command aus LLM-Params extrahieren: {"command": "mail suche RK Bedachung"}
        command_text = None
        if llm_result.action_params and isinstance(llm_result.action_params, dict):
            command_text = llm_result.action_params.get("command", "")

        if not command_text:
            logger.debug("LLM remote_command ohne command-Parameter")
            return

        logger.info("LLM → remote_command: %s", command_text)

        # Command durch den Handler parsen und ausführen
        cmd = self._remote_commands.parse_command(command_text)
        if cmd:
            # Fake-Message mit dem Command-Text (statt Original)
            cmd_msg = IncomingMessage(
                sender=msg.sender,
                room_id=msg.room_id,
                body=command_text,
                timestamp=msg.timestamp,
            )
            await self._handle_remote_command(cmd_msg, cmd)
        else:
            logger.warning(
                "LLM schlug remote_command vor, aber parse_command matcht nicht: %s",
                command_text,
            )

    def _log_error(
        self, sender: str, message: str, error: Exception,
        handler: str = "unknown",
    ) -> None:
        """Schreibt einen Fehler in logs/error_log.txt.

        Args:
            sender: Absender der Nachricht (z.B. @user:matrix.example.com).
            message: Originale Nachricht die den Fehler ausgelöst hat.
            error: Die aufgetretene Exception.
            handler: Welcher Handler den Fehler hatte (command/agent/llm).
        """
        if not self._error_log_dir:
            return

        try:
            self._error_log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self._error_log_dir / "error_log.txt"

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tb = traceback.format_exception(type(error), error, error.__traceback__)
            tb_str = "".join(tb).strip()

            entry = (
                f"[{timestamp}] handler={handler}\n"
                f"  sender: {sender}\n"
                f"  message: {message}\n"
                f"  error: {type(error).__name__}: {error}\n"
                f"  traceback:\n"
                + "\n".join(f"    {line}" for line in tb_str.splitlines())
                + "\n\n"
            )

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(entry)

        except Exception as log_err:
            logger.debug("Error-Log schreiben fehlgeschlagen: %s", log_err)

    def _start_alert_monitor(self) -> None:
        """Konfiguriert und startet den AlertMonitor mit thread-safe Callback."""
        loop = self._loop
        room_id = self._alert_room_id
        channel = self._channel

        def send_alert(text: str) -> None:
            """Thread-safe Alert-Sender: dispatcht in den async Event-Loop."""
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    channel.send_text(room_id, f"🔔 {text}"),
                    loop,
                )

        self._alert_monitor._send_alert = send_alert
        self._alert_monitor.start()

    def _start_reminder_scheduler(self) -> None:
        """Konfiguriert und startet den ReminderScheduler mit thread-safe Callback."""
        loop = self._loop
        room_id = self._alert_room_id  # Erinnerungen gehen an denselben Raum
        channel = self._channel

        def send_reminder(user_id: str, text: str) -> None:
            """Thread-safe Reminder-Sender: dispatcht in den async Event-Loop."""
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    channel.send_text(room_id, text),
                    loop,
                )

        self._reminder_scheduler._send_reminder = send_reminder
        self._reminder_scheduler.start()

    def _start_briefing_scheduler(self) -> None:
        """Konfiguriert und startet den BriefingScheduler mit thread-safe Callback."""
        loop = self._loop
        room_id = self._alert_room_id
        channel = self._channel

        def send_briefing(text: str) -> None:
            """Thread-safe Briefing-Sender: dispatcht in den async Event-Loop."""
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    channel.send_text(room_id, text),
                    loop,
                )

        self._briefing_scheduler._send_briefing = send_briefing
        self._briefing_scheduler.start()

    async def _perform_restart(self, room_id: str) -> None:
        """Schreibt Restart-Flag und startet den Prozess neu.

        Wird innerhalb des Bridge-Threads aufgerufen, daher kein self.stop()
        (Thread kann sich nicht selbst joinen). Stattdessen: disconnect → Flag → execv.

        Args:
            room_id: Room-ID für die Rückmeldung nach dem Restart.
        """
        logger.info("Restart angefordert, starte Prozess neu...")

        # Flag-Datei schreiben (room_id für Startup-Nachricht)
        try:
            RESTART_FLAG_FILE.write_text(room_id, encoding="utf-8")
        except Exception as e:
            logger.error("Restart-Flag schreiben fehlgeschlagen: %s", e)

        # AlertMonitor stoppen (wenn vorhanden)
        if self._alert_monitor and self._alert_monitor.is_running:
            self._alert_monitor.stop()

        # ReminderScheduler stoppen (wenn vorhanden)
        if self._reminder_scheduler and self._reminder_scheduler.is_running:
            self._reminder_scheduler.stop()

        # BriefingScheduler stoppen (wenn vorhanden)
        if self._briefing_scheduler and self._briefing_scheduler.is_running:
            self._briefing_scheduler.stop()

        # Matrix-Verbindung trennen (wir sind im async Loop)
        try:
            await self._channel.disconnect()
        except Exception as e:
            logger.debug("Disconnect bei Restart (ignoriert): %s", e)

        self._running = False

        # Prozess ersetzen: gleiche Python-Exe + gleiche Argumente
        python = sys.executable
        args = sys.argv[:]

        logger.info("os.execv(%s, %s)", python, [python, *args])
        try:
            os.execv(python, [python, *args])
        except Exception as e:
            logger.error("os.execv fehlgeschlagen: %s", e)
            # Fallback: Flag aufräumen
            RESTART_FLAG_FILE.unlink(missing_ok=True)

    @staticmethod
    async def send_restart_notification(channel: MessageChannel) -> None:
        """Prüft ob ein Restart-Flag existiert und sendet Begrüßung.

        Wird beim Start aufgerufen (vor sync_loop). Löscht das Flag nach dem Senden.
        """
        if not RESTART_FLAG_FILE.exists():
            return

        try:
            room_id = RESTART_FLAG_FILE.read_text(encoding="utf-8").strip()
            RESTART_FLAG_FILE.unlink(missing_ok=True)

            if room_id:
                await channel.send_text(
                    room_id,
                    "Bin wieder da! Neustart erfolgreich. ✅",
                )
                logger.info("Restart-Benachrichtigung gesendet an %s", room_id)
        except Exception as e:
            logger.error("Restart-Benachrichtigung fehlgeschlagen: %s", e)
            RESTART_FLAG_FILE.unlink(missing_ok=True)

    async def _shutdown(self) -> None:
        """Async Shutdown: Disconnect und Loop stoppen."""
        try:
            await self._channel.disconnect()
        except Exception as e:
            logger.debug("Disconnect-Fehler (ignoriert): %s", e)

        # Alle laufenden Tasks abbrechen
        loop = asyncio.get_running_loop()
        for task in asyncio.all_tasks(loop):
            if task is not asyncio.current_task():
                task.cancel()
        loop.stop()
