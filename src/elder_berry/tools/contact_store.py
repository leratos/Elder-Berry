"""ContactStore – Persistenter Kontaktspeicher (SQLite + FTS5).

Speichert Kontakte mit allen Nextcloud-vCard-Feldern plus Elder-Berry-eigenen
Metadaten (role, formality, notes). Unterstützt mehrere Telefonnummern und
Email-Adressen als JSON-Arrays.

Verwendung:
    store = ContactStore()
    store.add("@user:matrix.org", name="Herr Müller",
              emails='[{"type":"work","email":"info@mueller-immo.de"}]',
              role="Vermieter", formality="förmlich")
    contact = store.find_by_email("@user:matrix.org", "info@mueller-immo.de")
    results = store.search("@user:matrix.org", "Müller")
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".elder-berry" / "contacts.db"

# Mapping: vCard TEL TYPE → deutscher Label
_PHONE_TYPE_LABELS: dict[str, str] = {
    "cell": "Mobil", "mobile": "Mobil",
    "home": "Privat", "work": "Arbeit",
    "voice": "Telefon", "fax": "Fax",
    "pager": "Pager",
}

# Mapping: vCard EMAIL TYPE → deutscher Label
_EMAIL_TYPE_LABELS: dict[str, str] = {
    "home": "Privat", "work": "Arbeit",
    "internet": "Email",
}


@dataclass(frozen=True)
class Contact:
    """Ein Kontakt mit allen Nextcloud- und Elder-Berry-Feldern."""

    id: int
    user_id: str
    name: str
    """Anzeigename (z.B. 'Herr Müller', 'Lisa', 'Dr. Weber')."""
    emails: str
    """JSON-Array: [{"type":"work","email":"x@y.de"}, ...]. Leer = '[]'."""
    phones: str
    """JSON-Array: [{"type":"cell","number":"+49..."}, ...]. Leer = '[]'."""
    role: str
    """Beziehung/Rolle (z.B. 'Vermieter', 'Schwester', 'Zahnarzt')."""
    formality: str
    """Anrede-Stil: 'förmlich' (Sie) oder 'locker' (Du). Default: 'förmlich'."""
    notes: str
    """Freie Notizen (z.B. 'hat Hund namens Rex')."""
    birthday: str
    """Geburtstag im Format 'YYYY-MM-DD' oder leer. Jahr=0000 wenn unbekannt."""
    address: str
    """Freitext-Adresse (aus ADR zusammengesetzt)."""
    organization: str
    """Firma / Organisation."""
    title: str
    """Jobtitel."""
    categories: str
    """Komma-separierte Gruppen ('Familie, Arbeit')."""
    nickname: str
    """Spitzname."""
    anniversary: str
    """Jahrestag im Format 'YYYY-MM-DD' oder leer."""
    url: str
    """Website."""
    vcard_uid: str
    """Original-UID aus der Nextcloud-vCard (für Sync-Matching)."""
    created_at: datetime
    updated_at: datetime

    # -- Convenience Properties für Rückwärtskompatibilität --

    @property
    def email(self) -> str:
        """Primäre Email-Adresse (erste aus emails-JSON)."""
        try:
            items = json.loads(self.emails) if self.emails else []
            if items and isinstance(items, list):
                return items[0].get("email", "")
        except (json.JSONDecodeError, AttributeError, IndexError):
            pass
        return ""

    @property
    def phone(self) -> str:
        """Primäre Telefonnummer (erste aus phones-JSON)."""
        try:
            items = json.loads(self.phones) if self.phones else []
            if items and isinstance(items, list):
                return items[0].get("number", "")
        except (json.JSONDecodeError, AttributeError, IndexError):
            pass
        return ""

    def get_phones_list(self) -> list[dict[str, str]]:
        """Parsed phones-JSON als Liste von Dicts."""
        try:
            items = json.loads(self.phones) if self.phones else []
            return items if isinstance(items, list) else []
        except (json.JSONDecodeError, AttributeError):
            return []

    def get_emails_list(self) -> list[dict[str, str]]:
        """Parsed emails-JSON als Liste von Dicts."""
        try:
            items = json.loads(self.emails) if self.emails else []
            return items if isinstance(items, list) else []
        except (json.JSONDecodeError, AttributeError):
            return []

    def get_categories_list(self) -> list[str]:
        """Parsed categories als Liste von Strings."""
        if not self.categories:
            return []
        return [c.strip() for c in self.categories.split(",") if c.strip()]

    def format_short(self) -> str:
        """Einzeilige Darstellung."""
        parts = [f"#{self.id} {self.name}"]
        if self.role:
            parts.append(f"– {self.role}")
        parts.append(f"({self.formality})")
        email = self.email
        if email:
            parts.append(f"– {email}")
        return " ".join(parts)

    def format_detail(self) -> str:
        """Mehrzeilige Detail-Darstellung."""
        lines = [f"📇 #{self.id} {self.name}"]
        if self.nickname:
            lines.append(f"  Spitzname: {self.nickname}")
        if self.role:
            lines.append(f"  Rolle: {self.role}")
        # Emails
        email_items = self.get_emails_list()
        if email_items:
            if len(email_items) == 1:
                lines.append(f"  Email: {email_items[0].get('email', '')}")
            else:
                for ei in email_items:
                    label = _EMAIL_TYPE_LABELS.get(
                        ei.get("type", ""), ei.get("type", ""),
                    )
                    lines.append(f"  Email ({label}): {ei.get('email', '')}")
        # Phones
        phone_items = self.get_phones_list()
        if phone_items:
            if len(phone_items) == 1:
                lines.append(f"  Telefon: {phone_items[0].get('number', '')}")
            else:
                for pi in phone_items:
                    label = _PHONE_TYPE_LABELS.get(
                        pi.get("type", ""), pi.get("type", ""),
                    )
                    lines.append(f"  Telefon ({label}): {pi.get('number', '')}")
        lines.append(f"  Anrede: {self.formality}")
        if self.address:
            lines.append(f"  Adresse: {self.address}")
        if self.organization:
            lines.append(f"  Organisation: {self.organization}")
        if self.title:
            lines.append(f"  Titel: {self.title}")
        if self.birthday:
            if self.birthday.startswith("0000-"):
                lines.append(f"  Geburtstag: {self.birthday[5:]}")
            else:
                lines.append(f"  Geburtstag: {self.birthday}")
        if self.anniversary:
            lines.append(f"  Jahrestag: {self.anniversary}")
        if self.categories:
            lines.append(f"  Gruppen: {self.categories}")
        if self.url:
            lines.append(f"  Website: {self.url}")
        if self.notes:
            lines.append(f"  📝 {self.notes}")
        return "\n".join(lines)

    def format_for_llm(self) -> str:
        """Kontext-String für LLM System-Prompts (Email-Draft etc.)."""
        lines = [f"Kontakt: {self.name}"]
        if self.nickname:
            lines.append(f"Spitzname: {self.nickname}")
        if self.role:
            lines.append(f"Beziehung: {self.role}")
        hint = "Sie" if self.formality == "förmlich" else "Du"
        lines.append(f"Anrede: {self.formality} ({hint})")
        # Phones
        phone_items = self.get_phones_list()
        if phone_items:
            if len(phone_items) == 1:
                lines.append(f"Telefon: {phone_items[0].get('number', '')}")
            else:
                parts = []
                for pi in phone_items:
                    label = _PHONE_TYPE_LABELS.get(
                        pi.get("type", ""), pi.get("type", ""),
                    )
                    parts.append(f"{pi.get('number', '')} ({label})")
                lines.append(f"Telefon: {', '.join(parts)}")
        # Emails
        email_items = self.get_emails_list()
        if email_items:
            if len(email_items) == 1:
                lines.append(f"Email: {email_items[0].get('email', '')}")
            else:
                parts = []
                for ei in email_items:
                    label = _EMAIL_TYPE_LABELS.get(
                        ei.get("type", ""), ei.get("type", ""),
                    )
                    parts.append(f"{ei.get('email', '')} ({label})")
                lines.append(f"Email: {', '.join(parts)}")
        if self.address:
            lines.append(f"Adresse: {self.address}")
        if self.organization:
            lines.append(f"Firma: {self.organization}")
        if self.title:
            lines.append(f"Position: {self.title}")
        if self.birthday:
            lines.append(f"Geburtstag: {self.birthday}")
        if self.anniversary:
            lines.append(f"Jahrestag: {self.anniversary}")
        if self.categories:
            lines.append(f"Gruppen: {self.categories}")
        if self.url:
            lines.append(f"Website: {self.url}")
        if self.notes:
            lines.append(f"Notizen: {self.notes}")
        return "\n".join(lines)


class ContactStore:
    """SQLite-basierter Kontaktspeicher mit FTS5-Volltextsuche.

    Thread-safe: check_same_thread=False.
    WAL-Modus für bessere Concurrent-Read-Performance.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path), check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        # Schritt 1: Tabelle erstellen (nur für neue DBs)
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS contacts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                name         TEXT NOT NULL,
                emails       TEXT NOT NULL DEFAULT '[]',
                phones       TEXT NOT NULL DEFAULT '[]',
                role         TEXT NOT NULL DEFAULT '',
                formality    TEXT NOT NULL DEFAULT 'förmlich',
                notes        TEXT NOT NULL DEFAULT '',
                birthday     TEXT NOT NULL DEFAULT '',
                address      TEXT NOT NULL DEFAULT '',
                organization TEXT NOT NULL DEFAULT '',
                title        TEXT NOT NULL DEFAULT '',
                categories   TEXT NOT NULL DEFAULT '',
                nickname     TEXT NOT NULL DEFAULT '',
                anniversary  TEXT NOT NULL DEFAULT '',
                url          TEXT NOT NULL DEFAULT '',
                vcard_uid    TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            );
        """)
        self._conn.commit()

        # Schritt 2: Migration (v1 email/phone → v2 emails/phones)
        # MUSS vor Indizes/FTS laufen, da die neuen Spalten referenziert werden
        self._migrate_from_v1()

        # Schritt 3: Indizes (IF NOT EXISTS = safe für neue + migrierte DBs)
        self._conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_contacts_user
                ON contacts(user_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_user_name
                ON contacts(user_id, name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_contacts_vcard_uid
                ON contacts(vcard_uid) WHERE vcard_uid != '';
        """)
        self._conn.commit()

        # Schritt 4: FTS + Trigger (immer droppen + neu erstellen,
        # damit sie zum aktuellen Schema passen)
        self._rebuild_fts()

    def _rebuild_fts(self) -> None:
        """Erstellt FTS5-Tabelle und Trigger (immer frisch).

        Wird bei jedem Start aufgerufen, damit Trigger/FTS immer zum
        aktuellen Schema passen – auch nach Migrationen.
        """
        self._conn.executescript("""
            DROP TRIGGER IF EXISTS contacts_ai;
            DROP TRIGGER IF EXISTS contacts_au;
            DROP TRIGGER IF EXISTS contacts_ad;
            DROP TABLE IF EXISTS contacts_fts;

            CREATE VIRTUAL TABLE contacts_fts USING fts5(
                name, role, notes, emails, phones, categories,
                organization, nickname, address,
                content=contacts, content_rowid=id
            );
            CREATE TRIGGER contacts_ai AFTER INSERT ON contacts
            BEGIN
                INSERT INTO contacts_fts(rowid, name, role, notes, emails,
                    phones, categories, organization, nickname, address)
                VALUES (new.id, new.name, new.role, new.notes, new.emails,
                    new.phones, new.categories, new.organization,
                    new.nickname, new.address);
            END;
            CREATE TRIGGER contacts_au AFTER UPDATE ON contacts
            BEGIN
                INSERT INTO contacts_fts(contacts_fts, rowid, name, role,
                    notes, emails, phones, categories, organization,
                    nickname, address)
                VALUES('delete', old.id, old.name, old.role, old.notes,
                    old.emails, old.phones, old.categories,
                    old.organization, old.nickname, old.address);
                INSERT INTO contacts_fts(rowid, name, role, notes, emails,
                    phones, categories, organization, nickname, address)
                VALUES (new.id, new.name, new.role, new.notes, new.emails,
                    new.phones, new.categories, new.organization,
                    new.nickname, new.address);
            END;
            CREATE TRIGGER contacts_ad AFTER DELETE ON contacts
            BEGIN
                INSERT INTO contacts_fts(contacts_fts, rowid, name, role,
                    notes, emails, phones, categories, organization,
                    nickname, address)
                VALUES('delete', old.id, old.name, old.role, old.notes,
                    old.emails, old.phones, old.categories,
                    old.organization, old.nickname, old.address);
            END;
        """)
        # FTS mit bestehenden Daten befüllen (rebuild)
        try:
            self._conn.execute(
                "INSERT INTO contacts_fts(contacts_fts) VALUES('rebuild')",
            )
        except sqlite3.OperationalError:
            pass
        self._conn.commit()

    def _migrate_from_v1(self) -> None:
        """Migriert alte Datenbank (v1: email/phone Spalten) zum neuen Schema.

        Erkennt v1 am Vorhandensein einer 'email'-Spalte (statt 'emails').
        SQLite kann keine Spalten droppen, daher: Tabelle kopieren → neu
        erstellen → Daten rüber → alte droppen.
        """
        try:
            cursor = self._conn.execute("PRAGMA table_info(contacts)")
            columns = {row[1] for row in cursor.fetchall()}
        except sqlite3.OperationalError:
            return

        # Kein v1-Schema → nichts zu tun
        if "email" not in columns or "emails" in columns:
            return

        logger.info("Migration v1→v2: Tabelle wird neu aufgebaut")
        try:
            # Alte FTS/Trigger droppen (referenzieren alte Spalten)
            self._conn.executescript("""
                DROP TRIGGER IF EXISTS contacts_ai;
                DROP TRIGGER IF EXISTS contacts_au;
                DROP TRIGGER IF EXISTS contacts_ad;
                DROP TABLE IF EXISTS contacts_fts;
            """)

            # Alte Tabelle umbenennen
            self._conn.execute("ALTER TABLE contacts RENAME TO contacts_v1")

            # Neue Tabelle erstellen (v2 Schema)
            self._conn.executescript("""
                CREATE TABLE contacts (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      TEXT NOT NULL,
                    name         TEXT NOT NULL,
                    emails       TEXT NOT NULL DEFAULT '[]',
                    phones       TEXT NOT NULL DEFAULT '[]',
                    role         TEXT NOT NULL DEFAULT '',
                    formality    TEXT NOT NULL DEFAULT 'förmlich',
                    notes        TEXT NOT NULL DEFAULT '',
                    birthday     TEXT NOT NULL DEFAULT '',
                    address      TEXT NOT NULL DEFAULT '',
                    organization TEXT NOT NULL DEFAULT '',
                    title        TEXT NOT NULL DEFAULT '',
                    categories   TEXT NOT NULL DEFAULT '',
                    nickname     TEXT NOT NULL DEFAULT '',
                    anniversary  TEXT NOT NULL DEFAULT '',
                    url          TEXT NOT NULL DEFAULT '',
                    vcard_uid    TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL
                );
            """)

            # Daten konvertieren und kopieren
            rows = self._conn.execute(
                "SELECT id, user_id, name, email, role, formality, phone, "
                "notes, birthday, created_at, updated_at FROM contacts_v1",
            ).fetchall()
            for (id_, user_id, name, old_email, role, formality, old_phone,
                 notes, birthday, created_at, updated_at) in rows:
                emails_json = "[]"
                if old_email:
                    emails_json = json.dumps(
                        [{"type": "home", "email": old_email}],
                    )
                phones_json = "[]"
                if old_phone:
                    phones_json = json.dumps(
                        [{"type": "cell", "number": old_phone}],
                    )
                self._conn.execute(
                    "INSERT INTO contacts (id, user_id, name, emails, phones, "
                    "role, formality, notes, birthday, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (id_, user_id, name, emails_json, phones_json,
                     role, formality or "förmlich", notes, birthday,
                     created_at, updated_at),
                )

            # Alte Tabelle entfernen
            self._conn.execute("DROP TABLE contacts_v1")
            self._conn.commit()
            logger.info(
                "Migration v1→v2 abgeschlossen: %d Kontakte konvertiert",
                len(rows),
            )
        except sqlite3.OperationalError as e:
            logger.error("Migration v1→v2 fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    _ALL_FIELDS = (
        "name", "emails", "phones", "role", "formality", "notes",
        "birthday", "address", "organization", "title", "categories",
        "nickname", "anniversary", "url", "vcard_uid",
    )

    def add(self, user_id: str, name: str, **kwargs: str) -> Contact:
        """Kontakt hinzufügen oder aktualisieren (Upsert per Name).

        Wenn ein Kontakt mit gleichem Namen (case-insensitive) existiert,
        werden nur non-empty Felder aktualisiert.
        Bei neuem Kontakt wird formality auf 'förmlich' gesetzt wenn leer.

        Akzeptiert alle Contact-Felder als kwargs:
            emails, phones, role, formality, notes, birthday,
            address, organization, title, categories, nickname,
            anniversary, url, vcard_uid
        """
        now = datetime.now(timezone.utc).isoformat()
        existing = self.find_by_name(user_id, name)
        if existing:
            return self._upsert_existing(existing, **kwargs)

        formality = kwargs.get("formality", "") or "förmlich"
        values = {f: kwargs.get(f, "") for f in self._ALL_FIELDS}
        values["formality"] = formality
        values["name"] = name
        # Default für JSON-Felder
        if not values["emails"]:
            values["emails"] = "[]"
        if not values["phones"]:
            values["phones"] = "[]"

        cols = ["user_id"] + list(values.keys()) + ["created_at", "updated_at"]
        placeholders = ", ".join(["?"] * len(cols))
        col_str = ", ".join(cols)
        vals = [user_id] + [values[k] for k in values] + [now, now]

        cursor = self._conn.execute(
            f"INSERT INTO contacts ({col_str}) VALUES ({placeholders})",
            vals,
        )
        self._conn.commit()
        return self._get_by_rowid(cursor.lastrowid)

    def _upsert_existing(self, existing: Contact, **kwargs: str) -> Contact:
        """Aktualisiert bestehenden Kontakt – nur non-empty Felder."""
        now = datetime.now(timezone.utc).isoformat()
        updates: dict[str, str] = {}
        for field in self._ALL_FIELDS:
            if field == "name":
                continue
            new_val = kwargs.get(field, "")
            old_val = getattr(existing, field, "")
            if new_val and new_val != old_val:
                updates[field] = new_val

        if not updates:
            return existing

        set_parts = [f"{k} = ?" for k in updates]
        set_parts.append("updated_at = ?")
        vals = list(updates.values()) + [now, existing.id]
        self._conn.execute(
            f"UPDATE contacts SET {', '.join(set_parts)} WHERE id = ?",
            vals,
        )
        self._conn.commit()
        return self._get_by_rowid(existing.id)

    def update(self, contact_id: int, **kwargs: str) -> Contact | None:
        """Kontakt per ID aktualisieren. Nur non-empty Felder überschreiben."""
        existing = self.get_by_id(contact_id)
        if not existing:
            return None
        now = datetime.now(timezone.utc).isoformat()
        updates: dict[str, str] = {}
        for field in self._ALL_FIELDS:
            new_val = kwargs.get(field, "")
            if new_val:
                updates[field] = new_val

        if not updates:
            return existing

        set_parts = [f"{k} = ?" for k in updates]
        set_parts.append("updated_at = ?")
        vals = list(updates.values()) + [now, contact_id]
        self._conn.execute(
            f"UPDATE contacts SET {', '.join(set_parts)} WHERE id = ?",
            vals,
        )
        self._conn.commit()
        return self._get_by_rowid(contact_id)

    def add_or_update_by_vcard_uid(
        self, user_id: str, vcard_uid: str, **kwargs: str,
    ) -> Contact:
        """Kontakt per vCard-UID finden und aktualisieren, oder neu anlegen.

        Verwendet für CardDAV-Sync: Matching per NC-UID statt per Name.
        """
        existing = self.find_by_vcard_uid(user_id, vcard_uid)
        if existing:
            return self._upsert_existing(existing, **kwargs)
        # Fallback: per Name suchen (falls UID sich geändert hat)
        name = kwargs.pop("name", "")
        if name:
            by_name = self.find_by_name(user_id, name)
            if by_name:
                # vcard_uid nachträglich setzen
                kwargs["vcard_uid"] = vcard_uid
                return self._upsert_existing(by_name, **kwargs)
        # Neu anlegen
        kwargs["vcard_uid"] = vcard_uid
        return self.add(user_id, name=name, **kwargs)

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def find_by_email(self, user_id: str, email: str) -> Contact | None:
        """Kontakt per Email-Adresse finden (sucht im JSON-Array)."""
        # emails enthält JSON wie [{"type":"work","email":"x@y.de"}]
        # Wir suchen case-insensitive mit LIKE
        needle = email.strip().lower()
        rows = self._conn.execute(
            "SELECT * FROM contacts WHERE user_id=? AND LOWER(emails) LIKE ?",
            (user_id, f"%{needle}%"),
        ).fetchall()
        for row in rows:
            contact = self._row_to_contact(row)
            for ei in contact.get_emails_list():
                if ei.get("email", "").lower() == needle:
                    return contact
        return None

    def find_by_name(self, user_id: str, name: str) -> Contact | None:
        """Kontakt per Name finden (case-insensitive)."""
        row = self._conn.execute(
            "SELECT * FROM contacts "
            "WHERE user_id=? AND name=? COLLATE NOCASE",
            (user_id, name.strip()),
        ).fetchone()
        return self._row_to_contact(row) if row else None

    def find_by_vcard_uid(self, user_id: str, vcard_uid: str) -> Contact | None:
        """Kontakt per vCard-UID finden."""
        if not vcard_uid:
            return None
        row = self._conn.execute(
            "SELECT * FROM contacts WHERE user_id=? AND vcard_uid=?",
            (user_id, vcard_uid),
        ).fetchone()
        return self._row_to_contact(row) if row else None

    def search(self, user_id: str, query: str,
               limit: int = 10) -> list[Contact]:
        """Volltextsuche über alle Kontakte (FTS5 MATCH)."""
        try:
            fts_query = query.strip() + "*"
            rows = self._conn.execute(
                "SELECT c.* FROM contacts c "
                "JOIN contacts_fts f ON c.id = f.rowid "
                "WHERE f.contacts_fts MATCH ? AND c.user_id=? LIMIT ?",
                (fts_query, user_id, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        return [self._row_to_contact(r) for r in rows]

    def list_all(self, user_id: str, limit: int = 20) -> list[Contact]:
        """Alle Kontakte eines Users (alphabetisch nach Name)."""
        rows = self._conn.execute(
            "SELECT * FROM contacts WHERE user_id=? "
            "ORDER BY name COLLATE NOCASE LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [self._row_to_contact(r) for r in rows]

    def get_by_id(self, contact_id: int) -> Contact | None:
        """Kontakt per ID abrufen."""
        row = self._conn.execute(
            "SELECT * FROM contacts WHERE id=?",
            (contact_id,),
        ).fetchone()
        return self._row_to_contact(row) if row else None

    def get_birthdays_today(self, user_id: str,
                            today: date | None = None) -> list[Contact]:
        """Kontakte deren Geburtstag heute ist."""
        if today is None:
            today = date.today()
        mm_dd = today.strftime("%m-%d")
        rows = self._conn.execute(
            "SELECT * FROM contacts "
            "WHERE user_id=? AND birthday LIKE ?",
            (user_id, f"%-{mm_dd}"),
        ).fetchall()
        return [self._row_to_contact(r) for r in rows]

    def get_upcoming_birthdays(self, user_id: str, days: int = 7,
                               today: date | None = None) -> list[Contact]:
        """Kontakte deren Geburtstag in den nächsten N Tagen ist."""
        if today is None:
            today = date.today()
        results: list[Contact] = []
        for offset in range(days):
            check_date = today + timedelta(days=offset)
            mm_dd = check_date.strftime("%m-%d")
            rows = self._conn.execute(
                "SELECT * FROM contacts "
                "WHERE user_id=? AND birthday LIKE ? AND birthday != ''",
                (user_id, f"%-{mm_dd}"),
            ).fetchall()
            results.extend(self._row_to_contact(r) for r in rows)
        return results

    def get_upcoming_anniversaries(self, user_id: str, days: int = 7,
                                   today: date | None = None) -> list[Contact]:
        """Kontakte deren Jahrestag in den nächsten N Tagen ist."""
        if today is None:
            today = date.today()
        results: list[Contact] = []
        for offset in range(days):
            check_date = today + timedelta(days=offset)
            mm_dd = check_date.strftime("%m-%d")
            rows = self._conn.execute(
                "SELECT * FROM contacts "
                "WHERE user_id=? AND anniversary LIKE ? AND anniversary != ''",
                (user_id, f"%-{mm_dd}"),
            ).fetchall()
            results.extend(self._row_to_contact(r) for r in rows)
        return results

    def find_by_category(self, user_id: str,
                         category: str) -> list[Contact]:
        """Kontakte die eine bestimmte Kategorie/Gruppe haben."""
        # categories ist komma-separiert, z.B. "Familie, Arbeit"
        rows = self._conn.execute(
            "SELECT * FROM contacts WHERE user_id=? AND categories != ''",
            (user_id,),
        ).fetchall()
        needle = category.strip().lower()
        results = []
        for row in rows:
            contact = self._row_to_contact(row)
            cats = [c.strip().lower() for c in contact.categories.split(",")]
            if needle in cats:
                results.append(contact)
        return results

    def find_by_group(self, user_id: str, group: str) -> list[Contact]:
        """Alias für find_by_category – Kontakte mit bestimmter Gruppe."""
        return self.find_by_category(user_id, group)

    def delete_all(self, user_id: str) -> int:
        """Löscht alle Kontakte eines Users. Gibt Anzahl zurück."""
        cursor = self._conn.execute(
            "DELETE FROM contacts WHERE user_id=?", (user_id,),
        )
        self._conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Löschen
    # ------------------------------------------------------------------

    def delete(self, contact_id: int) -> bool:
        """Kontakt per ID löschen. Returns True wenn gelöscht."""
        cursor = self._conn.execute(
            "DELETE FROM contacts WHERE id=?", (contact_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_by_name(self, user_id: str, name: str) -> bool:
        """Kontakt per Name löschen (case-insensitive)."""
        cursor = self._conn.execute(
            "DELETE FROM contacts WHERE user_id=? "
            "AND name=? COLLATE NOCASE",
            (user_id, name.strip()),
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

    def _get_by_rowid(self, rowid: int) -> Contact:
        """Holt Contact per rowid (nach INSERT/UPDATE)."""
        row = self._conn.execute(
            "SELECT * FROM contacts WHERE id=?",
            (rowid,),
        ).fetchone()
        return self._row_to_contact(row)

    @staticmethod
    def _row_to_contact(row: tuple) -> Contact:
        """Konvertiert DB-Row in Contact-DTO."""
        (id_, user_id, name, emails, phones, role, formality,
         notes, birthday, address, organization, title, categories,
         nickname, anniversary, url, vcard_uid,
         created_at, updated_at) = row
        return Contact(
            id=id_, user_id=user_id, name=name,
            emails=emails or "[]", phones=phones or "[]",
            role=role or "", formality=formality or "förmlich",
            notes=notes or "", birthday=birthday or "",
            address=address or "", organization=organization or "",
            title=title or "", categories=categories or "",
            nickname=nickname or "", anniversary=anniversary or "",
            url=url or "", vcard_uid=vcard_uid or "",
            created_at=datetime.fromisoformat(created_at),
            updated_at=datetime.fromisoformat(updated_at),
        )
