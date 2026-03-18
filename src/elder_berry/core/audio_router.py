"""AudioRouter – steuert ob Audio lokal abgespielt wird, nur an Matrix geht, oder beides."""

from enum import Enum
from threading import Lock


class AudioOutputMode(Enum):
    """Audio-Ausgabemodus."""

    MATRIX_ONLY = "matrix_only"
    MATRIX_AND_LOCAL = "matrix_and_local"


class AudioRouter:
    """Thread-safe Audio-Routing-Flag.

    Bestimmt ob TTS-Audio nur an Matrix gesendet wird oder zusätzlich
    lokal am PC abgespielt wird. Default: matrix_only (sicher für unterwegs).

    Parameters
    ----------
    default_mode : AudioOutputMode
        Startwert. Default ``MATRIX_ONLY``.
    local_available : bool
        Ob lokale Wiedergabe überhaupt möglich ist (sounddevice / AgentClient).
        Wenn False, kann der Modus nicht auf MATRIX_AND_LOCAL gesetzt werden.
    """

    def __init__(
        self,
        default_mode: AudioOutputMode = AudioOutputMode.MATRIX_ONLY,
        local_available: bool = False,
    ) -> None:
        self._lock = Lock()
        self._local_available = local_available
        # Wenn lokal nicht verfügbar, erzwinge matrix_only
        if not local_available and default_mode == AudioOutputMode.MATRIX_AND_LOCAL:
            default_mode = AudioOutputMode.MATRIX_ONLY
        self._mode = default_mode

    @property
    def mode(self) -> AudioOutputMode:
        """Aktueller Ausgabemodus (thread-safe)."""
        with self._lock:
            return self._mode

    @property
    def local_available(self) -> bool:
        """Ob lokale Wiedergabe überhaupt möglich ist."""
        return self._local_available

    def set_mode(self, mode: AudioOutputMode) -> AudioOutputMode:
        """Modus setzen. Gibt den tatsächlich gesetzten Modus zurück.

        Wenn lokale Wiedergabe nicht verfügbar ist und MATRIX_AND_LOCAL
        angefragt wird, bleibt der Modus auf MATRIX_ONLY.
        """
        with self._lock:
            if mode == AudioOutputMode.MATRIX_AND_LOCAL and not self._local_available:
                return self._mode
            self._mode = mode
            return self._mode

    def toggle(self) -> AudioOutputMode:
        """Modus umschalten. Gibt den neuen Modus zurück."""
        with self._lock:
            if not self._local_available:
                return self._mode
            if self._mode == AudioOutputMode.MATRIX_ONLY:
                self._mode = AudioOutputMode.MATRIX_AND_LOCAL
            else:
                self._mode = AudioOutputMode.MATRIX_ONLY
            return self._mode

    def should_play_local(self) -> bool:
        """Soll Audio lokal abgespielt werden?"""
        with self._lock:
            return self._mode == AudioOutputMode.MATRIX_AND_LOCAL

    def should_send_matrix(self) -> bool:
        """Soll Audio an Matrix gesendet werden? (Immer True.)"""
        return True
