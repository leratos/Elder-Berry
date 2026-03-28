"""NoteStore – Persistenter Fakten- und Notizspeicher (SQLite + FTS5).

Zwei Modi:
- Key-Value-Fakten: "WLAN Büro" → "xyz123" (exakter Abruf per Schlüssel)
- Freitext-Notizen: "Vermieter heißt Müller" (Volltextsuche via FTS5)

Verwendung:
    store = NoteStore()
    store.set_fact("@user:matrix.org", "wlan büro", "xyz123")
    note = store.get_fact("@user:matrix.org", "WLAN Büro")  # normalisiert
    store.add_note("@user:matrix.org", "Vermieter Müller, Kaution 1200€")
    results = store.search("@user:matrix.org", "Vermieter")
"""
from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".elder-berry" / "notes.db"


@dataclass(frozen=True)
class Note:
    """Eine einzelne Notiz oder ein Fakten-Eintrag."""

    id: int
    user_id: str
    key: str | None
    """None = Freitext-Notiz, gesetzt = Key-Value-Fakt."""
    content: str
    tags: list[str]
    """Geparst aus komma-separiertem DB-Feld."""
    created_at: datetime
    updated_at: datetime

    @property
    def is_fact(self) -> bool:
        """True wenn Key-Value-Fakt (hat einen Schlüssel)."""
        return self.key is not None

    def format_short(self) -> str:
        """Einzeilige Darstellung für Listenansicht."""
        if self.key:
            return f"#{self.id} 🔑 {self.key}: {self.content}"
        preview = self.content[:80] + ("..." if len(self.content) > 80 else "")
        return f"#{self.id} 📝 {preview}"


class NoteStore:
    """SQLite-basierter Notizen- und Wissensspeicher mit FTS5-Volltextsuche.

    Thread-safe: check_same_thread=False.
    WAL-Modus für bessere Concurrent-Read-Performance.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        """Erstellt Tabellen, Indices und FTS5-Trigger."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                key         TEXT,
                content     TEXT NOT NULL,
                tags        TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_notes_user_key
                ON notes(user_id, key) WHERE key IS NOT NULL;

            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                content,
                key,
                tags,
                content=notes,
                content_rowid=id
            );

            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, content, key, tags)
                VALUES (new.id, new.content, new.key, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, content, key, tags)
                VALUES('delete', old.id, old.content, old.key, old.tags);
                INSERT INTO notes_fts(rowid, content, key, tags)
                VALUES (new.id, new.content, new.key, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, content, key, tags)
                VALUES('delete', old.id, old.content, old.key, old.tags);
            END;
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def set_fact(
        self,
        user_id: str,
        key: str,
        value: str,
        tags: list[str] | None = None,
    ) -> Note:
        """Key-Value-Fakt speichern (Upsert: existierender Key wird überschrieben).

        Args:
            user_id: Matrix-User-ID.
            key: Schlüssel (wird normalisiert: lowercase, strip).
            value: Wert.
            tags: Optionale Tags zur Kategorisierung.

        Returns:
            Die erstellte/aktualisierte Note.
        """
        norm_key = self._normalize_key(key)
        tags_str = ",".join(tags) if tags else None
        now = datetime.now(timezone.utc).isoformat()

        existing = self._conn.execute(
            "SELECT id FROM notes WHERE user_id = ? AND key = ?",
            (user_id, norm_key),
        ).fetchone()

        if existing:
            self._conn.execute(
                "UPDATE notes SET content = ?, tags = ?, updated_at = ? "
                "WHERE user_id = ? AND key = ?",
                (value, tags_str, now, user_id, norm_key),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id, user_id, key, content, tags, created_at, updated_at "
                "FROM notes WHERE user_id = ? AND key = ?",
                (user_id, norm_key),
            ).fetchone()
        else:
            cursor = self._conn.execute(
                "INSERT INTO notes (user_id, key, content, tags, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, norm_key, value, tags_str, now, now),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id, user_id, key, content, tags, created_at, updated_at "
                "FROM notes WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()

        return self._row_to_note(row)

    def add_note(
        self,
        user_id: str,
        content: str,
        tags: list[str] | None = None,
    ) -> Note:
        """Freitext-Notiz speichern (kein Key, immer neuer Eintrag).

        Args:
            user_id: Matrix-User-ID.
            content: Notiztext.
            tags: Optionale Tags.

        Returns:
            Die erstellte Note.
        """
        tags_str = ",".join(tags) if tags else None
        now = datetime.now(timezone.utc).isoformat()

        cursor = self._conn.execute(
            "INSERT INTO notes (user_id, key, content, tags, created_at, updated_at) "
            "VALUES (?, NULL, ?, ?, ?, ?)",
            (user_id, content, tags_str, now, now),
        )
        self._conn.commit()

        row = self._conn.execute(
            "SELECT id, user_id, key, content, tags, created_at, updated_at "
            "FROM notes WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return self._row_to_note(row)

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def get_fact(self, user_id: str, key: str) -> Note | None:
        """Exakten KV-Fakt per normalisiertem Schlüssel abrufen.

        Args:
            user_id: Matrix-User-ID.
            key: Schlüssel (wird normalisiert).

        Returns:
            Note oder None wenn nicht gefunden.
        """
        norm_key = self._normalize_key(key)
        row = self._conn.execute(
            "SELECT id, user_id, key, content, tags, created_at, updated_at "
            "FROM notes WHERE user_id = ? AND key = ?",
            (user_id, norm_key),
        ).fetchone()
        return self._row_to_note(row) if row else None

    def search(self, user_id: str, query: str, limit: int = 10) -> list[Note]:
        """Volltextsuche über alle Notizen des Users (FTS5 MATCH).

        Durchsucht content, key und tags. Ergebnisse nach FTS5-Relevanz sortiert.

        Args:
            user_id: Matrix-User-ID.
            query: Suchbegriff.
            limit: Maximale Ergebnisse.

        Returns:
            Liste von Notes, nach Relevanz sortiert.
        """
        try:
            rows = self._conn.execute(
                "SELECT n.id, n.user_id, n.key, n.content, n.tags, "
                "n.created_at, n.updated_at "
                "FROM notes n "
                "JOIN notes_fts ON notes_fts.rowid = n.id "
                "WHERE notes_fts MATCH ? AND n.user_id = ? "
                "ORDER BY rank "
                "LIMIT ?",
                (query, user_id, limit),
            ).fetchall()
            return [self._row_to_note(r) for r in rows]
        except sqlite3.OperationalError as e:
            logger.warning("FTS-Suche fehlgeschlagen (Query: %r): %s", query, e)
            return []

    def list_all(self, user_id: str, limit: int = 20) -> list[Note]:
        """Alle Notizen eines Users (neueste zuerst).

        Args:
            user_id: Matrix-User-ID.
            limit: Maximale Ergebnisse.

        Returns:
            Liste von Notes, nach updated_at DESC sortiert.
        """
        rows = self._conn.execute(
            "SELECT id, user_id, key, content, tags, created_at, updated_at "
            "FROM notes WHERE user_id = ? "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [self._row_to_note(r) for r in rows]

    def get_notes_from_date(self, user_id: str, month: int, day: int,
                            limit: int = 5) -> list[Note]:
        """Notizen die an einem bestimmten Tag erstellt wurden (±1 Tag Toleranz).

        Sucht über alle Jahre hinweg nach Notizen deren created_at auf
        den angegebenen Monat/Tag fällt (±1 Tag).

        Args:
            user_id: Matrix-User-ID.
            month: Monat (1-12).
            day: Tag (1-31).
            limit: Maximale Ergebnisse.

        Returns:
            Liste von Notes, neueste zuerst.
        """
        try:
            ref = date(2000, month, day)
            dates = [ref + timedelta(days=d) for d in (-1, 0, 1)]
        except ValueError:
            return []

        conditions = " OR ".join(
            "created_at LIKE ?" for _ in dates
        )
        params: list[str | int] = [user_id]
        for d in dates:
            # created_at ist ISO: '2025-03-28T12:00:00+00:00'
            params.append(f"%-{d.month:02d}-{d.day:02d}T%")

        rows = self._conn.execute(
            "SELECT id, user_id, key, content, tags, created_at, updated_at "
            "FROM notes WHERE user_id = ? AND (" + conditions + ") "
            "ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._row_to_note(r) for r in rows]

    # ------------------------------------------------------------------
    # Löschen
    # ------------------------------------------------------------------

    def delete(self, note_id: int) -> bool:
        """Notiz per ID löschen.

        Returns:
            True wenn gelöscht, False wenn nicht gefunden.
        """
        cursor = self._conn.execute(
            "DELETE FROM notes WHERE id = ?",
            (note_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_fact(self, user_id: str, key: str) -> bool:
        """KV-Fakt per normalisiertem Schlüssel löschen.

        Returns:
            True wenn gelöscht, False wenn nicht gefunden.
        """
        norm_key = self._normalize_key(key)
        cursor = self._conn.execute(
            "DELETE FROM notes WHERE user_id = ? AND key = ?",
            (user_id, norm_key),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Verbindung sauber schließen."""
        try:
            self._conn.close()
        except Exception:
            pass

    @staticmethod
    def _normalize_key(key: str) -> str:
        """Normalisiert Keys: lowercase, strip, mehrfache Leerzeichen → einfach."""
        return re.sub(r"\s+", " ", key.strip().lower())

    @staticmethod
    def _row_to_note(row: tuple) -> Note:
        """Konvertiert einen DB-Row-Tuple in ein Note-DTO."""
        note_id, user_id, key, content, tags_str, created_at, updated_at = row
        tags = [t.strip() for t in tags_str.split(",")] if tags_str else []
        return Note(
            id=note_id,
            user_id=user_id,
            key=key,
            content=content,
            tags=tags,
            created_at=datetime.fromisoformat(created_at),
            updated_at=datetime.fromisoformat(updated_at),
        )
