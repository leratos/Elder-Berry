# Phase 36.3 – CardDAV Kontakte (Nextcloud-Sync)

## Kontext

ContactStore speichert Kontakte in SQLite (lokal, schnell, FTS5-Suche).
Phase 36.3 ergänzt einen optionalen CardDAV-Sync mit Nextcloud, damit
Kontakte auch auf dem Handy (DAVx5) und in der Nextcloud-Kontakte-App
verfügbar sind.

**Wichtig:** SQLite bleibt die primäre Datenquelle. CardDAV ist nur
ein Sync-Kanal — kein Echtzeit-Sync, kein Ersetzen von ContactStore.

Nextcloud 33 läuft auf `cloud.example.com`. Credentials sind
seit Phase 36.1 im SecretStore (nextcloud_url, nextcloud_user, nextcloud_app_password).

## Vorbereitung

1. Lies `docs/journal.txt` (letzte 80 Zeilen) für den aktuellen Stand
2. Lies `docs/concepts/phase-36-nextcloud-integration.md` (Abschnitt 36.3)
3. Lies `src/elder_berry/tools/contact_store.py` — das ist der bestehende Store
4. Lies `src/elder_berry/comms/commands/contact_commands.py` — bestehende Commands
5. Lies `CLAUDE.md` für Projektkonventionen
6. Erstelle Branch: `feature/phase-36-3-carddav-contacts`

## Architektur-Entscheidung: Sync-Richtungen

**Bidirektionaler manueller Sync:**

```
kontakte sync         → Pull (NC→lokal) + Push (lokal→NC)
kontakte sync push    → Nur lokal→NC
kontakte sync pull    → Nur NC→lokal
```

**Konflikt-Strategie:** Last-Write-Wins basierend auf `updated_at` (lokal)
vs. `REV`/`LAST-MODIFIED` (vCard). Bei Gleichstand: lokal gewinnt
(SQLite ist primär). Neue Kontakte auf einer Seite werden zur anderen
Seite hinzugefügt, nicht überschrieben.

**Mapping Contact ↔ vCard:**

| Contact-Feld | vCard-Property | Hinweise |
|---|---|---|
| name | FN (Formatted Name) | Pflichtfeld in vCard |
| email | EMAIL | Kann mehrere geben, wir nutzen die erste |
| role | ORG oder NOTE | ORG passt nicht immer ("Schwester"), besser als NOTE-Prefix |
| formality | X-ELDERBERRY-FORMALITY | Custom Extension (vCard erlaubt X-Properties) |
| notes | NOTE | Freitext |
| birthday | BDAY | Format: YYYY-MM-DD oder --MM-DD (Jahr unbekannt) |
| id | UID | Lokal generiert: `elderberry-contact-{id}` |

**Nicht gemappt:** `user_id` (lokal, Matrix-spezifisch), `created_at`/`updated_at`
(werden beim Sync aktualisiert).

## Neue Dateien

### 1. `src/elder_berry/tools/carddav_sync.py`

Klasse `CardDAVSyncClient` — CardDAV-Sync für Nextcloud Contacts.

**Credentials aus SecretStore (identisch mit Files + CalDAV):**
- `nextcloud_url` → `https://cloud.example.com`
- `nextcloud_user` → Nextcloud-Benutzername
- `nextcloud_app_password` → App-Passwort

**CardDAV-Basis-URL:**
`{nextcloud_url}/remote.php/dav/addressbooks/users/{user}/contacts/`

("contacts" ist der Standard-Adressbuch-Name in Nextcloud.)

**Dependencies:**
- `httpx` (bereits vorhanden) — für CardDAV-HTTP-Requests
- `vobject` (NEU) — für vCard-Parsing und -Erstellung

`vobject` ist die Standard-Library für vCard in Python, klein, stabil,
keine transitiven Dependencies. Alternative wäre manuelles vCard-String-Bauen,
aber das ist fehleranfällig (Escaping, Folding, etc.).

**Klasse:**
```python
from dataclasses import dataclass

@dataclass
class SyncResult:
    """Ergebnis einer Sync-Operation."""
    pushed: int          # Kontakte lokal → Nextcloud geschrieben
    pulled: int          # Kontakte Nextcloud → lokal geschrieben
    conflicts: int       # Konflikte (lokal gewinnt)
    errors: list[str]    # Fehlermeldungen

class CardDAVSyncClient:
    def __init__(self, secret_store: SecretStore) -> None: ...
    def is_available(self) -> bool: ...

    def push_contacts(self, contacts: list[Contact], user_id: str) -> SyncResult:
        """Lokale Kontakte → Nextcloud (PUT vCards)."""
        ...

    def pull_contacts(self, user_id: str) -> list[Contact]:
        """Nextcloud → lokale Contact-Objekte (GET + Parse vCards)."""
        ...

    def sync(self, contact_store: ContactStore, user_id: str) -> SyncResult:
        """Bidirektionaler Sync: Pull + Merge + Push."""
        ...
```

**Implementierungsdetails je Methode:**

`push_contacts(contacts, user_id)`:
- Für jeden Contact: `_contact_to_vcard()` → vCard-String
- UID: `elderberry-contact-{contact.id}` (deterministisch, idempotent)
- PUT auf `{carddav_url}/{uid}.vcf` mit Content-Type `text/vcard; charset=utf-8`
- HTTP Basic Auth (user + app_password)
- Bei 201 (Created) oder 204 (Updated): Erfolg
- Bei Fehler: in errors-Liste aufnehmen, weiter mit nächstem

`pull_contacts(user_id)`:
- PROPFIND auf CardDAV-URL mit Depth:1
- Für jedes `<d:response>` mit `.vcf` in href: GET → vCard-String
- Alternativ (effizienter): Multiget REPORT für alle vCards auf einmal
- `_vcard_to_contact()` → Contact-Objekt (ohne id, wird beim Merge zugewiesen)
- Rückgabe: Liste von Contact-Objekten (noch nicht in DB)

`sync(contact_store, user_id)`:
1. Lokale Kontakte laden: `contact_store.list_all(user_id, limit=1000)`
2. Remote Kontakte laden: `pull_contacts(user_id)`
3. Merge:
   - Match per Name (case-insensitive) — Name ist der natürliche Key
   - Lokal vorhanden + Remote nicht: → Push (lokaler Kontakt → NC)
   - Remote vorhanden + Lokal nicht: → Pull (NC-Kontakt → ContactStore.add)
   - Beide vorhanden: updated_at vs. vCard REV vergleichen
     - Lokal neuer: Push (überschreibe NC)
     - Remote neuer: Pull (überschreibe lokal via ContactStore.update)
     - Gleichstand: Skip (kein Konflikt)
4. Push neue/aktualisierte Kontakte
5. Rückgabe: SyncResult

**vCard-Konvertierung:**

```python
import vobject

def _contact_to_vcard(self, contact: Contact) -> str:
    """Konvertiert Contact → vCard 3.0 String."""
    card = vobject.vCard()
    card.add("fn").value = contact.name
    card.add("uid").value = f"elderberry-contact-{contact.id}"
    card.add("rev").value = contact.updated_at.strftime("%Y%m%dT%H%M%SZ")

    if contact.email:
        card.add("email").value = contact.email

    if contact.birthday:
        bday = card.add("bday")
        if contact.birthday.startswith("0000-"):
            # Jahr unbekannt → --MM-DD (vCard partial date)
            bday.value = "--" + contact.birthday[5:]
        else:
            bday.value = contact.birthday

    if contact.notes or contact.role:
        # Role als Prefix in NOTE (ORG passt semantisch nicht immer)
        note_parts = []
        if contact.role:
            note_parts.append(f"Rolle: {contact.role}")
        if contact.notes:
            note_parts.append(contact.notes)
        card.add("note").value = "\n".join(note_parts)

    # Custom Extension für Anrede-Stil
    if contact.formality:
        card.add("x-elderberry-formality").value = contact.formality

    return card.serialize()

def _vcard_to_contact(self, vcard_str: str, user_id: str) -> Contact | None:
    """Parst vCard-String → Contact (ohne DB-ID)."""
    try:
        card = vobject.readOne(vcard_str)
    except Exception as e:
        logger.warning("vCard parse error: %s", e)
        return None

    fn = str(getattr(card, "fn", None) and card.fn.value or "")
    if not fn:
        return None

    email = ""
    if hasattr(card, "email"):
        email = str(card.email.value)

    birthday = ""
    if hasattr(card, "bday"):
        bday_val = str(card.bday.value)
        if bday_val.startswith("--"):
            # Partial date → 0000-MM-DD
            birthday = "0000-" + bday_val[2:]
        else:
            birthday = bday_val[:10]  # YYYY-MM-DD

    role = ""
    notes = ""
    if hasattr(card, "note"):
        note_text = str(card.note.value)
        # Rolle aus NOTE extrahieren wenn mit "Rolle: " beginnt
        lines = note_text.split("\n")
        remaining = []
        for line in lines:
            if line.startswith("Rolle: "):
                role = line[7:]
            else:
                remaining.append(line)
        notes = "\n".join(remaining).strip()

    formality = "förmlich"
    # X-ELDERBERRY-FORMALITY auslesen
    for child in card.getChildren():
        if child.name.upper() == "X-ELDERBERRY-FORMALITY":
            formality = str(child.value)
            break

    now = datetime.now(timezone.utc)
    return Contact(
        id=0,  # Wird beim Import durch ContactStore vergeben
        user_id=user_id,
        name=fn, email=email, role=role,
        formality=formality, notes=notes,
        birthday=birthday,
        created_at=now, updated_at=now,
    )
```

**CardDAV HTTP-Details:**

PROPFIND (Adressbuch-Inhalt auflisten):
```http
PROPFIND /remote.php/dav/addressbooks/users/{user}/contacts/ HTTP/1.1
Depth: 1
Content-Type: application/xml

<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:getetag/>
    <d:getcontenttype/>
  </d:prop>
</d:propfind>
```
Response enthält `<d:href>` für jede `.vcf`-Datei.

GET (einzelne vCard abrufen):
```http
GET /remote.php/dav/addressbooks/users/{user}/contacts/{uid}.vcf HTTP/1.1
```

PUT (vCard erstellen/aktualisieren):
```http
PUT /remote.php/dav/addressbooks/users/{user}/contacts/{uid}.vcf HTTP/1.1
Content-Type: text/vcard; charset=utf-8

BEGIN:VCARD
VERSION:3.0
FN:Herr Müller
...
END:VCARD
```

DELETE (vCard löschen):
```http
DELETE /remote.php/dav/addressbooks/users/{user}/contacts/{uid}.vcf HTTP/1.1
```

- Auth: HTTP Basic Auth (wie NextcloudFilesClient)
- Timeout: 10s für Listing, 15s für Sync-Operationen
- Fehler: `NextcloudError` (aus nextcloud_files.py importieren)

### 2. `tests/test_carddav_sync.py`

Tests für `CardDAVSyncClient`. HTTP komplett gemockt.

**Test-Kategorien (~25 Tests):**

Credentials & Verfügbarkeit:
- `test_is_available_success` — Credentials vorhanden + Server erreichbar
- `test_is_available_no_credentials` — Fehlende Credentials → False
- `test_is_available_server_unreachable` — Timeout → False

vCard-Konvertierung:
- `test_contact_to_vcard_full` — Alle Felder gesetzt
- `test_contact_to_vcard_minimal` — Nur Name
- `test_contact_to_vcard_birthday_unknown_year` — 0000-MM-DD → --MM-DD
- `test_contact_to_vcard_with_role_in_note` — Rolle als NOTE-Prefix
- `test_contact_to_vcard_formality_extension` — X-ELDERBERRY-FORMALITY
- `test_vcard_to_contact_full` — Alle Properties parsen
- `test_vcard_to_contact_minimal` — Nur FN
- `test_vcard_to_contact_partial_birthday` — --MM-DD → 0000-MM-DD
- `test_vcard_to_contact_role_from_note` — "Rolle: xyz" extrahieren
- `test_vcard_to_contact_formality_from_extension` — X-Property lesen
- `test_vcard_to_contact_no_fn` — Kein FN → None (skip)
- `test_vcard_to_contact_external` — vCard ohne X-ELDERBERRY → Default förmlich

Push:
- `test_push_contacts_success` — PUT für jeden Kontakt
- `test_push_contacts_server_error` — Einzelner Fehler → in errors-Liste
- `test_push_contacts_empty` — Leere Liste → SyncResult(0,0,0,[])

Pull:
- `test_pull_contacts_success` — PROPFIND + GET + Parse
- `test_pull_contacts_empty_addressbook` — Leeres Adressbuch → []
- `test_pull_contacts_skip_invalid` — Ungültige vCard → überspringen

Sync:
- `test_sync_new_local_pushed` — Lokaler Kontakt fehlt in NC → Push
- `test_sync_new_remote_pulled` — NC-Kontakt fehlt lokal → Pull
- `test_sync_local_newer_pushes` — Lokal neuer → Push gewinnt
- `test_sync_remote_newer_pulls` — Remote neuer → Pull gewinnt
- `test_sync_both_same_skips` — Gleicher Stand → kein Update

## Zu ändernde Dateien

### 3. `src/elder_berry/comms/commands/contact_commands.py`

Neue Patterns + Command für Sync:

```python
CONTACT_SYNC_PATTERN = re.compile(
    r"^kontakte?\s+sync(?:\s+(push|pull))?\s*$",
    re.IGNORECASE,
)
```

- `kontakte sync` → bidirektionaler Sync
- `kontakte sync push` → nur lokal → NC
- `kontakte sync pull` → nur NC → lokal

**DI:** Neuer Parameter `carddav_sync: CardDAVSyncClient | None = None`

**Pattern in patterns-Liste einfügen** (VOR CONTACT_ADD_PATTERN, da "kontakte sync"
sonst als "kontakt: sync" geparst werden könnte).

**command_descriptions erweitern:**
```
"kontakte sync – Kontakte mit Nextcloud synchronisieren",
"kontakte sync push – Nur lokal → Nextcloud",
"kontakte sync pull – Nur Nextcloud → lokal",
```

### 4. `tests/test_contact_commands.py`

Neue Tests für Sync-Command (~5 Tests):
- `test_sync_pattern_bidirectional` — "kontakte sync"
- `test_sync_pattern_push` — "kontakte sync push"
- `test_sync_pattern_pull` — "kontakte sync pull"
- `test_sync_no_carddav` — Client fehlt → Fehlermeldung
- `test_sync_success` — Erfolgreicher Sync mit gemocktem Client

### 5. `src/elder_berry/comms/remote_commands.py`

- TYPE_CHECKING: `from elder_berry.tools.carddav_sync import CardDAVSyncClient`
- `__init__`: Neuer Parameter `carddav_sync: CardDAVSyncClient | None = None`
- An ContactCommandHandler durchreichen: `carddav_sync=carddav_sync`
- HELP_TEXT: Sync-Sektion unter Kontakte ergänzen:
  ```
  kontakte sync – Kontakte mit Nextcloud synchronisieren
  kontakte sync push – Nur lokal → Nextcloud
  kontakte sync pull – Nur Nextcloud → lokal
  ```

### 6. `scripts/start_saleria.py`

In `_init_productivity_services()`:
```python
# Nextcloud CardDAV Sync
if secrets.get_or_none("nextcloud_url"):
    try:
        from elder_berry.tools.carddav_sync import CardDAVSyncClient
        carddav = CardDAVSyncClient(secret_store=secrets)
        if carddav.is_available():
            svc["carddav_sync"] = carddav
            logger.info("CardDAV Sync: aktiv (%s)", secrets.get("nextcloud_url"))
    except ImportError:
        logger.debug("CardDAV: vobject nicht installiert")
    except Exception as e:
        logger.warning("CardDAV Sync nicht verfügbar: %s", e)
```

Im `RemoteCommandHandler(...)` Aufruf:
```python
carddav_sync=svc.get("carddav_sync"),
```

Im `ContactCommandHandler(...)` Aufruf (innerhalb RemoteCommandHandler.__init__):
```python
ContactCommandHandler(
    contact_store=contact_store,
    default_user_id=default_user_id,
    carddav_sync=carddav_sync,  # NEU
)
```

### 7. `pyproject.toml`

Die `[nextcloud]` Gruppe erweitern:
```toml
nextcloud = [
    "caldav>=1.0",
    "vobject>=0.9",
]
```

## Edge Cases und Fallstricke

**vCard-Encoding:** vCards können UTF-8, QUOTED-PRINTABLE oder BASE64-kodiert sein.
`vobject` handhabt das automatisch. Trotzdem: beim Schreiben immer UTF-8 erzwingen.

**Kontakte ohne Name:** vCard erfordert FN. Beim Pull: vCards ohne FN überspringen.
Beim Push: Kontakte ohne Name kommen aus ContactStore nicht vor (Pflichtfeld).

**Doppelte Kontakte:** Matching per Name (case-insensitive). Wenn jemand
"Herr Müller" lokal hat und "Hr. Müller" in Nextcloud, werden das zwei
verschiedene Kontakte. Das ist akzeptabel — perfektes Matching ist unmöglich
ohne UUIDs, und die existieren erst nach dem ersten Sync.

**Nach erstem Push:** Alle Kontakte haben eine UID (`elderberry-contact-{id}`).
Weitere Syncs matchen per UID wenn vorhanden, per Name als Fallback.

**Externe Kontakte:** Kontakte die manuell in Nextcloud oder per DAVx5 angelegt
wurden haben keine `elderberry-contact-*` UID. Beim Pull werden sie per Name
gematcht oder als neue Kontakte importiert.

**Große Adressbücher:** Bei >100 Kontakten kann der Sync langsam werden
(ein HTTP-Request pro vCard). Das ist akzeptabel für manuellen Sync.
Für die Zukunft: Multiget REPORT (ein Request für alle vCards).

## Was NICHT gemacht wird

- Kein Echtzeit-Sync (zu komplex, Konflikte)
- Kein automatischer Sync per Timer (manuell per Command)
- Kein Löschen über Sync (wenn ein Kontakt lokal gelöscht wird, bleibt er in NC)
- Kein Merge von mehreren Email-Adressen (nur die erste wird gemappt)
- ContactStore-Schema wird NICHT geändert (kein UID-Feld — die UID wird
  deterministisch aus der ID berechnet)

## Reihenfolge

1. `CardDAVSyncClient` implementieren (carddav_sync.py)
2. Tests schreiben (test_carddav_sync.py) — ~25 Tests, HTTP gemockt
3. `contact_commands.py` anpassen (Sync-Pattern + Command)
4. Tests für Sync-Command ergänzen (test_contact_commands.py) — ~5 Tests
5. `remote_commands.py` anpassen (DI durchreichen + HELP_TEXT)
6. `start_saleria.py` anpassen (CardDAV Init + DI)
7. `pyproject.toml` — `vobject>=0.9` zur `[nextcloud]` Gruppe
8. Alle Tests ausführen, 0 Fehler
9. Journal-Eintrag abschließen
10. Commit auf Branch
