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

from elder_berry.comms.message_channel import IncomingMessage, MessageChannel

if TYPE_CHECKING:
    from elder_berry.comms.alert_monitor import AlertMonitor
    from elder_berry.comms.audio_converter import AudioConverter
    from elder_berry.comms.claude_agent import ClaudeAgent
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.core.assistant import Assistant

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
    ) -> None:
        self._channel = channel
        self._assistant = assistant
        self._audio_converter = audio_converter
        self._remote_commands = remote_commands
        self._claude_agent = claude_agent
        self._alert_monitor = alert_monitor
        self._alert_room_id = alert_room_id
        self._error_log_dir = error_log_dir
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._running = False

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

            # Text-Antwort senden
            if result.text:
                await self._channel.send_text(msg.room_id, result.text)

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

    async def _handle_assistant_message(self, msg: IncomingMessage) -> None:
        """Delegiert an Assistant.process() (bestehender Flow)."""
        tmp_wav: Path | None = None
        tmp_ogg: Path | None = None

        try:
            loop = asyncio.get_running_loop()

            # Audio-Modus: TTS in Datei generieren statt abspielen
            if self._audio_converter and self._audio_converter.ffmpeg_available:
                tmp_wav = Path(tempfile.mktemp(suffix=".wav"))
                result = await loop.run_in_executor(
                    None, self._assistant.process, msg.body, tmp_wav,
                )
            else:
                result = await loop.run_in_executor(
                    None, self._assistant.process, msg.body,
                )

            # Textantwort senden
            if result.response:
                await self._channel.send_text(msg.room_id, result.response)

            # Audio senden (WAV → OGG → Matrix)
            if result.audio_path and result.audio_path.exists():
                tmp_ogg = result.audio_path.with_suffix(".ogg")
                ogg_path, _duration = self._audio_converter.to_ogg_opus(
                    result.audio_path, output_path=tmp_ogg,
                )
                await self._channel.send_audio(msg.room_id, ogg_path)
                logger.debug("Sprachnachricht gesendet: %s", ogg_path.name)

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
            if tmp_ogg and tmp_ogg.exists():
                tmp_ogg.unlink(missing_ok=True)

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
