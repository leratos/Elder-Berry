"""NearbyDraftStore -- persistenter Pending-Draft fuer die Umkreissuche.

Phase 97 (E4). Haelt zwischen zwei Turns den ``NearbyQueryDraft``, solange
noch ``location_text``/``travel_mode`` per Rueckfrage fehlen (R2-C5/B1).

Muster wie ``RouteSessionStore`` (SQLite, eine Row pro ``user_id``, TTL).
Begruendung der Persistenz: die Rueckfrage-Antwort ("zu Fuss" / "Leipzig
Hbf") kommt als FRISCHE Nachricht; ohne Speicher gingen subject/
search_query/exclude_types verloren.

WICHTIG (B1, Phase-92-Lektion): Der Key ist immer die ``default_user_id``
des Handlers, NICHT ``msg.sender``. Turn 1 schreibt und der Folge-Turn liest
unter demselben Key -- Saleria ist single-user. ``msg.sender`` durchzureichen
wuerde mit der Turn-1-Speicherung kollidieren (vgl.
``MultiStopRouteCommandHandler.continue_with_pick`` /
``message_handlers._dispatch_route_pick``).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from elder_berry.tools.nearby_place_search import NearbyQueryDraft

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".elder-berry" / "nearby_drafts.db"
_DEFAULT_TTL = timedelta(hours=1)


def _draft_to_dict(draft: NearbyQueryDraft) -> dict[str, Any]:
    return {
        "subject": draft.subject,
        "search_query": draft.search_query,
        "included_type": draft.included_type,
        "exclude_types": list(draft.exclude_types),
        "location_text": draft.location_text,
        "travel_mode": draft.travel_mode,
        "open_now": draft.open_now,
        "fallback_query": draft.fallback_query,
    }


def _draft_from_dict(data: dict[str, Any]) -> NearbyQueryDraft:
    exclude_raw = data.get("exclude_types") or []
    return NearbyQueryDraft(
        subject=str(data.get("subject", "")),
        search_query=str(data.get("search_query", "")),
        included_type=data.get("included_type"),
        exclude_types=tuple(str(t) for t in exclude_raw),
        location_text=data.get("location_text"),
        travel_mode=data.get("travel_mode"),
        open_now=bool(data.get("open_now", True)),
        fallback_query=data.get("fallback_query"),
    )


class NearbyDraftStore:
    """SQLite-persistenter Store fuer Nearby-Drafts, eine Row pro User.

    Thread-safe: ``check_same_thread=False`` + WAL. ``set()`` ueberschreibt
    den alten Draft desselben Users (Upsert).
    """

    def __init__(
        self,
        db_path: Path | None = None,
        ttl: timedelta = _DEFAULT_TTL,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl muss positiv sein")
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS nearby_drafts (
                user_id    TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_nearby_drafts_expires
                ON nearby_drafts(expires_at);
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(self, user_id: str, draft: NearbyQueryDraft) -> None:
        """Setzt den Draft fuer einen User (Upsert) + frischer TTL."""
        if not user_id:
            raise ValueError("user_id darf nicht leer sein")
        now = self._clock()
        expires = now + self._ttl
        payload = json.dumps(_draft_to_dict(draft), ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO nearby_drafts (user_id, data, updated_at, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                data=excluded.data,
                updated_at=excluded.updated_at,
                expires_at=excluded.expires_at
            """,
            (user_id, payload, now.isoformat(), expires.isoformat()),
        )
        self._conn.commit()

    def get(self, user_id: str) -> NearbyQueryDraft | None:
        """Liefert den aktiven Draft oder None (abgelaufen / nicht da)."""
        self._evict_expired()
        row = self._conn.execute(
            "SELECT data FROM nearby_drafts WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return _draft_from_dict(json.loads(row[0]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "NearbyDraft fuer %s nicht deserialisierbar (%s) -- verworfen",
                user_id,
                exc,
            )
            self.clear(user_id)
            return None

    def clear(self, user_id: str) -> None:
        """Loescht den Draft fuer einen User."""
        self._conn.execute(
            "DELETE FROM nearby_drafts WHERE user_id = ?",
            (user_id,),
        )
        self._conn.commit()

    def evict_expired(self) -> int:
        """Explicit eviction -- liefert Anzahl entfernter Drafts."""
        return self._evict_expired()

    def close(self) -> None:
        """Verbindung schliessen."""
        try:
            self._conn.close()
        except sqlite3.Error as exc:
            logger.warning("NearbyDraftStore.close: %s", exc)

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _evict_expired(self) -> int:
        now = self._clock().isoformat()
        cursor = self._conn.execute(
            "DELETE FROM nearby_drafts WHERE expires_at <= ?",
            (now,),
        )
        self._conn.commit()
        return cursor.rowcount or 0
