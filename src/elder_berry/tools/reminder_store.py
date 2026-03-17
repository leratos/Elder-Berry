"""ReminderStore – Persistente Erinnerungen und Timer (SQLite).

Speichert Erinnerungen mit Fälligkeitszeit in einer SQLite-Datenbank.
Neustart-sicher, Multi-User-fähig (Matrix User-IDs).

Verwendung:
    store = ReminderStore()
    r = store.add("@user:matrix.org", "Wäsche", due_at)
    due = store.get_due()
    store.mark_fired(r.id)
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".elder-berry" / "reminders.db"
_CLEANUP_DAYS = 30


@dataclass(frozen=True)
class Reminder:
    """Eine einzelne Erinnerung."""

    id: int
    user_id: str
    message: str
    due_at: datetime
    created_at: datetime
    fired: bool
    cancelled: bool


class ReminderStore:
    """SQLite-basierter Erinnerungs-Speicher.

    Alle Zeiten werden intern als UTC gespeichert (ISO 8601).
    Thread-safe: check_same_thread=False.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                message     TEXT NOT NULL,
                due_at      TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                fired       INTEGER NOT NULL DEFAULT 0,
                cancelled   INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.commit()

    def add(self, user_id: str, message: str, due_at: datetime) -> Reminder:
        """Neue Erinnerung anlegen.

        Args:
            user_id: Matrix-User-ID.
            message: Erinnerungstext.
            due_at: Fälligkeitszeit (muss timezone-aware sein, wird als UTC gespeichert).

        Returns:
            Die erstellte Reminder-Instanz.

        Raises:
            ValueError: Wenn due_at nicht timezone-aware ist.
        """
        if due_at.tzinfo is None:
            raise ValueError(
                "due_at muss timezone-aware sein (z.B. datetime.now(timezone.utc))"
            )

        now = datetime.now(timezone.utc)
        due_utc = due_at.astimezone(timezone.utc)

        cursor = self._conn.execute(
            "INSERT INTO reminders (user_id, message, due_at, created_at) VALUES (?, ?, ?, ?)",
            (user_id, message, due_utc.isoformat(), now.isoformat()),
        )
        self._conn.commit()

        return Reminder(
            id=cursor.lastrowid,
            user_id=user_id,
            message=message,
            due_at=due_utc,
            created_at=now,
            fired=False,
            cancelled=False,
        )

    def get_pending(self, user_id: str | None = None) -> list[Reminder]:
        """Alle offenen (unfired + uncancelled) Erinnerungen.

        Args:
            user_id: Optional – nur Erinnerungen dieses Users.
        """
        if user_id:
            rows = self._conn.execute(
                "SELECT id, user_id, message, due_at, created_at, fired, cancelled "
                "FROM reminders WHERE fired = 0 AND cancelled = 0 AND user_id = ? "
                "ORDER BY due_at",
                (user_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, user_id, message, due_at, created_at, fired, cancelled "
                "FROM reminders WHERE fired = 0 AND cancelled = 0 "
                "ORDER BY due_at",
            ).fetchall()

        return [self._row_to_reminder(row) for row in rows]

    def get_due(self) -> list[Reminder]:
        """Alle fälligen Erinnerungen (due_at <= jetzt UND nicht fired)."""
        now = datetime.now(timezone.utc).isoformat()
        rows = self._conn.execute(
            "SELECT id, user_id, message, due_at, created_at, fired, cancelled "
            "FROM reminders WHERE due_at <= ? AND fired = 0 AND cancelled = 0 "
            "ORDER BY due_at",
            (now,),
        ).fetchall()

        return [self._row_to_reminder(row) for row in rows]

    def mark_fired(self, reminder_id: int) -> None:
        """Markiert eine Erinnerung als gesendet."""
        self._conn.execute(
            "UPDATE reminders SET fired = 1 WHERE id = ?",
            (reminder_id,),
        )
        self._conn.commit()

    def cancel(self, reminder_id: int) -> None:
        """Markiert eine Erinnerung als gelöscht."""
        self._conn.execute(
            "UPDATE reminders SET cancelled = 1 WHERE id = ?",
            (reminder_id,),
        )
        self._conn.commit()

    def cancel_all(self, user_id: str) -> int:
        """Löscht alle ausstehenden Erinnerungen eines Users.

        Returns:
            Anzahl gelöschter Erinnerungen.
        """
        cursor = self._conn.execute(
            "UPDATE reminders SET cancelled = 1 WHERE user_id = ? AND fired = 0 AND cancelled = 0",
            (user_id,),
        )
        self._conn.commit()
        return cursor.rowcount

    def cleanup_old(self) -> int:
        """Löscht physisch alte fired Reminders (> 30 Tage)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_CLEANUP_DAYS)).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM reminders WHERE fired = 1 AND due_at < ?",
            (cutoff,),
        )
        self._conn.commit()
        return cursor.rowcount

    def format_pending(self, reminders: list[Reminder]) -> str:
        """Formatierter Text für Matrix: Liste offener Erinnerungen."""
        if not reminders:
            return "Keine offenen Erinnerungen."

        lines = ["⏰ Offene Erinnerungen:\n"]
        for r in reminders:
            local_time = r.due_at.astimezone()
            time_str = local_time.strftime("%d.%m. %H:%M")
            lines.append(f"  #{r.id} – {r.message} (fällig: {time_str})")

        return "\n".join(lines)

    def close(self) -> None:
        """Schließt die Datenbankverbindung."""
        self._conn.close()

    @staticmethod
    def _row_to_reminder(row: tuple) -> Reminder:
        """Konvertiert eine DB-Zeile in ein Reminder-Objekt."""
        return Reminder(
            id=row[0],
            user_id=row[1],
            message=row[2],
            due_at=datetime.fromisoformat(row[3]),
            created_at=datetime.fromisoformat(row[4]),
            fired=bool(row[5]),
            cancelled=bool(row[6]),
        )
