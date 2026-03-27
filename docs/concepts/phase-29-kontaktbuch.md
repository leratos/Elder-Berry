# Phase 29 – Kontaktbuch (ContactStore)

## Übersicht

Saleria kennt Personen und deren Kontext. Das Kontaktbuch speichert
Beziehungen, Anrede-Präferenzen und Notizen zu Kontakten. Diese
Informationen fließen automatisch in Email-Antworten (Phase 28) und
Kalender-Kontext ein.

### Warum

Ohne Kontaktbuch generiert der EMAIL_SYSTEM_PROMPT blinde Antworten.
Saleria weiß nicht, ob "info@firma.de" der Vermieter ist (förmlich) oder
ein Freund (locker). Mit Kontaktbuch:
- Email-Drafts passen Ton und Anrede automatisch an
- Kalender-Termine bekommen Kontext ("Termin mit Herr Müller — dein Vermieter")
- Proaktivität (Phase 31) kann Personen-bezogen agieren

### User-Flow

```
Nutzer: "merk dir kontakt: Herr Müller, vermieter, info@mueller-immo.de, förmlich"
Saleria: "✅ Kontakt gespeichert: Herr Müller (Vermieter, förmlich)"

Nutzer: "antworte auf mail #4523 positiv"
        → Mail ist von info@mueller-immo.de
        → ContactStore liefert: {name: "Herr Müller", role: "Vermieter", formality: "förmlich"}
        → EMAIL_SYSTEM_PROMPT bekommt Kontakt-Kontext
        → Draft: "Sehr geehrter Herr Müller, ..."

Nutzer: "wer ist Herr Müller?"
Saleria: "Herr Müller ist dein Vermieter (info@mueller-immo.de, förmlich)"

Nutzer: "kontakte"
Saleria: "3 Kontakte:
  #1 Herr Müller – Vermieter (förmlich) – info@mueller-immo.de
  #2 Lisa – Schwester (locker) – lisa@gmail.com
  #3 Dr. Weber – Zahnarzt (förmlich) – praxis@weber-dental.de"
```
---

## 1. ContactStore – Persistenter Kontaktspeicher

**Datei**: `src/elder_berry/tools/contact_store.py`

Folgt dem NoteStore-Pattern: SQLite, WAL-Modus, FTS5, Thread-safe.
Eigene DB-Datei (`contacts.db`), nicht in notes.db — saubere Trennung.

### Datenmodell

```python
"""ContactStore – Persistenter Kontaktspeicher (SQLite + FTS5).

Speichert Kontakte mit Name, Email(s), Rolle/Beziehung, Anrede-Präferenz
und freien Notizen. Automatischer Lookup per Email-Adresse für Email-Reply-Kontext.

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
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".elder-berry" / "contacts.db"

@dataclass(frozen=True)
class Contact:
    """Ein Kontakt."""

    id: int
    user_id: str
    name: str
    """Anzeigename (z.B. "Herr Müller", "Lisa", "Dr. Weber")."""

    email: str
    """Primäre Email-Adresse (für automatischen Lookup). Leer wenn unbekannt."""

    role: str
    """Beziehung/Rolle (z.B. "Vermieter", "Schwester", "Zahnarzt", "Kollege")."""

    formality: str
    """Anrede-Stil: "förmlich" (Sie) oder "locker" (Du). Default: "förmlich"."""

    notes: str
    """Freie Notizen (z.B. "hat Hund namens Rex", "bevorzugt Anrufe Mo-Fr")."""

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

    def format_for_llm(self) -> str:
        """Kontext-String für LLM System-Prompts (Email-Draft etc.)."""
        lines = [f"Kontakt: {self.name}"]
        if self.role:
            lines.append(f"Beziehung: {self.role}")
        lines.append(f"Anrede: {self.formality} ({'Sie' if self.formality == 'förmlich' else 'Du'})")
        if self.notes:
            lines.append(f"Notizen: {self.notes}")
        return "\n".join(lines)
```
### SQL-Schema

```python
class ContactStore:
    """SQLite-basierter Kontaktspeicher mit FTS5-Volltextsuche.

    Thread-safe: check_same_thread=False.
    WAL-Modus für bessere Concurrent-Read-Performance.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
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
                notes       TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            -- Email-Index für schnellen Lookup (pro User)
            CREATE INDEX IF NOT EXISTS idx_contacts_user_email
                ON contacts(user_id, email) WHERE email != '';

            -- Name muss pro User eindeutig sein (normalisiert)
            CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_user_name
                ON contacts(user_id, name COLLATE NOCASE);

            -- FTS5 für Volltextsuche über Name, Role, Notes
            CREATE VIRTUAL TABLE IF NOT EXISTS contacts_fts USING fts5(
                name, role, notes, email,
                content=contacts,
                content_rowid=id
            );

            CREATE TRIGGER IF NOT EXISTS contacts_ai AFTER INSERT ON contacts BEGIN
                INSERT INTO contacts_fts(rowid, name, role, notes, email)
                VALUES (new.id, new.name, new.role, new.notes, new.email);
            END;

            CREATE TRIGGER IF NOT EXISTS contacts_au AFTER UPDATE ON contacts BEGIN
                INSERT INTO contacts_fts(contacts_fts, rowid, name, role, notes, email)
                VALUES('delete', old.id, old.name, old.role, old.notes, old.email);
                INSERT INTO contacts_fts(rowid, name, role, notes, email)
                VALUES (new.id, new.name, new.role, new.notes, new.email);
            END;

            CREATE TRIGGER IF NOT EXISTS contacts_ad AFTER DELETE ON contacts BEGIN
                INSERT INTO contacts_fts(contacts_fts, rowid, name, role, notes, email)
                VALUES('delete', old.id, old.name, old.role, old.notes, old.email);
            END;
        """)
        self._conn.commit()
```
### Methoden

```python
    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def add(
        self,
        user_id: str,
        name: str,
        email: str = "",
        role: str = "",
        formality: str = "förmlich",
        notes: str = "",
    ) -> Contact:
        """Kontakt hinzufügen oder aktualisieren (Upsert per Name).

        Wenn ein Kontakt mit gleichem Namen (case-insensitive) existiert,
        werden die Felder aktualisiert. Leere Strings überschreiben
        bestehende Werte NICHT (nur non-empty Felder updaten).

        Args:
            user_id: Matrix-User-ID.
            name: Anzeigename.
            email: Email-Adresse (optional).
            role: Beziehung/Rolle (optional).
            formality: "förmlich" oder "locker" (default: "förmlich").
            notes: Freitext-Notizen (optional).

        Returns:
            Der erstellte/aktualisierte Contact.
        """
        ...

    def update(
        self,
        contact_id: int,
        name: str = "",
        email: str = "",
        role: str = "",
        formality: str = "",
        notes: str = "",
    ) -> Contact | None:
        """Kontakt per ID aktualisieren. Nur non-empty Felder werden überschrieben.

        Returns:
            Aktualisierter Contact oder None wenn ID nicht existiert.
        """
        ...
```
```python
    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def find_by_email(self, user_id: str, email: str) -> Contact | None:
        """Kontakt per Email-Adresse finden.

        Wichtigste Methode für die Email-Reply-Integration:
        Original-Mail kommt rein → Absender-Email → ContactStore Lookup
        → Kontext für EMAIL_SYSTEM_PROMPT.

        Args:
            user_id: Matrix-User-ID.
            email: Email-Adresse (case-insensitive Vergleich).

        Returns:
            Contact oder None.
        """
        row = self._conn.execute(
            "SELECT id, user_id, name, email, role, formality, notes, "
            "created_at, updated_at "
            "FROM contacts WHERE user_id = ? AND email = ? COLLATE NOCASE",
            (user_id, email.strip()),
        ).fetchone()
        return self._row_to_contact(row) if row else None

    def find_by_name(self, user_id: str, name: str) -> Contact | None:
        """Kontakt per Name finden (case-insensitive).

        Args:
            user_id: Matrix-User-ID.
            name: Name (case-insensitive).

        Returns:
            Contact oder None.
        """
        ...

    def search(self, user_id: str, query: str, limit: int = 10) -> list[Contact]:
        """Volltextsuche über alle Kontakte (FTS5 MATCH).

        Durchsucht name, role, notes, email.
        """
        ...

    def list_all(self, user_id: str, limit: int = 20) -> list[Contact]:
        """Alle Kontakte eines Users (alphabetisch nach Name)."""
        ...

    def get_by_id(self, contact_id: int) -> Contact | None:
        """Kontakt per ID abrufen."""
        ...

    # ------------------------------------------------------------------
    # Löschen
    # ------------------------------------------------------------------

    def delete(self, contact_id: int) -> bool:
        """Kontakt per ID löschen. Returns True wenn gelöscht."""
        ...

    def delete_by_name(self, user_id: str, name: str) -> bool:
        """Kontakt per Name löschen (case-insensitive). Returns True wenn gelöscht."""
        ...

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Verbindung sauber schließen."""
        ...

    @staticmethod
    def _row_to_contact(row: tuple) -> Contact:
        """Konvertiert DB-Row in Contact-DTO."""
        ...
```
---

## 2. ContactCommandHandler – Matrix Commands

**Datei**: `src/elder_berry/comms/commands/contact_commands.py`

### Patterns

```python
"""ContactCommandHandler – Kontaktbuch-Commands.

Commands:
- kontakt: Name, Rolle, Email, Anrede       → Kontakt anlegen/aktualisieren
- kontakt ändern #ID: Feld=Wert             → Kontakt bearbeiten
- wer ist <Name>?                           → Kontakt abrufen
- kontakte                                   → Alle Kontakte auflisten
- kontakte suche <Begriff>                   → Volltextsuche
- kontakt löschen #<ID>                      → Per ID löschen
- kontakt löschen <Name>                     → Per Name löschen
"""

# "kontakt: Herr Müller, Vermieter, info@mueller.de, förmlich"
# "neuer kontakt: Lisa, Schwester, lisa@gmail.com, locker"
# "kontakt: Dr. Weber, Zahnarzt, förmlich"  (ohne Email)
# "kontakt: Max, Kollege, max@firma.de"     (ohne Anrede → default förmlich)
CONTACT_ADD_PATTERN = re.compile(
    r"^(?:neuer?\s+)?kontakt[:\s]+(.+)$",
    re.IGNORECASE,
)

# "kontakt ändern #3: email=neue@adresse.de"
# "kontakt #3 ändern: rolle=Chef"
CONTACT_UPDATE_PATTERN = re.compile(
    r"kontakt\s+(?:ändern\s+)?#?(\d+)[:\s]+(.+)",
    re.IGNORECASE,
)

# "wer ist Herr Müller?" / "wer ist Lisa?"
# Achtung: Kollision mit NOTE_GET_FACT_PATTERN ("was ist X?")!
# "wer ist" (Person) vs "was ist" (Fakt) → klar getrennt
CONTACT_WHO_PATTERN = re.compile(
    r"^wer\s+ist\s+(.+?)\??\s*$",
    re.IGNORECASE,
)

# "kontakte suche Müller" / "kontakt suche Zahnarzt"
CONTACT_SEARCH_PATTERN = re.compile(
    r"^kontakte?\s+suche?\s+(.+)$",
    re.IGNORECASE,
)

# "kontakt löschen #3" oder "kontakt löschen Herr Müller"
CONTACT_DELETE_PATTERN = re.compile(
    r"^kontakte?\s+(?:löschen|lösche|entferne?)\s+(?:#(\d+)|(.+))$",
    re.IGNORECASE,
)
```
### Klassen-Signatur

```python
class ContactCommandHandler(CommandHandler):
    def __init__(
        self,
        contact_store: ContactStore | None = None,
        default_user_id: str = "",
    ) -> None:
        self._store = contact_store
        self._default_user_id = default_user_id

    @property
    def simple_commands(self) -> set[str]:
        return {"kontakte"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (CONTACT_ADD_PATTERN, "contact_add", False, False),
            (CONTACT_UPDATE_PATTERN, "contact_update", False, True),
            (CONTACT_WHO_PATTERN, "contact_who", False, False),
            (CONTACT_SEARCH_PATTERN, "contact_search", False, False),
            (CONTACT_DELETE_PATTERN, "contact_delete", False, False),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "kontakte": [
                "kontakte", "adressbuch", "kontaktliste",
                "meine kontakte", "alle kontakte",
            ],
            "contact_add": [
                "neuer kontakt", "kontakt speichern",
                "kontakt anlegen", "kontakt hinzufügen",
            ],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "kontakt: Name, Rolle, Email, Anrede – Kontakt anlegen",
            "wer ist <Name>? – Kontakt abrufen",
            "kontakte – Alle Kontakte auflisten",
            "kontakte suche <Begriff> – Kontakt suchen",
            "kontakt löschen #<ID> – Kontakt löschen",
        ]
```
### Parsing-Logik für kontakt: Komma-separierte Felder

Das Eingabeformat ist bewusst flexibel:
- `kontakt: Herr Müller, Vermieter, info@mueller.de, förmlich`
- `kontakt: Lisa, Schwester, locker` (ohne Email)
- `kontakt: Max, Kollege, max@firma.de` (ohne Anrede → default förmlich)
- `kontakt: Dr. Weber, Zahnarzt` (nur Name + Rolle)

Parsing-Algorithmus:

```python
def _parse_contact_fields(self, raw: str) -> dict[str, str]:
    """Parst komma-separierte Kontakt-Felder.

    Erkennt automatisch:
    - Email: enthält "@"
    - Anrede: "förmlich" oder "locker"
    - Erstes Feld: Name
    - Restliche Felder ohne @ und ohne Anrede-Keyword: Rolle

    Returns:
        Dict mit keys: name, email, role, formality
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return {}

    result = {"name": parts[0], "email": "", "role": "", "formality": "förmlich"}

    for part in parts[1:]:
        lower = part.lower()
        if "@" in part:
            result["email"] = part
        elif lower in ("förmlich", "formell", "sie"):
            result["formality"] = "förmlich"
        elif lower in ("locker", "informell", "du"):
            result["formality"] = "locker"
        else:
            # Alles andere ist Rolle (erste nicht erkannte Angabe)
            if not result["role"]:
                result["role"] = part
            else:
                # Zusätzliche unerkannte Felder → an Notizen hängen
                result.setdefault("notes", "")
                result["notes"] += f" {part}".strip()

    return result
```
---

## 3. Integration mit Phase 28 (Email-Reply)

**Datei**: `src/elder_berry/comms/commands/mail_commands.py`

Das ist der Hauptnutzen des Kontaktbuchs. Wenn `_cmd_mail_reply()` die
Original-Mail holt, schaut es per Email-Adresse im ContactStore nach
und erweitert den EMAIL_SYSTEM_PROMPT um den Kontakt-Kontext.

### Änderung in MailCommandHandler

```python
class MailCommandHandler(CommandHandler):
    def __init__(
        self,
        email_client: IMAPEmailClient | None = None,
        anthropic_client: AnthropicClient | None = None,
        contact_store: ContactStore | None = None,      # NEU (Phase 29)
        default_user_id: str = "",                        # NEU (für ContactStore Lookup)
    ) -> None:
        self._email_client = email_client
        self._anthropic = anthropic_client
        self._contacts = contact_store
        self._default_user_id = default_user_id
```

### Änderung in _generate_draft()

```python
def _generate_draft(self, original: EmailMessage, instruction: str) -> str:
    # Kontakt-Lookup per Absender-Email
    contact_context = ""
    if self._contacts and self._default_user_id:
        sender_email = self._extract_email_address(original.sender)
        contact = self._contacts.find_by_email(self._default_user_id, sender_email)
        if contact:
            contact_context = (
                f"\n\nKontext zum Empfänger:\n"
                f"{contact.format_for_llm()}\n"
            )

    # System-Prompt mit optionalem Kontakt-Kontext
    system = EMAIL_SYSTEM_PROMPT + contact_context

    # ... rest wie gehabt ...
    return self._anthropic.generate(prompt, system=system)
```

Das heißt: Wenn ein Kontakt gefunden wird, bekommt Claude z.B.:

```
Kontext zum Empfänger:
Kontakt: Herr Müller
Beziehung: Vermieter
Anrede: förmlich (Sie)
Notizen: hat Hund namens Rex
```

Und der Draft wird automatisch förmlich, ohne dass der Nutzer "förmlich"
als Anweisung geben muss.
---

## 4. RemoteCommandHandler + Start-Script

### remote_commands.py

```python
# Neuer Import
from elder_berry.comms.commands.contact_commands import ContactCommandHandler

class RemoteCommandHandler:
    def __init__(
        self,
        # ... bestehende Parameter ...
        contact_store: ContactStore | None = None,  # NEU
    ) -> None:
        # ...
        # ContactCommandHandler: nur wenn ContactStore vorhanden
        self._contacts: ContactCommandHandler | None = None
        if contact_store is not None:
            self._contacts = ContactCommandHandler(
                contact_store=contact_store,
                default_user_id=default_user_id,
            )

        # MailCommandHandler bekommt auch den ContactStore:
        self._mail = MailCommandHandler(
            email_client=email_client,
            anthropic_client=anthropic_client,
            contact_store=contact_store,       # NEU
            default_user_id=default_user_id,   # NEU
        )

        # Handler-Liste: _contacts nach _notes, vor _advanced
        # ...
        if self._contacts is not None:
            self._handlers.append(self._contacts)
        self._handlers.append(self._advanced)
```

### HELP_TEXT Erweiterung

```
📇 Kontakte:
  kontakt: Name, Rolle, Email, Anrede – Kontakt anlegen
    Beispiel: kontakt: Herr Müller, Vermieter, info@mueller.de, förmlich
  wer ist <n>? – Kontakt abrufen
  kontakte – Alle Kontakte anzeigen
  kontakte suche <Begriff> – Kontakt suchen
  kontakt löschen #<ID> – Kontakt löschen
  kontakt löschen <n> – Per Name löschen
```

### scripts/start.py

```python
from elder_berry.tools.contact_store import ContactStore

contact_store = ContactStore()
logger.info("ContactStore initialisiert: %s", contact_store._db_path)

# An RemoteCommandHandler durchreichen:
remote_commands = RemoteCommandHandler(
    # ... bestehende Parameter ...
    contact_store=contact_store,  # NEU
)
```
---

## 5. Design-Entscheidungen

1. **Eigene DB-Datei**: `contacts.db` statt Erweiterung von `notes.db`.
   Begründung: Kontakte haben ein festes Schema (Name, Email, Rolle etc.),
   Notizen sind frei. Verschiedene Lebensdauer, verschiedene Backup-Strategien.

2. **Name als Primary Key (logisch)**: UNIQUE Index auf (user_id, name COLLATE NOCASE).
   "kontakt: Herr Müller, neue-email@x.de" updated den bestehenden Müller,
   statt einen Duplikat anzulegen. Das ist intuitiver als IDs für User.

3. **find_by_email als Kernfeature**: Das ist die Integration mit Phase 28.
   Email → ContactStore → Kontext für LLM. Muss schnell sein (Index).

4. **Formality Default "förmlich"**: Im Deutschen ist man per Default per Sie.
   Wer "locker" will, muss es explizit sagen. Besser zu förmlich als zu locker.

5. **Keine separate Email-Tabelle**: Ein Kontakt = eine Email. Für den Anfang
   reicht das. Wenn jemand mehrere Emails hat, kann er mehrere Kontakte
   anlegen oder die Email später ändern. Komplexität vermeiden.

6. **"wer ist" statt "was ist"**: Klare sprachliche Trennung zu NoteStore.
   "was ist X?" → Fakt. "wer ist X?" → Person. Kein Pattern-Konflikt.

---

## 6. Potenzielle Kollision: "wer ist" → LLM-Fallthrough

"wer ist X?" matched den CONTACT_WHO_PATTERN. Wenn kein Kontakt gefunden
wird, sollte der Command NICHT einfach "Kontakt nicht gefunden" sagen —
das wäre frustrierend bei allgemeinen Wissensfragen ("wer ist Einstein?").

**Lösung**: Bei "wer ist X" ohne Treffer im ContactStore → CommandResult
mit `success=False` zurückgeben, damit die Bridge den normalen LLM-Fallback
nutzt. Das LLM kann dann allgemeine Wissensfragen beantworten.

```python
def _cmd_contact_who(self, raw_text: str) -> CommandResult:
    match = CONTACT_WHO_PATTERN.match(raw_text.strip())
    name = match.group(1).strip()

    contact = self._store.find_by_name(self._user_id, name)
    if contact:
        return CommandResult(
            command="contact_who", success=True,
            text=f"📇 {contact.format_short()}"
                 + (f"\n📝 {contact.notes}" if contact.notes else ""),
        )

    # Kein Kontakt gefunden → KEIN Fehler, sondern Rückgabe None
    # damit die Bridge den normalen LLM-Flow nutzt
    return CommandResult(command="contact_who", success=False, text=None)
```

**Achtung**: Die Bridge muss bei `success=False` UND `text=None` den
Command-Result ignorieren und zum LLM weiterleiten. Aktuell sendet die
Bridge `result.text` bei jedem Command. Prüfen ob ein `text=None`-Check
schon existiert.
**Genauer betrachtet ist das ein echtes Problem**, weil die Bridge bei
einem erkannten Command sofort `return` macht:

```python
if command:
    await self._handle_remote_command(msg, command)
    return  # ← LLM wird nie erreicht!
```

Wenn `parse_command()` "wer ist Einstein?" als `contact_who` erkennt,
und der ContactStore keinen Treffer hat, kommt eine leere Antwort statt
einer LLM-Antwort.

**Lösung: Neues Feld `fallthrough` in CommandResult:**

```python
@dataclass
class CommandResult:
    # ... bestehende Felder ...
    fallthrough: bool = False
    """True wenn der Command nichts gefunden hat und die Bridge
    zum LLM-Fallback weiterleiten soll."""
```

In der Bridge, in `_handle_remote_command()`:

```python
if result.fallthrough:
    # Command erkannt aber nichts gefunden → weiter an LLM
    logger.debug("Command '%s' fallthrough → LLM", command)
    await self._handle_assistant_message(msg)
    return
```

Das NoteStore hat das gleiche Problem bei "was ist X?" — prüfen ob es
dort bereits eine Lösung gibt. Falls ja: gleiches Pattern verwenden.
---

## 7. Neue und geänderte Dateien

### Neue Dateien

| Datei | Beschreibung |
|-------|-------------|
| `src/elder_berry/tools/contact_store.py` | ContactStore – SQLite + FTS5 Kontaktspeicher |
| `src/elder_berry/comms/commands/contact_commands.py` | ContactCommandHandler – Matrix Commands |
| `tests/test_contact_store.py` | Tests für ContactStore |
| `tests/test_contact_commands.py` | Tests für ContactCommandHandler |

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `src/elder_berry/comms/commands/base.py` | `CommandResult`: +fallthrough Feld |
| `src/elder_berry/comms/commands/mail_commands.py` | +contact_store DI, Kontakt-Kontext in _generate_draft() |
| `src/elder_berry/comms/remote_commands.py` | +contact_store DI, ContactCommandHandler registrieren, HELP_TEXT |
| `src/elder_berry/comms/bridge.py` | fallthrough-Check in _handle_remote_command() |
| `scripts/start.py` | ContactStore erstellen + durchreichen |

---

## 8. Tests

### test_contact_store.py

```
TestContactStore:
  test_add_and_find_by_name              – Kontakt anlegen + per Name finden
  test_add_and_find_by_email             – Kontakt anlegen + per Email finden
  test_find_by_email_case_insensitive    – "MAX@X.DE" findet "max@x.de"
  test_upsert_by_name                    – Gleicher Name → Update statt Insert
  test_upsert_keeps_existing_fields      – Leere Felder überschreiben nicht
  test_update_by_id                      – Kontakt per ID aktualisieren
  test_update_nonexistent                – Unbekannte ID → None
  test_search_fts                        – Volltextsuche über Name + Role + Notes
  test_search_no_results                 – Kein Treffer → leere Liste
  test_list_all                          – Alle Kontakte auflisten
  test_list_all_empty                    – Keine Kontakte → leere Liste
  test_delete_by_id                      – Per ID löschen → True
  test_delete_by_id_not_found            – Unbekannte ID → False
  test_delete_by_name                    – Per Name löschen
  test_delete_by_name_case_insensitive   – "herr müller" löscht "Herr Müller"
  test_formality_default                 – Default ist "förmlich"
  test_unique_name_constraint            – Doppelter Name → Upsert, kein Error
  test_format_short                      – Einzeilige Darstellung
  test_format_for_llm                    – LLM-Kontext-String
  test_multi_user_isolation              – User A sieht User B's Kontakte nicht
  test_close                             – Verbindung sauber schließen
```
### test_contact_commands.py

```
TestContactAddPattern:
  test_kontakt_with_all_fields           – "kontakt: Müller, Vermieter, x@y.de, förmlich" → match
  test_neuer_kontakt                     – "neuer kontakt: Lisa, Schwester" → match
  test_kontakt_without_email             – "kontakt: Dr. Weber, Zahnarzt, förmlich" → match
  test_kontakt_minimal                   – "kontakt: Max" → match (nur Name)
  test_no_match_kontakte                 – "kontakte" → kein Match (ist simple_command)

TestContactWhoPattern:
  test_wer_ist_name                      – "wer ist Herr Müller?" → match
  test_wer_ist_without_question_mark     – "wer ist Lisa" → match
  test_no_match_was_ist                  – "was ist WLAN?" → kein Match (ist NoteStore)

TestContactSearchPattern:
  test_kontakte_suche                    – "kontakte suche Müller" → match
  test_kontakt_suche                     – "kontakt suche Zahnarzt" → match

TestContactDeletePattern:
  test_delete_by_id                      – "kontakt löschen #3" → match, group(1)="3"
  test_delete_by_name                    – "kontakt löschen Herr Müller" → match, group(2)
  test_loeschen_variation                – "kontakt lösche Lisa" → match

TestContactUpdatePattern:
  test_update_by_id                      – "kontakt ändern #3: email=neu@x.de" → match
  test_kontakt_id_aendern               – "kontakt #3 ändern: rolle=Chef" → match

TestParseContactFields:
  test_all_fields                        – Name, Rolle, Email, Anrede korrekt
  test_email_detection                   – "@" wird als Email erkannt
  test_formality_foermlich               – "förmlich"/"formell"/"sie" → förmlich
  test_formality_locker                  – "locker"/"informell"/"du" → locker
  test_formality_default                 – Ohne Angabe → förmlich
  test_extra_fields_to_notes             – Zusätzliche Felder → notes

TestCmdContactAdd:
  test_add_success                       – Kontakt wird angelegt
  test_add_upsert                        – Gleicher Name → Update
  test_no_store                          – Fehlermeldung "nicht konfiguriert"

TestCmdContactWho:
  test_found                             – Kontakt gefunden → Anzeige
  test_not_found_fallthrough             – Nicht gefunden → fallthrough=True

TestCmdContactList:
  test_list_contacts                     – Alle Kontakte auflisten
  test_list_empty                        – Keine Kontakte → "Keine Kontakte"

TestCmdContactSearch:
  test_search_results                    – Treffer anzeigen
  test_search_no_results                 – "Keine Kontakte gefunden"

TestCmdContactDelete:
  test_delete_by_id_success              – Gelöscht → Bestätigung
  test_delete_by_name_success            – Per Name gelöscht
  test_delete_not_found                  – Nicht gefunden → Fehler

TestContactKeywords:
  test_keyword_registration              – Keywords sind registriert
  test_command_descriptions              – Beschreibungen vorhanden
```
---

## 9. Implementierungsreihenfolge für Claude Code

### Schritt 1: ContactStore

1. **`contact_store.py`**: Neue Datei – SQLite + FTS5, alle CRUD-Methoden
   + `test_contact_store.py`

### Schritt 2: CommandResult erweitern

2. **`base.py`**: +fallthrough Feld (bool, default False)
   Prüfe ob NoteStore bei "was ist X?" ohne Treffer dasselbe Problem hat.
   Falls ja: gleiches Pattern dort auch einbauen.

### Schritt 3: ContactCommandHandler

3. **`contact_commands.py`**: Neue Datei – alle Patterns + Commands
   + `test_contact_commands.py`
   Besondere Aufmerksamkeit auf _parse_contact_fields() – das Komma-Parsing
   muss robust sein.

### Schritt 4: Integration

4. **`remote_commands.py`**: contact_store DI, ContactCommandHandler registrieren
   + HELP_TEXT ergänzen
   + Handler-Reihenfolge: nach _notes, vor _advanced
5. **`bridge.py`**: fallthrough-Check in _handle_remote_command()
6. **`mail_commands.py`**: contact_store DI, Kontakt-Kontext in _generate_draft()
   (nur wenn Phase 28 bereits implementiert ist — sonst überspringen)
7. **`scripts/start.py`**: ContactStore erstellen + durchreichen

### Schritt 5: Tests laufen lassen

8. Alle bestehenden Tests + neue Tests ausführen
   Besonders prüfen: "was ist X?" und "wer ist X?" kollidieren nicht

---

## 10. Hinweise für Claude Code

1. **NoteStore als Vorlage**: ContactStore folgt exakt dem NoteStore-Pattern
   (SQLite, WAL, FTS5, Thread-safe). Code-Struktur kopieren und anpassen.

2. **"wer ist" vs "was ist" Kollision**: CONTACT_WHO_PATTERN matched "wer ist".
   NOTE_GET_FACT_PATTERN matched "was ist". Sprachlich klar getrennt.
   Aber: in der Handler-Reihenfolge muss ContactCommandHandler NACH
   NoteCommandHandler kommen, falls es doch Überschneidungen gibt.
   Nein — andersrum: VOR NoteCommandHandler, weil "wer ist" spezifischer ist.
   Tatsächlich: keine Kollision, weil die Patterns unterschiedliche Wörter matchen.

3. **fallthrough in der Bridge**: Prüfe genau wie die Bridge aktuell mit
   success=False umgeht. Wenn sie bei success=False eine Fehlermeldung
   sendet (result.text), dann muss fallthrough VOR dem Text-Check geprüft werden.

4. **Upsert-Logik**: Beim Upsert (gleicher Name) sollen leere Felder den
   bestehenden Wert NICHT überschreiben. D.h. wenn der User
   "kontakt: Herr Müller, neue-email@x.de" sagt, soll die bestehende
   Rolle ("Vermieter") erhalten bleiben. SQL: nur non-empty Felder updaten.

5. **Plattformhinweis**: Alles plattformunabhängig (sqlite3 ist Standardbibliothek).

6. **Branch**: `feature/phase-29-kontaktbuch`
