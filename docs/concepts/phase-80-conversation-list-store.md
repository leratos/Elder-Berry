# Phase 80 – ConversationListStore 📋

**Status:** Konzept (2026-05-08)
**Branch:** `feature/phase-80-conversation-list-store` (geplant)
**Aufwand:** ~1 Session
**Voraussetzung:** keine harte Abhängigkeit (kann unabhängig von Phase 79
geschehen)
**Roadmap-Referenz:** Reaktion auf Live-Befund Phase 78 — LLM
halluzinierte URLs beim „den 2. Link aus der Suche" weil die Liste nur
im Chat-History persistierte und durch Truncation verloren ging.

## 1. Ausgangslage

Saleria's heutige „nimm Eintrag N aus der Liste"-Pfade verlassen sich auf
das LLM-Gedächtnis: das Modell sieht im Chat-History die letzten N
Saleria-Antworten und soll daraus den richtigen Index wieder herausziehen.

**Live-Befund 2026-05-08 (Drohnen-Suche):**

```
User:    suche mir eine anleitung für den bau einer drohne raus
Saleria: 🔍 5 Ergebnisse: 1. formlabs.com … 2. fpv24.com … 3. heimwerker.de …
User:    fasse mir den 2 link zusammen
Saleria: → web_summary mit URL "www.fpv-drohne-bauen.de"   ← HALLUZINIERT
                                                            (nicht in Liste)
```

Mehrere Failure-Modi:
- LLM rät plausible URLs statt zurückzufragen.
- Nach Chat-History-Truncation ist die Liste komplett weg.
- Token-Verschwendung: 5 Treffer mit Snippets stehen in jedem Folge-LLM-
  Call im Kontext, obwohl nur ein Index gebraucht wird.

## 2. Ziel

Eine **interne Listen-Tabelle**, die strukturierte Mehrfachergebnisse
unabhängig vom LLM-Gedächtnis vorhält. Das LLM bekommt nur einen
**Listen-Index**, das System löst auf den realen Wert auf.

**Kern-Eigenschaften:**

1. Pro User maximal **eine aktive Liste pro `list_type`**. Neue Liste
   desselben Typs überschreibt die alte.
2. **TTL = 1 Stunde** ab letztem Zugriff. Cleanup-Pass entfernt
   abgelaufene Einträge.
3. Nicht-persistent: in-memory `dict`, ephemer. Geht beim Saleria-
   Restart verloren — das ist OK, weil die Listen kurzlebig sind und
   bei Bedarf neu erzeugt werden (suche neu, mail-inbox neu lesen, …).
4. Index-Convention: 1-basiert (User sagt „Treffer 2", nicht
   „Treffer 0"). Saleria-Antwort nummeriert konsistent.

**Nicht-Ziele:**

- Keine SQLite-Persistenz. Wenn Saleria neu startet, sind alle Listen
  weg. Das spart Migration + Lebenszyklus-Code.
- Keine Cross-User-Listen. Pro `user_id` getrennt.
- Keine Auto-Aggregation („alle Suchergebnisse der letzten Woche").
- Keine UI-Anbindung im Settings-Dashboard. Listen sind LLM-internes
  State, nicht Lera-Pflege.

## 3. Architektur

### 3.1 Klasse

```
src/elder_berry/tools/conversation_list_store.py
└── class ConversationListStore
    ├── register(user_id, list_type, items, expires_in=timedelta(hours=1))
    │       → list_ref (str)
    ├── get_item(user_id, list_ref, index) → item | None
    ├── get_active(user_id, list_type) → (list_ref, items) | None
    ├── pop_active(user_id, list_type) → (list_ref, items) | None
    └── _evict_expired() (intern, vor jedem read aufgerufen)
```

### 3.2 Datenmodell

```python
@dataclass(frozen=True)
class ListEntry:
    list_ref: str         # z.B. "search_2026_05_08_15_00_31_a3f9"
    list_type: str        # "search" | "mail_inbox" | "note_search" | ...
    user_id: str
    items: list[Any]      # heterogen pro list_type
    created_at: datetime
    last_accessed: datetime
    expires_at: datetime  # last_accessed + TTL
```

Storage: `dict[(user_id, list_type), ListEntry]`. Maximal ein Eintrag
pro Tupel. Bei `register()` mit existierendem Tupel → alter Eintrag
wird überschrieben (mit Info-Log: „Liste {old_ref} ueberschrieben
durch {new_ref}").

### 3.3 list_ref-Format

`{list_type}_{ISO-timestamp-no-ms}_{4-char-hash}`. Beispiele:
- `search_20260508T150031_a3f9`
- `mail_inbox_20260508T160012_b71c`
- `note_search_20260508T161205_d82e`

`list_ref` ist nur internal — der User soll ihn nicht sehen müssen
(„Treffer 2" reicht). Aber er ist eindeutig für den LLM, falls eine
Disambiguation nötig wird („alte search-Liste oder neue?").

### 3.4 Integration mit bestehenden Commands

**Beispiel `web_search`** (advanced_commands.py):

```python
# heute:
results = self._search_client.search(query)
return CommandResult(
    command="web_search",
    text=format_search_results(results),  # Markdown mit 1./2./3. ...
)

# nach Phase 80:
results = self._search_client.search(query)
list_ref = self._conversation_lists.register(
    user_id=ctx.sender,
    list_type="search",
    items=[
        {"title": r.title, "url": r.url, "snippet": r.snippet}
        for r in results
    ],
)
return CommandResult(
    command="web_search",
    text=format_search_results(results, list_ref=list_ref),
    history_text=...  # damit auch das LLM weiss was Saleria zeigte
)
```

**Neuer Command `list_pick`** (oder als Action im LLM-Routing):

```python
# LLM-System-Prompt-Erweiterung:
"""
Wenn der User auf eine Listen-Position referenziert ('Treffer 2',
'der zweite Link', 'Eintrag 4', 'die dritte Mail'), antworte mit:

  {"action": "list_pick", "params": {"list_type": "search", "index": 2}}

Triggere KEIN web_summary mit halluzinierter URL. Wenn es keine
aktive Liste gibt, frage zurueck.
"""

# Bridge-Handler list_pick:
async def handle_list_pick(self, msg, params):
    active = self._conversation_lists.get_active(
        msg.sender, params["list_type"]
    )
    if active is None:
        await self._channel.send_text(
            msg.room_id,
            "Keine aktive Liste vom Typ '{}' -- frag mich nach einer "
            "neuen Suche / Mail-Inbox / Notiz-Suche.".format(params["list_type"])
        )
        return
    list_ref, items = active
    idx = params["index"] - 1  # 1-basiert -> 0-basiert
    if idx < 0 or idx >= len(items):
        await self._channel.send_text(
            msg.room_id,
            f"Liste hat nur {len(items)} Eintraege; #{params['index']} "
            "existiert nicht."
        )
        return
    item = items[idx]
    # Trigger Folge-Action (typ-spezifisch):
    if params["list_type"] == "search":
        await self.handle_remote_command_with_text(
            msg, command="web_summary",
            text=f"fasse {item['url']} zusammen",
        )
    elif params["list_type"] == "mail_inbox":
        # ... mail_by_id
```

### 3.5 Liste-Typen (Phase-80-Liefereumfang)

Phase 80 baut die Infrastruktur + integriert **drei** Listen-Typen
als Beispiel:

| `list_type` | Quelle | Items |
|---|---|---|
| `search` | `web_search`-Command | `{title, url, snippet}` |
| `mail_inbox` | `mail` / `mail_unread` | `{from, subject, msg_id, date}` |
| `note_search` | `notiz suche` | `{id, key, content_excerpt}` |

Weitere Typen (Termine, Kontakte, Plugin-Vorschläge etc.) folgen in
Phase 80.x als kleine Patches — die Infrastruktur ist generisch.

## 4. Lebenszyklus + Threading

- **TTL:** 1 Stunde ab `last_accessed`. Jeder `get_active` /
  `get_item` updated den Zeitpunkt.
- **Eviction:** Lazy beim nächsten Lookup (`_evict_expired()` läuft
  vor jedem read). Kein Background-Cron nötig.
- **Threading:** Saleria-Bridge ist Single-Reader pro User-Anfrage,
  also reicht ein einfaches `threading.Lock` um den `dict`-Zugriff
  serialisieren. Kein async/await nötig — der Store ist sync.
- **Memory-Cap:** Pro User maximal 10 aktive Listen-Typen × wenige
  KB pro Liste = vernachlässigbar.

## 5. Etappen

### 5.1 Etappe 1 — Store + Tests (1 Session)

- `src/elder_berry/tools/conversation_list_store.py` (Klasse,
  TTL-Logik, Index-Validierung, Lock).
- `tests/test_conversation_list_store.py` (register, overwrite, TTL,
  out-of-range, cross-user-isolation).
- **Akzeptanz:** Alle Unit-Tests grün, mypy strict clean.

### 5.2 Etappe 2 — Integration `search` (1 Session)

- `web_search` (advanced_commands.py) registriert Ergebnisse.
- LLM-System-Prompt um den `list_pick`-Hint erweitern.
- Bridge-Handler `handle_list_pick`.
- **Akzeptanz-Smoketest:** „suche X" → 5 Treffer → „Treffer 2" →
  Saleria liefert zusammenfassung des realen 2. Treffers, KEINE
  Halluzination.

### 5.3 Etappe 3 — `mail_inbox` + `note_search` (1 Session)

- Analog zu §5.2 für die zwei zusätzlichen Typen.
- **Akzeptanz:** „lies Mail 3" und „zeig Notiz 1" funktionieren.

## 6. Risiken / aktive Hinweise

- **R1 — Stale-Liste:** User fragt „Treffer 2" 90 Min nach der Suche.
  TTL hat geklappt, Liste weg. Saleria muss klar zurückmelden („keine
  aktive Suchliste, sag mir was du suchen willst") statt zu raten.

- **R2 — Liste-Type-Disambiguation:** User hat parallel eine `search`
  und eine `mail_inbox` aktiv. „Eintrag 2" ist mehrdeutig. LLM muss
  aus Chat-Kontext den richtigen Typ wählen oder zurückfragen.
  Mitigation: System-Prompt-Hint: „Wenn mehrere Listentypen aktiv
  sind, frage was gemeint ist."

- **R3 — User sieht list_ref:** Nicht primärer Output, aber falls in
  Logs / Dashboards leakt — kein Sicherheitsproblem (nur Zeitstempel
  + Hash). OK.

- **R4 — Saleria-Restart verliert alle Listen:** Akzeptierter
  Tradeoff. Persistenz wäre Overkill für ephemer-Listen. Falls Saleria
  öfter cycled als geplant: TTL ist eh nur 1h, kein großer Verlust.

- **R5 — Multi-User-Setup (OSS-Repo):** `user_id` ist im Store-Key.
  Lera sieht die Liste eines anderen Matrix-Users im selben Raum
  nicht. Sauber isoliert.

## 7. Tests / Akzeptanzkriterien

- `pytest tests/test_conversation_list_store.py` — Unit (CRUD, TTL,
  Overwrite, Cross-User).
- `pytest tests/test_advanced_commands.py::TestWebSearchListIntegration`
  — Integration (Etappe 2).
- E2E manuell:
  1. Saleria: „suche mir eine anleitung für drohnenbau" → 5 Treffer.
  2. „fasse mir den 2 link zusammen" → echter zweiter Treffer (keine
     halluzinierten URLs).
  3. 70 Minuten warten → „nimm den 4 treffer" → Saleria meldet sauber
     dass die Liste abgelaufen ist (nicht: greift in alten Chat-
     Verlauf).
  4. Neue Suche → alte Liste wird überschrieben → „Treffer 2" geht
     auf neue Liste.
- mypy strict für `conversation_list_store.py`.

## 8. Out of Scope

- SQLite-/persistent Storage (siehe R4).
- Cross-User-Listen (Multi-User-Aggregation).
- Listen-UI im Dashboard.
- Auto-Listen aus dem LLM-Output (z. B. „Saleria hat in einer
  Markdown-Liste eine `1.` `2.` Aufzählung emittiert → automatisch
  als Liste registrieren"). Wäre ein Phase-80.x-Sub-Step, sobald die
  Hauptinfrastruktur eingespielt ist und sich zeigt, dass das wirklich
  hilfreich wäre.

## 9. Folge-Phasen / Erweiterungen

- **Phase 80.x — weitere Listen-Typen:** Termine (Kalender),
  Kontakte, aktive Plugin-Vorschläge, Reminder. Jeweils kleiner Patch.
- **Phase 80.y — auto-Listenerkennung:** Saleria emittiert Markdown-
  Listen → System extrahiert sie automatisch als `generic_list`.
  Tradeoff: könnte False-Positives erzeugen.
- **Phase 81 (offen) — Listen-Persistenz:** falls Real-Use zeigt, dass
  Stale-Liste-Frust überwiegt. Dann SQLite-Backend mit längerer TTL.
