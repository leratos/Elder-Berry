"""TodoStore – Persistente Aufgabenliste (SQLite).

.. deprecated:: Phase 56
    Ersetzt durch CalDAVTaskClient (tools/caldav_tasks.py).
    Nextcloud Tasks ist die Single Source of Truth für Aufgaben.
    Diese Klasse wird nur noch vom Migrations-Script
    (scripts/migrate_todos_to_nextcloud.py) verwendet.
    Wird in einer zukünftigen Version entfernt.

Speichert Aufgaben ohne feste Zeitbindung mit optionaler Priorität
und Kategorie. Neustart-sicher, Multi-User-fähig (Matrix User-IDs).
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".elder-berry" / "todos.db"
_CLEANUP_DAYS = 90

PRIORITIES = ("hoch", "mittel", "niedrig")
PRIORITY_ICONS = {"hoch": "🔴", "mittel": "🟡", "niedrig": "🟢"}


@dataclass(frozen=True)
class Todo:
    """Eine einzelne Aufgabe."""

    id: int
    user_id: str
    text: str
    """Aufgabentext."""
    priority: str
    """Priorität: 'hoch', 'mittel', 'niedrig'. Default: 'niedrig'."""
    category: str
    """Optionale Kategorie (z.B. 'Einkauf', 'Arbeit'). Leer wenn nicht gesetzt."""
    done: bool
    """True wenn erledigt."""
    created_at: datetime
    completed_at: datetime | None
    """Zeitpunkt der Erledigung (None wenn offen)."""

    def format_short(self) -> str:
        """Einzeilige Darstellung."""
        check = "☑" if self.done else "⬚"
        prio = PRIORITY_ICONS.get(self.priority, "")
        cat = f", {self.category}" if self.category else ""
        if self.priority != "niedrig" or self.category:
            if self.priority == "niedrig" and self.category:
                extras = f" ({self.category})"
            else:
                extras = f" ({prio} {self.priority}{cat})"
        else:
            extras = ""
        return f"#{self.id} {check} {self.text}{extras}"


class TodoStore:
    """SQLite-basierter Aufgabenspeicher.

    Alle Zeiten intern als UTC (ISO 8601). Thread-safe.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path), check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS todos (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                text         TEXT NOT NULL,
                priority     TEXT NOT NULL DEFAULT 'niedrig',
                category     TEXT NOT NULL DEFAULT '',
                done         INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def add(self, user_id: str, text: str, priority: str = "niedrig",
            category: str = "") -> Todo:
        """Aufgabe hinzufügen."""
        if priority not in PRIORITIES:
            raise ValueError(
                f"Ungültige Priorität: {priority}. "
                f"Erlaubt: {', '.join(PRIORITIES)}"
            )
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            "INSERT INTO todos (user_id, text, priority, category, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, text, priority, category, now),
        )
        self._conn.commit()
        return self._get_by_id(cursor.lastrowid)

    def complete(self, todo_id: int) -> Todo | None:
        """Aufgabe als erledigt markieren."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            "UPDATE todos SET done=1, completed_at=? "
            "WHERE id=? AND done=0",
            (now, todo_id),
        )
        self._conn.commit()
        return self._get_by_id(todo_id) if cursor.rowcount > 0 else None

    def reopen(self, todo_id: int) -> Todo | None:
        """Erledigtes Todo wieder öffnen."""
        cursor = self._conn.execute(
            "UPDATE todos SET done=0, completed_at=NULL "
            "WHERE id=? AND done=1", (todo_id,),
        )
        self._conn.commit()
        return self._get_by_id(todo_id) if cursor.rowcount > 0 else None

    def update_priority(self, todo_id: int, priority: str) -> Todo | None:
        """Priorität ändern."""
        if priority not in PRIORITIES:
            raise ValueError(f"Ungültige Priorität: {priority}")
        cursor = self._conn.execute(
            "UPDATE todos SET priority=? WHERE id=?",
            (priority, todo_id),
        )
        self._conn.commit()
        return self._get_by_id(todo_id) if cursor.rowcount > 0 else None

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def get_open(self, user_id: str, priority: str = "",
                 category: str = "", limit: int = 50) -> list[Todo]:
        """Offene Todos eines Users, sortiert: hoch→mittel→niedrig."""
        query = "SELECT * FROM todos WHERE user_id=? AND done=0"
        params: list = [user_id]
        if priority:
            query += " AND priority=?"
            params.append(priority)
        if category:
            query += " AND category=? COLLATE NOCASE"
            params.append(category)
        query += """
            ORDER BY
                CASE priority
                    WHEN 'hoch' THEN 0
                    WHEN 'mittel' THEN 1
                    WHEN 'niedrig' THEN 2
                END, id ASC
            LIMIT ?
        """
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def get_done(self, user_id: str, limit: int = 20) -> list[Todo]:
        """Erledigte Todos (neueste zuerst)."""
        rows = self._conn.execute(
            "SELECT * FROM todos WHERE user_id=? AND done=1 "
            "ORDER BY completed_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def count_open(self, user_id: str) -> dict[str, int]:
        """Anzahl offener Todos pro Priorität."""
        rows = self._conn.execute(
            "SELECT priority, COUNT(*) FROM todos "
            "WHERE user_id=? AND done=0 GROUP BY priority",
            (user_id,),
        ).fetchall()
        counts = {p: 0 for p in PRIORITIES}
        for prio, count in rows:
            counts[prio] = count
        counts["total"] = sum(counts.values())
        return counts

    def format_for_briefing(self, user_id: str) -> str:
        """Kompakte Zusammenfassung für das Tages-Briefing."""
        counts = self.count_open(user_id)
        total = counts["total"]
        if total == 0:
            return "📋 Keine offenen Todos."
        if total <= 5:
            todos = self.get_open(user_id, limit=5)
            lines = [f"📋 {total} offene Todos:"]
            for t in todos:
                lines.append(f"  {t.format_short()}")
            return "\n".join(lines)
        parts = []
        for p in PRIORITIES:
            if counts[p] > 0:
                parts.append(f"{counts[p]} {p}")
        return f"📋 {total} offene Todos ({', '.join(parts)})"

    # ------------------------------------------------------------------
    # Löschen + Aufräumen
    # ------------------------------------------------------------------

    def delete(self, todo_id: int) -> bool:
        """Todo per ID löschen."""
        cursor = self._conn.execute(
            "DELETE FROM todos WHERE id=?", (todo_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_all_done(self, user_id: str) -> int:
        """Alle erledigten Todos eines Users löschen."""
        cursor = self._conn.execute(
            "DELETE FROM todos WHERE user_id=? AND done=1", (user_id,),
        )
        self._conn.commit()
        return cursor.rowcount

    def cleanup(self, days: int = _CLEANUP_DAYS) -> int:
        """Erledigte Todos älter als N Tage aufräumen."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cursor = self._conn.execute(
            "DELETE FROM todos WHERE done=1 AND completed_at < ?",
            (cutoff.isoformat(),),
        )
        self._conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info("TodoStore cleanup: %d erledigte Todos entfernt",
                        deleted)
        return deleted

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _get_by_id(self, todo_id: int) -> Todo:
        """Holt ein Todo per ID (nach INSERT/UPDATE)."""
        row = self._conn.execute(
            "SELECT * FROM todos WHERE id=?", (todo_id,),
        ).fetchone()
        return self._row_to_todo(row)

    @staticmethod
    def _row_to_todo(row: tuple) -> Todo:
        """Konvertiert DB-Row in Todo-DTO."""
        id_, user_id, text, priority, category, done, created, completed = row
        return Todo(
            id=id_, user_id=user_id, text=text, priority=priority,
            category=category, done=bool(done),
            created_at=datetime.fromisoformat(created),
            completed_at=(datetime.fromisoformat(completed)
                          if completed else None),
        )

    def close(self) -> None:
        """Verbindung sauber schließen."""
        try:
            self._conn.close()
        except Exception:
            pass
