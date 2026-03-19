# Phase 23 – Konversations-Zusammenfassung

> **Status:** Konzept
> **Erstellt:** 2026-03-19
> **Abhängigkeit:** ChatHistory (Phase 8), Assistant (Phase 1/5),
>   MemoryStore/ChromaDB (Phase 5)

---

## Ziel

Saleria vergisst den Gesprächsanfang nicht mehr, wenn die ChatHistory rotiert.
Statt die ältesten Nachrichten einfach zu verwerfen, werden sie zu einer
kompakten Zusammenfassung komprimiert und als Kontext behalten.

**Aktuell (10 Nachrichten Sliding Window):**
```
[Message 1-5: verworfen]
[Message 6-10: im Prompt als Kontext]
→ LLM weiß nicht mehr was in Message 1-5 besprochen wurde
```

**Nachher:**
```
[Summary: "Nutzer hat nach Mails von Max gefragt, 3 gefunden,
 die letzte zusammengefasst, Termin erstellt"]
[Message 6-10: im Prompt als Kontext]
→ LLM hat Gesamtbild
```

---

## Ist-Zustand

### ChatHistory (comms/chat_history.py)
- Per-User Sliding Window: `deque(maxlen=max_messages)` mit max_messages=10
- `add(sender, role, text)` → FIFO-Eviction wenn voll
- `format_for_prompt(sender)` → "Bisheriger Gesprächsverlauf: ..."
- Nachrichten >500 Zeichen werden gekürzt
- **Kein Mechanismus für evicted Messages** → die sind weg

### RAG Memory (MemoryStore / ChromaDB)
- Speichert jede Nachricht einzeln als Embedding
- `get_context(query)` → semantische Suche + letzte N
- **Problem:** Einzelne Nachrichten als Embeddings sind fragmentiert.
  "Max schlägt Donnerstag vor" ist ohne Kontext ("wofür?") nutzlos.
- Memory ist für langfristigen Recall, nicht für laufende Konversation

---

## Lösung

### Ansatz: Rolling Summary

Wenn Nachrichten aus dem Window rotieren, wird ein LLM-Summary erstellt:

```
ChatHistory (Kapazität: 10)
│
├─ Nachricht 1-10 ankommen → alles im Window
│
├─ Nachricht 11 kommt → Nachricht 1 wird evicted
│  └─ Summary-Trigger: Nachrichten 1-3 zusammenfassen
│  └─ Summary in _conversation_summary gespeichert
│
├─ Nachricht 14 kommt → Nachrichten 2-4 evicted
│  └─ Summary aktualisieren (alter Summary + neue evicted Nachrichten)
│
├─ format_for_prompt():
│  "Zusammenfassung bisheriges Gespräch: [Summary]
│   Letzte Nachrichten:
│   User: ...
│   Saleria: ..."
```

### ChatHistory erweitern

```python
class ChatHistory:
    def __init__(self, max_messages=10, summarizer=None):
        self._max_messages = max_messages
        self._summarizer = summarizer  # Callable[[str, list[ChatMessage]], str]
        self._summaries: dict[str, str] = {}  # sender → rolling summary

    def add(self, sender, role, text):
        messages = self._history[sender]
        evicted = []

        # Sammle evicted Messages
        while len(messages) >= self._max_messages:
            evicted.append(messages.popleft())

        messages.append(ChatMessage(role=role, text=text, ...))

        # Summary aktualisieren wenn Nachrichten evicted wurden
        if evicted and self._summarizer:
            old_summary = self._summaries.get(sender, "")
            self._summaries[sender] = self._summarizer(old_summary, evicted)

    def format_for_prompt(self, sender):
        parts = []
        summary = self._summaries.get(sender, "")
        if summary:
            parts.append(f"Zusammenfassung bisheriges Gespräch:\n{summary}")
        parts.append("Letzte Nachrichten:")
        for msg in self._history.get(sender, []):
            ...
        return "\n".join(parts)
```

### Summarizer-Implementierung

```python
def create_summarizer(llm: LLMClient):
    def summarize(old_summary: str, evicted: list[ChatMessage]) -> str:
        evicted_text = "\n".join(f"{m.role}: {m.text}" for m in evicted)
        prompt = (
            f"Bisherige Zusammenfassung: {old_summary or 'Keine'}\n\n"
            f"Neue Nachrichten:\n{evicted_text}\n\n"
            f"Aktualisiere die Zusammenfassung. Maximal 3 Sätze. "
            f"Behalte nur was für den weiteren Gesprächsverlauf relevant ist."
        )
        return llm.generate(prompt, system="Du fasst Gespräche zusammen.")
    return summarize
```

---

## Alternativen (verworfen)

### Einfach max_messages erhöhen
- Von 10 auf 30 → mehr Kontext, aber:
  - System-Prompt wird riesig (Token-Limit, Kosten)
  - LLM wird langsamer (mehr Input-Tokens)
  - Irgendwann rotiert es trotzdem
- **Keine Lösung, nur Aufschub.**

### Alles in RAG Memory speichern
- Jede evicted Message wird als Embedding gespeichert
- Problem: Semantische Suche findet fragmentierte Einzelnachrichten
- "Was haben wir vorhin besprochen?" → findet einzelne Messages ohne Kontext
- **Existiert bereits, löst das Problem nicht.**

---

## Performance & Kosten

- **LLM-Call pro Summary:** ~200 Input + ~100 Output Tokens → ~0.2 Cent
- **Frequenz:** Nur wenn Nachrichten aus dem Window fallen → ca. alle 5-10
  Nachrichten (bei max_messages=10)
- **Latenz:** Summary wird NACH dem add() erstellt, nicht im Request-Pfad.
  Kann async/in Background Thread laufen → keine User-Latenz.
- **Token-Budget im Prompt:** Summary ist maximal 3 Sätze (~50-80 Tokens) →
  vernachlässigbar im Vergleich zum restlichen System-Prompt

---

## Scope

### Neue/geänderte Dateien
| Datei | Änderung |
|-------|----------|
| `comms/chat_history.py` | Rolling Summary Logik, Summarizer-Callback |
| `comms/bridge.py` | Summarizer erstellen und an ChatHistory übergeben |
| `tests/test_chat_history.py` | Tests für Summary-Trigger, Format, Edge-Cases |

### Was sich NICHT ändert
- MemoryStore/ChromaDB (bleibt für Langzeit-Recall)
- Assistant.process() (bekommt weiterhin `chat_context` als String)
- ChatHistory API für add/get/clear (Rückwärtskompatibel)
- format_for_prompt() Signatur (Rückwärtskompatibel)

---

## Offene Entscheidungen

1. **Wann summarisieren?** Bei jedem Evict, oder batch (alle 3-5 Evicts)?
   - Empfehlung: Batch (alle 3 evicted Messages auf einmal) → weniger LLM-Calls

2. **Summarizer-LLM:** Gleicher LLM wie für Konversation (phi4/Sonnet), oder
   ein leichterer? phi4 lokal reicht für Zusammenfassungen.
   - Empfehlung: Gleicher LLM (keine zweite Konfiguration nötig)

3. **Summary-Persistenz:** In-Memory oder SQLite?
   - In-Memory: Geht bei Neustart verloren (wie ChatHistory selbst)
   - SQLite: Persistiert, aber ChatHistory ist aktuell rein In-Memory
   - Empfehlung: In-Memory (konsistent mit ChatHistory, bei Neustart startet
     sowieso eine neue Konversation)

4. **Summary-Länge:** 3 Sätze, oder dynamisch nach Gesprächsinhalt?
   - Empfehlung: Fix 3 Sätze → vorhersagbares Token-Budget
