"""LogCommandHandler – Remote-Zugriff auf die letzten Log-Einträge.

Ermöglicht es dem Nutzer, die letzten N Einträge aus ``logs/elder_berry.log``
und ``logs/security.log`` über Matrix zu lesen, ohne per SSH auf den Server
zu müssen.

Commands:
  log [n]          – Letzte N Einträge (default 10, max 50)
  log errors [n]   – Nur ERROR/CRITICAL (default 10)
  log warnings [n] – Nur WARNING+ (default 10)
  log security [n] – Aus security.log (default 10)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from elder_berry.comms.commands.base import CommandHandler, CommandResult

logger = logging.getLogger(__name__)

# Maximale Anzahl Einträge pro Request (Spam-Schutz)
MAX_ENTRIES = 50

# Default-Anzahl wenn keine Zahl angegeben wird
DEFAULT_ENTRIES = 10

# Maximale Zeichen pro Matrix-Nachricht (Safety-Margin)
MAX_RESPONSE_CHARS = 3800

# Regex: "log", "log 20", "log errors", "log errors 5",
# "log warnings", "log warnings 20", "log security", "log security 15"
LOG_PATTERN = re.compile(
    r"^log(?:\s+(errors|warnings|security))?(?:\s+(\d+))?$",
    re.IGNORECASE,
)


class LogCommandHandler(CommandHandler):
    """Handler für Log-Zugriff via Matrix.

    Liest ausschließlich aus dem konfigurierten log_dir (default ``logs/``).
    Kein Path-Traversal, kein Schreiben.
    """

    def __init__(self, log_dir: Path | None = None) -> None:
        self._log_dir = log_dir or Path("logs")

    @property
    def simple_commands(self) -> set[str]:
        return {"log"}

    @property
    def patterns(self) -> list:
        return [
            (LOG_PATTERN, "log", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "log [n]: Letzte N Log-Einträge (default 10, max 50)",
            "log errors [n]: Nur Fehler-Einträge",
            "log warnings [n]: Nur Warnungen+",
            "log security [n]: Security-Audit-Log",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "log": [
                "log", "logs", "logfile", "log-datei", "log datei",
                "zeig log", "zeig mir log", "letzte log",
                "fehlermeldungen", "fehler log", "error log",
                "was sagen die logs",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command != "log":
            return CommandResult(
                command=command, success=False,
                text=f"Unbekannter Command: {command}",
            )

        return self._cmd_log(raw_text)

    def _cmd_log(self, raw_text: str) -> CommandResult:
        match = LOG_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="log", success=False,
                text=(
                    "Nutze: log [n] / log errors [n] / "
                    "log warnings [n] / log security [n]"
                ),
            )

        filter_kind = (match.group(1) or "").lower()
        count_str = match.group(2)
        count = int(count_str) if count_str else DEFAULT_ENTRIES
        count = min(count, MAX_ENTRIES)

        if filter_kind == "security":
            log_file = self._log_dir / "security.log"
            filter_level = None
            title = f"🔐 Security-Log (letzte {count})"
        else:
            log_file = self._log_dir / "elder_berry.log"
            filter_level = self._level_filter(filter_kind)
            title = self._title(filter_kind, count)

        if not log_file.exists():
            return CommandResult(
                command="log", success=False,
                text=f"❌ Log-Datei nicht gefunden: {log_file.name}",
            )

        try:
            entries = self._read_last_entries(log_file, count, filter_level)
        except OSError as e:
            logger.error("Log-Datei lesen fehlgeschlagen: %s", e)
            return CommandResult(
                command="log", success=False,
                text=f"❌ Log-Datei konnte nicht gelesen werden: {type(e).__name__}",
            )

        if not entries:
            return CommandResult(
                command="log", success=True,
                text=f"{title}\n(keine Einträge gefunden)",
            )

        body = "\n".join(entries)
        text = f"{title}\n{body}"
        if len(text) > MAX_RESPONSE_CHARS:
            text = text[:MAX_RESPONSE_CHARS] + "\n[...gekürzt]"

        return CommandResult(
            command="log", success=True, text=text,
        )

    @staticmethod
    def _level_filter(filter_kind: str) -> set[str] | None:
        """Liefert das Set von Log-Leveln die durchgelassen werden."""
        if filter_kind == "errors":
            return {"ERROR", "CRITICAL"}
        if filter_kind == "warnings":
            return {"WARNING", "ERROR", "CRITICAL"}
        return None

    @staticmethod
    def _title(filter_kind: str, count: int) -> str:
        if filter_kind == "errors":
            return f"❌ Fehler-Einträge (letzte {count})"
        if filter_kind == "warnings":
            return f"⚠ Warnungen+ (letzte {count})"
        return f"📋 Log (letzte {count})"

    @staticmethod
    def _read_last_entries(
        log_file: Path, count: int, filter_level: set[str] | None,
    ) -> list[str]:
        """Liest die letzten N Einträge – optional gefiltert nach Log-Level.

        Beim Filtern werden mehr Zeilen gelesen als ohne Filter, damit
        z.B. 10 Error-Zeilen auch dann gefunden werden, wenn sie selten
        vorkommen. Hart limitiert durch tail-Größe.
        """
        # Mehr Zeilen lesen wenn gefiltert wird, damit wir genug treffer finden
        read_lines = count if filter_level is None else min(count * 200, 5000)

        with log_file.open("r", encoding="utf-8", errors="replace") as f:
            # Effizientes Tail: von hinten lesen
            lines = _tail_lines(f, read_lines)

        if filter_level:
            filtered = [line for line in lines if _line_matches_level(line, filter_level)]
            return filtered[-count:]

        return lines[-count:]


def _tail_lines(file_obj, max_lines: int) -> list[str]:
    """Liest die letzten max_lines Zeilen aus einer Datei.

    Für kleine Logs (<5000 Zeilen) einfach komplett lesen.
    Für größere Logs: von hinten blockweise lesen.
    """
    # Einfache Implementierung: alle Zeilen lesen, dann tail
    # Logs sind durch RotatingFileHandler auf 5MB begrenzt → kein Memory-Problem
    all_lines = file_obj.read().splitlines()
    return all_lines[-max_lines:]


def _line_matches_level(line: str, levels: set[str]) -> bool:
    """Prüft ob eine Log-Zeile ein bestimmtes Level hat.

    Format: "2026-04-23 12:34:56 [LEVEL] logger: message"
    """
    for level in levels:
        if f"[{level}]" in line:
            return True
    return False
