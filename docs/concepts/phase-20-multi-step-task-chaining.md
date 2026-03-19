# Phase 20 – Multi-Step Task Chaining

> **Status:** Konzept
> **Erstellt:** 2026-03-19
> **Abhängigkeit:** RemoteCommandHandler (Phase 7), Assistant (Phase 1/5),
>   ChatHistory (Phase 8)

---

## Ziel

Saleria kann mehrstufige Aufgaben abarbeiten, bei denen das Ergebnis eines
Schritts als Input für den nächsten dient. Aktuell ist jeder Command atomar –
der Nutzer muss komplexe Abläufe manuell in Einzelschritte zerlegen.

**Beispiel (aktuell nicht möglich):**
> "Suche die letzte Mail von Max, fasse sie zusammen und erstelle daraus einen Termin."

**Aktuell nötig:**
1. "mail suche Max" → Ergebnis lesen
2. "fasse die mail zusammen" → Zusammenfassung lesen
3. "erstelle termin Besprechung mit Max morgen 14:00"

---

## Ist-Zustand

### Command-Ausführung (Bridge)
- `_handle_message()` dispatched genau EINEN Pfad:
  1. Remote Command (direkt) → OR
  2. Claude Agent → OR
  3. LLM (mit optional `remote_command` Action)
- Kein Mechanismus für sequenzielle Ausführung mehrerer Commands

### LLM-driven Commands
- LLM kann EIN `remote_command` pro Turn generieren
- Ergebnis wird via `_handle_llm_remote_command()` ausgeführt
- Kein Feedback-Loop: LLM sieht das Ergebnis des Commands nicht

### ChatHistory
- Speichert Text, aber kein strukturiertes Command-Ergebnis
- `history_text` aus CommandResult wird in ChatHistory geschrieben
  (z.B. Mail-Body für Rückfragen), aber nur für den nächsten manuellen Turn

---

## Lösung

### Ansatz: LLM-gesteuerte Schleife (ReAct-Pattern)

Das LLM entscheidet bei jeder Anfrage, ob es:
1. **Direkt antwortet** (action: null) → fertig
2. **Einen Command ausführt** (action: remote_command) → Ergebnis zurück ans LLM → neuer Turn

```
User: "Suche die letzte Mail von Max und fasse sie zusammen"
│
├─ Turn 1: LLM → action: "remote_command", command: "mail suche Max"
│  └─ Ausführung → CommandResult.text + history_text
│  └─ Ergebnis als Kontext zurück ans LLM
│
├─ Turn 2: LLM → action: null, response: "Zusammenfassung: Max schlägt..."
│  └─ Fertig → Antwort an User
```

### Neue Klasse: TaskExecutor

```python
class TaskExecutor:
    """Führt Multi-Step Tasks aus (LLM → Command → LLM → ... → Antwort)."""

    MAX_STEPS = 5  # Sicherheit: maximal 5 Schritte pro Anfrage

    def execute(self, user_input, assistant, command_handler) -> TaskResult:
        steps = []
        current_input = user_input

        for step in range(self.MAX_STEPS):
            result = assistant.process(current_input, ...)

            if result.action_executed != "remote_command":
                # LLM hat direkt geantwortet → fertig
                return TaskResult(response=result.response, steps=steps)

            # Command ausführen
            cmd_result = command_handler.execute(...)
            steps.append(StepResult(command=..., result=cmd_result))

            # Ergebnis als neuen Kontext formulieren
            current_input = (
                f"Ergebnis von '{cmd}': {cmd_result.text}\n\n"
                f"Ursprüngliche Anfrage: {user_input}\n"
                f"Führe den nächsten Schritt aus oder antworte dem Nutzer."
            )

        return TaskResult(response="Maximale Schritte erreicht.", steps=steps)
```

### Integration in MatrixBridge

In `_handle_assistant_message()`:

```python
# Statt einzelner LLM-Call:
result = self._task_executor.execute(
    user_input=msg.body,
    assistant=self._assistant,
    command_handler=self._remote_commands,
)
# TaskExecutor liefert finale Antwort nach 1-N Schritten
```

### System-Prompt Erweiterung

Das LLM braucht die Anweisung, mehrstufig denken zu können:

```
Wenn eine Anfrage mehrere Schritte erfordert, führe sie nacheinander aus.
Du kannst pro Antwort EINE Aktion ausführen. Nach der Ausführung bekommst du
das Ergebnis und kannst den nächsten Schritt planen oder direkt antworten.
```

---

## Sicherheit

- **MAX_STEPS = 5:** Verhindert Endlosschleifen (LLM ruft immer wieder Commands auf)
- **Kosten-Limit:** Jeder Step = 1 LLM-Call. Bei Anthropic ~1-2 Cent pro Step.
  5 Steps = max ~10 Cent pro Anfrage. Akzeptabel bei gelegentlicher Nutzung.
- **Keine destruktiven Chains:** Commands wie "lösche alle termine" sollten
  weiterhin eine Bestätigung vom User erfordern → nicht automatisch in einer Chain.
- **Timeout:** Gesamte Chain sollte ein Timeout haben (z.B. 60s)

---

## Scope

### Neue/geänderte Dateien
| Datei | Änderung |
|-------|----------|
| `core/task_executor.py` | **Neu:** TaskExecutor + TaskResult + StepResult |
| `comms/bridge.py` | `_handle_assistant_message()` nutzt TaskExecutor |
| `core/assistant.py` | Ggf. `process()` Signatur erweitern für Zwischen-Kontext |
| `character/saleria.yaml` | System-Prompt um Multi-Step-Anweisung erweitern |
| `tests/test_task_executor.py` | **Neu:** Tests für Chaining, Max-Steps, Einzelschritt |

### Was sich NICHT ändert
- RemoteCommandHandler (Commands bleiben atomar)
- CommandHandler-Subklassen (keine Änderung nötig)
- ChatHistory (Steps werden nicht einzeln gespeichert, nur Endergebnis)

---

## Offene Entscheidungen

1. **Transparenz:** Soll der User Zwischenschritte sehen?
   - Option A: Stille Ausführung, nur Endergebnis → cleaner
   - Option B: "Schritt 1: Suche Mails... Schritt 2: Fasse zusammen..." → transparenter
   - Empfehlung: Option B mit kompakter Zusammenfassung am Ende

2. **Bestätigungs-Commands:** Sollen destruktive Commands (löschen, update) in
   einer Chain automatisch ausgeführt werden oder Bestätigung verlangen?
   - Empfehlung: Bestätigung → Chain pausiert, User bestätigt, Chain geht weiter

3. **Ollama-Qualität:** phi4:14b ist gut für einfache Anfragen, aber Multi-Step
   Reasoning ist anspruchsvoll. Reicht Ollama für Chains, oder nur Anthropic?
   - Empfehlung: Erst mit Anthropic testen, Ollama-Fallback evaluieren

4. **Token-Budget:** Jeder Step akkumuliert Kontext. Bei 5 Steps kann der Prompt
   sehr groß werden. Brauchen wir ein Kontext-Limit pro Chain?
