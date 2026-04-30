"""Tests für BriefingScheduler Phase 38 Erweiterungen.

Testet: erweiterte Geburtstage (morgen/diese Woche), Jahrestage, Auto-Sync.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.briefing_scheduler import BriefingScheduler
from elder_berry.tools.contact_store import ContactStore

USER = "@test:matrix.org"

_WEDNESDAY = datetime(2026, 6, 15, 7, 30)  # Mittwoch


@pytest.fixture()
def store(tmp_path: Path) -> ContactStore:
    db = tmp_path / "contacts.db"
    s = ContactStore(db_path=db)
    yield s
    s.close()


def _make_scheduler(
    store: ContactStore,
    carddav_sync: MagicMock | None = None,
) -> BriefingScheduler:
    return BriefingScheduler(
        send_briefing=MagicMock(),
        contact_store=store,
        carddav_sync=carddav_sync,
        default_user_id=USER,
    )


class TestBirthdaySectionExtended:
    def test_birthday_today(self, store: ContactStore) -> None:
        store.add(USER, "Lisa", birthday="1990-06-15")
        scheduler = _make_scheduler(store)
        briefing = scheduler.build_briefing(now=_WEDNESDAY)
        assert "Geburtstage heute" in briefing
        assert "Lisa" in briefing
        assert "wird 36" in briefing

    def test_birthday_tomorrow(self, store: ContactStore) -> None:
        store.add(USER, "Max", birthday="1985-06-16")
        scheduler = _make_scheduler(store)
        briefing = scheduler.build_briefing(now=_WEDNESDAY)
        assert "Geburtstage morgen" in briefing
        assert "Max" in briefing
        assert "wird 41" in briefing

    def test_birthday_this_week(self, store: ContactStore) -> None:
        store.add(USER, "Anna", birthday="1995-06-19")
        scheduler = _make_scheduler(store)
        briefing = scheduler.build_briefing(now=_WEDNESDAY)
        assert "Geburtstage diese Woche" in briefing
        assert "Anna" in briefing
        assert "in 4 Tagen" in briefing

    def test_birthday_with_group(self, store: ContactStore) -> None:
        store.add(USER, "Lisa", birthday="1990-06-15", categories="Familie, Freunde")
        scheduler = _make_scheduler(store)
        briefing = scheduler.build_briefing(now=_WEDNESDAY)
        assert "[Familie]" in briefing

    def test_birthday_unknown_year(self, store: ContactStore) -> None:
        store.add(USER, "Lisa", birthday="0000-06-15")
        scheduler = _make_scheduler(store)
        briefing = scheduler.build_briefing(now=_WEDNESDAY)
        assert "Lisa" in briefing
        assert "wird" not in briefing

    def test_no_birthdays(self, store: ContactStore) -> None:
        store.add(USER, "Max", birthday="1990-12-24")
        scheduler = _make_scheduler(store)
        briefing = scheduler.build_briefing(now=_WEDNESDAY)
        assert "Geburtstag" not in briefing


class TestAnniversarySection:
    def test_anniversary_today(self, store: ContactStore) -> None:
        store.add(USER, "Partner", anniversary="2015-06-15")
        scheduler = _make_scheduler(store)
        briefing = scheduler.build_briefing(now=_WEDNESDAY)
        assert "Jahrestage" in briefing
        assert "Partner" in briefing
        assert "11. Jahrestag" in briefing
        assert "heute" in briefing

    def test_anniversary_in_3_days(self, store: ContactStore) -> None:
        store.add(USER, "Eltern", anniversary="2000-06-18")
        scheduler = _make_scheduler(store)
        briefing = scheduler.build_briefing(now=_WEDNESDAY)
        assert "Jahrestage" in briefing
        assert "Eltern" in briefing
        assert "in 3 Tagen" in briefing

    def test_no_anniversaries(self, store: ContactStore) -> None:
        store.add(USER, "Max")
        scheduler = _make_scheduler(store)
        briefing = scheduler.build_briefing(now=_WEDNESDAY)
        assert "Jahrestage" not in briefing


class TestAutoSync:
    def test_auto_sync_called_before_briefing(
        self,
        store: ContactStore,
    ) -> None:
        from elder_berry.tools.carddav_sync import SyncResult

        mock_sync = MagicMock()
        mock_sync.sync.return_value = SyncResult()
        scheduler = _make_scheduler(store, carddav_sync=mock_sync)
        scheduler.build_briefing(now=_WEDNESDAY)
        mock_sync.sync.assert_called_once_with(store, USER)

    def test_auto_sync_failure_does_not_crash(
        self,
        store: ContactStore,
    ) -> None:
        mock_sync = MagicMock()
        mock_sync.sync.side_effect = Exception("Connection refused")
        scheduler = _make_scheduler(store, carddav_sync=mock_sync)
        # Darf nicht crashen
        briefing = scheduler.build_briefing(now=_WEDNESDAY)
        # Kein Briefing-Inhalt (keine Daten), aber kein Crash
        assert isinstance(briefing, str)

    def test_no_sync_without_carddav(self, store: ContactStore) -> None:
        scheduler = _make_scheduler(store, carddav_sync=None)
        # Darf nicht crashen
        briefing = scheduler.build_briefing(now=_WEDNESDAY)
        assert isinstance(briefing, str)
