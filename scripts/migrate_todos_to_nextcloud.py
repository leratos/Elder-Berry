#!/usr/bin/env python3
"""Einmal-Migration: TodoStore (SQLite) → Nextcloud Tasks (CalDAV VTODO).

Liest alle offenen Todos aus ~/.elder-berry/todos.db und erstellt
je ein VTODO in Nextcloud Tasks via CalDAVTaskClient.

Idempotent: Prüft per SUMMARY-Match ob bereits migriert.
Stoppt bei Fehler (kein stilles Überspringen).

Verwendung:
    python scripts/migrate_todos_to_nextcloud.py
    python scripts/migrate_todos_to_nextcloud.py --db-path /pfad/zu/todos.db
    python scripts/migrate_todos_to_nextcloud.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Projekt-Root ins Path aufnehmen
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from elder_berry.core.secret_store import SecretStore
from elder_berry.tools.caldav_tasks import CalDAVTaskClient
from elder_berry.tools.todo_store import TodoStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _get_existing_summaries(client: CalDAVTaskClient) -> set[str]:
    """Holt die SUMMARY aller vorhandenen Tasks (offen + erledigt)."""
    summaries: set[str] = set()
    for item in client.get_open(limit=9999):
        summaries.add(item.text)
    for item in client.get_done(limit=9999):
        summaries.add(item.text)
    return summaries


def migrate(db_path: Path, dry_run: bool = False) -> None:
    """Migriert offene Todos aus SQLite nach Nextcloud Tasks."""
    # TodoStore öffnen
    if not db_path.exists():
        logger.error("Datenbank nicht gefunden: %s", db_path)
        sys.exit(1)

    store = TodoStore(db_path=db_path)
    logger.info("TodoStore geöffnet: %s", db_path)

    # Alle offenen Todos aller User holen
    # TodoStore hat keinen get_all – wir gehen über die DB direkt
    rows = store._conn.execute(
        "SELECT * FROM todos WHERE done=0 ORDER BY id ASC",
    ).fetchall()
    all_todos = [store._row_to_todo(r) for r in rows]

    if not all_todos:
        logger.info("Keine offenen Todos gefunden. Nichts zu migrieren.")
        store.close()
        return

    logger.info("%d offene Todos gefunden", len(all_todos))

    if dry_run:
        logger.info("=== DRY RUN – keine Änderungen ===")
        for todo in all_todos:
            logger.info(
                "  Würde migrieren: #%d %s (prio=%s, cat=%s)",
                todo.id, todo.text, todo.priority, todo.category,
            )
        store.close()
        return

    # CalDAVTaskClient initialisieren
    secrets = SecretStore()
    client = CalDAVTaskClient(secret_store=secrets)

    if not client.is_available():
        logger.error(
            "Nextcloud Tasks nicht erreichbar. "
            "Prüfe nextcloud_url, nextcloud_user, nextcloud_app_password."
        )
        store.close()
        sys.exit(1)

    logger.info("Nextcloud Tasks verbunden")

    # Bestehende Tasks holen für Idempotenz-Prüfung
    existing = _get_existing_summaries(client)
    logger.info("%d bestehende Tasks in Nextcloud", len(existing))

    migrated = 0
    skipped = 0

    for todo in all_todos:
        if todo.text in existing:
            logger.info(
                "  Übersprungen (bereits vorhanden): #%d %s",
                todo.id, todo.text,
            )
            skipped += 1
            continue

        client.add(
            text=todo.text,
            priority=todo.priority,
            category=todo.category,
        )
        logger.info(
            "  Migriert: #%d %s (prio=%s, cat=%s)",
            todo.id, todo.text, todo.priority, todo.category,
        )
        migrated += 1

    store.close()
    logger.info(
        "Migration abgeschlossen: %d migriert, %d übersprungen",
        migrated, skipped,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migriert TodoStore-Todos nach Nextcloud Tasks",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path.home() / ".elder-berry" / "todos.db",
        help="Pfad zur todos.db (default: ~/.elder-berry/todos.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur anzeigen was migriert würde, keine Änderungen",
    )
    args = parser.parse_args()
    migrate(db_path=args.db_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
