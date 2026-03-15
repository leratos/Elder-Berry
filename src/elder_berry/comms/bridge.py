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

Verwendung:
    bridge = MatrixBridge(channel=matrix_channel, assistant=assistant)
    bridge.start()   # Startet async Loop + Message-Handler
    ...
    bridge.stop()    # Stoppt sauber
"""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.message_channel import IncomingMessage, MessageChannel

if TYPE_CHECKING:
    from elder_berry.core.assistant import Assistant

logger = logging.getLogger(__name__)


class MatrixBridge:
    """Verbindet einen async MessageChannel mit dem synchronen Assistant.

    - Startet den MessageChannel sync_loop in einem eigenen Thread mit eigenem Event-Loop.
    - Empfangene Nachrichten werden an Assistant.process() delegiert (in Thread-Pool).
    - Antworten (Text + optional Audio) werden über den Kanal zurückgesendet.
    """

    def __init__(
        self,
        channel: MessageChannel,
        assistant: Assistant,
        audio_dir: Path | None = None,
    ) -> None:
        self._channel = channel
        self._assistant = assistant
        self._audio_dir = audio_dir or Path.home() / ".elder-berry" / "audio"
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
        self._channel.on_message(self._handle_message)
        logger.info("Bridge verbunden, warte auf Nachrichten...")

        try:
            await self._channel.sync_loop()
        except asyncio.CancelledError:
            logger.debug("Sync-Loop abgebrochen")
        except Exception as e:
            logger.error("Sync-Loop Fehler: %s", e)

    async def _handle_message(self, msg: IncomingMessage) -> None:
        """Callback für eingehende Nachrichten.

        Delegiert Assistant.process() in den Thread-Pool (blockierend → async).
        Sendet Antwort (Text + Audio) über den Kanal zurück.
        """
        logger.info("Nachricht von %s: %s", msg.sender, msg.body[:100])

        try:
            # Assistant.process() ist synchron → in Thread-Pool ausführen
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self._assistant.process, msg.body,
            )

            # Textantwort senden
            if result.response:
                await self._channel.send_text(msg.room_id, result.response)

            # Audio senden (wenn TTS eine Datei generiert hat)
            audio_path = self._find_latest_audio()
            if audio_path and audio_path.exists():
                await self._channel.send_audio(msg.room_id, audio_path)

        except Exception as e:
            logger.error("Fehler bei Nachrichtenverarbeitung: %s", e)
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"⚠ Fehler bei der Verarbeitung: {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")

    def _find_latest_audio(self) -> Path | None:
        """Sucht die neueste Audio-Datei im Audio-Verzeichnis.

        Hinweis: In der finalen Integration wird der Audio-Pfad direkt
        vom Assistant/TTS übergeben. Diese Methode ist ein Platzhalter.
        """
        if not self._audio_dir.exists():
            return None

        ogg_files = sorted(
            self._audio_dir.glob("*.ogg"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return ogg_files[0] if ogg_files else None

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
