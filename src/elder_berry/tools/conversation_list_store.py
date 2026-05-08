"""ConversationListStore -- In-Memory-Speicher fuer LLM-Listen-Disambiguation.

Phase 80: Saleria registriert strukturierte Mehrfachergebnisse (Suche,
Mail-Inbox, Notiz-Treffer) in dieser Tabelle. Das LLM bekommt nur einen
Listen-Index ('Treffer 2'), das System loest auf den realen Wert auf --
verhindert Halluzinationen wie 'web_summary auf raterischer URL'.

Eigenschaften (Konzept §2 + §4):
- Pro (user_id, list_type) maximal eine aktive Liste. register()
  ueberschreibt eine alte Liste desselben Tupels.
- TTL = 1h ab letztem Zugriff (Konstruktor-Parameter, default 1h).
  Jeder get_active/get_item updated last_accessed -> verlaengert TTL.
- Lazy Eviction: _evict_expired() laeuft vor jedem read.
- Nicht-persistent. Saleria-Restart verliert alle Listen (akzeptiert,
  Konzept §6 R4).
- Thread-safe via threading.Lock; Saleria-Bridge ruft sync.

Pattern wie NoteStore/ProposalStore (Klasse pro Datei, Dataclass-DTO,
Logger pro Modul) -- aber KEIN SQLite.
"""

from __future__ import annotations

import logging
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TTL = timedelta(hours=1)
_LIST_REF_HASH_BYTES = 2  # 4 hex-chars


@dataclass(frozen=True)
class ListEntry:
    """Eine aktive Listen-Registrierung (Konzept §3.2).

    items ist heterogen pro list_type:
    - search       -> {"title", "url", "snippet"}
    - mail_inbox   -> {"from", "subject", "msg_id", "date"}
    - note_search  -> {"id", "key", "content_excerpt"}
    """

    list_ref: str
    list_type: str
    user_id: str
    items: tuple[Any, ...]
    """Tuple statt list, damit ListEntry frozen/hashable bleibt."""
    created_at: datetime
    last_accessed: datetime
    expires_at: datetime


class ConversationListStore:
    """In-Memory-Listen-Tabelle, ein Eintrag pro (user_id, list_type).

    Lebenszyklus:
    - register() legt einen Eintrag an, ueberschreibt Vorgaenger desselben
      Tupels (Info-Log).
    - get_active() / get_item() liefern den Eintrag und verlaengern TTL.
    - pop_active() entfernt + retourniert.
    - _evict_expired() raeumt vor jedem read auf (lazy GC).

    Thread-Safety: einfacher threading.Lock um den Storage-Dict.
    Saleria-Bridge ist Single-Reader pro User-Anfrage, also reicht das.
    """

    def __init__(
        self,
        ttl: timedelta = _DEFAULT_TTL,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl muss positiv sein")
        self._ttl = ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._store: dict[tuple[str, str], ListEntry] = {}

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def register(
        self,
        user_id: str,
        list_type: str,
        items: list[Any] | tuple[Any, ...],
    ) -> str:
        """Neue aktive Liste anlegen; vorherige desselben Tupels wird
        ueberschrieben (mit Info-Log).

        Args:
            user_id: Eindeutige User-ID (z.B. Matrix-MXID).
            list_type: Listen-Typ ("search", "mail_inbox", "note_search", ...).
            items: Reihenfolge-stabile Sequenz; wird intern als Tuple gespeichert.

        Returns:
            list_ref im Format ``{list_type}_{YYYYmmddTHHMMSS}_{4-hex}``.
        """
        if not user_id:
            raise ValueError("user_id darf nicht leer sein")
        if not list_type:
            raise ValueError("list_type darf nicht leer sein")

        now = self._clock()
        list_ref = self._make_list_ref(list_type, now)
        entry = ListEntry(
            list_ref=list_ref,
            list_type=list_type,
            user_id=user_id,
            items=tuple(items),
            created_at=now,
            last_accessed=now,
            expires_at=now + self._ttl,
        )
        key = (user_id, list_type)
        with self._lock:
            previous = self._store.get(key)
            self._store[key] = entry
        if previous is not None:
            logger.info(
                "Liste %s ueberschrieben durch %s (user=%s, type=%s)",
                previous.list_ref,
                list_ref,
                user_id,
                list_type,
            )
        else:
            logger.debug(
                "Liste %s registriert (user=%s, type=%s, n=%d)",
                list_ref,
                user_id,
                list_type,
                len(entry.items),
            )
        return list_ref

    # ------------------------------------------------------------------
    # Lesen (TTL-aware)
    # ------------------------------------------------------------------

    def get_active(self, user_id: str, list_type: str) -> tuple[str, list[Any]] | None:
        """Liefert (list_ref, items) der aktiven Liste oder None.

        Updated last_accessed/expires_at als Side-Effect.
        """
        with self._lock:
            self._evict_expired_locked()
            entry = self._touch_locked(user_id, list_type)
            if entry is None:
                return None
            return entry.list_ref, list(entry.items)

    def get_item(
        self,
        user_id: str,
        list_ref: str,
        index: int,
    ) -> Any | None:
        """Liefert das Item an 1-basierter Position oder None.

        None wenn:
        - keine aktive Liste,
        - list_ref passt nicht zur aktuellen aktiven Liste (z.B. wurde
          ueberschrieben oder ist abgelaufen),
        - index ausserhalb [1..len(items)].

        Ein Match updated last_accessed/expires_at.
        """
        if index < 1:
            return None
        with self._lock:
            self._evict_expired_locked()
            entry = self._find_by_ref_locked(user_id, list_ref)
            if entry is None:
                return None
            if index > len(entry.items):
                return None
            self._touch_locked(entry.user_id, entry.list_type)
            return entry.items[index - 1]

    def pop_active(self, user_id: str, list_type: str) -> tuple[str, list[Any]] | None:
        """Entfernt die aktive Liste und retourniert sie. Kein Touch noetig."""
        with self._lock:
            self._evict_expired_locked()
            entry = self._store.pop((user_id, list_type), None)
            if entry is None:
                return None
            return entry.list_ref, list(entry.items)

    # ------------------------------------------------------------------
    # Intern (alle innerhalb _lock auszufuehren)
    # ------------------------------------------------------------------

    def _evict_expired_locked(self) -> None:
        """Entfernt alle abgelaufenen Eintraege. MUSS unter Lock laufen."""
        now = self._clock()
        expired_keys = [
            key for key, entry in self._store.items() if entry.expires_at <= now
        ]
        for key in expired_keys:
            entry = self._store.pop(key)
            logger.debug(
                "Liste %s abgelaufen (user=%s, type=%s)",
                entry.list_ref,
                entry.user_id,
                entry.list_type,
            )

    def _touch_locked(self, user_id: str, list_type: str) -> ListEntry | None:
        """Verlaengert TTL und retourniert den (ggf. aktualisierten) Eintrag."""
        key = (user_id, list_type)
        entry = self._store.get(key)
        if entry is None:
            return None
        now = self._clock()
        refreshed = replace(entry, last_accessed=now, expires_at=now + self._ttl)
        self._store[key] = refreshed
        return refreshed

    def _find_by_ref_locked(self, user_id: str, list_ref: str) -> ListEntry | None:
        """Sucht den Eintrag eines Users mit passender list_ref.

        Da pro (user_id, list_type) maximal ein Eintrag aktiv ist und
        list_ref den list_type als Praefix enthaelt, reicht ein direkter
        Lookup -- aber wir scannen defensiv ueber alle list_types des
        Users, falls list_ref-Format mal driftet.
        """
        for (uid, _ltype), entry in self._store.items():
            if uid == user_id and entry.list_ref == list_ref:
                return entry
        return None

    # ------------------------------------------------------------------
    # list_ref-Format
    # ------------------------------------------------------------------

    @staticmethod
    def _make_list_ref(list_type: str, now: datetime) -> str:
        """``{list_type}_{YYYYmmddTHHMMSS}_{4-hex}`` (Konzept §3.3).

        Hash via secrets.token_hex -- collision-resistant genug fuer den
        Use-Case (eine Liste pro Tupel pro Sekunde reicht aus, der Hash
        ist nur Tiebreaker / Disambiguation-Hint fuer den LLM).
        """
        ts = now.strftime("%Y%m%dT%H%M%S")
        suffix = secrets.token_hex(_LIST_REF_HASH_BYTES)
        return f"{list_type}_{ts}_{suffix}"
