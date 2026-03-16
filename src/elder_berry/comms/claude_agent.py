"""ClaudeAgent – Anthropic API Client für komplexe Anfragen via Matrix.

Stufe 2 des Remote-Feature-Systems: Wenn eine Nachricht kein direkter Command ist,
wird sie an die Claude API (Sonnet) weitergeleitet. Claude analysiert die Anfrage,
entscheidet welche Aktion ausgeführt werden soll (aus einer Whitelist), und gibt
ein strukturiertes JSON-Ergebnis zurück.

Sicherheit:
- Nur Whitelist-Aktionen erlaubt (read_file, write_file nur in docs/, etc.)
- Pfad-Validierung: kein Zugriff außerhalb des Projekts
- journal.txt nur per append, nie überschreiben
- Kein Shell-Zugriff, keine Paket-Installation

Verwendung:
    agent = ClaudeAgent(
        api_key="sk-ant-...",
        project_root=Path("C:/Dev/Elder-Berry"),
    )
    result = agent.process("Was war der letzte Arbeitsschritt?")
    print(result.summary)
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Standard-Modell für den Agent
DEFAULT_MODEL = "claude-sonnet-4-6"

# Maximale Anzahl Zeilen aus journal.txt für den Kontext
JOURNAL_TAIL_LINES = 80

# Erlaubte Aktionen (Whitelist)
ALLOWED_ACTIONS = frozenset({
    "read_file",
    "write_file",
    "append_file",
    "list_directory",
    "search_files",
    "system_status",
    "screenshot",
    "run_tests",
    "git_status",
    "answer_only",
})

# Verzeichnisse in denen write_file erlaubt ist (relativ zum Projekt-Root)
WRITABLE_DIRS = ("docs",)

# Dateien die per append_file beschrieben werden dürfen (relativ zum Projekt-Root)
APPENDABLE_FILES = ("docs/journal.txt",)

# System-Prompt Template für die Claude API
AGENT_SYSTEM_PROMPT = """\
Du bist Saleria's interner Agent. Du erhältst Anfragen vom Nutzer über Matrix \
und entscheidest welche Aktion ausgeführt werden soll.

Antworte IMMER als valides JSON (kein Markdown, kein Codeblock):
{{
    "action": "<action_name>",
    "params": {{ ... }},
    "summary": "<kurze Zusammenfassung für den Nutzer>",
    "reasoning": "<warum diese Aktion>"
}}

Erlaubte Aktionen und ihre Parameter:
- read_file: {{"path": "<relativer Pfad>"}} – Datei lesen
- write_file: {{"path": "<relativer Pfad>", "content": "<Inhalt>"}} – Datei schreiben (NUR in docs/)
- append_file: {{"path": "docs/journal.txt", "content": "<Text>"}} – An journal.txt anhängen
- list_directory: {{"path": "<relativer Pfad>"}} – Verzeichnis auflisten
- search_files: {{"pattern": "<glob Pattern>", "path": "<Startverzeichnis>"}} – Dateien suchen
- system_status: {{}} – Systemstatus abfragen (CPU, RAM, GPU)
- screenshot: {{}} – Screenshot aufnehmen
- run_tests: {{"path": "<optionaler Test-Pfad>"}} – pytest ausführen (read-only)
- git_status: {{}} – git status + letzte Commits
- answer_only: {{}} – Nur Text-Antwort, keine Aktion ausführen

Regeln:
- Nur die oben genannten Aktionen vorschlagen
- Bei Unklarheit: action="answer_only" und im summary nachfragen
- write_file NUR in docs/ erlaubt
- append_file NUR für docs/journal.txt
- Kein Code generieren, keine Dateien in src/ ändern \
(dafür ist Claude Code in VS Code zuständig)
- Pfade immer relativ zum Projekt-Root angeben
- Heutiges Datum: {date}

Projekt-Kontext (CLAUDE.md):
{claude_md}

Aktueller Stand (journal.txt, letzte {journal_lines} Zeilen):
{journal_tail}
"""


@dataclass(frozen=True)
class AgentResult:
    """Ergebnis einer ClaudeAgent-Anfrage."""

    success: bool
    """True wenn die Aktion erfolgreich ausgeführt wurde."""

    action_taken: str
    """Name der ausgeführten Aktion (z.B. 'read_file', 'answer_only')."""

    summary: str
    """Menschenlesbare Zusammenfassung für den Nutzer."""

    details: str | None = None
    """Technische Details (optional, z.B. Dateiinhalt, Testergebnis)."""


class ClaudeAgent:
    """Leitet komplexe Anfragen an die Anthropic Claude API weiter.

    - Lädt automatisch Projekt-Kontext (CLAUDE.md + journal.txt)
    - Baut System-Prompt mit Whitelist-Aktionen
    - Validiert die Antwort gegen die Whitelist
    - Führt erlaubte Aktionen aus und gibt AgentResult zurück
    """

    def __init__(
        self,
        api_key: str,
        project_root: Path,
        model: str = DEFAULT_MODEL,
        allowed_actions: frozenset[str] | None = None,
        max_tokens: int = 1024,
    ) -> None:
        self._api_key = api_key
        self._project_root = Path(project_root).resolve()
        self._model = model
        self._allowed_actions = allowed_actions or ALLOWED_ACTIONS
        self._max_tokens = max_tokens
        self._client: Any = None  # Lazy-Init des Anthropic Clients

    @property
    def model(self) -> str:
        """Verwendetes Claude-Modell."""
        return self._model

    @property
    def project_root(self) -> Path:
        """Projekt-Wurzelverzeichnis."""
        return self._project_root

    @property
    def allowed_actions(self) -> frozenset[str]:
        """Erlaubte Aktionen."""
        return self._allowed_actions

    def _get_client(self) -> Any:
        """Gibt den Anthropic Client zurück (Lazy-Init)."""
        if self._client is not None:
            return self._client

        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "anthropic nicht installiert. "
                "Installiere mit: pip install 'elder-berry[remote]'"
            ) from e

        self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def _load_claude_md(self) -> str:
        """Lädt CLAUDE.md aus dem Projekt-Root."""
        claude_md_path = self._project_root / "CLAUDE.md"
        if claude_md_path.exists():
            return claude_md_path.read_text(encoding="utf-8")
        logger.warning("CLAUDE.md nicht gefunden: %s", claude_md_path)
        return "(CLAUDE.md nicht gefunden)"

    def _load_journal_tail(self) -> str:
        """Lädt die letzten N Zeilen aus journal.txt."""
        journal_path = self._project_root / "docs" / "journal.txt"
        if not journal_path.exists():
            logger.warning("journal.txt nicht gefunden: %s", journal_path)
            return "(journal.txt nicht gefunden)"

        lines = journal_path.read_text(encoding="utf-8").splitlines()
        tail = lines[-JOURNAL_TAIL_LINES:] if len(lines) > JOURNAL_TAIL_LINES else lines
        return "\n".join(tail)

    def _build_system_prompt(self) -> str:
        """Baut den System-Prompt mit aktuellem Projekt-Kontext."""
        from datetime import date as date_cls

        return AGENT_SYSTEM_PROMPT.format(
            date=date_cls.today().isoformat(),
            claude_md=self._load_claude_md(),
            journal_tail=self._load_journal_tail(),
            journal_lines=JOURNAL_TAIL_LINES,
        )

    def _parse_response(self, raw_text: str) -> dict[str, Any]:
        """Parst die JSON-Antwort von Claude.

        Versucht:
        1. Direktes JSON-Parsing
        2. JSON-Block-Extraktion (falls in Markdown-Codeblock)

        Returns:
            Geparstes Dict mit action, params, summary, reasoning.

        Raises:
            ValueError: Wenn kein gültiges JSON gefunden wird.
        """
        text = raw_text.strip()

        # Versuch 1: Direktes Parsing
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Versuch 2: JSON aus Markdown-Codeblock extrahieren
        import re
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Versuch 3: Erstes { ... } extrahieren
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start:brace_end + 1])
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Konnte kein gültiges JSON in der Antwort finden: {text[:200]}")

    def _validate_action(self, parsed: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
        """Validiert die geparste Aktion gegen die Whitelist.

        Returns:
            Tuple (action, params, summary).

        Raises:
            ValueError: Wenn die Aktion nicht erlaubt ist oder Pflichtfelder fehlen.
        """
        action = parsed.get("action", "")
        params = parsed.get("params", {})
        summary = parsed.get("summary", "")

        if not action:
            raise ValueError("Antwort enthält kein 'action'-Feld")

        if action not in self._allowed_actions:
            raise ValueError(
                f"Aktion '{action}' nicht erlaubt. "
                f"Erlaubt: {sorted(self._allowed_actions)}"
            )

        if not summary:
            summary = f"Aktion: {action}"

        return action, params, summary

    def _validate_path(self, relative_path: str) -> Path:
        """Validiert und löst einen relativen Pfad gegen das Projekt-Root auf.

        Stellt sicher, dass der Pfad innerhalb des Projekts liegt (kein Path-Traversal).

        Returns:
            Aufgelöster absoluter Pfad.

        Raises:
            ValueError: Wenn der Pfad außerhalb des Projekts liegt.
        """
        # Normalisiere den Pfad und entferne führende Slashes
        clean = relative_path.lstrip("/").lstrip("\\")
        resolved = (self._project_root / clean).resolve()

        if not resolved.is_relative_to(self._project_root):
            raise ValueError(
                f"Pfad '{relative_path}' liegt außerhalb des Projekts"
            )

        return resolved

    def _validate_writable_path(self, relative_path: str) -> Path:
        """Validiert dass der Pfad in einem beschreibbaren Verzeichnis liegt.

        Raises:
            ValueError: Wenn der Pfad nicht beschreibbar ist.
        """
        resolved = self._validate_path(relative_path)
        rel = resolved.relative_to(self._project_root)
        rel_posix = rel.as_posix()

        for writable_dir in WRITABLE_DIRS:
            if rel_posix.startswith(writable_dir + "/") or rel_posix == writable_dir:
                return resolved

        raise ValueError(
            f"Schreibzugriff auf '{relative_path}' nicht erlaubt. "
            f"Nur in {WRITABLE_DIRS} erlaubt."
        )

    def _validate_appendable_path(self, relative_path: str) -> Path:
        """Validiert dass der Pfad appendbar ist.

        Raises:
            ValueError: Wenn der Pfad nicht appendbar ist.
        """
        resolved = self._validate_path(relative_path)
        rel = resolved.relative_to(self._project_root)
        rel_posix = rel.as_posix()

        if rel_posix not in APPENDABLE_FILES:
            raise ValueError(
                f"Append auf '{relative_path}' nicht erlaubt. "
                f"Nur {APPENDABLE_FILES} erlaubt."
            )

        return resolved

    # --- Aktions-Handler ---

    def _exec_read_file(self, params: dict[str, Any]) -> AgentResult:
        """Liest eine Datei und gibt den Inhalt zurück."""
        path_str = params.get("path", "")
        if not path_str:
            return AgentResult(
                success=False, action_taken="read_file",
                summary="Kein Pfad angegeben.",
            )

        try:
            resolved = self._validate_path(path_str)
        except ValueError as e:
            return AgentResult(
                success=False, action_taken="read_file", summary=str(e),
            )

        if not resolved.exists():
            return AgentResult(
                success=False, action_taken="read_file",
                summary=f"Datei nicht gefunden: {path_str}",
            )

        if not resolved.is_file():
            return AgentResult(
                success=False, action_taken="read_file",
                summary=f"Kein reguläre Datei: {path_str}",
            )

        try:
            content = resolved.read_text(encoding="utf-8")
            # Begrenze die Ausgabe auf sinnvolle Länge
            if len(content) > 5000:
                content = content[:5000] + "\n... (gekürzt, Datei hat mehr Inhalt)"
            return AgentResult(
                success=True, action_taken="read_file",
                summary=f"Datei gelesen: {path_str}",
                details=content,
            )
        except Exception as e:
            return AgentResult(
                success=False, action_taken="read_file",
                summary=f"Fehler beim Lesen: {e}",
            )

    def _exec_write_file(self, params: dict[str, Any]) -> AgentResult:
        """Schreibt eine Datei (nur in docs/)."""
        path_str = params.get("path", "")
        content = params.get("content", "")

        if not path_str:
            return AgentResult(
                success=False, action_taken="write_file",
                summary="Kein Pfad angegeben.",
            )

        try:
            resolved = self._validate_writable_path(path_str)
        except ValueError as e:
            return AgentResult(
                success=False, action_taken="write_file", summary=str(e),
            )

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return AgentResult(
                success=True, action_taken="write_file",
                summary=f"Datei geschrieben: {path_str}",
            )
        except Exception as e:
            return AgentResult(
                success=False, action_taken="write_file",
                summary=f"Fehler beim Schreiben: {e}",
            )

    def _exec_append_file(self, params: dict[str, Any]) -> AgentResult:
        """Hängt Text an eine Datei an (nur journal.txt)."""
        path_str = params.get("path", "")
        content = params.get("content", "")

        if not path_str:
            return AgentResult(
                success=False, action_taken="append_file",
                summary="Kein Pfad angegeben.",
            )

        try:
            resolved = self._validate_appendable_path(path_str)
        except ValueError as e:
            return AgentResult(
                success=False, action_taken="append_file", summary=str(e),
            )

        try:
            with resolved.open("a", encoding="utf-8") as f:
                # Newline vor dem Content, falls Datei nicht mit Newline endet
                existing = resolved.read_text(encoding="utf-8")
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write(content)
                if not content.endswith("\n"):
                    f.write("\n")
            return AgentResult(
                success=True, action_taken="append_file",
                summary=f"Text angehängt an: {path_str}",
            )
        except Exception as e:
            return AgentResult(
                success=False, action_taken="append_file",
                summary=f"Fehler beim Anhängen: {e}",
            )

    def _exec_list_directory(self, params: dict[str, Any]) -> AgentResult:
        """Listet ein Verzeichnis auf."""
        path_str = params.get("path", ".")

        try:
            resolved = self._validate_path(path_str)
        except ValueError as e:
            return AgentResult(
                success=False, action_taken="list_directory", summary=str(e),
            )

        if not resolved.exists():
            return AgentResult(
                success=False, action_taken="list_directory",
                summary=f"Verzeichnis nicht gefunden: {path_str}",
            )

        if not resolved.is_dir():
            return AgentResult(
                success=False, action_taken="list_directory",
                summary=f"Kein Verzeichnis: {path_str}",
            )

        try:
            entries = sorted(resolved.iterdir())
            lines = []
            for entry in entries[:100]:  # Begrenze auf 100 Einträge
                rel = entry.relative_to(self._project_root)
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{rel.as_posix()}{suffix}")

            total = len(list(resolved.iterdir()))
            header = f"Verzeichnis: {path_str} ({total} Einträge)"
            if total > 100:
                header += " (erste 100 angezeigt)"

            return AgentResult(
                success=True, action_taken="list_directory",
                summary=header,
                details="\n".join(lines),
            )
        except Exception as e:
            return AgentResult(
                success=False, action_taken="list_directory",
                summary=f"Fehler beim Auflisten: {e}",
            )

    def _exec_search_files(self, params: dict[str, Any]) -> AgentResult:
        """Sucht Dateien nach Glob-Pattern."""
        pattern = params.get("pattern", "")
        path_str = params.get("path", ".")

        if not pattern:
            return AgentResult(
                success=False, action_taken="search_files",
                summary="Kein Suchmuster angegeben.",
            )

        try:
            resolved = self._validate_path(path_str)
        except ValueError as e:
            return AgentResult(
                success=False, action_taken="search_files", summary=str(e),
            )

        try:
            matches = sorted(resolved.glob(pattern))
            # Filtere auf Einträge innerhalb des Projekts
            safe_matches = []
            for m in matches[:50]:
                try:
                    rel = m.relative_to(self._project_root)
                    suffix = "/" if m.is_dir() else ""
                    safe_matches.append(f"{rel.as_posix()}{suffix}")
                except ValueError:
                    continue

            total = len(matches)
            header = f"Suche '{pattern}': {total} Treffer"
            if total > 50:
                header += " (erste 50 angezeigt)"

            return AgentResult(
                success=True, action_taken="search_files",
                summary=header,
                details="\n".join(safe_matches) if safe_matches else "(keine Treffer)",
            )
        except Exception as e:
            return AgentResult(
                success=False, action_taken="search_files",
                summary=f"Fehler bei der Suche: {e}",
            )

    def _exec_system_status(self) -> AgentResult:
        """Gibt den Systemstatus zurück (delegiert an SystemMonitor)."""
        try:
            from elder_berry.system.info import SystemMonitor
            monitor = SystemMonitor()
            info = monitor.get_info(top_processes=5)

            lines = [
                f"CPU: {info.cpu.usage_percent}% "
                f"({info.cpu.core_count} Kerne, {info.cpu.thread_count} Threads)",
                f"RAM: {info.ram.used_mb:.0f} / {info.ram.total_mb:.0f} MB "
                f"({info.ram.usage_percent}%)",
            ]
            for gpu in info.gpus:
                lines.append(
                    f"GPU: {gpu.name} – {gpu.gpu_util_percent}%, "
                    f"VRAM {gpu.vram_used_mb:.0f}/{gpu.vram_total_mb:.0f} MB"
                )

            return AgentResult(
                success=True, action_taken="system_status",
                summary="Systemstatus abgerufen.",
                details="\n".join(lines),
            )
        except Exception as e:
            return AgentResult(
                success=False, action_taken="system_status",
                summary=f"Systemstatus nicht verfügbar: {e}",
            )

    def _exec_screenshot(self) -> AgentResult:
        """Nimmt einen Screenshot auf.

        Gibt den Pfad zur PNG-Datei zurück. Die Bridge ist dafür zuständig,
        das Bild zu senden und aufzuräumen.
        """
        try:
            import mss
            import mss.tools
        except ImportError:
            return AgentResult(
                success=False, action_taken="screenshot",
                summary="mss nicht installiert (pip install mss).",
            )

        try:
            import tempfile as tmp_mod
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                shot = sct.grab(monitor)
                tmp = tmp_mod.NamedTemporaryFile(
                    suffix=".png", prefix="agent_screenshot_", delete=False,
                )
                tmp_path = Path(tmp.name)
                tmp.close()
                mss.tools.to_png(shot.rgb, shot.size, output=str(tmp_path))

            return AgentResult(
                success=True, action_taken="screenshot",
                summary="Screenshot aufgenommen.",
                details=str(tmp_path),
            )
        except Exception as e:
            return AgentResult(
                success=False, action_taken="screenshot",
                summary=f"Screenshot fehlgeschlagen: {e}",
            )

    def _exec_run_tests(self, params: dict[str, Any]) -> AgentResult:
        """Führt pytest aus (read-only, keine Code-Änderungen)."""
        test_path = params.get("path", "")

        cmd = ["python", "-m", "pytest", "-v", "--tb=short"]
        if test_path:
            try:
                resolved = self._validate_path(test_path)
                cmd.append(str(resolved))
            except ValueError as e:
                return AgentResult(
                    success=False, action_taken="run_tests", summary=str(e),
                )

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self._project_root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout
            if result.returncode == 0:
                return AgentResult(
                    success=True, action_taken="run_tests",
                    summary="Tests bestanden.",
                    details=output,
                )
            else:
                return AgentResult(
                    success=False, action_taken="run_tests",
                    summary=f"Tests fehlgeschlagen (Exit-Code {result.returncode}).",
                    details=output + ("\n--- STDERR ---\n" + result.stderr[-1000:] if result.stderr else ""),
                )
        except subprocess.TimeoutExpired:
            return AgentResult(
                success=False, action_taken="run_tests",
                summary="Tests abgebrochen (Timeout 120s).",
            )
        except Exception as e:
            return AgentResult(
                success=False, action_taken="run_tests",
                summary=f"Fehler beim Ausführen der Tests: {e}",
            )

    def _exec_git_status(self) -> AgentResult:
        """Gibt git status + letzte Commits zurück."""
        try:
            status = subprocess.run(
                ["git", "status", "--short"],
                cwd=str(self._project_root),
                capture_output=True, text=True, timeout=10,
            )
            log = subprocess.run(
                ["git", "log", "--oneline", "-10"],
                cwd=str(self._project_root),
                capture_output=True, text=True, timeout=10,
            )

            lines = ["--- git status ---"]
            lines.append(status.stdout.strip() or "(clean)")
            lines.append("\n--- letzte 10 Commits ---")
            lines.append(log.stdout.strip())

            return AgentResult(
                success=True, action_taken="git_status",
                summary="Git-Status abgerufen.",
                details="\n".join(lines),
            )
        except Exception as e:
            return AgentResult(
                success=False, action_taken="git_status",
                summary=f"Git-Status nicht verfügbar: {e}",
            )

    def _execute_action(
        self, action: str, params: dict[str, Any], summary: str,
    ) -> AgentResult:
        """Führt eine validierte Aktion aus.

        Args:
            action: Validierter Aktionsname.
            params: Parameter für die Aktion.
            summary: Zusammenfassung von Claude.

        Returns:
            AgentResult mit dem Ergebnis.
        """
        if action == "answer_only":
            return AgentResult(
                success=True, action_taken="answer_only", summary=summary,
            )

        if action == "read_file":
            return self._exec_read_file(params)

        if action == "write_file":
            return self._exec_write_file(params)

        if action == "append_file":
            return self._exec_append_file(params)

        if action == "list_directory":
            return self._exec_list_directory(params)

        if action == "search_files":
            return self._exec_search_files(params)

        if action == "system_status":
            return self._exec_system_status()

        if action == "screenshot":
            return self._exec_screenshot()

        if action == "run_tests":
            return self._exec_run_tests(params)

        if action == "git_status":
            return self._exec_git_status()

        return AgentResult(
            success=False, action_taken=action,
            summary=f"Aktion '{action}' hat keinen Handler.",
        )

    def process(self, user_message: str) -> AgentResult:
        """Verarbeitet eine Nutzer-Nachricht über die Claude API.

        1. Kontext laden (CLAUDE.md + journal.txt)
        2. System-Prompt bauen
        3. Claude API aufrufen
        4. JSON-Antwort parsen und validieren
        5. Aktion ausführen
        6. AgentResult zurückgeben

        Args:
            user_message: Nachricht vom Nutzer (via Matrix).

        Returns:
            AgentResult mit Ergebnis der Aktion.
        """
        if not user_message or not user_message.strip():
            return AgentResult(
                success=False, action_taken="none",
                summary="Leere Nachricht erhalten.",
            )

        try:
            client = self._get_client()
        except ImportError as e:
            return AgentResult(
                success=False, action_taken="none", summary=str(e),
            )

        system_prompt = self._build_system_prompt()

        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_message},
                ],
            )
        except Exception as e:
            logger.error("Claude API Fehler: %s", e)
            return AgentResult(
                success=False, action_taken="none",
                summary=f"Claude API Fehler: {type(e).__name__}: {e}",
            )

        # Antwort-Text extrahieren
        raw_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw_text += block.text

        if not raw_text.strip():
            return AgentResult(
                success=False, action_taken="none",
                summary="Leere Antwort von Claude erhalten.",
            )

        # JSON parsen
        try:
            parsed = self._parse_response(raw_text)
        except ValueError as e:
            logger.warning("JSON-Parsing fehlgeschlagen: %s", e)
            # Fallback: Rohtext als answer_only behandeln
            return AgentResult(
                success=True, action_taken="answer_only",
                summary=raw_text[:500],
            )

        # Aktion validieren
        try:
            action, params, summary = self._validate_action(parsed)
        except ValueError as e:
            logger.warning("Aktions-Validierung fehlgeschlagen: %s", e)
            return AgentResult(
                success=False, action_taken="none", summary=str(e),
            )

        # Aktion ausführen
        logger.info(
            "ClaudeAgent: Aktion '%s' mit params=%s", action, params,
        )
        return self._execute_action(action, params, summary)
