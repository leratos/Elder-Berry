"""Aktions-Datenbank – Befehl → Aktion Mapping (SQLite, selbstlernend)."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "actions.db"


@dataclass
class Action:
    id: int
    trigger: str
    action_type: str
    action_payload: str
    last_used: str | None
    use_count: int


class ActionsDB:
    """
    Verwaltet das Mapping von Sprachbefehlen zu Aktionen.

    action_type: z.B. "open_app", "tts", "ollama_query", "system_info"
    action_payload: JSON-String oder plain text je nach action_type
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS actions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger      TEXT    NOT NULL UNIQUE,
                    action_type  TEXT    NOT NULL,
                    action_payload TEXT  NOT NULL DEFAULT '',
                    last_used    TEXT,
                    use_count    INTEGER NOT NULL DEFAULT 0
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, trigger: str, action_type: str, action_payload: str = "") -> int:
        """Fügt eine neue Aktion hinzu. Gibt die ID zurück."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO actions (trigger, action_type, action_payload) VALUES (?, ?, ?)",
                (trigger.lower().strip(), action_type, action_payload),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def get(self, trigger: str) -> Action | None:
        """Sucht eine Aktion nach Trigger-Text (exakter Match)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM actions WHERE trigger = ?",
                (trigger.lower().strip(),),
            ).fetchone()
        return Action(**dict(row)) if row else None

    def record_use(self, trigger: str) -> None:
        """Aktualisiert use_count und last_used."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE actions SET use_count = use_count + 1, last_used = ? WHERE trigger = ?",
                (datetime.now(timezone.utc).isoformat(), trigger.lower().strip()),
            )

    def update_payload(self, trigger: str, new_payload: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE actions SET action_payload = ? WHERE trigger = ?",
                (new_payload, trigger.lower().strip()),
            )

    def delete(self, trigger: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM actions WHERE trigger = ?", (trigger.lower().strip(),)
            )

    def list_all(self) -> list[Action]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM actions ORDER BY use_count DESC"
            ).fetchall()
        return [Action(**dict(r)) for r in rows]

    def top_actions(self, n: int = 10) -> list[Action]:
        """Die n am häufigsten genutzten Aktionen."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM actions ORDER BY use_count DESC LIMIT ?", (n,)
            ).fetchall()
        return [Action(**dict(r)) for r in rows]
