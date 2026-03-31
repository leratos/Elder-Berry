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

Handler-Logik ist in separate Module ausgelagert:
- message_handlers.py: BridgeMessageHandler (Commands, LLM, Claude Agent)
- audio_pipeline.py: AudioPipeline (STT, TTS, Dateien)
- restart_manager.py: Restart-Logik (Flag, Lock, Prozess-Ersetzung)
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import threading
from datetime import datetime
from typing import TYPE_CHECKING

from elder_berry.comms.audio_pipeline import AudioPipeline
from elder_berry.comms.chat_history import ChatHistory, Summarizer
from elder_berry.comms.message_channel import IncomingMessage, MessageChannel
from elder_berry.comms.message_handlers import BridgeMessageHandler
from elder_berry.comms.pending_confirmation import PendingConfirmationStore
from elder_berry.comms.restart_manager import (
    RESTART_FLAG_FILE,
    read_restart_timestamp,
    send_restart_notification,
)
from elder_berry.comms.scheduler_manager import SchedulerManager

if TYPE_CHECKING:
    from elder_berry.comms.alert_monitor import AlertMonitor
    from elder_berry.comms.audio_converter import AudioConverter
    from elder_berry.comms.calendar_watcher import CalendarWatcher
    from elder_berry.comms.claude_agent import ClaudeAgent
    from elder_berry.comms.briefing_scheduler import BriefingScheduler
    from elder_berry.comms.reminder_scheduler import ReminderScheduler
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.core.assistant import Assistant
    from elder_berry.core.audio_router import AudioRouter
    from elder_berry.core.task_chain import TaskChainRunner
    from elder_berry.stt.base import STTEngine
    from elder_berry.tools.document_reader import DocumentReader
    from elder_berry.tools.email_sender import EmailSender
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient

logger = logging.getLogger(__name__)

# Regex: Text in Anführungszeichen extrahieren (erste Fundstelle)
_QUOTED_TEXT_PATTERN = re.compile(r'"([^"]+)"')


class MatrixBridge:
    """Verbindet einen async MessageChannel mit dem synchronen Assistant.

    - Startet den MessageChannel sync_loop in einem eigenen Thread mit eigenem Event-Loop.
    - Empfangene Nachrichten werden an BridgeMessageHandler delegiert.
    - Optional: AudioPipeline für STT/TTS, RestartManager für Neustarts.
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
        allowed_senders: frozenset[str] | None = None,
        stt: STTEngine | None = None,
        reminder_scheduler: ReminderScheduler | None = None,
        briefing_scheduler: BriefingScheduler | None = None,
        calendar_watcher: CalendarWatcher | None = None,
        document_reader: DocumentReader | None = None,
        audio_router: AudioRouter | None = None,
        task_chain: TaskChainRunner | None = None,
        summarizer: Summarizer | None = None,
        email_sender: EmailSender | None = None,
        pending_store: PendingConfirmationStore | None = None,
        nextcloud_files: NextcloudFilesClient | None = None,
    ) -> None:
        self._channel = channel
        self._assistant = assistant
        self._remote_commands = remote_commands
        self._claude_agent = claude_agent
        self._alert_monitor = alert_monitor
        self._alert_room_id = alert_room_id
        self._allowed_senders = allowed_senders
        self._reminder_scheduler = reminder_scheduler
        self._briefing_scheduler = briefing_scheduler
        self._calendar_watcher = calendar_watcher

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._start_time: float = 0.0
        self._restart_cooldown_until: float = 0.0

        self._chat_history = ChatHistory(
            max_messages=10, summarizer=summarizer,
        )
        self._pending = pending_store or PendingConfirmationStore()
        self._scheduler_mgr: SchedulerManager | None = None

        # AudioPipeline (STT, TTS, Dateien)
        self._audio = AudioPipeline(
            channel=channel,
            assistant=assistant,
            chat_history=self._chat_history,
            stt=stt,
            audio_converter=audio_converter,
            audio_router=audio_router,
            document_reader=document_reader,
        )

        # MessageHandler (Commands, LLM, Claude Agent, Pending)
        self._handler = BridgeMessageHandler(
            channel=channel,
            assistant=assistant,
            audio_pipeline=self._audio,
            chat_history=self._chat_history,
            pending=self._pending,
            remote_commands=remote_commands,
            claude_agent=claude_agent,
            task_chain=task_chain,
            email_sender=email_sender,
            nextcloud_files=nextcloud_files,
        )

    @staticmethod
    def extract_claude_message(text: str) -> str | None:
        """Prüft ob eine Nachricht an den ClaudeAgent gerichtet ist.

        Erkennung: Das Wort "claude" muss im Text vorkommen UND der eigentliche
        Auftrag muss in Anführungszeichen stehen.

        Returns:
            Der extrahierte Text in Anführungszeichen oder None.
        """
        if "claude" not in text.lower():
            return None
        match = _QUOTED_TEXT_PATTERN.search(text)
        if not match:
            return None
        return match.group(1)

    @property
    def _audio_to_matrix(self) -> bool:
        """True wenn TTS-Audio als Datei generiert werden soll (für Matrix)."""
        return self._audio.audio_to_matrix

    @property
    def is_running(self) -> bool:
        """True wenn die Bridge aktiv ist."""
        return self._running

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Startet die Bridge in einem Hintergrund-Thread."""
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

        if self._scheduler_mgr:
            self._scheduler_mgr.stop_all()

        self._running = False

        if self._loop and self._loop.is_running():
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

        # Startzeitpunkt setzen
        is_restart = RESTART_FLAG_FILE.exists()
        restart_server_ts = read_restart_timestamp()
        if restart_server_ts > 0:
            self._start_time = restart_server_ts
        elif is_restart:
            self._start_time = datetime.now().timestamp() + 10
        else:
            self._start_time = datetime.now().timestamp()

        if is_restart:
            self._restart_cooldown_until = time.monotonic() + 60
            self._handler.restart_cooldown_until = self._restart_cooldown_until
            logger.info(
                "Restart erkannt: _start_time=%.3f (server_ts=%.3f), "
                "Cooldown 60s aktiv",
                self._start_time, restart_server_ts,
            )

        await send_restart_notification(self._channel)

        self._channel.on_message(self._handle_message)
        self._audio.set_message_callback(self._handle_message)
        logger.info("Bridge verbunden, warte auf Nachrichten...")

        # Error-Alerting verdrahten
        if self._alert_room_id:
            self._setup_error_alerting()

        # Scheduler registrieren und starten
        self._scheduler_mgr = SchedulerManager(
            channel=self._channel,
            room_id=self._alert_room_id,
            loop=self._loop,
        )
        self._handler._scheduler_mgr = self._scheduler_mgr

        if self._alert_monitor and self._alert_room_id:
            self._scheduler_mgr.register(
                "AlertMonitor", self._alert_monitor,
                "_send_alert", prefix="\U0001f514",
            )

        if self._reminder_scheduler:
            self._scheduler_mgr.register(
                "ReminderScheduler", self._reminder_scheduler,
                "_send_reminder",
            )

        if self._briefing_scheduler:
            self._scheduler_mgr.register(
                "BriefingScheduler", self._briefing_scheduler,
                "_send_briefing",
            )

        if self._calendar_watcher:
            self._scheduler_mgr.register(
                "CalendarWatcher", self._calendar_watcher,
                "_send_alert",
            )

        self._scheduler_mgr.start_all()

        try:
            await self._channel.sync_loop()
        except asyncio.CancelledError:
            logger.debug("Sync-Loop abgebrochen")
        except Exception as e:
            logger.error("Sync-Loop Fehler: %s", e)

    # ------------------------------------------------------------------
    # Message Dispatcher
    # ------------------------------------------------------------------

    async def _handle_message(self, msg: IncomingMessage) -> None:
        """Callback für eingehende Nachrichten – dispatcht an Handler."""
        logger.info(
            "Nachricht von %s (ts=%.3f): %s",
            msg.sender, msg.timestamp, msg.body[:100],
        )

        # Alte Nachrichten ignorieren
        if msg.timestamp > 0 and msg.timestamp <= self._start_time:
            logger.info(
                "Alte Nachricht ignoriert (ts=%.3f <= start=%.3f): %s",
                msg.timestamp, self._start_time, msg.body[:50],
            )
            return

        # Sender-Whitelist
        if self._allowed_senders and msg.sender not in self._allowed_senders:
            logger.warning("Nachricht von unbekanntem Sender ignoriert: %s", msg.sender)
            return

        # Audio → STT → Text → Re-Dispatch
        if msg.audio_data is not None:
            await self._audio.handle_audio_message(msg)
            return

        # Datei → DocumentReader → LLM
        if msg.file_data is not None:
            await self._audio.handle_file_message(msg)
            return

        # Pending Confirmation Intercept (Phase 28)
        response_type, action = self._pending.check_response(
            msg.sender, msg.body,
        )
        if response_type == "confirm":
            await self._handler.handle_pending_confirm(msg, action)
            return
        if response_type == "cancel":
            await self._channel.send_text(msg.room_id, "\u274c Verworfen.")
            self._chat_history.add(msg.sender, "user", msg.body)
            self._chat_history.add(msg.sender, "assistant", "Verworfen.")
            return
        if response_type == "modify":
            await self._handler.handle_pending_modify(msg, action)
            return
        if response_type == "pending":
            await self._channel.send_text(
                msg.room_id,
                f"\u23f3 Du hast noch eine offene Aktion ({action.action_type}).\n"
                f"Antworte mit 'ja' zum Bestätigen, 'nein' zum Verwerfen, "
                f"oder 'ändern: <Anweisung>' zum Anpassen.",
            )
            return

        # Command-Router: direkte Commands vor LLM
        if self._remote_commands:
            command = self._remote_commands.parse_command(msg.body)
            if command:
                await self._handler.handle_remote_command(msg, command)
                return

        # Claude Agent: nur bei explizitem "claude" + "..."
        if self._claude_agent:
            claude_text = self.extract_claude_message(msg.body)
            if claude_text:
                await self._handler.handle_claude_agent(msg, claude_text)
                return

        # LLM-Fallback
        await self._handler.handle_assistant_message(msg)

    # ------------------------------------------------------------------
    # Error Alerting
    # ------------------------------------------------------------------

    def _setup_error_alerting(self) -> None:
        """Verdrahtet den ErrorCollectorHandler mit Matrix-Alerting."""
        from elder_berry.core.error_collector import ErrorCollectorHandler

        loop = self._loop
        room_id = self._alert_room_id
        channel = self._channel

        collector = None
        for handler in logging.getLogger().handlers:
            if isinstance(handler, ErrorCollectorHandler):
                collector = handler
                break

        if not collector:
            logger.debug("Kein ErrorCollectorHandler gefunden – Error-Alerting inaktiv")
            return

        def alert(msg: str) -> None:
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    channel.send_text(room_id, msg),
                    loop,
                )

        collector.set_alert_callback(alert)
        logger.info("Error-Alerting via Matrix aktiviert")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def _shutdown(self) -> None:
        """Async Shutdown: Disconnect und Loop stoppen."""
        try:
            await self._channel.disconnect()
        except Exception as e:
            logger.debug("Disconnect-Fehler (ignoriert): %s", e)

        loop = asyncio.get_running_loop()
        for task in asyncio.all_tasks(loop):
            if task is not asyncio.current_task():
                task.cancel()
        loop.stop()
