"""RouteSessionStore -- SQLite-persistenter Session-Store fuer Multi-Stop-
Disambiguation.

Phase 92 (E3). Lera-Entscheidung 2026-05-20: persistent (analog
PendingConfirmationStore-Idee, aber mit SQLite), damit ein
Saleria-Restart waehrend laufender Disambiguation die Session
ueberlebt. TTL=1h ab letzter Aenderung.

Pro user_id maximal eine aktive Session. Wird im Multi-Stop-Handler
zwischen den Turns persistiert; ConversationListStore enthaelt nur die
jeweils aktuelle Kandidaten-Liste, der echte Route-State lebt hier.

Lebenszyklus:
- handler.execute()    -> store.set(user_id, RouteSession(...))
- handler.continue_with_pick() -> store.get(user_id) + Updates + set()
- Routing abgeschlossen -> store.clear(user_id)
- TTL abgelaufen       -> evict_expired() oder lazy beim get()

Schema-Hinweis: Wir serialisieren die ganze RouteSession als JSON-Blob,
nicht in separate Spalten. Begruendung: jede aenderung an
ResolvedStop/POI-Felder wuerde sonst eine Migration brauchen. Die
Session ist ein In-Flight-Objekt mit kurzer Lebensdauer -- JSON ist
hier billig genug.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from elder_berry.tools.google_maps_route_planner import POICandidate, POIRequest

logger = logging.getLogger(__name__)


_DEFAULT_DB_PATH = Path.home() / ".elder-berry" / "route_sessions.db"
_DEFAULT_TTL = timedelta(hours=1)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass
class ResolvedStop:
    """Ein Stop in einer RouteSession, evtl. noch nicht aufgeloest.

    Bei eindeutigem Treffer: ``address`` gesetzt, ``candidate_names`` /
    ``candidate_addresses`` leer.
    Bei Mehrdeutigkeit: ``address=None``, beide candidate-Listen
    befuellt (parallel indexed: ``candidate_names[i]`` gehoert zu
    ``candidate_addresses[i]``).

    ``intent_type`` und ``intent_value`` halten die urspruengliche
    Sonnet-Extraktion, damit der Handler beim Re-Resolving nach einer
    Pick-Antwort weiss, wonach er suchen soll. Bei POI-Stops sind
    ``poi_category`` + ``poi_place_id`` relevant.
    """

    label: str
    """Anzeigename, z.B. ``"Lisa"`` oder ``"Kaufland Gruenau"``."""

    intent_type: str
    """``"home"``, ``"contact"``, ``"address"``, ``"poi"``."""

    intent_value: str
    """Urspruenglicher Eingabe-Text (``"Lisa"``, ``"Hauptstr. 12"``)."""

    address: str | None = None
    """Aufgeloeste Adresse, ``None`` bei offener Disambig."""

    candidate_names: list[str] = field(default_factory=list)
    candidate_addresses: list[str] = field(default_factory=list)

    poi_category: str = ""
    poi_place_id: str = ""

    @property
    def is_resolved(self) -> bool:
        return self.address is not None and self.address != ""

    @property
    def is_ambiguous(self) -> bool:
        return self.address is None and len(self.candidate_names) > 0


@dataclass
class RouteSession:
    """Persistenter Zustand zwischen Turns.

    Wird komplett serialisiert -- der Handler liest die Session, fuellt
    Slots auf, schreibt sie zurueck. Routing-Phase passiert erst, wenn
    alle people-Stops aufgeloest sind (``next_open_disambiguation()``
    liefert None).
    """

    user_id: str
    raw_text: str
    origin: ResolvedStop
    destination: ResolvedStop
    waypoints: list[ResolvedStop] = field(default_factory=list)
    arrival_time_text: str = ""

    poi_request: POIRequest | None = None
    """Phase-2-Wunsch: ``"Kaufland"`` o.ae. Phase 1 Routing nutzt es
    NICHT (nur Personen-Stops); erst nach Phase-1-Routing wird die
    Places-Suche damit angestossen."""

    poi_candidates: list[POICandidate] = field(default_factory=list)
    """Gefuellt nach Phase-1-Routing; leer wenn poi_request None."""

    chosen_poi: POICandidate | None = None

    def next_open_disambiguation(self) -> tuple[str, ResolvedStop] | None:
        """Liefert den naechsten Slot mit offener Disambig oder None.

        Reihenfolge: origin -> destination -> waypoints (in Listen-
        Reihenfolge). POIs werden NICHT geliefert -- die laufen ueber
        ``poi_candidates`` + ``chosen_poi`` einen anderen Pfad.
        """
        if self.origin.is_ambiguous:
            return ("origin", self.origin)
        if self.destination.is_ambiguous:
            return ("destination", self.destination)
        for idx, wp in enumerate(self.waypoints):
            if wp.is_ambiguous:
                return (f"waypoint_{idx}", wp)
        return None

    def all_resolved(self) -> bool:
        """``True`` wenn jeder People-Stop eine Adresse hat."""
        if not self.origin.is_resolved:
            return False
        if not self.destination.is_resolved:
            return False
        return all(wp.is_resolved for wp in self.waypoints if wp.intent_type != "poi")

    def people_stops(self) -> list[ResolvedStop]:
        """Waypoints ohne POI-Slots -- die gehen ans Phase-1-Routing."""
        return [wp for wp in self.waypoints if wp.intent_type != "poi"]

    # ------------------------------------------------------------------
    # Serialisierung
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisierbares Dict."""
        return {
            "user_id": self.user_id,
            "raw_text": self.raw_text,
            "origin": asdict(self.origin),
            "destination": asdict(self.destination),
            "waypoints": [asdict(wp) for wp in self.waypoints],
            "arrival_time_text": self.arrival_time_text,
            "poi_request": asdict(self.poi_request) if self.poi_request else None,
            "poi_candidates": [asdict(p) for p in self.poi_candidates],
            "chosen_poi": asdict(self.chosen_poi) if self.chosen_poi else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RouteSession:
        """Reconstruct aus dem to_dict-Format."""
        return cls(
            user_id=str(data["user_id"]),
            raw_text=str(data.get("raw_text", "")),
            origin=_stop_from_dict(data["origin"]),
            destination=_stop_from_dict(data["destination"]),
            waypoints=[_stop_from_dict(d) for d in data.get("waypoints", [])],
            arrival_time_text=str(data.get("arrival_time_text", "")),
            poi_request=_poi_request_from_dict(data.get("poi_request")),
            poi_candidates=[
                cand
                for d in data.get("poi_candidates", [])
                if (cand := _poi_candidate_from_dict(d)) is not None
            ],
            chosen_poi=_poi_candidate_from_dict(data.get("chosen_poi"))
            if data.get("chosen_poi")
            else None,
        )


def _stop_from_dict(data: dict[str, Any]) -> ResolvedStop:
    return ResolvedStop(
        label=str(data.get("label", "")),
        intent_type=str(data.get("intent_type", "")),
        intent_value=str(data.get("intent_value", "")),
        address=data.get("address"),
        candidate_names=list(data.get("candidate_names", []) or []),
        candidate_addresses=list(data.get("candidate_addresses", []) or []),
        poi_category=str(data.get("poi_category", "")),
        poi_place_id=str(data.get("poi_place_id", "")),
    )


def _poi_request_from_dict(data: dict[str, Any] | None) -> POIRequest | None:
    if not data:
        return None
    return POIRequest(
        category=str(data.get("category", "")),
        name_hint=data.get("name_hint"),
        max_results=int(data.get("max_results", 10)),
        max_detour_seconds=int(data.get("max_detour_seconds", 600)),
    )


def _poi_candidate_from_dict(data: dict[str, Any] | None) -> POICandidate | None:
    if not data:
        return None
    return POICandidate(
        name=str(data.get("name", "")),
        address=str(data.get("address", "")),
        place_id=str(data.get("place_id", "")),
        detour_seconds=int(data.get("detour_seconds", 0)),
        rating=data.get("rating"),
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class RouteSessionStore:
    """SQLite-persistenter Store fuer Multi-Stop-Sessions, eine pro User.

    Thread-safe: ``check_same_thread=False`` + WAL. Eine Row pro
    ``user_id`` (PK), set() ueberschreibt eine alte Session.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        ttl: timedelta = _DEFAULT_TTL,
        clock: Any = None,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl muss positiv sein")
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl
        # clock kann None sein (Default) oder ein Callable -> datetime
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS route_sessions (
                user_id    TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_route_sessions_expires
                ON route_sessions(expires_at);
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(self, user_id: str, session: RouteSession) -> None:
        """Setzt die Session fuer einen User (Upsert).

        Schreibt zugleich ``updated_at`` + neuen ``expires_at`` und
        behaelt ``created_at`` der alten Session, falls vorhanden.
        """
        if not user_id:
            raise ValueError("user_id darf nicht leer sein")
        now = self._clock()
        expires = now + self._ttl
        payload = json.dumps(session.to_dict(), ensure_ascii=False)

        existing_created = self._conn.execute(
            "SELECT created_at FROM route_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        created_at = existing_created[0] if existing_created else now.isoformat()
        self._conn.execute(
            """
            INSERT INTO route_sessions
                (user_id, data, created_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                data=excluded.data,
                updated_at=excluded.updated_at,
                expires_at=excluded.expires_at
            """,
            (user_id, payload, created_at, now.isoformat(), expires.isoformat()),
        )
        self._conn.commit()
        logger.debug(
            "RouteSession gesetzt fuer %s (expires %s)",
            user_id,
            expires.isoformat(timespec="seconds"),
        )

    def get(self, user_id: str) -> RouteSession | None:
        """Liefert die aktive Session oder None (abgelaufen / nicht da).

        Side-Effekt: laeuft ``_evict_expired()`` lazy vor dem Read.
        """
        self._evict_expired()
        row = self._conn.execute(
            "SELECT data FROM route_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            data = json.loads(row[0])
            return RouteSession.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            # Korrupte Row -> wegwerfen, statt Crash.
            logger.warning(
                "RouteSession fuer %s nicht deserialisierbar (%s) -- wird verworfen",
                user_id,
                exc,
            )
            self.clear(user_id)
            return None

    def clear(self, user_id: str) -> None:
        """Loescht die Session fuer einen User."""
        self._conn.execute(
            "DELETE FROM route_sessions WHERE user_id = ?",
            (user_id,),
        )
        self._conn.commit()

    def evict_expired(self) -> int:
        """Explicit eviction -- liefert Anzahl entfernter Sessions."""
        return self._evict_expired()

    def close(self) -> None:
        """Verbindung schliessen."""
        try:
            self._conn.close()
        except sqlite3.Error as exc:
            logger.warning("RouteSessionStore.close: %s", exc)

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _evict_expired(self) -> int:
        now = self._clock().isoformat()
        cursor = self._conn.execute(
            "DELETE FROM route_sessions WHERE expires_at <= ?",
            (now,),
        )
        self._conn.commit()
        removed = cursor.rowcount or 0
        if removed:
            logger.debug("RouteSessionStore: %d abgelaufene Sessions entfernt", removed)
        return removed
