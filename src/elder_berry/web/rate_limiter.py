"""RateLimiter – Sliding-Window-Rate-Limiting für Auth-Endpoints (Phase 59).

Schützt Login- und Token-Validierungs-Endpoints vor Brute-Force-Angriffen.
Pro Client-IP wird ein gleitendes Zeitfenster mit fehlgeschlagenen Versuchen
geführt. Bei Überschreitung des Schwellwerts wird die IP für ``lockout_seconds``
gesperrt.

Merkmale
--------
- In-Memory (kein externer State). Restart setzt alle Limits zurück.
- asyncio-safe: internes asyncio.Lock schützt den gemeinsamen State.
- Automatische Bereinigung veralteter Einträge nach jedem Check.
- Konfigurierbar: max_attempts, window_seconds, lockout_seconds.
- Audit-Events gehen an den Logger ``elder_berry.security``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import NamedTuple

security_logger = logging.getLogger("elder_berry.security")

_DEFAULT_CLEANUP_INTERVAL = 300  # 5 min zwischen Bereinigungsläufen


class _State(NamedTuple):
    attempts: list  # list[float] – Zeitstempel fehlgeschlagener Versuche
    lockout_until: float  # Unix-Timestamp; 0.0 = kein Lockout


class RateLimiter:
    """Sliding-Window-Rate-Limiter, in-memory, asyncio-safe.

    Parameters
    ----------
    max_attempts : int
        Maximale Fehlversuche innerhalb von ``window_seconds`` bevor
        ein Lockout ausgelöst wird.
    window_seconds : int
        Länge des Beobachtungsfensters in Sekunden.
    lockout_seconds : int
        Dauer des Lockouts nach Überschreitung.
    name : str
        Bezeichner für Audit-Log-Einträge (z.B. ``"dashboard_login"``).
    """

    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        lockout_seconds: int,
        name: str = "rate_limiter",
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts muss >= 1 sein")
        if window_seconds < 1:
            raise ValueError("window_seconds muss >= 1 sein")
        if lockout_seconds < 1:
            raise ValueError("lockout_seconds muss >= 1 sein")

        self._max = max_attempts
        self._window = window_seconds
        self._lockout = lockout_seconds
        self._name = name

        # key → (timestamps_of_failures, lockout_until_ts)
        self._data: dict[str, tuple[list[float], float]] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup: float = 0.0

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    async def check_and_record(
        self, key: str, now: float | None = None,
    ) -> bool:
        """Prüft ob ``key`` erlaubt ist und zählt einen Fehlversuch.

        Muss nach einem fehlgeschlagenen Auth-Versuch aufgerufen werden.
        Bei erfolgreichem Login :meth:`reset` aufrufen.

        Returns
        -------
        bool
            ``True`` wenn der Request erlaubt ist (Limit noch nicht
            erreicht), ``False`` wenn gesperrt.
        """
        ts = now if now is not None else time.time()
        async with self._lock:
            self._maybe_cleanup(ts)
            attempts, lockout_until = self._data.get(key, ([], 0.0))

            # Aktiver Lockout?
            if lockout_until > ts:
                remaining = int(lockout_until - ts)
                security_logger.warning(
                    "[%s] BLOCKED %s – Lockout noch %ds",
                    self._name, key, remaining,
                )
                return False

            # Abgelaufene Versuche aus dem Fenster entfernen
            cutoff = ts - self._window
            attempts = [t for t in attempts if t > cutoff]

            # Fehlversuch aufzeichnen
            attempts.append(ts)

            if len(attempts) >= self._max:
                # Lockout auslösen
                lockout_until = ts + self._lockout
                self._data[key] = ([], lockout_until)
                security_logger.warning(
                    "[%s] LOCKOUT %s – %d Fehlversuche in %ds, "
                    "gesperrt für %ds bis %s",
                    self._name, key, len(attempts), self._window,
                    self._lockout,
                    _format_ts(lockout_until),
                )
                return False

            self._data[key] = (attempts, 0.0)
            return True

    async def is_blocked(self, key: str, now: float | None = None) -> bool:
        """True wenn ``key`` gerade im Lockout ist."""
        ts = now if now is not None else time.time()
        async with self._lock:
            _, lockout_until = self._data.get(key, ([], 0.0))
            return lockout_until > ts

    async def reset(self, key: str) -> None:
        """Löscht alle Fehlversuche für ``key`` (bei erfolgreichem Login)."""
        async with self._lock:
            if key in self._data:
                del self._data[key]

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _maybe_cleanup(self, now: float) -> None:
        """Entfernt abgelaufene Einträge – wird beim Lock gehalten aufgerufen."""
        if now - self._last_cleanup < _DEFAULT_CLEANUP_INTERVAL:
            return
        cutoff = now - max(self._window, self._lockout)
        stale = [
            k for k, (attempts, lockout_until) in self._data.items()
            if lockout_until <= now and (not attempts or max(attempts) <= cutoff)
        ]
        for k in stale:
            del self._data[k]
        if stale:
            security_logger.debug(
                "[%s] Cleanup: %d veraltete Einträge entfernt", self._name, len(stale),
            )
        self._last_cleanup = now

    @property
    def name(self) -> str:
        return self._name

    @property
    def max_attempts(self) -> int:
        return self._max

    @property
    def window_seconds(self) -> int:
        return self._window

    @property
    def lockout_seconds(self) -> int:
        return self._lockout


def _format_ts(ts: float) -> str:
    """Lesbare UTC-Zeit für Log-Ausgaben."""
    import datetime
    return datetime.datetime.fromtimestamp(ts, tz=datetime.UTC).strftime("%H:%M:%S UTC")
