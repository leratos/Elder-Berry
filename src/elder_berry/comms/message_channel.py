"""MessageChannel – Abstrakte Basisklasse für bidirektionale Nachrichtenkanäle.

Definiert das Interface für Kommunikationskanäle (Matrix, Discord, etc.).
Jede Implementierung muss connect/disconnect/send/receive abbilden.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine


@dataclass(frozen=True)
class IncomingMessage:
    """DTO für eingehende Nachrichten aus einem Kanal."""

    sender: str
    """Absender-ID (z.B. @user:matrix.example.com)."""

    room_id: str
    """Raum/Kanal-ID in dem die Nachricht empfangen wurde."""

    body: str
    """Nachrichtentext. Bei Audio-Nachrichten: Dateiname oder leer."""

    timestamp: float
    """Unix-Timestamp des Nachrichtenempfangs."""

    raw: Any = None
    """Optionale Rohdaten des Quellsystems (z.B. nio.RoomMessageText)."""

    audio_data: bytes | None = None
    """Rohe Audio-Bytes (heruntergeladen vom Matrix-Server) oder None bei Textnachrichten."""


# Typ-Alias für den Callback: empfängt IncomingMessage, gibt None zurück (async).
MessageCallback = Callable[[IncomingMessage], Coroutine[Any, Any, None]]


class MessageChannel(ABC):
    """Abstrakte Basisklasse für bidirektionale Nachrichtenkanäle.

    Implementierungen: MatrixChannel (Phase 6), ggf. DiscordChannel etc.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Verbindung zum Kanal herstellen (Login, initialer Sync, etc.)."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Verbindung sauber trennen."""
        ...

    @abstractmethod
    async def send_text(self, room_id: str, text: str) -> None:
        """Sendet eine Textnachricht in den angegebenen Raum."""
        ...

    @abstractmethod
    async def send_audio(self, room_id: str, audio_path: Path) -> None:
        """Sendet eine Audiodatei (z.B. OGG/Opus Sprachnachricht) in den Raum."""
        ...

    async def send_image(self, room_id: str, image_path: Path) -> None:
        """Sendet ein Bild (z.B. Screenshot) in den Raum.

        Standardimplementierung wirft NotImplementedError.
        Unterklassen können dies überschreiben.
        """
        raise NotImplementedError("send_image nicht implementiert")

    async def send_file(self, room_id: str, file_path: Path) -> None:
        """Sendet eine beliebige Datei in den Raum.

        Standardimplementierung wirft NotImplementedError.
        Unterklassen können dies überschreiben.
        """
        raise NotImplementedError("send_file nicht implementiert")

    @abstractmethod
    def on_message(self, callback: MessageCallback) -> None:
        """Registriert einen Callback für eingehende Nachrichten.

        Der Callback wird für jede empfangene Textnachricht aufgerufen.
        Mehrere Callbacks sind möglich (additive Registrierung).
        """
        ...

    @abstractmethod
    async def sync_loop(self) -> None:
        """Startet den Sync-Loop (blockierend, für asyncio.create_task).

        Läuft bis disconnect() aufgerufen wird oder ein fataler Fehler auftritt.
        """
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True wenn der Kanal verbunden und bereit ist."""
        ...
