"""ProposalStore – Persistenter Speicher fuer Plugin-Vorschlaege (Phase 78).

Saleria erkennt bei LLM-Fallbacks Capability-Luecken und legt Vorschlaege
in dieser SQLite-DB ab. Lera reviewt + implementiert manuell -- es gibt
explizit keinen Auto-Load (siehe Konzept §6 R1).

Pattern wie ContactStore (FTS5) / FactStore (Phase 91-A, ohne FTS5):
- DB-Anlage im Konstruktor via `_create_tables()`.
- WAL-Modus, `check_same_thread=False` fuer Multi-Threading.
- FTS5 fuer Volltext-Dedupe-Suche.

Schema: siehe `docs/concepts/phase-78-plugin-self-suggestion.md` §3.2.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".elder-berry" / "proposals.db"

ProposalStatus = Literal["in_pruefung", "in_bearbeitung", "abgelehnt", "fertiggestellt"]
ChangedBy = Literal["saleria", "lera"]

_VALID_STATUSES: tuple[ProposalStatus, ...] = (
    "in_pruefung",
    "in_bearbeitung",
    "abgelehnt",
    "fertiggestellt",
)
_VALID_CHANGED_BY: tuple[ChangedBy, ...] = ("saleria", "lera")
_ACTIVE_STATUSES: tuple[ProposalStatus, ...] = ("in_pruefung", "in_bearbeitung")


@dataclass(frozen=True)
class Proposal:
    """Plugin-Vorschlag, wie er in `plugin_proposals` gespeichert ist."""

    id: str
    title: str
    status: ProposalStatus
    description_md: str
    suggested_category: str | None
    suggested_priority: int | None
    created_at: datetime
    updated_at: datetime
    trigger_count: int
    last_triggered_at: datetime
    notified_at: datetime | None
    last_confidence: float | None
    rejected_reason: str | None
    implemented_in: str | None
    related_proposals: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProposalTrigger:
    """Eine einzelne Trigger-Auswertung fuer ein Proposal."""

    proposal_id: str
    triggered_at: datetime
    sample_message: str
    sender_hash: str | None
    confidence: float | None


@dataclass(frozen=True)
class ProposalHistoryEntry:
    """Audit-Eintrag fuer einen Status-Wechsel."""

    proposal_id: str
    timestamp: datetime
    old_status: ProposalStatus | None
    new_status: ProposalStatus
    changed_by: ChangedBy
    note: str | None


class ProposalStoreError(Exception):
    """Basis-Exception fuer ProposalStore-Fehler."""


class ProposalNotFoundError(ProposalStoreError):
    """Proposal mit gegebener ID existiert nicht."""


class ProposalAlreadyExistsError(ProposalStoreError):
    """Proposal mit dieser ID ist bereits angelegt."""


class InvalidStatusError(ProposalStoreError):
    """Status-Wert ausserhalb der erlaubten Menge."""


class ProposalStore:
    """SQLite-basierter Plugin-Vorschlags-Speicher mit FTS5.

    Status-Wechsel werden in `plugin_proposal_history` auditiert.
    Threshold-Pruefung erfolgt nicht hier, sondern im
    `ProposalIntentAggregator` -- der Store liefert nur die Bausteine
    (`count_triggers_since`, `mark_notified`).
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        """Erstellt Tabellen, Indices, FTS5-Trigger (idempotent)."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS plugin_proposals (
                id                   TEXT PRIMARY KEY,
                title                TEXT NOT NULL,
                status               TEXT NOT NULL DEFAULT 'in_pruefung'
                    CHECK (status IN ('in_pruefung', 'in_bearbeitung',
                                      'abgelehnt', 'fertiggestellt')),
                description_md       TEXT NOT NULL,
                suggested_category   TEXT,
                suggested_priority   INTEGER,
                created_at           TEXT NOT NULL,
                updated_at           TEXT NOT NULL,
                trigger_count        INTEGER NOT NULL DEFAULT 1,
                last_triggered_at    TEXT NOT NULL,
                notified_at          TEXT,
                last_confidence      REAL,
                rejected_reason      TEXT,
                implemented_in       TEXT,
                related_proposals    TEXT
            );

            CREATE TABLE IF NOT EXISTS plugin_proposal_triggers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id     TEXT NOT NULL
                    REFERENCES plugin_proposals(id) ON DELETE CASCADE,
                triggered_at    TEXT NOT NULL,
                sample_message  TEXT NOT NULL,
                sender_hash     TEXT,
                confidence      REAL
            );

            CREATE INDEX IF NOT EXISTS idx_triggers_proposal_time
                ON plugin_proposal_triggers(proposal_id, triggered_at);

            CREATE TABLE IF NOT EXISTS plugin_proposal_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id     TEXT NOT NULL
                    REFERENCES plugin_proposals(id) ON DELETE CASCADE,
                timestamp       TEXT NOT NULL,
                old_status      TEXT,
                new_status      TEXT NOT NULL,
                changed_by      TEXT NOT NULL
                    CHECK (changed_by IN ('saleria', 'lera')),
                note            TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_history_proposal_time
                ON plugin_proposal_history(proposal_id, timestamp);

            CREATE VIRTUAL TABLE IF NOT EXISTS plugin_proposals_fts
            USING fts5(
                title,
                description_md,
                content='plugin_proposals',
                content_rowid='rowid'
            );

            CREATE TRIGGER IF NOT EXISTS plugin_proposals_ai
            AFTER INSERT ON plugin_proposals BEGIN
                INSERT INTO plugin_proposals_fts(
                    rowid, title, description_md
                ) VALUES (new.rowid, new.title, new.description_md);
            END;

            CREATE TRIGGER IF NOT EXISTS plugin_proposals_au
            AFTER UPDATE ON plugin_proposals BEGIN
                INSERT INTO plugin_proposals_fts(
                    plugin_proposals_fts, rowid, title, description_md
                ) VALUES('delete', old.rowid, old.title, old.description_md);
                INSERT INTO plugin_proposals_fts(
                    rowid, title, description_md
                ) VALUES (new.rowid, new.title, new.description_md);
            END;

            CREATE TRIGGER IF NOT EXISTS plugin_proposals_ad
            AFTER DELETE ON plugin_proposals BEGIN
                INSERT INTO plugin_proposals_fts(
                    plugin_proposals_fts, rowid, title, description_md
                ) VALUES('delete', old.rowid, old.title, old.description_md);
            END;
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def create_pending(
        self,
        *,
        intent: str,
        title: str,
        description_md: str,
        sample_message: str,
        sender_hash: str | None,
        confidence: float | None,
        suggested_category: str | None = None,
        suggested_priority: int | None = None,
    ) -> Proposal:
        """Neuer Proposal + erster Trigger transaktional anlegen.

        Nach Rueckkehr existiert der Proposal mit `trigger_count = 1`,
        Status `in_pruefung` und genau einem Trigger-Row.

        Raises:
            ProposalAlreadyExistsError: Wenn `intent` bereits existiert.
        """
        now = self._now_iso()
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO plugin_proposals (
                        id, title, status, description_md,
                        suggested_category, suggested_priority,
                        created_at, updated_at,
                        trigger_count, last_triggered_at,
                        notified_at, last_confidence
                    ) VALUES (?, ?, 'in_pruefung', ?, ?, ?, ?, ?, 1, ?, NULL, ?)
                    """,
                    (
                        intent,
                        title,
                        description_md,
                        suggested_category,
                        suggested_priority,
                        now,
                        now,
                        now,
                        confidence,
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO plugin_proposal_triggers (
                        proposal_id, triggered_at, sample_message,
                        sender_hash, confidence
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (intent, now, sample_message, sender_hash, confidence),
                )
                self._conn.execute(
                    """
                    INSERT INTO plugin_proposal_history (
                        proposal_id, timestamp, old_status, new_status,
                        changed_by, note
                    ) VALUES (?, ?, NULL, 'in_pruefung', 'saleria', ?)
                    """,
                    (intent, now, "Proposal angelegt nach LLM-Fallback"),
                )
        except sqlite3.IntegrityError as exc:
            raise ProposalAlreadyExistsError(
                f"Proposal '{intent}' existiert bereits"
            ) from exc

        proposal = self.get_by_id(intent)
        assert proposal is not None  # gerade angelegt
        return proposal

    def add_trigger(
        self,
        proposal_id: str,
        sample_message: str,
        sender_hash: str | None,
        confidence: float | None,
    ) -> None:
        """Trigger-Eintrag hinzufuegen + Counter/Timestamp/Confidence updaten.

        Raises:
            ProposalNotFoundError: Wenn `proposal_id` nicht existiert.
        """
        now = self._now_iso()
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE plugin_proposals
                   SET trigger_count = trigger_count + 1,
                       last_triggered_at = ?,
                       last_confidence = COALESCE(?, last_confidence),
                       updated_at = ?
                 WHERE id = ?
                """,
                (now, confidence, now, proposal_id),
            )
            if cursor.rowcount == 0:
                raise ProposalNotFoundError(f"Proposal '{proposal_id}' existiert nicht")
            self._conn.execute(
                """
                INSERT INTO plugin_proposal_triggers (
                    proposal_id, triggered_at, sample_message,
                    sender_hash, confidence
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (proposal_id, now, sample_message, sender_hash, confidence),
            )

    def mark_notified(self, proposal_id: str) -> None:
        """Setzt `notified_at` auf jetzt. No-Op wenn bereits gesetzt.

        Raises:
            ProposalNotFoundError: Wenn `proposal_id` nicht existiert.
        """
        now = self._now_iso()
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE plugin_proposals
                   SET notified_at = ?, updated_at = ?
                 WHERE id = ? AND notified_at IS NULL
                """,
                (now, now, proposal_id),
            )
        if cursor.rowcount == 0:
            # Pruefen ob Proposal existiert oder bereits notified
            if self.get_by_id(proposal_id) is None:
                raise ProposalNotFoundError(f"Proposal '{proposal_id}' existiert nicht")
            # Bereits notified -- still durchwinken
            logger.debug("mark_notified: Proposal %s war bereits notified", proposal_id)

    def update_status(
        self,
        proposal_id: str,
        new_status: ProposalStatus,
        changed_by: ChangedBy = "lera",
        note: str | None = None,
        rejected_reason: str | None = None,
    ) -> None:
        """Status wechseln + History-Eintrag transaktional schreiben.

        Raises:
            ProposalNotFoundError: Wenn `proposal_id` nicht existiert.
            InvalidStatusError: Wenn `new_status` oder `changed_by`
                nicht in der erlaubten Menge ist.
        """
        if new_status not in _VALID_STATUSES:
            raise InvalidStatusError(f"Ungueltiger Status: {new_status!r}")
        if changed_by not in _VALID_CHANGED_BY:
            raise InvalidStatusError(f"Ungueltiger changed_by: {changed_by!r}")
        now = self._now_iso()
        with self._conn:
            row = self._conn.execute(
                "SELECT status FROM plugin_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise ProposalNotFoundError(f"Proposal '{proposal_id}' existiert nicht")
            old_status = row[0]
            if old_status == new_status:
                return
            self._conn.execute(
                """
                UPDATE plugin_proposals
                   SET status = ?,
                       rejected_reason = COALESCE(?, rejected_reason),
                       updated_at = ?
                 WHERE id = ?
                """,
                (new_status, rejected_reason, now, proposal_id),
            )
            self._conn.execute(
                """
                INSERT INTO plugin_proposal_history (
                    proposal_id, timestamp, old_status, new_status,
                    changed_by, note
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (proposal_id, now, old_status, new_status, changed_by, note),
            )

    def set_implementation(self, proposal_id: str, path: str) -> None:
        """Setzt `implemented_in`-Pfad (typischerweise nach `fertiggestellt`).

        Raises:
            ProposalNotFoundError: Wenn `proposal_id` nicht existiert.
        """
        now = self._now_iso()
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE plugin_proposals
                   SET implemented_in = ?, updated_at = ?
                 WHERE id = ?
                """,
                (path, now, proposal_id),
            )
        if cursor.rowcount == 0:
            raise ProposalNotFoundError(f"Proposal '{proposal_id}' existiert nicht")

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def get_by_id(self, proposal_id: str) -> Proposal | None:
        row = self._conn.execute(
            "SELECT " + _PROPOSAL_COLS + " FROM plugin_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        return self._row_to_proposal(row) if row else None

    def list_active(self, limit: int = 15) -> list[Proposal]:
        """Aktive Proposals (in_pruefung + in_bearbeitung).

        Sortiert nach `last_triggered_at DESC` -- liefert die fuer den
        Dedupe-Prompt relevantesten zuerst (siehe Konzept §3.6).
        """
        placeholders = ", ".join("?" for _ in _ACTIVE_STATUSES)
        rows = self._conn.execute(
            f"SELECT {_PROPOSAL_COLS} FROM plugin_proposals "
            f"WHERE status IN ({placeholders}) "
            "ORDER BY last_triggered_at DESC LIMIT ?",
            (*_ACTIVE_STATUSES, limit),
        ).fetchall()
        return [self._row_to_proposal(r) for r in rows]

    def list_by_status(
        self, status: ProposalStatus | None = None, limit: int = 100
    ) -> list[Proposal]:
        """Liste aller Proposals, optional gefiltert nach Status."""
        if status is not None and status not in _VALID_STATUSES:
            raise InvalidStatusError(f"Ungueltiger Status: {status!r}")
        if status is None:
            rows = self._conn.execute(
                f"SELECT {_PROPOSAL_COLS} FROM plugin_proposals "
                "ORDER BY last_triggered_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {_PROPOSAL_COLS} FROM plugin_proposals "
                "WHERE status = ? ORDER BY last_triggered_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return [self._row_to_proposal(r) for r in rows]

    def count_triggers_since(self, proposal_id: str, days: int) -> int:
        """Anzahl Trigger fuer Proposal innerhalb der letzten `days` Tage.

        Wird vom `ProposalIntentAggregator` fuer den Threshold-Check
        genutzt (3x in 7 Tagen).
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        row = self._conn.execute(
            """
            SELECT COUNT(*) FROM plugin_proposal_triggers
             WHERE proposal_id = ? AND triggered_at >= ?
            """,
            (proposal_id, cutoff),
        ).fetchone()
        return int(row[0]) if row else 0

    def get_triggers(self, proposal_id: str, limit: int = 20) -> list[ProposalTrigger]:
        rows = self._conn.execute(
            """
            SELECT proposal_id, triggered_at, sample_message,
                   sender_hash, confidence
              FROM plugin_proposal_triggers
             WHERE proposal_id = ?
             ORDER BY triggered_at DESC LIMIT ?
            """,
            (proposal_id, limit),
        ).fetchall()
        return [
            ProposalTrigger(
                proposal_id=r[0],
                triggered_at=datetime.fromisoformat(r[1]),
                sample_message=r[2],
                sender_hash=r[3],
                confidence=r[4],
            )
            for r in rows
        ]

    def get_history(self, proposal_id: str) -> list[ProposalHistoryEntry]:
        rows = self._conn.execute(
            """
            SELECT proposal_id, timestamp, old_status, new_status,
                   changed_by, note
              FROM plugin_proposal_history
             WHERE proposal_id = ?
             ORDER BY timestamp ASC
            """,
            (proposal_id,),
        ).fetchall()
        return [
            ProposalHistoryEntry(
                proposal_id=r[0],
                timestamp=datetime.fromisoformat(r[1]),
                old_status=r[2],
                new_status=r[3],
                changed_by=r[4],
                note=r[5],
            )
            for r in rows
        ]

    def search_similar(self, query: str, limit: int = 10) -> list[Proposal]:
        """FTS5-Volltextsuche ueber title + description_md.

        Wird vom Aggregator genutzt, um Saleria vor dem Erstellen eines
        Vorschlags eine Hint-Liste aehnlicher existierender Proposals zu
        liefern (Konzept §3.6).
        """
        sanitized = self._sanitize_fts_query(query)
        if not sanitized:
            return []
        try:
            rows = self._conn.execute(
                f"SELECT {_PROPOSAL_COLS_PREFIXED} "
                "FROM plugin_proposals p "
                "JOIN plugin_proposals_fts fts ON fts.rowid = p.rowid "
                "WHERE plugin_proposals_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (sanitized, limit),
            ).fetchall()
            return [self._row_to_proposal(r) for r in rows]
        except sqlite3.OperationalError as exc:
            logger.warning("FTS-Suche fehlgeschlagen (Query: %r): %s", query, exc)
            return []

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001 -- close-Fehler sind irrelevant
            pass

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Bereinigt Query fuer FTS5 MATCH (analog ContactStore)."""
        words = re.findall(r"[\w]+", query, re.UNICODE)
        fts_operators = {"AND", "OR", "NOT", "NEAR"}
        words = [w for w in words if w.upper() not in fts_operators]
        return " ".join(words)

    @staticmethod
    def _row_to_proposal(row: tuple[Any, ...]) -> Proposal:
        (
            id_,
            title,
            status,
            description_md,
            suggested_category,
            suggested_priority,
            created_at,
            updated_at,
            trigger_count,
            last_triggered_at,
            notified_at,
            last_confidence,
            rejected_reason,
            implemented_in,
            related_proposals_json,
        ) = row
        related: list[str] = []
        if related_proposals_json:
            try:
                parsed = json.loads(related_proposals_json)
                if isinstance(parsed, list):
                    related = [str(x) for x in parsed]
            except json.JSONDecodeError:
                logger.warning(
                    "related_proposals JSON kaputt fuer %s: %r",
                    id_,
                    related_proposals_json,
                )
        return Proposal(
            id=id_,
            title=title,
            status=status,
            description_md=description_md,
            suggested_category=suggested_category,
            suggested_priority=suggested_priority,
            created_at=datetime.fromisoformat(created_at),
            updated_at=datetime.fromisoformat(updated_at),
            trigger_count=trigger_count,
            last_triggered_at=datetime.fromisoformat(last_triggered_at),
            notified_at=(datetime.fromisoformat(notified_at) if notified_at else None),
            last_confidence=last_confidence,
            rejected_reason=rejected_reason,
            implemented_in=implemented_in,
            related_proposals=related,
        )


_PROPOSAL_COLS = (
    "id, title, status, description_md, "
    "suggested_category, suggested_priority, "
    "created_at, updated_at, "
    "trigger_count, last_triggered_at, "
    "notified_at, last_confidence, "
    "rejected_reason, implemented_in, "
    "related_proposals"
)

_PROPOSAL_COLS_PREFIXED = (
    "p.id, p.title, p.status, p.description_md, "
    "p.suggested_category, p.suggested_priority, "
    "p.created_at, p.updated_at, "
    "p.trigger_count, p.last_triggered_at, "
    "p.notified_at, p.last_confidence, "
    "p.rejected_reason, p.implemented_in, "
    "p.related_proposals"
)
