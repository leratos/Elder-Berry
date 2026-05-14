"""FactStore -- Key-Value-Fakten-Speicher (SQLite).

Speichert kurze Lookup-Fakten pro User: "WLAN Bueero" -> "xyz123".
Keine Volltextsuche, keine Freitext-Notizen -- der Notizen-Teil von
NoteStore (Phase 16) wandert in Etappe 2/3 zu Nextcloud Notes API.

Phase 91-A: extrahiert aus dem alten NoteStore. Beim ersten Start
migriert die Klasse einmalig alle Fact-Rows (key IS NOT NULL) aus der
alten ~/.elder-berry/notes.db in die neue ~/.elder-berry/facts.db
(idempotent via UNIQUE(user_id, key) + INSERT OR IGNORE). Freitext-
Notizen (key IS NULL) werden NICHT migriert -- Lera-Freigabe 2026-05-13,
Testphase ohne produktive Notizen.

Verwendung:
    store = FactStore()
    store.set_fact("@user:matrix.org", "wlan bueero", "xyz123")
    fact = store.get_fact("@user:matrix.org", "WLAN Bueero")  # normalisiert
    store.delete_fact("@user:matrix.org", "wlan bueero")
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".elder-berry" / "facts.db"
_LEGACY_NOTES_DB = Path.home() / ".elder-berry" / "notes.db"


@dataclass(frozen=True)
class Fact:
    """Ein Key-Value-Fakten-Eintrag."""

    id: int
    user_id: str
    key: str
    content: str
    created_at: datetime
    updated_at: datetime

    def format_short(self) -> str:
        """Einzeilige Darstellung fuer Listenansicht."""
        return f"#{self.id} 🔑 {self.key}: {self.content}"


class FactStore:
    """SQLite-basierter Fakten-Speicher (Key-Value, pro User).

    Thread-safe: check_same_thread=False.
    WAL-Modus fuer bessere Concurrent-Read-Performance.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        legacy_notes_db: Path | None = None,
    ) -> None:
        """
        Args:
            db_path: Pfad zur SQLite-DB. Default ~/.elder-berry/facts.db.
            legacy_notes_db: Pfad zur alten notes.db fuer Einmalig-Migration.
                Default ~/.elder-berry/notes.db. None deaktiviert Migration.
        """
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        db_existed_before = self._db_path.exists()
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

        if not db_existed_before and legacy_notes_db is not None:
            self._migrate_legacy_facts(legacy_notes_db)
        elif not db_existed_before and legacy_notes_db is None:
            # Default-Verhalten: alte notes.db pruefen, wenn nichts uebergeben
            self._migrate_legacy_facts(_LEGACY_NOTES_DB)

    def _create_tables(self) -> None:
        """Erstellt facts-Tabelle + Index."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                key         TEXT NOT NULL,
                content     TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                UNIQUE(user_id, key)
            );

            CREATE INDEX IF NOT EXISTS idx_facts_user
                ON facts(user_id);
        """)
        self._conn.commit()

    def _migrate_legacy_facts(self, legacy_db: Path) -> None:
        """Migriert einmalig Fakten aus alter notes.db in facts.db.

        Idempotent: INSERT OR IGNORE verhindert doppelte Eintraege bei
        wiederholtem Aufruf. Wird nur ausgefuehrt wenn die facts.db neu
        ist (siehe __init__).
        """
        if not legacy_db.exists():
            return

        try:
            src = sqlite3.connect(str(legacy_db))
            src.row_factory = sqlite3.Row
            rows = src.execute(
                "SELECT user_id, key, content, created_at, updated_at "
                "FROM notes WHERE key IS NOT NULL"
            ).fetchall()
            src.close()
        except sqlite3.Error as e:
            logger.warning(
                "FactStore-Migration: Konnte alte notes.db nicht lesen: %s", e
            )
            return

        if not rows:
            return

        try:
            cursor = self._conn.executemany(
                "INSERT OR IGNORE INTO facts "
                "(user_id, key, content, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        r["user_id"],
                        r["key"],
                        r["content"],
                        r["created_at"],
                        r["updated_at"],
                    )
                    for r in rows
                ],
            )
            self._conn.commit()
            logger.info(
                "FactStore-Migration: %d Fakten aus %s uebernommen",
                cursor.rowcount,
                legacy_db,
            )
        except sqlite3.Error as e:
            logger.error("FactStore-Migration fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def set_fact(self, user_id: str, key: str, value: str) -> Fact:
        """Key-Value-Fakt speichern (Upsert: existierender Key wird ueberschrieben).

        Args:
            user_id: Matrix-User-ID.
            key: Schluessel (wird normalisiert: lowercase, strip, Whitespace).
            value: Wert.

        Returns:
            Die erstellte/aktualisierte Fact.
        """
        norm_key = self._normalize_key(key)
        now = datetime.now(timezone.utc).isoformat()

        existing = self._conn.execute(
            "SELECT id, created_at FROM facts WHERE user_id = ? AND key = ?",
            (user_id, norm_key),
        ).fetchone()

        if existing:
            self._conn.execute(
                "UPDATE facts SET content = ?, updated_at = ? "
                "WHERE user_id = ? AND key = ?",
                (value, now, user_id, norm_key),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id, user_id, key, content, created_at, updated_at "
                "FROM facts WHERE user_id = ? AND key = ?",
                (user_id, norm_key),
            ).fetchone()
        else:
            cursor = self._conn.execute(
                "INSERT INTO facts (user_id, key, content, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, norm_key, value, now, now),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id, user_id, key, content, created_at, updated_at "
                "FROM facts WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()

        return self._row_to_fact(row)

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def get_fact(self, user_id: str, key: str) -> Fact | None:
        """Exakten Fakt per normalisiertem Schluessel abrufen.

        Args:
            user_id: Matrix-User-ID.
            key: Schluessel (wird normalisiert).

        Returns:
            Fact oder None wenn nicht gefunden.
        """
        norm_key = self._normalize_key(key)
        row = self._conn.execute(
            "SELECT id, user_id, key, content, created_at, updated_at "
            "FROM facts WHERE user_id = ? AND key = ?",
            (user_id, norm_key),
        ).fetchone()
        return self._row_to_fact(row) if row else None

    def list_facts(self, user_id: str, limit: int = 20) -> list[Fact]:
        """Alle Fakten eines Users (neueste zuerst).

        Args:
            user_id: Matrix-User-ID.
            limit: Maximale Ergebnisse.

        Returns:
            Liste von Facts, nach updated_at DESC sortiert.
        """
        rows = self._conn.execute(
            "SELECT id, user_id, key, content, created_at, updated_at "
            "FROM facts WHERE user_id = ? "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    # ------------------------------------------------------------------
    # Loeschen
    # ------------------------------------------------------------------

    def delete_fact(self, user_id: str, key: str) -> bool:
        """Fakt per normalisiertem Schluessel loeschen.

        Returns:
            True wenn geloescht, False wenn nicht gefunden.
        """
        norm_key = self._normalize_key(key)
        cursor = self._conn.execute(
            "DELETE FROM facts WHERE user_id = ? AND key = ?",
            (user_id, norm_key),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Verbindung sauber schliessen."""
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    @staticmethod
    def _normalize_key(key: str) -> str:
        """Normalisiert Keys: lowercase, strip, mehrfache Leerzeichen -> einfach."""
        return re.sub(r"\s+", " ", key.strip().lower())

    @staticmethod
    def _row_to_fact(row: tuple[Any, ...]) -> Fact:
        """Konvertiert einen DB-Row-Tuple in ein Fact-DTO."""
        fact_id, user_id, key, content, created_at, updated_at = row
        return Fact(
            id=fact_id,
            user_id=user_id,
            key=key,
            content=content,
            created_at=datetime.fromisoformat(created_at),
            updated_at=datetime.fromisoformat(updated_at),
        )
