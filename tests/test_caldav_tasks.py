"""Tests für CalDAVTaskClient – CalDAV komplett gemockt."""
from __future__ import annotations

from datetime import date, datetime, timezone
import sys
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.tools.caldav_tasks import (
    CalDAVTaskClient,
    TaskItem,
    PRIORITIES,
    _ICAL_TO_SALERIA,
    _SALERIA_TO_ICAL,
)

# icalendar ist optionale Dependency (kommt mit caldav)
_has_icalendar = True
try:
    import icalendar as _ical  # noqa: F401
except ImportError:
    _has_icalendar = False

needs_icalendar = pytest.mark.skipif(
    not _has_icalendar, reason="icalendar nicht installiert",
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_secret_store(**overrides):
    """Erstellt einen Mock-SecretStore mit Nextcloud-Credentials."""
    defaults = {
        "nextcloud_url": "https://cloud.example.com",
        "nextcloud_user": "testuser",
        "nextcloud_app_password": "secret123",
    }
    defaults.update(overrides)

    store = MagicMock()
    store.get.side_effect = lambda key: defaults[key]
    store.get_or_none.side_effect = lambda key: defaults.get(key)
    return store


def _make_vtodo_ical(
    summary="Test Aufgabe",
    uid="uid-task-001",
    priority=None,
    categories=None,
    status="NEEDS-ACTION",
    due=None,
    description=None,
    created=None,
    completed=None,
):
    """Erzeugt einen iCal-String für ein VTODO."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Elder-Berry//Tasks//DE",
        "BEGIN:VTODO",
        f"UID:{uid}",
        f"SUMMARY:{summary}",
        f"STATUS:{status}",
    ]
    if priority is not None:
        lines.append(f"PRIORITY:{priority}")
    if categories:
        lines.append(f"CATEGORIES:{categories}")
    if due:
        lines.append(f"DUE;VALUE=DATE:{due}")
    if description:
        lines.append(f"DESCRIPTION:{description}")
    if created:
        lines.append(f"CREATED:{created}")
    if completed:
        lines.append(f"COMPLETED:{completed}")
    lines.extend(["END:VTODO", "END:VCALENDAR"])
    return "\r\n".join(lines)


def _make_caldav_todo(ical_str):
    """Erzeugt ein Mock-caldav-Todo mit .data Attribut."""
    todo = MagicMock()
    todo.data = ical_str
    return todo


def _client_with_task_list(mock_task_list=None):
    """Erstellt einen CalDAVTaskClient mit vorgefertigtem Task-Liste-Mock."""
    store = _make_secret_store()
    client = CalDAVTaskClient(secret_store=store)
    if mock_task_list is None:
        mock_task_list = MagicMock()
    client._task_lists = [mock_task_list]
    return client, mock_task_list


# ── TaskItem Dataclass ───────────────────────────────────────────────

class TestTaskItem:
    def test_format_short_basic(self):
        item = TaskItem(
            uid="u1", text="Milch kaufen", priority="niedrig",
            category="", done=False, due=None, description="",
            created_at=None, completed_at=None,
        )
        result = item.format_short()
        assert "⬚" in result
        assert "Milch kaufen" in result
        assert "(" not in result  # keine Extras bei niedrig + keine Kategorie

    def test_format_short_done(self):
        item = TaskItem(
            uid="u2", text="Erledigt", priority="niedrig",
            category="", done=True, due=None, description="",
            created_at=None, completed_at=None,
        )
        assert "☑" in item.format_short()

    def test_format_short_high_priority(self):
        item = TaskItem(
            uid="u3", text="Wichtig", priority="hoch",
            category="", done=False, due=None, description="",
            created_at=None, completed_at=None,
        )
        result = item.format_short()
        assert "🔴" in result
        assert "hoch" in result

    def test_format_short_with_category(self):
        item = TaskItem(
            uid="u4", text="Task", priority="niedrig",
            category="Arbeit", done=False, due=None, description="",
            created_at=None, completed_at=None,
        )
        assert "Arbeit" in item.format_short()

    def test_format_short_with_due(self):
        item = TaskItem(
            uid="u5", text="Task", priority="niedrig",
            category="", done=False, due=date(2026, 5, 15), description="",
            created_at=None, completed_at=None,
        )
        result = item.format_short()
        assert "fällig 15.05." in result

    def test_format_short_all_extras(self):
        item = TaskItem(
            uid="u6", text="Alles", priority="hoch",
            category="Privat", done=False, due=date(2026, 3, 1),
            description="", created_at=None, completed_at=None,
        )
        result = item.format_short()
        assert "🔴" in result
        assert "Privat" in result
        assert "fällig 01.03." in result

    def test_frozen(self):
        item = TaskItem(
            uid="u7", text="Test", priority="niedrig", category="",
            done=False, due=None, description="", created_at=None,
            completed_at=None,
        )
        with pytest.raises(AttributeError):
            item.text = "Geändert"


# ── Prioritäts-Mapping ──────────────────────────────────────────────

class TestPriorityMapping:
    def test_ical_to_saleria_hoch(self):
        for i in (1, 2, 3, 4):
            assert _ICAL_TO_SALERIA[i] == "hoch"

    def test_ical_to_saleria_mittel(self):
        assert _ICAL_TO_SALERIA[5] == "mittel"

    def test_ical_to_saleria_niedrig(self):
        for i in (0, 6, 7, 8, 9):
            assert _ICAL_TO_SALERIA[i] == "niedrig"

    def test_saleria_to_ical(self):
        assert _SALERIA_TO_ICAL["hoch"] == 1
        assert _SALERIA_TO_ICAL["mittel"] == 5
        assert _SALERIA_TO_ICAL["niedrig"] == 0

    def test_roundtrip(self):
        for prio in PRIORITIES:
            ical_val = _SALERIA_TO_ICAL[prio]
            assert _ICAL_TO_SALERIA[ical_val] == prio


# ── Credentials & Verfügbarkeit ─────────────────────────────────────

class TestCredentialsAndAvailability:
    def test_init_from_secret_store(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)
        assert client._store is store
        assert client._task_lists is None
        assert client._client is None

    def test_is_available_success(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)
        client._task_lists = [MagicMock()]
        assert client.is_available() is True

    def test_is_available_no_credentials(self):
        store = MagicMock()
        store.get_or_none.return_value = None
        client = CalDAVTaskClient(secret_store=store)
        assert client.is_available() is False

    def test_is_available_server_unreachable(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)

        with patch.object(
            client, "_get_task_lists", side_effect=ConnectionError("timeout"),
        ):
            assert client.is_available() is False

    def test_lazy_init(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)
        assert client._task_lists is None
        assert client._client is None


# ── Task-Liste finden ────────────────────────────────────────────────

class TestGetTaskLists:
    def test_finds_all_vtodo_collections(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)

        mock_cal_events = MagicMock()
        mock_cal_events.name = "Personal"
        mock_cal_events.get_supported_components.return_value = ["VEVENT"]

        mock_cal_tasks = MagicMock()
        mock_cal_tasks.name = "Aufgaben"
        mock_cal_tasks.get_supported_components.return_value = ["VTODO"]

        mock_cal_haushalt = MagicMock()
        mock_cal_haushalt.name = "Haushalt"
        mock_cal_haushalt.get_supported_components.return_value = ["VTODO"]

        mock_principal = MagicMock()
        mock_principal.calendars.return_value = [
            mock_cal_events, mock_cal_tasks, mock_cal_haushalt,
        ]

        mock_caldav = MagicMock()
        mock_caldav.DAVClient.return_value.principal.return_value = (
            mock_principal
        )
        with patch.dict(sys.modules, {"caldav": mock_caldav}):
            result = client._get_task_lists()

        assert len(result) == 2
        assert mock_cal_tasks in result
        assert mock_cal_haushalt in result
        assert mock_cal_events not in result

    def test_default_prefers_aufgaben(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)

        mock_haushalt = MagicMock()
        mock_haushalt.name = "Haushalt"

        mock_aufgaben = MagicMock()
        mock_aufgaben.name = "Aufgaben"

        client._task_lists = [mock_haushalt, mock_aufgaben]
        assert client._get_default_task_list() is mock_aufgaben

    def test_default_fallback_to_first(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)

        mock_custom = MagicMock()
        mock_custom.name = "Meine Liste"

        client._task_lists = [mock_custom]
        assert client._get_default_task_list() is mock_custom

    def test_no_vtodo_collection_raises(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)

        mock_cal = MagicMock()
        mock_cal.name = "Personal"
        mock_cal.get_supported_components.return_value = ["VEVENT"]

        mock_principal = MagicMock()
        mock_principal.calendars.return_value = [mock_cal]

        mock_caldav = MagicMock()
        mock_caldav.DAVClient.return_value.principal.return_value = (
            mock_principal
        )
        with patch.dict(sys.modules, {"caldav": mock_caldav}):
            with pytest.raises(RuntimeError, match="VTODO-Support"):
                client._get_task_lists()

    def test_no_collections_at_all_raises(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)

        mock_principal = MagicMock()
        mock_principal.calendars.return_value = []

        mock_caldav = MagicMock()
        mock_caldav.DAVClient.return_value.principal.return_value = (
            mock_principal
        )
        with patch.dict(sys.modules, {"caldav": mock_caldav}):
            with pytest.raises(RuntimeError, match="Keine CalDAV-Collections"):
                client._get_task_lists()

    def test_caches_task_lists(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)
        mock_lists = [MagicMock()]
        client._task_lists = mock_lists
        assert client._get_task_lists() is mock_lists


# ── Parsing ──────────────────────────────────────────────────────────

@needs_icalendar
class TestParseTodo:
    def test_parse_basic(self):
        ical = _make_vtodo_ical(
            summary="Milch kaufen", uid="abc-123",
        )
        item = CalDAVTaskClient._parse_todo(_make_caldav_todo(ical))
        assert item.uid == "abc-123"
        assert item.text == "Milch kaufen"
        assert item.priority == "niedrig"
        assert item.category == ""
        assert item.done is False
        assert item.due is None
        assert item.description == ""

    def test_parse_completed(self):
        ical = _make_vtodo_ical(
            summary="Erledigt", uid="done-1", status="COMPLETED",
            completed="20260401T120000Z",
        )
        item = CalDAVTaskClient._parse_todo(_make_caldav_todo(ical))
        assert item.done is True
        assert item.completed_at is not None

    def test_parse_priority_hoch(self):
        ical = _make_vtodo_ical(summary="P1", uid="p1", priority=1)
        item = CalDAVTaskClient._parse_todo(_make_caldav_todo(ical))
        assert item.priority == "hoch"

    def test_parse_priority_mittel(self):
        ical = _make_vtodo_ical(summary="P5", uid="p5", priority=5)
        item = CalDAVTaskClient._parse_todo(_make_caldav_todo(ical))
        assert item.priority == "mittel"

    def test_parse_priority_niedrig(self):
        ical = _make_vtodo_ical(summary="P9", uid="p9", priority=9)
        item = CalDAVTaskClient._parse_todo(_make_caldav_todo(ical))
        assert item.priority == "niedrig"

    def test_parse_category(self):
        ical = _make_vtodo_ical(
            summary="Cat", uid="c1", categories="Arbeit,Privat",
        )
        item = CalDAVTaskClient._parse_todo(_make_caldav_todo(ical))
        assert item.category == "Arbeit"

    def test_parse_due_date(self):
        ical = _make_vtodo_ical(
            summary="Fällig", uid="d1", due="20260515",
        )
        item = CalDAVTaskClient._parse_todo(_make_caldav_todo(ical))
        assert item.due == date(2026, 5, 15)

    def test_parse_description(self):
        ical = _make_vtodo_ical(
            summary="Desc", uid="desc1",
            description="Detaillierte Beschreibung",
        )
        item = CalDAVTaskClient._parse_todo(_make_caldav_todo(ical))
        assert item.description == "Detaillierte Beschreibung"

    def test_parse_created_at(self):
        ical = _make_vtodo_ical(
            summary="Created", uid="cr1",
            created="20260401T100000Z",
        )
        item = CalDAVTaskClient._parse_todo(_make_caldav_todo(ical))
        assert item.created_at is not None
        assert item.created_at.year == 2026

    def test_parse_no_vtodo_raises(self):
        ical = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR"
        with pytest.raises(ValueError, match="Kein VTODO"):
            CalDAVTaskClient._parse_todo(_make_caldav_todo(ical))


# ── Lese-Operationen ────────────────────────────────────────────────

@needs_icalendar
class TestGetOpen:
    def test_get_open_basic(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary="A", uid="a1", priority=1,
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="B", uid="b1", priority=9,
            )),
        ]

        items = client.get_open()
        assert len(items) == 2
        assert items[0].text == "A"  # hoch zuerst
        assert items[1].text == "B"

    def test_get_open_excludes_done(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary="Offen", uid="o1",
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="Erledigt", uid="d1", status="COMPLETED",
            )),
        ]

        items = client.get_open()
        assert len(items) == 1
        assert items[0].text == "Offen"

    def test_get_open_limit(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary=f"Task {i}", uid=f"t{i}",
            ))
            for i in range(10)
        ]

        items = client.get_open(limit=3)
        assert len(items) == 3

    def test_get_open_sorted_by_priority(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary="Niedrig", uid="n1", priority=9,
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="Hoch", uid="h1", priority=1,
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="Mittel", uid="m1", priority=5,
            )),
        ]

        items = client.get_open()
        assert items[0].priority == "hoch"
        assert items[1].priority == "mittel"
        assert items[2].priority == "niedrig"

    def test_get_open_empty(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = []
        assert client.get_open() == []


@needs_icalendar
class TestGetByDue:
    def test_get_open_by_due(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary="Heute", uid="h1", due="20260416",
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="Morgen", uid="m1", due="20260417",
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="Ohne", uid="o1",
            )),
        ]

        items = client.get_open_by_due(date(2026, 4, 16))
        assert len(items) == 1
        assert items[0].text == "Heute"

    def test_get_overdue(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary="Überfällig", uid="o1", due="20260101",
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="Zukunft", uid="z1", due="20991231",
            )),
        ]

        items = client.get_overdue()
        assert len(items) == 1
        assert items[0].text == "Überfällig"

    def test_get_open_by_due_range(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary="Mo", uid="mo", due="20260413",
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="Mi", uid="mi", due="20260415",
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="Sa", uid="sa", due="20260418",
            )),
        ]

        items = client.get_open_by_due_range(
            date(2026, 4, 13), date(2026, 4, 17),
        )
        assert len(items) == 2
        assert items[0].text == "Mo"
        assert items[1].text == "Mi"


@needs_icalendar
class TestGetDone:
    def test_get_done(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary="Offen", uid="o1",
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="Erledigt", uid="d1", status="COMPLETED",
                completed="20260401T120000Z",
            )),
        ]

        items = client.get_done()
        assert len(items) == 1
        assert items[0].text == "Erledigt"
        assert items[0].done is True

    def test_get_done_fallback_without_include_completed(self):
        """Falls caldav-Version include_completed nicht kennt."""
        client, tl = _client_with_task_list()
        tl.todos.side_effect = [
            TypeError("unexpected keyword"),
            [_make_caldav_todo(_make_vtodo_ical(
                summary="Done", uid="d1", status="COMPLETED",
            ))],
        ]

        items = client.get_done()
        assert len(items) == 1


@needs_icalendar
class TestCountAndBriefing:
    def test_count_open(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary="H1", uid="h1", priority=1,
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="H2", uid="h2", priority=2,
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="M1", uid="m1", priority=5,
            )),
        ]

        counts = client.count_open()
        assert counts["hoch"] == 2
        assert counts["mittel"] == 1
        assert counts["niedrig"] == 0
        assert counts["total"] == 3

    def test_format_for_briefing_empty(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = []

        result = client.format_for_briefing()
        assert "Keine offenen" in result

    def test_format_for_briefing_few(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary="Task A", uid="a1",
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="Task B", uid="b1",
            )),
        ]

        result = client.format_for_briefing()
        assert "2 offene Aufgaben" in result
        assert "Task A" in result
        assert "Task B" in result

    def test_format_for_briefing_many(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary=f"Task {i}", uid=f"t{i}",
            ))
            for i in range(10)
        ]

        result = client.format_for_briefing()
        assert "10 offene Aufgaben" in result

    def test_format_for_briefing_with_overdue(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary="Überfällig", uid="o1", due="20260101",
            )),
        ]

        result = client.format_for_briefing()
        assert "überfällig" in result


# ── Schreib-Operationen ─────────────────────────────────────────────

class TestAdd:
    def test_add_basic(self):
        client, tl = _client_with_task_list()

        item = client.add("Milch kaufen")
        assert item.text == "Milch kaufen"
        assert item.priority == "niedrig"
        assert item.done is False
        tl.save_todo.assert_called_once()

    def test_add_with_priority(self):
        client, tl = _client_with_task_list()

        item = client.add("Wichtig", priority="hoch")
        assert item.priority == "hoch"
        ical_str = tl.save_todo.call_args[0][0]
        assert "PRIORITY:1" in ical_str

    def test_add_with_category(self):
        client, tl = _client_with_task_list()

        item = client.add("Task", category="Arbeit")
        assert item.category == "Arbeit"
        ical_str = tl.save_todo.call_args[0][0]
        assert "CATEGORIES:Arbeit" in ical_str

    def test_add_with_due_date(self):
        client, tl = _client_with_task_list()

        item = client.add("Fällig", due=date(2026, 5, 15))
        assert item.due == date(2026, 5, 15)
        ical_str = tl.save_todo.call_args[0][0]
        assert "DUE;VALUE=DATE:20260515" in ical_str

    def test_add_invalid_priority_raises(self):
        client, tl = _client_with_task_list()
        with pytest.raises(ValueError, match="Ungültige Priorität"):
            client.add("Test", priority="ultra")

    def test_add_niedrig_no_priority_in_ical(self):
        """Bei niedrig (= iCal 0/undefiniert) wird kein PRIORITY geschrieben."""
        client, tl = _client_with_task_list()
        client.add("Normal")
        ical_str = tl.save_todo.call_args[0][0]
        assert "PRIORITY:" not in ical_str


class TestComplete:
    def test_complete_success(self):
        client, tl = _client_with_task_list()
        mock_todo = _make_caldav_todo(_make_vtodo_ical(
            summary="Task", uid="c1", status="COMPLETED",
            completed="20260416T120000Z",
        ))
        tl.todo_by_uid.return_value = mock_todo

        with patch.object(
            CalDAVTaskClient, "_parse_todo",
            return_value=TaskItem(
                uid="c1", text="Task", priority="niedrig", category="",
                done=True, due=None, description="",
                created_at=None,
                completed_at=datetime(2026, 4, 16, 12, tzinfo=timezone.utc),
            ),
        ):
            item = client.complete("c1")

        assert item is not None
        assert item.done is True
        mock_todo.complete.assert_called_once()

    def test_complete_not_found(self):
        client, tl = _client_with_task_list()
        tl.todo_by_uid.side_effect = Exception("404 Not Found")

        result = client.complete("nonexistent")
        assert result is None


@needs_icalendar
class TestReopen:
    def test_reopen_success(self):
        client, tl = _client_with_task_list()
        ical = _make_vtodo_ical(
            summary="Reopened", uid="r1", status="COMPLETED",
            completed="20260401T120000Z",
        )
        mock_todo = _make_caldav_todo(ical)
        tl.todo_by_uid.return_value = mock_todo

        item = client.reopen("r1")
        assert item is not None
        mock_todo.save.assert_called_once()

    def test_reopen_not_found(self):
        client, tl = _client_with_task_list()
        tl.todo_by_uid.side_effect = Exception("404 Not Found")

        result = client.reopen("nonexistent")
        assert result is None


@needs_icalendar
class TestUpdatePriority:
    def test_update_priority_success(self):
        client, tl = _client_with_task_list()
        ical = _make_vtodo_ical(summary="Prio", uid="p1", priority=9)
        mock_todo = _make_caldav_todo(ical)
        tl.todo_by_uid.return_value = mock_todo

        item = client.update_priority("p1", "hoch")
        assert item is not None
        mock_todo.save.assert_called_once()

    def test_update_priority_invalid_raises(self):
        client, tl = _client_with_task_list()
        with pytest.raises(ValueError, match="Ungültige Priorität"):
            client.update_priority("p1", "ultra")

    def test_update_priority_not_found(self):
        client, tl = _client_with_task_list()
        tl.todo_by_uid.side_effect = Exception("404 Not Found")

        result = client.update_priority("nonexistent", "hoch")
        assert result is None


class TestDelete:
    def test_delete_success(self):
        client, tl = _client_with_task_list()
        mock_todo = MagicMock()
        tl.todo_by_uid.return_value = mock_todo

        result = client.delete("del-1")
        assert result is True
        mock_todo.delete.assert_called_once()

    def test_delete_not_found_idempotent(self):
        client, tl = _client_with_task_list()
        tl.todo_by_uid.side_effect = Exception("404 Not Found")

        result = client.delete("gone")
        assert result is True

    def test_delete_not_found_across_lists(self):
        """delete() gibt True zurück wenn UID in keiner Liste gefunden."""
        client, tl = _client_with_task_list()
        tl.todo_by_uid.side_effect = Exception("404 Not Found")

        result = client.delete("nowhere")
        assert result is True


@needs_icalendar
class TestDeleteAllDone:
    def test_delete_all_done(self):
        client, tl = _client_with_task_list()
        tl.todos.return_value = [
            _make_caldav_todo(_make_vtodo_ical(
                summary="Done1", uid="d1", status="COMPLETED",
                completed="20260401T120000Z",
            )),
            _make_caldav_todo(_make_vtodo_ical(
                summary="Done2", uid="d2", status="COMPLETED",
                completed="20260402T120000Z",
            )),
        ]

        mock_todo = MagicMock()
        tl.todo_by_uid.return_value = mock_todo

        deleted = client.delete_all_done()
        assert deleted == 2


# ── Connection Recovery ──────────────────────────────────────────────

class TestConnectionRecovery:
    def test_retry_after_connection_error(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)

        mock_tl = MagicMock()
        call_count = 0

        def todos_with_fail():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("connection reset")
            return []

        mock_tl.todos.side_effect = todos_with_fail

        with patch.object(client, "_get_task_lists", return_value=[mock_tl]):
            items = client.get_open()

        assert items == []
        assert call_count == 2

    def test_retry_resets_cached_state(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)
        client._task_lists = [MagicMock(name="old_task_list")]
        client._client = MagicMock(name="old_client")

        def failing_op():
            raise OSError("broken pipe")

        with pytest.raises(OSError):
            client._call_with_retry(failing_op)

        # Nach dem Fehler sollten die gecachten Objekte resettet sein
        assert client._task_lists is None
        assert client._client is None

    def test_timeout_error_triggers_retry(self):
        store = _make_secret_store()
        client = CalDAVTaskClient(secret_store=store)

        mock_tl = MagicMock()
        attempts = []

        def todos_timeout():
            attempts.append(1)
            if len(attempts) == 1:
                raise TimeoutError("read timed out")
            return []

        mock_tl.todos.side_effect = todos_timeout

        with patch.object(client, "_get_task_lists", return_value=[mock_tl]):
            result = client.get_open()

        assert result == []
        assert len(attempts) == 2
