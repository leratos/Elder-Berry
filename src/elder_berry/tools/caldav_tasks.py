"""CalDAVTaskClient – Nextcloud Tasks als Todo-Backend (CalDAV VTODO).

Liest und schreibt Aufgaben über die CalDAV-API einer Nextcloud-Instanz.
Ersetzt den SQLite-basierten TodoStore – Nextcloud Tasks ist die Single
Source of Truth.

Credentials werden aus dem SecretStore geladen (nextcloud_url, nextcloud_user,
nextcloud_app_password – identisch mit CalDAVCalendarClient).

Verwendung:
    client = CalDAVTaskClient(secret_store=store)
    tasks = client.get_open()
    client.add("Milch kaufen", priority="hoch", due=date(2026, 5, 1))
    client.complete(uid="abc-123")
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

PRIORITIES = ("hoch", "mittel", "niedrig")
PRIORITY_ICONS = {"hoch": "🔴", "mittel": "🟡", "niedrig": "🟢"}

# iCal PRIORITY (0-9) → Saleria-Priorität
_ICAL_TO_SALERIA = {
    0: "niedrig",   # undefiniert
    1: "hoch", 2: "hoch", 3: "hoch", 4: "hoch",
    5: "mittel",
    6: "niedrig", 7: "niedrig", 8: "niedrig", 9: "niedrig",
}

# Saleria-Priorität → iCal PRIORITY
_SALERIA_TO_ICAL = {"hoch": 1, "mittel": 5, "niedrig": 0}

# Bevorzugte Namen für die Task-Liste in Nextcloud
_TASK_LIST_NAMES = ("aufgaben", "tasks", "todos")


@dataclass(frozen=True)
class TaskItem:
    """Eine Aufgabe aus Nextcloud Tasks (VTODO)."""

    uid: str
    text: str
    priority: str           # "hoch" | "mittel" | "niedrig"
    category: str           # Erste CATEGORIES oder ""
    done: bool
    due: date | None        # Nur Datum, keine Uhrzeit
    description: str
    created_at: datetime | None
    completed_at: datetime | None

    def format_short(self) -> str:
        """Einzeilige Darstellung mit optionalem Fälligkeitsdatum."""
        check = "☑" if self.done else "⬚"
        prio = PRIORITY_ICONS.get(self.priority, "")

        extras_parts: list[str] = []
        if self.priority != "niedrig":
            extras_parts.append(f"{prio} {self.priority}")
        if self.category:
            extras_parts.append(self.category)
        if self.due:
            extras_parts.append(f"fällig {self.due.strftime('%d.%m.')}")

        extras = f" ({', '.join(extras_parts)})" if extras_parts else ""
        return f"{check} {self.text}{extras}"


class CalDAVTaskClient:
    """CalDAV Task Client für Nextcloud Tasks (VTODO).

    Verbindet sich lazy beim ersten Zugriff mit dem CalDAV-Server.
    Bei Connection-Fehlern wird die gecachte Task-Liste invalidiert,
    sodass der nächste Aufruf automatisch neu verbindet.
    """

    _RETRIABLE_ERRORS = (ConnectionError, OSError, TimeoutError)

    def __init__(self, secret_store: SecretStore) -> None:
        self._store = secret_store
        self._client = None
        self._task_list = None

    # ------------------------------------------------------------------
    # Verbindung
    # ------------------------------------------------------------------

    def _get_task_list(self):
        """Lazy-Init: Verbindet mit Nextcloud CalDAV, findet die Task-Liste.

        Sucht eine CalDAV-Collection mit VTODO-Support. Bevorzugt
        "Aufgaben"/"Tasks"/"Todos", sonst die erste mit VTODO-Support.
        """
        if self._task_list is not None:
            return self._task_list

        import caldav

        url = self._store.get("nextcloud_url")
        user = self._store.get("nextcloud_user")
        pw = self._store.get("nextcloud_app_password")

        self._client = caldav.DAVClient(
            url=f"{url}/remote.php/dav",
            username=user,
            password=pw,
        )
        principal = self._client.principal()
        calendars = principal.calendars()

        if not calendars:
            raise RuntimeError("Keine CalDAV-Collections in Nextcloud gefunden")

        # Finde Collection mit VTODO-Support
        vtodo_collections = []
        for cal in calendars:
            try:
                components = cal.get_supported_components()
                if "VTODO" in components:
                    vtodo_collections.append(cal)
            except Exception:
                # Fallback: versuche todos() aufzurufen
                try:
                    cal.todos()
                    vtodo_collections.append(cal)
                except Exception:
                    continue

        if not vtodo_collections:
            raise RuntimeError(
                "Keine Task-Liste mit VTODO-Support in Nextcloud gefunden"
            )

        # Bevorzuge bekannte Namen
        for cal in vtodo_collections:
            name = (getattr(cal, "name", "") or "").lower()
            if name in _TASK_LIST_NAMES:
                self._task_list = cal
                logger.info("Nextcloud Task-Liste gefunden: %s", cal.name)
                return self._task_list

        self._task_list = vtodo_collections[0]
        logger.info(
            "Nextcloud Task-Liste (Fallback): %s",
            getattr(self._task_list, "name", "unbekannt"),
        )
        return self._task_list

    def _call_with_retry(self, operation):
        """Führt operation() aus, mit 1x Retry bei stale Connection."""
        try:
            return operation()
        except self._RETRIABLE_ERRORS as e:
            logger.warning(
                "CalDAV Tasks Connection-Fehler, retry mit neuer Verbindung: %s",
                e,
            )
            self._task_list = None
            self._client = None
            return operation()

    def is_available(self) -> bool:
        """Prüft ob Nextcloud Tasks konfiguriert und erreichbar ist."""
        try:
            url = self._store.get_or_none("nextcloud_url")
            user = self._store.get_or_none("nextcloud_user")
            pw = self._store.get_or_none("nextcloud_app_password")
            if not all([url, user, pw]):
                return False
            self._get_task_list()
            return True
        except Exception:
            self._task_list = None
            self._client = None
            return False

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_todo(todo) -> TaskItem:
        """Parst ein caldav.Todo in ein TaskItem."""
        import icalendar

        cal = icalendar.Calendar.from_ical(todo.data)
        for component in cal.walk():
            if component.name != "VTODO":
                continue

            uid = str(component.get("UID", ""))
            summary = str(component.get("SUMMARY", "(Kein Titel)"))

            # Priorität
            ical_prio = component.get("PRIORITY")
            if ical_prio is not None:
                prio_val = int(ical_prio) if not isinstance(ical_prio, int) else ical_prio
                priority = _ICAL_TO_SALERIA.get(prio_val, "niedrig")
            else:
                priority = "niedrig"

            # Kategorie (erste)
            categories = component.get("CATEGORIES")
            category = ""
            if categories:
                cat_list = categories.to_ical().decode("utf-8", errors="replace")
                category = cat_list.split(",")[0].strip()

            # Status
            status = component.get("STATUS")
            done = str(status).upper() == "COMPLETED" if status else False

            # Fälligkeitsdatum (nur date, nicht datetime)
            due_prop = component.get("DUE")
            due_date: date | None = None
            if due_prop:
                dt = due_prop.dt
                if isinstance(dt, datetime):
                    due_date = dt.date()
                elif isinstance(dt, date):
                    due_date = dt

            # Beschreibung
            desc = component.get("DESCRIPTION")
            description = str(desc) if desc else ""

            # Timestamps
            created_prop = component.get("CREATED")
            created_at: datetime | None = None
            if created_prop:
                dt = created_prop.dt
                if isinstance(dt, datetime):
                    created_at = dt

            completed_prop = component.get("COMPLETED")
            completed_at: datetime | None = None
            if completed_prop:
                dt = completed_prop.dt
                if isinstance(dt, datetime):
                    completed_at = dt

            return TaskItem(
                uid=uid,
                text=summary,
                priority=priority,
                category=category,
                done=done,
                due=due_date,
                description=description,
                created_at=created_at,
                completed_at=completed_at,
            )

        raise ValueError("Kein VTODO in CalDAV-Antwort gefunden")

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def get_open(self, limit: int = 50) -> list[TaskItem]:
        """Offene Aufgaben, sortiert: hoch → mittel → niedrig."""
        def _op():
            task_list = self._get_task_list()
            todos = task_list.todos()

            items = []
            for todo in todos:
                try:
                    item = self._parse_todo(todo)
                    if not item.done:
                        items.append(item)
                except (ValueError, AttributeError) as e:
                    logger.debug("Todo-Parsing übersprungen: %s", e)

            prio_order = {"hoch": 0, "mittel": 1, "niedrig": 2}
            items.sort(key=lambda t: prio_order.get(t.priority, 2))
            return items[:limit]

        return self._call_with_retry(_op)

    def get_open_by_due(self, target: date) -> list[TaskItem]:
        """Offene Aufgaben mit Fälligkeit an einem bestimmten Datum."""
        def _op():
            task_list = self._get_task_list()
            todos = task_list.todos()

            items = []
            for todo in todos:
                try:
                    item = self._parse_todo(todo)
                    if not item.done and item.due == target:
                        items.append(item)
                except (ValueError, AttributeError) as e:
                    logger.debug("Todo-Parsing übersprungen: %s", e)

            prio_order = {"hoch": 0, "mittel": 1, "niedrig": 2}
            items.sort(key=lambda t: prio_order.get(t.priority, 2))
            return items

        return self._call_with_retry(_op)

    def get_open_by_due_range(
        self, start: date, end: date,
    ) -> list[TaskItem]:
        """Offene Aufgaben mit Fälligkeit in einem Zeitraum (inklusiv)."""
        def _op():
            task_list = self._get_task_list()
            todos = task_list.todos()

            items = []
            for todo in todos:
                try:
                    item = self._parse_todo(todo)
                    if not item.done and item.due and start <= item.due <= end:
                        items.append(item)
                except (ValueError, AttributeError) as e:
                    logger.debug("Todo-Parsing übersprungen: %s", e)

            items.sort(key=lambda t: (t.due or date.max, t.text))
            return items

        return self._call_with_retry(_op)

    def get_overdue(self) -> list[TaskItem]:
        """Offene Aufgaben deren Fälligkeitsdatum überschritten ist."""
        today = date.today()

        def _op():
            task_list = self._get_task_list()
            todos = task_list.todos()

            items = []
            for todo in todos:
                try:
                    item = self._parse_todo(todo)
                    if not item.done and item.due and item.due < today:
                        items.append(item)
                except (ValueError, AttributeError) as e:
                    logger.debug("Todo-Parsing übersprungen: %s", e)

            items.sort(key=lambda t: t.due or date.min)
            return items

        return self._call_with_retry(_op)

    def get_done(self, limit: int = 20) -> list[TaskItem]:
        """Erledigte Aufgaben (neueste zuerst)."""
        def _op():
            task_list = self._get_task_list()
            # caldav todos() holt standardmäßig nur offene;
            # für erledigte brauchen wir include_completed
            try:
                todos = task_list.todos(include_completed=True)
            except TypeError:
                # Fallback: manche caldav-Versionen kennen den Parameter nicht
                todos = task_list.todos()

            items = []
            for todo in todos:
                try:
                    item = self._parse_todo(todo)
                    if item.done:
                        items.append(item)
                except (ValueError, AttributeError) as e:
                    logger.debug("Todo-Parsing übersprungen: %s", e)

            items.sort(
                key=lambda t: t.completed_at or datetime.min.replace(
                    tzinfo=timezone.utc,
                ),
                reverse=True,
            )
            return items[:limit]

        return self._call_with_retry(_op)

    def count_open(self) -> dict[str, int]:
        """Anzahl offener Aufgaben pro Priorität."""
        items = self.get_open(limit=9999)
        counts = {p: 0 for p in PRIORITIES}
        for item in items:
            if item.priority in counts:
                counts[item.priority] += 1
        counts["total"] = sum(counts.values())
        return counts

    def format_for_briefing(self) -> str:
        """Kompakte Zusammenfassung für das Tages-Briefing."""
        counts = self.count_open()
        total = counts["total"]
        if total == 0:
            return "📋 Keine offenen Aufgaben."

        # Überfällige hervorheben
        overdue = self.get_overdue()
        overdue_hint = ""
        if overdue:
            overdue_hint = f" (⚠ {len(overdue)} überfällig)"

        if total <= 5:
            items = self.get_open(limit=5)
            lines = [f"📋 {total} offene Aufgaben{overdue_hint}:"]
            for item in items:
                lines.append(f"  {item.format_short()}")
            return "\n".join(lines)

        parts = []
        for p in PRIORITIES:
            if counts[p] > 0:
                parts.append(f"{counts[p]} {p}")
        return f"📋 {total} offene Aufgaben ({', '.join(parts)}){overdue_hint}"

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def add(
        self,
        text: str,
        priority: str = "niedrig",
        category: str = "",
        due: date | None = None,
    ) -> TaskItem:
        """Neue Aufgabe erstellen."""
        if priority not in PRIORITIES:
            raise ValueError(
                "Ungültige Priorität: %s. Erlaubt: %s"
                % (priority, ", ".join(PRIORITIES))
            )

        def _op():
            task_list = self._get_task_list()
            uid = str(uuid.uuid4())
            now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

            vcal_lines = [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//Elder-Berry//Tasks//DE",
                "BEGIN:VTODO",
                f"UID:{uid}",
                f"SUMMARY:{text}",
                f"CREATED:{now}",
                f"DTSTAMP:{now}",
                f"STATUS:NEEDS-ACTION",
            ]

            ical_prio = _SALERIA_TO_ICAL.get(priority, 0)
            if ical_prio > 0:
                vcal_lines.append(f"PRIORITY:{ical_prio}")

            if category:
                vcal_lines.append(f"CATEGORIES:{category}")

            if due:
                vcal_lines.append(f"DUE;VALUE=DATE:{due.strftime('%Y%m%d')}")

            vcal_lines.extend([
                "END:VTODO",
                "END:VCALENDAR",
            ])

            ical_str = "\r\n".join(vcal_lines)
            task_list.save_todo(ical_str)
            logger.info("Aufgabe erstellt: %s (%s)", text, uid)

            return TaskItem(
                uid=uid,
                text=text,
                priority=priority,
                category=category,
                done=False,
                due=due,
                description="",
                created_at=datetime.now(timezone.utc),
                completed_at=None,
            )

        return self._call_with_retry(_op)

    def complete(self, uid: str) -> TaskItem | None:
        """Aufgabe als erledigt markieren."""
        def _op():
            task_list = self._get_task_list()
            try:
                todo = task_list.todo_by_uid(uid)
                todo.complete()
                logger.info("Aufgabe erledigt: %s", uid)
                return self._parse_todo(todo)
            except Exception as e:
                error_str = str(e).lower()
                if "404" in error_str or "not found" in error_str:
                    logger.warning("Aufgabe nicht gefunden: %s", uid)
                    return None
                raise

        return self._call_with_retry(_op)

    def reopen(self, uid: str) -> TaskItem | None:
        """Erledigte Aufgabe wieder öffnen."""
        def _op():
            task_list = self._get_task_list()
            try:
                todo = task_list.todo_by_uid(uid)
            except Exception as e:
                error_str = str(e).lower()
                if "404" in error_str or "not found" in error_str:
                    logger.warning("Aufgabe nicht gefunden: %s", uid)
                    return None
                raise

            import icalendar

            cal = icalendar.Calendar.from_ical(todo.data)
            for component in cal.walk():
                if component.name == "VTODO":
                    component["STATUS"] = "NEEDS-ACTION"
                    if "COMPLETED" in component:
                        del component["COMPLETED"]
                    if "PERCENT-COMPLETE" in component:
                        del component["PERCENT-COMPLETE"]
                    break

            todo.data = cal.to_ical().decode("utf-8")
            todo.save()
            logger.info("Aufgabe wieder geöffnet: %s", uid)
            return self._parse_todo(todo)

        return self._call_with_retry(_op)

    def update_priority(self, uid: str, priority: str) -> TaskItem | None:
        """Priorität einer Aufgabe ändern."""
        if priority not in PRIORITIES:
            raise ValueError("Ungültige Priorität: %s" % priority)

        def _op():
            task_list = self._get_task_list()
            try:
                todo = task_list.todo_by_uid(uid)
            except Exception as e:
                error_str = str(e).lower()
                if "404" in error_str or "not found" in error_str:
                    logger.warning("Aufgabe nicht gefunden: %s", uid)
                    return None
                raise

            import icalendar

            cal = icalendar.Calendar.from_ical(todo.data)
            for component in cal.walk():
                if component.name == "VTODO":
                    ical_prio = _SALERIA_TO_ICAL.get(priority, 0)
                    component["PRIORITY"] = ical_prio
                    break

            todo.data = cal.to_ical().decode("utf-8")
            todo.save()
            logger.info("Aufgabe Priorität geändert: %s → %s", uid, priority)
            return self._parse_todo(todo)

        return self._call_with_retry(_op)

    def delete(self, uid: str) -> bool:
        """Aufgabe löschen."""
        def _op():
            task_list = self._get_task_list()
            try:
                todo = task_list.todo_by_uid(uid)
                todo.delete()
                logger.info("Aufgabe gelöscht: %s", uid)
                return True
            except Exception as e:
                error_str = str(e).lower()
                if "404" in error_str or "not found" in error_str:
                    logger.info(
                        "Aufgabe bereits gelöscht/nicht gefunden: %s", uid,
                    )
                    return True
                logger.error(
                    "Aufgabe löschen fehlgeschlagen (%s): %s", uid, e,
                )
                raise RuntimeError(
                    "Aufgabe löschen fehlgeschlagen: %s" % e,
                ) from e

        return self._call_with_retry(_op)

    def delete_all_done(self) -> int:
        """Alle erledigten Aufgaben löschen."""
        done_items = self.get_done(limit=9999)
        deleted = 0
        for item in done_items:
            if self.delete(item.uid):
                deleted += 1
        if deleted > 0:
            logger.info("Erledigte Aufgaben gelöscht: %d", deleted)
        return deleted
