"""ContactStore – Persistenter Kontaktspeicher (SQLite + FTS5).

Speichert Kontakte mit Name, Email(s), Rolle/Beziehung, Anrede-Präferenz
und freien Notizen. Automatischer Lookup per Email-Adresse für
Email-Reply-Kontext (Phase 28 Integration).

Verwendung:
    store = ContactStore()
    store.add("@user:matrix.org", name="Herr Müller",
              email="info@mueller-immo.de", role="Vermieter",
              formality="förmlich")
    contact = store.find_by_email("@user:matrix.org", "info@mueller-immo.de")
    results = store.search("@user:matrix.org", "Müller")
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".elder-berry" / "contacts.db"


@dataclass(frozen=True)
class Contact:
    """Ein Kontakt."""

    id: int
    user_id: str
    name: str
    """Anzeigename (z.B. 'Herr Müller', 'Lisa', 'Dr. Weber')."""
    email: str
    """Primäre Email-Adresse (für automatischen Lookup). Leer wenn unbekannt."""
    role: str
    """Beziehung/Rolle (z.B. 'Vermieter', 'Schwester', 'Zahnarzt')."""
    formality: str
    """Anrede-Stil: 'förmlich' (Sie) oder 'locker' (Du). Default: 'förmlich'."""
    phone: str
    """Telefonnummer (z.B. '+49 170 1234567'). Leer wenn unbekannt."""
    notes: str
    """Freie Notizen (z.B. 'hat Hund namens Rex')."""
    birthday: str
    """Geburtstag im Format 'YYYY-MM-DD' oder leer. Jahr=0000 wenn unbekannt."""
    created_at: datetime
    updated_at: datetime

    def format_short(self) -> str:
        """Einzeilige Darstellung."""
        parts = [f"#{self.id} {self.name}"]
        if self.role:
            parts.append(f"– {self.role}")
        parts.append(f"({self.formality})")
        if self.email:
            parts.append(f"– {self.email}")
        return " ".join(parts)

    def format_detail(self) -> str:
        """Mehrzeilige Detail-Darstellung."""
        lines = [f"📇 #{self.id} {self.name}"]
        if self.role:
            lines.append(f"  Rolle: {self.role}")
        if self.email:
            lines.append(f"  Email: {self.email}")
        if self.phone:
            lines.append(f"  Telefon: {self.phone}")
        lines.append(f"  Anrede: {self.formality}")
        if self.birthday:
            if self.birthday.startswith("0000-"):
                lines.append(f"  Geburtstag: {self.birthday[5:]}")
            else:
                lines.append(f"  Geburtstag: {self.birthday}")
        if self.notes:
            lines.append(f"  📝 {self.notes}")
        return "\n".join(lines)

    def format_for_llm(self) -> str:
        """Kontext-String für LLM System-Prompts (Email-Draft etc.)."""
        lines = [f"Kontakt: {self.name}"]
        if self.role:
            lines.append(f"Beziehung: {self.role}")
        hint = "Sie" if self.formality == "förmlich" else "Du"
        lines.append(f"Anrede: {self.formality} ({hint})")
        if self.phone:
            lines.append(f"Telefon: {self.phone}")
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
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS contacts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                name        TEXT NOT NULL,
                email       TEXT NOT NULL DEFAULT '',
                role        TEXT NOT NULL DEFAULT '',
                formality   TEXT NOT NULL DEFAULT 'förmlich',
                phone       TEXT NOT NULL DEFAULT '',
                notes       TEXT NOT NULL DEFAULT '',
                birthday    TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_contacts_user_email
                ON contacts(user_id, email) WHERE email != '';
            CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_user_name
                ON contacts(user_id, name COLLATE NOCASE);
            CREATE VIRTUAL TABLE IF NOT EXISTS contacts_fts USING fts5(
                name, role, notes, email,
                content=contacts, content_rowid=id
            );
            CREATE TRIGGER IF NOT EXISTS contacts_ai AFTER INSERT ON contacts
            BEGIN
                INSERT INTO contacts_fts(rowid, name, role, notes, email)
                VALUES (new.id, new.name, new.role, new.notes, new.email);
            END;
            CREATE TRIGGER IF NOT EXISTS contacts_au AFTER UPDATE ON contacts
            BEGIN
                INSERT INTO contacts_fts(contacts_fts, rowid, name, role,
                                         notes, email)
                VALUES('delete', old.id, old.name, old.role, old.notes,
                       old.email);
                INSERT INTO contacts_fts(rowid, name, role, notes, email)
                VALUES (new.id, new.name, new.role, new.notes, new.email);
            END;
            CREATE TRIGGER IF NOT EXISTS contacts_ad AFTER DELETE ON contacts
            BEGIN
                INSERT INTO contacts_fts(contacts_fts, rowid, name, role,
                                         notes, email)
                VALUES('delete', old.id, old.name, old.role, old.notes,
                       old.email);
            END;
        """)
        self._conn.commit()
        self._migrate_birthday_column()
        self._migrate_phone_column()

    def _migrate_birthday_column(self) -> None:
        """Fügt birthday-Spalte hinzu wenn sie noch nicht existiert."""
        try:
            self._conn.execute("SELECT birthday FROM contacts LIMIT 1")
        except sqlite3.OperationalError:
            try:
                self._conn.execute(
                    "ALTER TABLE contacts ADD COLUMN birthday TEXT NOT NULL DEFAULT ''",
                )
                self._conn.commit()
                logger.info("Migration: birthday-Spalte zu contacts hinzugefügt")
            except sqlite3.OperationalError as e:
                logger.warning("Migration birthday-Spalte fehlgeschlagen: %s", e)

    def _migrate_phone_column(self) -> None:
        """Fügt phone-Spalte hinzu wenn sie noch nicht existiert."""
        try:
            self._conn.execute("SELECT phone FROM contacts LIMIT 1")
        except sqlite3.OperationalError:
            try:
                self._conn.execute(
                    "ALTER TABLE contacts ADD COLUMN phone TEXT NOT NULL DEFAULT ''",
                )
                self._conn.commit()
                logger.info("Migration: phone-Spalte zu contacts hinzugefügt")
            except sqlite3.OperationalError as e:
                logger.warning("Migration phone-Spalte fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def add(self, user_id: str, name: str, email: str = "",
            role: str = "", formality: str = "",
            notes: str = "", birthday: str = "",
            phone: str = "") -> Contact:
        """Kontakt hinzufügen oder aktualisieren (Upsert per Name).

        Wenn ein Kontakt mit gleichem Namen (case-insensitive) existiert,
        werden nur non-empty Felder aktualisiert.
        Bei neuem Kontakt wird formality auf 'förmlich' gesetzt wenn leer.
        """
        now = datetime.now(timezone.utc).isoformat()
        existing = self.find_by_name(user_id, name)
        if existing:
            return self._upsert_existing(
                existing, email=email, role=role,
                formality=formality, notes=notes,
                birthday=birthday, phone=phone,
            )
        # Neuer Kontakt: Default-Formalität wenn nicht angegeben
        insert_formality = formality if formality else "förmlich"
        cursor = self._conn.execute(
            "INSERT INTO contacts "
            "(user_id, name, email, role, formality, notes, birthday, "
            "phone, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, email, role, insert_formality, notes,
             birthday, phone, now, now),
        )
        self._conn.commit()
        return self._get_by_rowid(cursor.lastrowid)

    def _upsert_existing(self, existing: Contact, email: str,
                         role: str, formality: str,
                         notes: str, birthday: str = "",
                         phone: str = "") -> Contact:
        """Aktualisiert bestehenden Kontakt – nur non-empty Felder."""
        now = datetime.now(timezone.utc).isoformat()
        new_email = email if email else existing.email
        new_role = role if role else existing.role
        new_formality = formality if formality else existing.formality
        new_notes = notes if notes else existing.notes
        new_birthday = birthday if birthday else existing.birthday
        new_phone = phone if phone else existing.phone
        self._conn.execute(
            "UPDATE contacts SET email = ?, role = ?, formality = ?, "
            "notes = ?, birthday = ?, phone = ?, updated_at = ? WHERE id = ?",
            (new_email, new_role, new_formality, new_notes, new_birthday,
             new_phone, now, existing.id),
        )
        self._conn.commit()
        return self._get_by_rowid(existing.id)

    def update(self, contact_id: int, name: str = "", email: str = "",
               role: str = "", formality: str = "",
               notes: str = "", birthday: str = "",
               phone: str = "") -> Contact | None:
        """Kontakt per ID aktualisieren. Nur non-empty Felder überschreiben."""
        existing = self.get_by_id(contact_id)
        if not existing:
            return None
        now = datetime.now(timezone.utc).isoformat()
        n = name if name else existing.name
        e = email if email else existing.email
        r = role if role else existing.role
        f = formality if formality else existing.formality
        no = notes if notes else existing.notes
        bd = birthday if birthday else existing.birthday
        ph = phone if phone else existing.phone
        self._conn.execute(
            "UPDATE contacts SET name=?, email=?, role=?, formality=?, "
            "notes=?, birthday=?, phone=?, updated_at=? WHERE id=?",
            (n, e, r, f, no, bd, ph, now, contact_id),
        )
        self._conn.commit()
        return self._get_by_rowid(contact_id)

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def find_by_email(self, user_id: str, email: str) -> Contact | None:
        """Kontakt per Email-Adresse finden (case-insensitive)."""
        row = self._conn.execute(
            "SELECT id, user_id, name, email, role, formality, phone, notes, birthday, "
            "created_at, updated_at "
            "FROM contacts WHERE user_id=? AND email=? COLLATE NOCASE",
            (user_id, email.strip()),
        ).fetchone()
        return self._row_to_contact(row) if row else None

    def find_by_name(self, user_id: str, name: str) -> Contact | None:
        """Kontakt per Name finden (case-insensitive)."""
        row = self._conn.execute(
            "SELECT id, user_id, name, email, role, formality, phone, notes, birthday, "
            "created_at, updated_at "
            "FROM contacts WHERE user_id=? AND name=? COLLATE NOCASE",
            (user_id, name.strip()),
        ).fetchone()
        return self._row_to_contact(row) if row else None

    def search(self, user_id: str, query: str,
               limit: int = 10) -> list[Contact]:
        """Volltextsuche über alle Kontakte (FTS5 MATCH)."""
        try:
            fts_query = query.strip() + "*"
            rows = self._conn.execute(
                "SELECT c.id, c.user_id, c.name, c.email, c.role, "
                "c.formality, c.phone, c.notes, c.birthday, c.created_at, c.updated_at "
                "FROM contacts c JOIN contacts_fts f ON c.id = f.rowid "
                "WHERE f.contacts_fts MATCH ? AND c.user_id=? LIMIT ?",
                (fts_query, user_id, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        return [self._row_to_contact(r) for r in rows]

    def list_all(self, user_id: str, limit: int = 20) -> list[Contact]:
        """Alle Kontakte eines Users (alphabetisch nach Name)."""
        rows = self._conn.execute(
            "SELECT id, user_id, name, email, role, formality, phone, notes, birthday, "
            "created_at, updated_at FROM contacts WHERE user_id=? "
            "ORDER BY name COLLATE NOCASE LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [self._row_to_contact(r) for r in rows]

    def get_by_id(self, contact_id: int) -> Contact | None:
        """Kontakt per ID abrufen."""
        row = self._conn.execute(
            "SELECT id, user_id, name, email, role, formality, phone, notes, birthday, "
            "created_at, updated_at FROM contacts WHERE id=?",
            (contact_id,),
        ).fetchone()
        return self._row_to_contact(row) if row else None

    def get_birthdays_today(self, user_id: str,
                            today: date | None = None) -> list[Contact]:
        """Kontakte deren Geburtstag heute ist.

        Vergleicht Monat+Tag des birthday-Felds (Format: YYYY-MM-DD).

        Args:
            user_id: Matrix-User-ID.
            today: Optionales Datum (für Tests). Default: date.today().

        Returns:
            Liste von Contacts mit heutigem Geburtstag.
        """
        if today is None:
            today = date.today()
        mm_dd = today.strftime("%m-%d")
        rows = self._conn.execute(
            "SELECT id, user_id, name, email, role, formality, phone, notes, birthday, "
            "created_at, updated_at "
            "FROM contacts WHERE user_id=? AND birthday LIKE ?",
            (user_id, f"%-{mm_dd}"),
        ).fetchall()
        return [self._row_to_contact(r) for r in rows]

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
            "SELECT id, user_id, name, email, role, formality, phone, notes, birthday, "
            "created_at, updated_at FROM contacts WHERE id=?",
            (rowid,),
        ).fetchone()
        return self._row_to_contact(row)

    @staticmethod
    def _row_to_contact(row: tuple) -> Contact:
        """Konvertiert DB-Row in Contact-DTO."""
        (id_, user_id, name, email, role, formality, phone, notes,
         birthday, created_at, updated_at) = row
        return Contact(
            id=id_, user_id=user_id, name=name, email=email,
            role=role, formality=formality, phone=phone or "",
            notes=notes, birthday=birthday or "",
            created_at=datetime.fromisoformat(created_at),
            updated_at=datetime.fromisoformat(updated_at),
        )
