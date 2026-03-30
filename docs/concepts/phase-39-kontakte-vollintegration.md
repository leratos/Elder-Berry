# Phase 39 – Kontakte: Vollintegration Nextcloud + Saleria

> **Status:** Konzept
> **Erstellt:** 2026-03-30
> **Abhängigkeit:** ContactStore (Phase 29), CardDAV-Sync (Phase 36.3),
>   SmartContextProvider (Phase 21), BriefingScheduler (Phase 8.3),
>   Intent-Routing (Phase 22)

---

## Ziel

Saleria kennt **alle** Informationen aus den Nextcloud-Kontakten und kann
natürliche Fragen über Personen beantworten. Nextcloud ist die vollständige
Datenquelle, Saleria ergänzt eigene Metadaten (Rolle, Anrede, Notizen).

**Aktuell:**
```
Nutzer: "Wann hat Lisa Geburtstag?"
Saleria: [kein Pattern-Match → LLM-Fallback → Glückssache]

Nutzer: "Was ist die Adresse von Herrn Müller?"
Saleria: [Adresse existiert nicht im Datenmodell]

Nutzer: "Welche Kontakte hab ich in der Gruppe Familie?"
Saleria: [Gruppen werden nicht gesynct]
```

**Ziel:**
```
Nutzer: "Wann hat Lisa Geburtstag?"
Saleria: "Lisa hat am 15. Juni Geburtstag – in 77 Tagen."

Nutzer: "Was ist die Adresse von Herrn Müller?"
Saleria: "Herr Müller wohnt in Musterstr. 42, 10115 Berlin."

Nutzer: "Welche Kontakte hab ich in der Gruppe Familie?"
Saleria: "In deiner Gruppe Familie: Lisa, Max, Oma Helga."

Nutzer: "Ruf Lisa an"
Saleria: "Lisa hat zwei Nummern: Mobil +49 170 123... und Festnetz +49 30 456...
          Welche soll ich wählen?"
```

---

## Ist-Zustand (nach Bugfix-Branch)

### Contact-Dataclass
| Feld | Quelle | Gesynct | In SmartContext | Im Briefing |
|------|--------|---------|-----------------|-------------|
| name | NC + lokal | ja (FN) | ja | ja |
| email | NC + lokal | ja (EMAIL) | ja | nein |
| phone | NC + lokal | ja (TEL, 1x) | **nein** | nein |
| role | lokal | ja (NOTE-Prefix) | ja | nein |
| formality | lokal | ja (X-ELDERBERRY) | nein | nein |
| notes | lokal | ja (NOTE) | nein (nur FTS) | nein |
| birthday | NC + lokal | ja (BDAY) | nein | ja (get_birthdays_today) |

### Was Nextcloud hat, aber Saleria nicht kennt
| vCard-Property | Beschreibung | Beispiel |
|----------------|-------------|---------|
| **ADR** | Strukturierte Adresse | Musterstr. 42, 10115 Berlin |
| **ORG** | Organisation / Firma | Acme Corp |
| **TITLE** | Jobtitel | Software Engineer |
| **CATEGORIES** | Gruppen / Tags | Familie, Arbeit, Ärzte |
| **URL** | Website | https://example.com |
| **ANNIVERSARY** | Jahrestag | 2010-06-15 |
| **N** | Strukturierter Name | Vorname/Nachname/Titel getrennt |
| **NICKNAME** | Spitzname | Hansi |
| **Mehrere TEL** | Mobil, Festnetz, Arbeit | TEL;TYPE=CELL / TEL;TYPE=HOME |
| **Mehrere EMAIL** | Privat, Arbeit | EMAIL;TYPE=WORK / EMAIL;TYPE=HOME |
| **PHOTO** | Kontaktfoto | Base64 oder URL |

### SmartContextProvider – Lücken
- Erkennt Keywords: kontakt, telefon, nummer, email, adresse, anrufen
- Injiziert aber nur: **name, email, role** — kein phone, birthday, notes
- "Wann hat Lisa Geburtstag?" triggert Kontakt-Kontext nicht (kein Keyword-Match
  für "geburtstag" in der Kontakt-Source)

---

## Lösung

### Schritt 1: Contact-Datenmodell erweitern

Neue Felder im Contact-Dataclass + SQLite-Schema:

```python
@dataclass(frozen=True)
class Contact:
    # Bestehend:
    id, user_id, name, email, phone, role, formality, notes, birthday
    created_at, updated_at

    # Neu:
    address: str        # Freitext-Adresse (aus ADR zusammengesetzt)
    organization: str   # Firma / Organisation
    title: str          # Jobtitel
    categories: str     # Komma-separierte Gruppen ("Familie, Arbeit")
    nickname: str       # Spitzname
    anniversary: str    # Jahrestag (YYYY-MM-DD)
    url: str            # Website
    phones: str         # JSON: [{"type": "cell", "number": "+49..."},
                        #         {"type": "home", "number": "+49..."}]
    emails: str         # JSON: [{"type": "work", "email": "x@y.de"},
                        #         {"type": "home", "email": "a@b.de"}]
```

**Design-Entscheidung:** `phones` / `emails` als JSON-String statt
Normalisierung in eigene Tabellen. Grund: Kontakte sind read-heavy,
JSON reicht für Anzeige + LLM-Kontext. FTS5 indexiert trotzdem.

**Migration:** `_migrate_*_column()` analog zu birthday/phone für jedes
neue Feld. Bestehende DBs bekommen leere Defaults.

### Schritt 2: CardDAV-Sync erweitern

**Pull (`_vcard_to_contact`):**

```python
# ADR → address (Freitext zusammengesetzt)
if hasattr(card, "adr"):
    adr = card.adr.value
    parts = [adr.street, f"{adr.code} {adr.city}", adr.country]
    address = ", ".join(p for p in parts if p)

# ORG → organization
if hasattr(card, "org"):
    organization = " / ".join(card.org.value)

# TITLE → title
if hasattr(card, "title"):
    title = str(card.title.value)

# CATEGORIES → categories (komma-separiert)
if hasattr(card, "categories"):
    categories = ", ".join(card.categories.value)

# Mehrere TEL → phones (JSON)
phones = []
for tel in card.contents.get("tel", []):
    phone_type = tel.params.get("TYPE", ["cell"])[0].lower()
    phones.append({"type": phone_type, "number": str(tel.value)})

# Mehrere EMAIL → emails (JSON)
emails = []
for em in card.contents.get("email", []):
    email_type = em.params.get("TYPE", ["home"])[0].lower()
    emails.append({"type": email_type, "email": str(em.value)})
```

**Push (`_contact_to_vcard`):** Rückkonvertierung. `address` → ADR,
`categories` → CATEGORIES, `phones` JSON → mehrere TEL-Properties, etc.

**Achtung:** Push darf Nextcloud-Daten nicht überschreiben wenn das
lokale Feld leer ist. Nur Elder-Berry-eigene Felder (role, formality,
notes) werden aktiv gepusht. Rest: NC ist die Quelle.

### Schritt 3: SmartContextProvider erweitern

**Keywords erweitern:**
```python
ContextSource.CONTACTS: [
    # Bestehend:
    "kontakt", "kontakte", "telefon", "nummer", "email",
    "adresse", "anrufen", "telefonnummer",
    # Neu:
    "geburtstag", "birthday", "wohnt", "arbeitet",
    "gruppe", "kategorie", "firma", "organisation",
    "jahrestag", "spitzname", "website",
]
```

**Kontext-Injection erweitern:**
Statt nur `name, email, role` → alle relevanten Felder:
```python
def _query_contacts(self, user_input):
    results = self._contact_store.search(user_id, user_input, limit=3)
    lines = []
    for c in results:
        lines.append(c.format_for_llm())  # ← nutzt format_for_llm()
    return "\n\n".join(lines)
```

`format_for_llm()` erweitern um alle neuen Felder:
```
Kontakt: Herr Müller
Beziehung: Vermieter
Anrede: förmlich (Sie)
Telefon: +49 170 123... (Mobil), +49 30 456... (Festnetz)
Email: mueller@immo.de (Arbeit), hans@web.de (Privat)
Adresse: Musterstr. 42, 10115 Berlin
Firma: Müller Immobilien GmbH
Geburtstag: 1970-05-15
Gruppen: Arbeit, Vermieter
```

### Schritt 4: Natürliche Kontakt-Abfragen (Pattern)

Neues Pattern `CONTACT_FIELD_QUERY_PATTERN` für gezielte Feld-Abfragen:

```python
# "Wann hat Lisa Geburtstag?"
# "Was ist die Adresse von Herrn Müller?"
# "Wie ist die Telefonnummer von Lisa?"
# "In welcher Gruppe ist Dr. Weber?"
# "Wo arbeitet Max?"
CONTACT_FIELD_QUERY_PATTERN = re.compile(
    r"^(?:wann\s+hat\s+(.+?)\s+geburtstag"
    r"|(?:was|wie)\s+ist\s+(?:die\s+)?(?:adresse|telefonnummer|email|nummer)"
    r"\s+von\s+(.+?)"
    r"|in\s+welcher\s+gruppe\s+ist\s+(.+?)"
    r"|wo\s+(?:arbeitet|wohnt)\s+(.+?))\??\s*$",
    re.IGNORECASE,
)
```

Handler gibt gezielt nur das gefragte Feld aus:
```
"Wann hat Lisa Geburtstag?"
→ "Lisa hat am 15. Juni 1990 Geburtstag – in 77 Tagen."

"Was ist die Adresse von Herrn Müller?"
→ "Herr Müller: Musterstr. 42, 10115 Berlin"

"Wie ist die Telefonnummer von Lisa?"
→ "Lisa hat 2 Nummern:
     Mobil: +49 170 1234567
     Festnetz: +49 30 9876543"
```

### Schritt 5: Briefing erweitern

**Geburtstags-Sektion verbessern:**
- Aktuell: nur "heute Geburtstag"
- Neu: auch "morgen" und "diese Woche"
- Gruppe anzeigen wenn vorhanden: "Lisa (Familie) wird 36"

**Jahrestage im Briefing:**
- Anniversary-Feld aus Nextcloud → "Dein Hochzeitstag ist in 3 Tagen"

**Namenstage (optional, niedrige Prio):**
- Nicht in Nextcloud, wäre ein eigenes Feature

### Schritt 6: Gruppen-basierte Features

- `kontakte gruppe Familie` → listet alle Kontakte in der Gruppe
- `kontakte gruppe Ärzte` → listet Ärzte mit Telefonnummern
- Default-Anrede per Gruppe: Familie → locker, Arbeit → förmlich
  (nur wenn kein explizites formality gesetzt)
- Gruppen als Filter in der Kontakt-Suche

---

## Sync-Strategie

### Nextcloud = Quelle der Wahrheit für:
- Name, Adresse, Telefonnummern, Emails, Geburtstag, Organisation,
  Titel, Gruppen, Jahrestag, Website, Spitzname, Foto

### Elder-Berry = Quelle der Wahrheit für:
- role (Beziehung/Kontext: "Vermieter", "Schwester")
- formality (Anrede-Stil: förmlich/locker)
- notes (Saleria-spezifische Notizen)

### Sync-Regeln:
1. **Pull:** NC-Felder überschreiben immer lokale NC-Felder
2. **Push:** Nur Elder-Berry-eigene Felder (role, formality, notes)
   werden nach NC gepusht (als NOTE + X-ELDERBERRY-*)
3. **Konflikt:** Bei NC-Feldern gewinnt NC. Bei EB-Feldern gewinnt lokal.
4. **Löschen:** Kontakt in NC gelöscht → lokal als "archiviert" markieren,
   nicht hart löschen (Notizen könnten wertvoll sein)

---

## Nicht in dieser Phase

- **Kontakt-Foto als Avatar:** Anzeigelogik für Pepper's Ghost (eigene Phase)
- **Pronomen-Auflösung:** "Ruf sie an" → bezieht sich auf letzte Lisa-Erwähnung
  (braucht Konversations-State, siehe Phase 20)
- **Automatischer Sync-Timer:** Sync bleibt manuell per "kontakte sync"
  (automatisch wäre ein Daemon mit Polling, zu viel Scope)
- **Kontakt-Erstellung in Nextcloud:** Aktuell nur Push bestehender Kontakte.
  "Neuer Kontakt" erstellt lokal, Push erzeugt vCard in NC.
- **Mehrere Adressbücher:** Nur Standard-Adressbuch wird gesynct

---

## Scope

### Neue Dateien
| Datei | Beschreibung |
|-------|-------------|
| tests/test_contact_field_query.py | Tests für Feld-Abfrage-Pattern |

### Geänderte Dateien
| Datei | Änderung |
|-------|----------|
| `tools/contact_store.py` | Neue Felder, Migrationen, format_detail/for_llm erweitern |
| `tools/carddav_sync.py` | Alle vCard-Properties parsen + schreiben |
| `comms/commands/contact_commands.py` | CONTACT_FIELD_QUERY_PATTERN, Gruppen-Commands |
| `core/smart_context.py` | Keywords erweitern, format_for_llm nutzen |
| `comms/briefing_scheduler.py` | Geburtstage morgen/diese Woche, Jahrestage |
| Tests | ~30-40 neue Tests |

### Teilschritte (Empfehlung)
1. Datenmodell + Migration (contact_store.py)
2. CardDAV-Sync erweitern (carddav_sync.py)
3. SmartContextProvider erweitern (smart_context.py)
4. Feld-Abfrage-Pattern + Handler (contact_commands.py)
5. Briefing erweitern (briefing_scheduler.py)
6. Gruppen-Features (contact_commands.py)

---

## Offene Entscheidungen

1. **JSON vs. Tabelle für phones/emails:** JSON im Text-Feld ist einfacher,
   aber FTS5 kann nicht einzelne Nummern matchen. Reicht `LIKE '%+49 170%'`?
   Oder brauchen wir eine contact_phones-Tabelle?

2. **Sync-Frequenz:** Manuell (`kontakte sync`) oder periodisch (z.B. alle
   6 Stunden)? Manuell ist einfacher, periodisch bequemer.

3. **Archivierung gelöschter Kontakte:** Soft-Delete mit `archived_at`-Feld?
   Oder komplett löschen und nur die NC-Daten als Quelle akzeptieren?

4. **Foto-Sync:** PHOTO-Property ist oft Base64 (mehrere KB). Im SQLite
   speichern oder als Datei auf Disk? Brauchen wir das überhaupt wenn kein
   Avatar-Display-Feature geplant ist?
