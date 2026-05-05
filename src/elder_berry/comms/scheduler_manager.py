"""SchedulerManager – Verwaltet Background-Scheduler mit thread-safe Callbacks.

Löst die Kopplung zwischen MatrixBridge und den einzelnen Schedulern.
Statt private Attribute der Scheduler zu setzen, werden Callbacks über
öffentliche Methoden registriert.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from elder_berry.comms.message_channel import MessageChannel

logger = logging.getLogger(__name__)


class Schedulable(Protocol):
    """Protocol für Objekte die als Background-Scheduler gestartet werden können.

    Callback-Attribut wird ueber ``setattr`` (siehe ``register``) gesetzt --
    nicht ueber eine ``set_callback``-Methode. Das Protocol bildet ab, was
    ``start_all``/``stop_all`` tatsaechlich braucht.
    """

    @property
    def is_running(self) -> bool: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


class SchedulerManager:
    """Verwaltet Background-Scheduler mit thread-safe Matrix-Callbacks.

    Statt dass die Bridge direkt auf private Attribute der Scheduler zugreift,
    registriert der SchedulerManager Callbacks über öffentliche Methoden.
    """

    def __init__(
        self,
        channel: MessageChannel,
        room_id: str | None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._channel = channel
        self._room_id = room_id
        self._loop = loop
        self._schedulers: list[tuple[str, Schedulable]] = []  # (name, scheduler)

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    @loop.setter
    def loop(self, value: asyncio.AbstractEventLoop | None) -> None:
        self._loop = value

    def _make_send_callback(self, prefix: str = "") -> Callable[..., None]:
        """Erstellt einen thread-safe Callback der Text an Matrix sendet."""
        loop = self._loop
        room_id = self._room_id
        channel = self._channel

        def send(text_or_user_id: str, text: str | None = None) -> None:
            """Thread-safe Sender. Unterstützt (text) und (user_id, text) Signaturen."""
            actual_text = text if text is not None else text_or_user_id
            if prefix:
                actual_text = f"{prefix} {actual_text}"
            # Kein room_id konfiguriert -> Silent-No-Op (Optional-Typ ist
            # Absicht: Bridge ohne Matrix-Anbindung).
            if loop and loop.is_running() and room_id:
                asyncio.run_coroutine_threadsafe(
                    channel.send_text(room_id, actual_text),
                    loop,
                )

        return send

    def register(
        self,
        name: str,
        scheduler: Schedulable,
        callback_attr: str,
        prefix: str = "",
    ) -> None:
        """Registriert einen Scheduler mit thread-safe Callback.

        Args:
            name: Name für Logging
            scheduler: Scheduler-Objekt (muss start()/stop()/is_running haben)
            callback_attr: Name des Callback-Attributs (z.B. '_send_alert')
            prefix: Optionaler Prefix für Nachrichten (z.B. '🔔')
        """
        self._schedulers.append((name, scheduler))
        callback = self._make_send_callback(prefix)
        setattr(scheduler, callback_attr, callback)
        logger.debug("Scheduler '%s' registriert (callback: %s)", name, callback_attr)

    def start_all(self) -> None:
        """Startet alle registrierten Scheduler."""
        for name, scheduler in self._schedulers:
            try:
                scheduler.start()
                logger.info("Scheduler '%s' gestartet", name)
            except Exception as e:
                logger.error(
                    "Scheduler '%s' konnte nicht gestartet werden: %s", name, e
                )

    def stop_all(self) -> None:
        """Stoppt alle laufenden Scheduler."""
        for name, scheduler in self._schedulers:
            if hasattr(scheduler, "is_running") and scheduler.is_running:
                try:
                    scheduler.stop()
                    logger.info("Scheduler '%s' gestoppt", name)
                except Exception as e:
                    logger.error("Scheduler '%s' Stop fehlgeschlagen: %s", name, e)
