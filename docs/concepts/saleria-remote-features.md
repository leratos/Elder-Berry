# Saleria Remote-Features – Konzept

> **Status:** Planung
> **Erstellt:** 2026-03-15 (Claude App)
> **Umsetzung:** Claude Code (nach Phase 6 TS4)
> **Abhängigkeit:** MatrixChannel muss funktionieren (Phase 6)

---

## 1. Übersicht

Saleria soll über Matrix nicht nur antworten, sondern aktiv den PC steuern
und als Claude-API-Agent komplexe Aufgaben ausführen können. Zwei Stufen:

- **Direkte Features:** Saleria führt selbst aus (Screenshot, Systemstatus, etc.)
- **Claude-Agent-Mode:** Saleria leitet Anfragen an Claude API weiter,
  bekommt strukturierte Antworten und führt sie aus

## 2. Architektur: Claude-Agent-Mode (Stufe 2)

```
[Du auf Handy]
    │ "Dokumentiere X im Journal"
    ▼
[Element → Matrix → Saleria]
    │
    ├─ Einfache Commands → Saleria führt direkt aus
    │   (screenshot, status, play/pause, ...)
    │
    └─ Komplexe Anfragen → Claude API
        │
        ├─ System-Prompt: CLAUDE.md Inhalt
        ├─ Kontext: journal.txt (letzte 80 Zeilen)
        ├─ User-Message: deine Nachricht
        │
        ▼
      [Anthropic API → claude-sonnet-4-20250514]
        │
        ├─ Structured Output (JSON)
        │   { "action": "write_file",
        │     "path": "docs/journal.txt",
        │     "content": "## ...",
        │     "mode": "append" }
        │
        ▼
      [Saleria führt Aktion aus]
        │
        ▼
      [Ergebnis → Matrix → Du]
```

## 3. Direkte Features (kein LLM nötig)

### Tier 1 – Quick Wins
| Feature | Command-Beispiel | Umsetzung |
|---------|-----------------|-----------|
| Systemzustand | "status" | psutil → CPU/RAM/GPU/Disk/Netz |
| Screenshot | "screenshot" | mss/PIL → Matrix Upload |
| Push-Alerts (proaktiv) | (automatisch) | Monitoring-Loop: Disk >90%, Download fertig, Prozess crashed |
| Medien-Steuerung | "pause", "skip", "volume 50" | WindowsActionController → Media-Keys |

### Tier 2 – Mittlerer Aufwand
| Feature | Command-Beispiel | Umsetzung |
|---------|-----------------|-----------|
| Prozess-Kontrolle | "starte chrome", "kill blender" | subprocess + psutil |
| Datei senden | "schick mir C:\...\datei.pdf" | Path → Matrix file upload |
| Wake-on-LAN | "weck tower auf" | WoL Magic Packet an Tower MAC |
| Clipboard-Sync | "clipboard" / "clip: text hier" | pyperclip → Matrix, Matrix → pyperclip |

### Tier 3 – Curated Shell
| Feature | Command-Beispiel | Umsetzung |
|---------|-----------------|-----------|
| Git-Befehle | "git pull elder-berry" | Whitelist: pull, status, log |
| Docker | "docker restart synapse" | Whitelist: ps, restart, logs |
| Download | "download https://..." | wget/requests → lokaler Pfad |

## 4. Claude-Agent-Mode (LLM-gestützt)

### 4.1 Wann Agent-Mode statt direkte Features?
- Direkte Features: klare, eindeutige Befehle ("screenshot", "status")
- Agent-Mode: alles was Interpretation, Planung oder Kontext braucht
  - "Dokumentiere dass die Matrix-Tests grün sind"
  - "Was war der letzte Arbeitsschritt?"
  - "Schreib eine Zusammenfassung von heute ins Journal"
  - "Welche Phase kommt als nächstes?"

### 4.2 Klassen-Design

```python
# src/elder_berry/comms/claude_agent.py

class ClaudeAgent:
    """Leitet komplexe Anfragen an Claude API weiter."""

    def __init__(
        self,
        api_key: str,                    # Anthropic API Key
        model: str = "claude-sonnet-4-20250514",
        project_root: Path,              # C:\Dev\Elder-Berry
        allowed_actions: list[str],      # Whitelist
    ): ...

    async def process(self, user_message: str) -> AgentResult:
        """
        1. Kontext laden (journal.txt, CLAUDE.md)
        2. System-Prompt bauen (Projekt-Kontext + erlaubte Aktionen)
        3. Claude API aufrufen (structured output: JSON)
        4. Aktion validieren (in Whitelist?)
        5. Aktion ausführen
        6. Ergebnis zurückgeben
        """

class AgentResult:
    """DTO für Agent-Ergebnis."""
    success: bool
    action_taken: str       # z.B. "write_file", "read_file", "none"
    summary: str            # Menschenlesbare Zusammenfassung
    details: str | None     # Technische Details (optional)
```

### 4.3 Erlaubte Aktionen (Whitelist)

Sicherheitskritisch – Claude darf NUR diese Aktionen vorschlagen:

```python
ALLOWED_ACTIONS = [
    "read_file",          # Datei lesen
    "write_file",         # Datei schreiben (nur in docs/)
    "append_file",        # An Datei anhängen (nur journal.txt)
    "list_directory",     # Verzeichnis auflisten
    "search_files",       # Dateien suchen
    "system_status",      # Systemstatus abfragen
    "screenshot",         # Screenshot machen
    "run_tests",          # pytest ausführen (read-only)
    "git_status",         # git status/log (read-only)
    "answer_only",        # Nur Text-Antwort, keine Aktion
]

# EXPLIZIT VERBOTEN:
# - Shell-Befehle ausführen
# - Dateien außerhalb des Projekts ändern
# - Pakete installieren
# - Netzwerk-Requests (außer Ollama/OpenRouter)
# - Prozesse starten/stoppen (dafür direkte Features nutzen)
```

### 4.4 System-Prompt für Claude API

```python
AGENT_SYSTEM_PROMPT = """
Du bist Saleria's interner Agent. Du erhältst Anfragen vom Nutzer
über Matrix und entscheidest welche Aktion ausgeführt werden soll.

Antworte IMMER als JSON:
{
    "action": "action_name",    // aus ALLOWED_ACTIONS
    "params": { ... },          // Parameter für die Aktion
    "summary": "...",           // Kurze Zusammenfassung für den Nutzer
    "reasoning": "..."          // Warum diese Aktion (intern)
}

Projekt-Kontext:
{claude_md_content}

Aktueller Stand (journal.txt, letzte 80 Zeilen):
{journal_tail}

Erlaubte Aktionen: {allowed_actions}

Regeln:
- Nur erlaubte Aktionen vorschlagen
- Bei Unklarheit: action="answer_only" und im summary nachfragen
- Dateien nur in docs/ oder tests/ ändern
- journal.txt nur mit append_file, nie überschreiben
- Kein Code generieren, keine Dateien in src/ ändern
  (dafür ist Claude Code in VS Code zuständig)
"""
```

### 4.5 API-Kosten Einschätzung

| Modell | Input (Kontext) | Output | Kosten pro Anfrage |
|--------|----------------|--------|-------------------|
| Sonnet | ~4k Tokens (CLAUDE.md + Journal) | ~200-500 Tokens | ~$0.02 |
| Haiku (Alternative) | ~4k Tokens | ~200-500 Tokens | ~$0.002 |

Bei ~50 Anfragen/Tag: Sonnet ~$1/Tag, Haiku ~$0.10/Tag.
Empfehlung: Sonnet für Agent-Mode, Haiku für simple Routing-Entscheidungen.

## 5. Integration in Assistant

```python
# Erweiterung in assistant.py → handle_matrix_message

async def handle_matrix_message(self, msg: IncomingMessage) -> None:
    text = msg.body.strip().lower()

    # Stufe 1: Direkte Commands (kein LLM)
    if text in ("status", "systemstatus"):
        result = await self.get_system_status()
        await self.message_channel.send_text(msg.room_id, result)
        return

    if text in ("screenshot", "screen"):
        path = await self.take_screenshot()
        await self.message_channel.send_image(msg.room_id, path)
        return

    if text in ("pause", "play", "skip", "next"):
        await self.media_control(text)
        await self.message_channel.send_text(msg.room_id, f"✓ {text}")
        return

    # Stufe 2: Claude Agent für alles andere
    if self.claude_agent:
        result = await self.claude_agent.process(msg.body)
        await self.message_channel.send_text(msg.room_id, result.summary)
        if result.details:
            await self.message_channel.send_text(msg.room_id, result.details)
    else:
        # Fallback: lokales LLM
        response = await self.process(msg.body)
        await self.message_channel.send_text(msg.room_id, response)
```

## 6. Sicherheit

| Risiko | Mitigation |
|--------|-----------|
| API-Key Leak | .env Datei, nie in Code/Config committed |
| Prompt Injection via Matrix | Whitelist-Aktionen, JSON-only Output, Validierung |
| Ungewollte Datei-Änderungen | Write nur in docs/, append nur journal.txt |
| Kosten-Explosion | Rate-Limit: max 100 API-Calls/Tag, Warnung bei >50 |
| Fremde Nachrichten | allowed_rooms + allowed_users Whitelist |

## 7. Neue Dateien

| Datei | Klasse / Zweck |
|-------|---------------|
| `src/elder_berry/comms/claude_agent.py` | `ClaudeAgent` – API-Client + Aktions-Ausführung |
| `src/elder_berry/comms/remote_commands.py` | `RemoteCommandHandler` – direkte Features (Tier 1-3) |
| `src/elder_berry/comms/system_monitor.py` | `SystemMonitor` – proaktive Alerts |
| `tests/test_claude_agent.py` | Unit-Tests mit Mock-API |
| `tests/test_remote_commands.py` | Unit-Tests für direkte Features |

## 8. Dependencies (neu)

```toml
# In pyproject.toml [project.optional-dependencies]
remote = [
    "anthropic>=0.40",     # Claude API Client
    "mss>=9.0",            # Screenshots (cross-platform)
    "pyperclip>=1.9",      # Clipboard-Zugriff
]
```

## 9. Umsetzungsreihenfolge

1. RemoteCommandHandler mit Tier-1-Features (status, screenshot, media)
2. Integration in handle_matrix_message (Command-Router)
3. ClaudeAgent Klasse (API-Client + Whitelist-Validierung)
4. SystemMonitor für proaktive Alerts
5. Tier-2-Features (Prozess-Kontrolle, Datei-Zugriff, WoL)
6. Tier-3-Features (curated Shell, Downloads)

## 10. Abgrenzung: Saleria vs. Claude Code

| | Saleria (Remote/Matrix) | Claude Code (VS Code) |
|-|------------------------|----------------------|
| **Zweck** | Monitoring, simple Tasks, Journal | Code schreiben, refactorn, testen |
| **Darf src/ ändern** | Nein | Ja |
| **Darf tests schreiben** | Nein | Ja |
| **Darf journal.txt schreiben** | Ja (append only) | Ja |
| **LLM** | Claude API (Sonnet) | Claude Code (Opus) |
| **Trigger** | Matrix-Nachricht | VS Code Terminal |
| **Kontext** | CLAUDE.md + journal.txt | Voller Workspace |

Saleria ist die "Augen und Ohren" von unterwegs.
Claude Code ist das "Hirn" für Entwicklung.
Die beiden ergänzen sich, überlappen nicht.
