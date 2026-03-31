"""Tests für ContactStore (Phase 29 + Phase 38 Vollintegration)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from elder_berry.tools.contact_store import Contact, ContactStore

USER = "@test:matrix.org"
USER_B = "@other:matrix.org"


def _emails_json(*pairs: tuple[str, str]) -> str:
    """Hilfsfunktion: Erstellt emails-JSON."""
    return json.dumps([{"type": t, "email": e} for t, e in pairs])


def _phones_json(*pairs: tuple[str, str]) -> str:
    """Hilfsfunktion: Erstellt phones-JSON."""
    return json.dumps([{"type": t, "number": n} for t, n in pairs])


@pytest.fixture()
def store(tmp_path: Path) -> ContactStore:
    db = tmp_path / "contacts.db"
    s = ContactStore(db_path=db)
    yield s
    s.close()


class TestAddAndFind:
    def test_add_and_find_by_name(self, store: ContactStore) -> None:
        c = store.add(USER, "Herr Müller", role="Vermieter")
        assert c.name == "Herr Müller"
        found = store.find_by_name(USER, "herr müller")
        assert found is not None
        assert found.id == c.id

    def test_add_and_find_by_email(self, store: ContactStore) -> None:
        emails = _emails_json(("home", "lisa@gmail.com"))
        c = store.add(USER, "Lisa", emails=emails)
        found = store.find_by_email(USER, "lisa@gmail.com")
        assert found is not None
        assert found.id == c.id

    def test_find_by_email_case_insensitive(self, store: ContactStore) -> None:
        emails = _emails_json(("home", "max@x.de"))
        store.add(USER, "Max", emails=emails)
        found = store.find_by_email(USER, "MAX@X.DE")
        assert found is not None
        assert found.name == "Max"

    def test_upsert_by_name(self, store: ContactStore) -> None:
        c1 = store.add(USER, "Herr Müller", role="Vermieter")
        emails = _emails_json(("home", "neu@x.de"))
        c2 = store.add(USER, "Herr Müller", emails=emails)
        assert c2.id == c1.id
        assert c2.email == "neu@x.de"
        assert c2.role == "Vermieter"

    def test_upsert_keeps_existing_fields(self, store: ContactStore) -> None:
        emails_old = _emails_json(("home", "a@b.de"))
        store.add(USER, "Lisa", emails=emails_old, role="Schwester",
                  formality="locker", notes="mag Katzen")
        emails_new = _emails_json(("home", "new@b.de"))
        updated = store.add(USER, "Lisa", emails=emails_new)
        assert updated.email == "new@b.de"
        assert updated.role == "Schwester"
        assert updated.formality == "locker"
        assert updated.notes == "mag Katzen"

    def test_update_by_id(self, store: ContactStore) -> None:
        c = store.add(USER, "Dr. Weber", role="Zahnarzt")
        emails = _emails_json(("work", "dr@weber.de"))
        updated = store.update(c.id, emails=emails)
        assert updated is not None
        assert updated.email == "dr@weber.de"
        assert updated.role == "Zahnarzt"

    def test_update_nonexistent(self, store: ContactStore) -> None:
        assert store.update(9999, name="Ghost") is None


class TestSearch:
    def test_search_fts(self, store: ContactStore) -> None:
        store.add(USER, "Herr Müller", role="Vermieter")
        store.add(USER, "Lisa", role="Schwester")
        results = store.search(USER, "Vermieter")
        assert len(results) == 1
        assert results[0].name == "Herr Müller"

    def test_search_no_results(self, store: ContactStore) -> None:
        store.add(USER, "Lisa", role="Schwester")
        assert store.search(USER, "Zahnarzt") == []


class TestListAll:
    def test_list_all(self, store: ContactStore) -> None:
        store.add(USER, "B-Name")
        store.add(USER, "A-Name")
        contacts = store.list_all(USER)
        assert len(contacts) == 2
        assert contacts[0].name == "A-Name"

    def test_list_all_empty(self, store: ContactStore) -> None:
        assert store.list_all(USER) == []


class TestDelete:
    def test_delete_by_id(self, store: ContactStore) -> None:
        c = store.add(USER, "Lisa")
        assert store.delete(c.id) is True
        assert store.get_by_id(c.id) is None

    def test_delete_by_id_not_found(self, store: ContactStore) -> None:
        assert store.delete(9999) is False

    def test_delete_by_name(self, store: ContactStore) -> None:
        store.add(USER, "Herr Müller")
        assert store.delete_by_name(USER, "Herr Müller") is True
        assert store.find_by_name(USER, "Herr Müller") is None

    def test_delete_by_name_case_insensitive(self, store: ContactStore) -> None:
        store.add(USER, "Herr Müller")
        assert store.delete_by_name(USER, "herr müller") is True

    def test_delete_all(self, store: ContactStore) -> None:
        store.add(USER, "Lisa")
        store.add(USER, "Max")
        store.add(USER_B, "Bob")
        assert store.delete_all(USER) == 2
        assert store.list_all(USER) == []
        assert len(store.list_all(USER_B)) == 1


class TestDefaults:
    def test_formality_default(self, store: ContactStore) -> None:
        c = store.add(USER, "Max")
        assert c.formality == "förmlich"

    def test_unique_name_upsert(self, store: ContactStore) -> None:
        store.add(USER, "Max", role="Freund")
        store.add(USER, "Max", role="Kollege")
        assert len(store.list_all(USER)) == 1


class TestFormat:
    def test_format_short(self, store: ContactStore) -> None:
        emails = _emails_json(("work", "x@y.de"))
        c = store.add(USER, "Herr Müller", role="Vermieter",
                      emails=emails, formality="förmlich")
        s = c.format_short()
        assert "Herr Müller" in s
        assert "Vermieter" in s
        assert "x@y.de" in s

    def test_format_for_llm(self, store: ContactStore) -> None:
        c = store.add(USER, "Lisa", role="Schwester",
                      formality="locker", notes="mag Katzen")
        llm = c.format_for_llm()
        assert "Kontakt: Lisa" in llm
        assert "Beziehung: Schwester" in llm
        assert "Du" in llm
        assert "mag Katzen" in llm


class TestMultiUser:
    def test_multi_user_isolation(self, store: ContactStore) -> None:
        store.add(USER, "Alice")
        store.add(USER_B, "Bob")
        assert len(store.list_all(USER)) == 1
        assert len(store.list_all(USER_B)) == 1
        assert store.find_by_name(USER, "Bob") is None


class TestPhones:
    def test_add_with_single_phone(self, store: ContactStore) -> None:
        phones = _phones_json(("cell", "+49 170 1234567"))
        c = store.add(USER, "Lisa", phones=phones)
        assert c.phone == "+49 170 1234567"

    def test_multiple_phones(self, store: ContactStore) -> None:
        phones = json.dumps([
            {"type": "cell", "number": "+49 170 1234567"},
            {"type": "home", "number": "+49 30 9876543"},
        ])
        c = store.add(USER, "Lisa", phones=phones)
        assert c.phone == "+49 170 1234567"
        items = c.get_phones_list()
        assert len(items) == 2
        assert items[1]["number"] == "+49 30 9876543"

    def test_update_phones(self, store: ContactStore) -> None:
        c = store.add(USER, "Lisa")
        assert c.phone == ""
        phones = _phones_json(("cell", "+49 30 9876543"))
        updated = store.update(c.id, phones=phones)
        assert updated.phone == "+49 30 9876543"

    def test_phone_in_format_detail(self, store: ContactStore) -> None:
        phones = _phones_json(("cell", "+49 170 1234567"))
        c = store.add(USER, "Lisa", phones=phones)
        detail = c.format_detail()
        assert "Telefon: +49 170 1234567" in detail

    def test_no_phone_not_in_detail(self, store: ContactStore) -> None:
        c = store.add(USER, "Lisa")
        detail = c.format_detail()
        assert "Telefon:" not in detail

    def test_phone_in_format_for_llm(self, store: ContactStore) -> None:
        phones = _phones_json(("cell", "+49 170 1234567"))
        c = store.add(USER, "Lisa", phones=phones)
        llm = c.format_for_llm()
        assert "Telefon: +49 170 1234567" in llm


class TestMultipleEmails:
    def test_multiple_emails(self, store: ContactStore) -> None:
        emails = json.dumps([
            {"type": "work", "email": "work@x.de"},
            {"type": "home", "email": "home@x.de"},
        ])
        c = store.add(USER, "Max", emails=emails)
        assert c.email == "work@x.de"
        items = c.get_emails_list()
        assert len(items) == 2
        assert items[1]["email"] == "home@x.de"

    def test_email_property_empty(self, store: ContactStore) -> None:
        c = store.add(USER, "Max")
        assert c.email == ""


class TestFormatDetail:
    def test_format_detail_full(self, store: ContactStore) -> None:
        emails = _emails_json(("home", "lisa@x.de"))
        c = store.add(USER, "Lisa", emails=emails, role="Freundin",
                      formality="locker", notes="wichtige Person",
                      birthday="1990-06-15")
        detail = c.format_detail()
        assert "📇 #" in detail
        assert "Lisa" in detail
        assert "Rolle: Freundin" in detail
        assert "Email: lisa@x.de" in detail
        assert "Anrede: locker" in detail
        assert "Geburtstag: 1990-06-15" in detail
        assert "📝 wichtige Person" in detail

    def test_format_detail_minimal(self, store: ContactStore) -> None:
        c = store.add(USER, "Max")
        detail = c.format_detail()
        assert "Max" in detail
        assert "Anrede: förmlich" in detail
        assert "Rolle:" not in detail
        assert "Email:" not in detail
        assert "📝" not in detail

    def test_format_detail_birthday_unknown_year(self, store: ContactStore) -> None:
        c = store.add(USER, "Anna", birthday="0000-06-15")
        detail = c.format_detail()
        assert "Geburtstag: 06-15" in detail
        assert "0000" not in detail

    def test_format_detail_multiple_phones(self, store: ContactStore) -> None:
        phones = json.dumps([
            {"type": "cell", "number": "+49 170 111"},
            {"type": "home", "number": "+49 30 222"},
        ])
        c = store.add(USER, "Max", phones=phones)
        detail = c.format_detail()
        assert "Mobil" in detail
        assert "Privat" in detail

    def test_format_detail_address(self, store: ContactStore) -> None:
        c = store.add(USER, "Max", address="Musterstr. 42, 10115 Berlin")
        detail = c.format_detail()
        assert "Adresse: Musterstr. 42, 10115 Berlin" in detail

    def test_format_detail_organization(self, store: ContactStore) -> None:
        c = store.add(USER, "Max", organization="Acme Corp", title="CTO")
        detail = c.format_detail()
        assert "Organisation: Acme Corp" in detail
        assert "Titel: CTO" in detail


class TestNewFields:
    """Tests für die neuen Felder aus Phase 38."""

    def test_add_with_all_new_fields(self, store: ContactStore) -> None:
        c = store.add(
            USER, "Max Mustermann",
            address="Musterstr. 42, 10115 Berlin",
            organization="Acme Corp",
            title="CTO",
            categories="Arbeit, Freunde",
            nickname="Maxi",
            anniversary="2015-06-20",
            url="https://max.example.com",
        )
        assert c.address == "Musterstr. 42, 10115 Berlin"
        assert c.organization == "Acme Corp"
        assert c.title == "CTO"
        assert c.categories == "Arbeit, Freunde"
        assert c.nickname == "Maxi"
        assert c.anniversary == "2015-06-20"
        assert c.url == "https://max.example.com"

    def test_get_categories_list(self, store: ContactStore) -> None:
        c = store.add(USER, "Lisa", categories="Familie, Freunde, Ärzte")
        cats = c.get_categories_list()
        assert cats == ["Familie", "Freunde", "Ärzte"]

    def test_get_categories_list_empty(self, store: ContactStore) -> None:
        c = store.add(USER, "Max")
        assert c.get_categories_list() == []

    def test_vcard_uid(self, store: ContactStore) -> None:
        c = store.add(USER, "Lisa", vcard_uid="abc-123-def")
        assert c.vcard_uid == "abc-123-def"
        found = store.find_by_vcard_uid(USER, "abc-123-def")
        assert found is not None
        assert found.id == c.id

    def test_find_by_vcard_uid_not_found(self, store: ContactStore) -> None:
        assert store.find_by_vcard_uid(USER, "nonexistent") is None

    def test_find_by_vcard_uid_empty(self, store: ContactStore) -> None:
        assert store.find_by_vcard_uid(USER, "") is None

    def test_add_or_update_by_vcard_uid_new(self, store: ContactStore) -> None:
        c = store.add_or_update_by_vcard_uid(
            USER, vcard_uid="uid-1", name="Lisa", role="Freundin",
        )
        assert c.name == "Lisa"
        assert c.vcard_uid == "uid-1"

    def test_add_or_update_by_vcard_uid_existing(self, store: ContactStore) -> None:
        store.add(USER, "Lisa", vcard_uid="uid-1")
        updated = store.add_or_update_by_vcard_uid(
            USER, vcard_uid="uid-1", name="Lisa", role="Schwester",
        )
        assert updated.role == "Schwester"
        assert len(store.list_all(USER)) == 1

    def test_add_or_update_by_vcard_uid_name_fallback(
        self, store: ContactStore,
    ) -> None:
        store.add(USER, "Lisa")
        updated = store.add_or_update_by_vcard_uid(
            USER, vcard_uid="uid-new", name="Lisa", role="Freundin",
        )
        assert updated.role == "Freundin"
        assert updated.vcard_uid == "uid-new"
        assert len(store.list_all(USER)) == 1

    def test_find_by_category(self, store: ContactStore) -> None:
        store.add(USER, "Lisa", categories="Familie, Freunde")
        store.add(USER, "Max", categories="Arbeit")
        store.add(USER, "Anna", categories="Familie")
        results = store.find_by_category(USER, "Familie")
        names = [c.name for c in results]
        assert "Lisa" in names
        assert "Anna" in names
        assert "Max" not in names

    def test_find_by_category_case_insensitive(
        self, store: ContactStore,
    ) -> None:
        store.add(USER, "Lisa", categories="Familie")
        results = store.find_by_category(USER, "familie")
        assert len(results) == 1

    def test_format_for_llm_new_fields(self, store: ContactStore) -> None:
        phones = json.dumps([
            {"type": "cell", "number": "+49 170 111"},
            {"type": "home", "number": "+49 30 222"},
        ])
        emails = json.dumps([
            {"type": "work", "email": "max@acme.de"},
            {"type": "home", "email": "max@privat.de"},
        ])
        c = store.add(
            USER, "Max", phones=phones, emails=emails,
            address="Musterstr. 42", organization="Acme Corp",
            title="CTO", categories="Arbeit", nickname="Maxi",
        )
        llm = c.format_for_llm()
        assert "Firma: Acme Corp" in llm
        assert "Position: CTO" in llm
        assert "Adresse: Musterstr. 42" in llm
        assert "Gruppen: Arbeit" in llm
        assert "Spitzname: Maxi" in llm
        assert "Mobil" in llm


class TestUpcomingBirthdays:
    def test_upcoming_birthdays_today(self, store: ContactStore) -> None:
        today = date(2026, 6, 15)
        store.add(USER, "Lisa", birthday="1990-06-15")
        results = store.get_upcoming_birthdays(USER, days=7, today=today)
        assert len(results) == 1
        assert results[0].name == "Lisa"

    def test_upcoming_birthdays_in_3_days(self, store: ContactStore) -> None:
        today = date(2026, 6, 12)
        store.add(USER, "Lisa", birthday="1990-06-15")
        results = store.get_upcoming_birthdays(USER, days=7, today=today)
        assert len(results) == 1

    def test_upcoming_birthdays_outside_range(
        self, store: ContactStore,
    ) -> None:
        today = date(2026, 6, 1)
        store.add(USER, "Lisa", birthday="1990-06-15")
        results = store.get_upcoming_birthdays(USER, days=7, today=today)
        assert len(results) == 0


class TestUpcomingAnniversaries:
    def test_upcoming_anniversary_today(self, store: ContactStore) -> None:
        today = date(2026, 6, 20)
        store.add(USER, "Max", anniversary="2015-06-20")
        results = store.get_upcoming_anniversaries(USER, days=7, today=today)
        assert len(results) == 1

    def test_upcoming_anniversary_in_range(self, store: ContactStore) -> None:
        today = date(2026, 6, 15)
        store.add(USER, "Max", anniversary="2015-06-20")
        results = store.get_upcoming_anniversaries(USER, days=7, today=today)
        assert len(results) == 1

    def test_upcoming_anniversary_out_of_range(
        self, store: ContactStore,
    ) -> None:
        today = date(2026, 6, 1)
        store.add(USER, "Max", anniversary="2015-06-20")
        results = store.get_upcoming_anniversaries(USER, days=7, today=today)
        assert len(results) == 0


class TestV1Migration:
    """Tests für die Migration von v1 (email/phone) → v2 (emails/phones)."""

    def test_v1_db_migrates_on_open(self, tmp_path: Path) -> None:
        """Bestehende v1-DB mit email/phone Spalten wird korrekt migriert."""
        import sqlite3

        db_path = tmp_path / "v1.db"
        # v1-Schema manuell erstellen
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT '',
                formality TEXT NOT NULL DEFAULT 'förmlich',
                phone TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                birthday TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.execute(
            "INSERT INTO contacts (user_id, name, email, phone, role, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (USER, "Lisa", "lisa@x.de", "+49 170 111", "Freundin",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
        conn.close()

        # ContactStore öffnet v1-DB → Migration muss laufen
        store = ContactStore(db_path=db_path)
        lisa = store.find_by_name(USER, "Lisa")
        assert lisa is not None
        assert lisa.role == "Freundin"
        # email/phone müssen als JSON in emails/phones konvertiert sein
        assert "lisa@x.de" in lisa.emails
        assert "+49 170 111" in lisa.phones
        # Convenience-Properties
        assert lisa.email == "lisa@x.de"
        assert lisa.phone == "+49 170 111"
        # FTS muss funktionieren
        results = store.search(USER, "Lisa")
        assert len(results) == 1
        store.close()


class TestClose:
    def test_close(self, tmp_path: Path) -> None:
        s = ContactStore(db_path=tmp_path / "c.db")
        s.add(USER, "Test")
        s.close()
        s.close()
