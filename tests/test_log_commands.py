"""Tests für LogCommandHandler."""
from __future__ import annotations

from pathlib import Path

import pytest

from elder_berry.comms.commands.log_commands import (
    LOG_PATTERN,
    LogCommandHandler,
    MAX_ENTRIES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    """Temp-Verzeichnis mit elder_berry.log + security.log."""
    d = tmp_path / "logs"
    d.mkdir()

    main_log = d / "elder_berry.log"
    main_log.write_text(
        "2026-04-23 10:00:00 [INFO] foo: Start\n"
        "2026-04-23 10:00:01 [INFO] bar: Something happened\n"
        "2026-04-23 10:00:02 [WARNING] baz: Slow query\n"
        "2026-04-23 10:00:03 [ERROR] qux: Connection failed\n"
        "2026-04-23 10:00:04 [INFO] foo: Recovered\n"
        "2026-04-23 10:00:05 [CRITICAL] sys: Out of memory\n",
        encoding="utf-8",
    )

    sec_log = d / "security.log"
    sec_log.write_text(
        "2026-04-23 11:00:00 [WARNING] security: Login failed for user X\n"
        "2026-04-23 11:00:05 [INFO] security: Login successful\n",
        encoding="utf-8",
    )

    return d


@pytest.fixture
def handler(log_dir: Path) -> LogCommandHandler:
    return LogCommandHandler(log_dir=log_dir)


# ---------------------------------------------------------------------------
# Pattern
# ---------------------------------------------------------------------------

class TestPattern:
    def test_log_bare(self):
        m = LOG_PATTERN.match("log")
        assert m
        assert m.group(1) is None
        assert m.group(2) is None

    def test_log_with_count(self):
        m = LOG_PATTERN.match("log 20")
        assert m
        assert m.group(1) is None
        assert m.group(2) == "20"

    def test_log_errors(self):
        m = LOG_PATTERN.match("log errors")
        assert m
        assert m.group(1) == "errors"
        assert m.group(2) is None

    def test_log_errors_with_count(self):
        m = LOG_PATTERN.match("log errors 5")
        assert m
        assert m.group(1) == "errors"
        assert m.group(2) == "5"

    def test_log_warnings(self):
        m = LOG_PATTERN.match("log warnings")
        assert m
        assert m.group(1) == "warnings"

    def test_log_security(self):
        m = LOG_PATTERN.match("log security")
        assert m
        assert m.group(1) == "security"

    def test_case_insensitive(self):
        assert LOG_PATTERN.match("LOG")
        assert LOG_PATTERN.match("Log Errors 10")

    def test_invalid(self):
        assert not LOG_PATTERN.match("log foo")
        assert not LOG_PATTERN.match("log errors foo")
        assert not LOG_PATTERN.match("log debug")
        assert not LOG_PATTERN.match("logs")


# ---------------------------------------------------------------------------
# execute – default log
# ---------------------------------------------------------------------------

class TestLogDefault:
    def test_returns_default_10(self, handler):
        # Log hat nur 6 Zeilen – sollte alle zurückgeben
        result = handler.execute("log", "log")
        assert result.success is True
        assert "📋 Log" in result.text
        assert "Start" in result.text
        assert "Out of memory" in result.text

    def test_returns_explicit_count(self, handler):
        result = handler.execute("log", "log 3")
        assert result.success is True
        # Letzte 3 Zeilen: Recovered, Out of memory... und vor Recovered die ERROR
        assert "Out of memory" in result.text
        assert "Recovered" in result.text
        assert "Connection failed" in result.text
        # Start + "Something happened" sollten NICHT dabei sein
        assert "Start" not in result.text
        assert "Something happened" not in result.text

    def test_max_entries_enforced(self, handler):
        # count=500 wird auf MAX_ENTRIES gekappt
        result = handler.execute("log", f"log {MAX_ENTRIES * 10}")
        assert result.success is True
        assert f"letzte {MAX_ENTRIES}" in result.text


# ---------------------------------------------------------------------------
# execute – filtered
# ---------------------------------------------------------------------------

class TestLogErrors:
    def test_only_errors_and_critical(self, handler):
        result = handler.execute("log", "log errors")
        assert result.success is True
        assert "Connection failed" in result.text  # [ERROR]
        assert "Out of memory" in result.text      # [CRITICAL]
        assert "Start" not in result.text          # [INFO]
        assert "Slow query" not in result.text     # [WARNING]

    def test_title_is_errors(self, handler):
        result = handler.execute("log", "log errors")
        assert "Fehler-Einträge" in result.text


class TestLogWarnings:
    def test_warnings_errors_and_critical(self, handler):
        result = handler.execute("log", "log warnings")
        assert result.success is True
        assert "Slow query" in result.text       # [WARNING]
        assert "Connection failed" in result.text  # [ERROR]
        assert "Out of memory" in result.text     # [CRITICAL]
        assert "Start" not in result.text         # [INFO]


# ---------------------------------------------------------------------------
# execute – security.log
# ---------------------------------------------------------------------------

class TestLogSecurity:
    def test_reads_security_log(self, handler):
        result = handler.execute("log", "log security")
        assert result.success is True
        assert "🔐 Security-Log" in result.text
        assert "Login failed" in result.text
        assert "Login successful" in result.text

    def test_security_ignores_filter(self, handler):
        """'log security' gibt alle Einträge zurück, keine Level-Filterung."""
        result = handler.execute("log", "log security")
        # Beide Einträge sollen dabei sein, egal welches Level
        assert "Login failed" in result.text
        assert "Login successful" in result.text


# ---------------------------------------------------------------------------
# execute – Fehlerfälle
# ---------------------------------------------------------------------------

class TestErrorCases:
    def test_log_file_missing(self, tmp_path: Path):
        """Fehlende Log-Datei liefert freundliche Fehlermeldung."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        h = LogCommandHandler(log_dir=empty_dir)
        result = h.execute("log", "log")
        assert result.success is False
        assert "nicht gefunden" in result.text

    def test_empty_log_file(self, tmp_path: Path):
        """Leere Log-Datei: success=True, aber 'keine Einträge'."""
        d = tmp_path / "logs"
        d.mkdir()
        (d / "elder_berry.log").write_text("", encoding="utf-8")
        h = LogCommandHandler(log_dir=d)
        result = h.execute("log", "log")
        assert result.success is True
        assert "keine Einträge" in result.text

    def test_no_matching_filter(self, tmp_path: Path):
        """Log ohne Errors: success=True, aber 'keine Einträge'."""
        d = tmp_path / "logs"
        d.mkdir()
        (d / "elder_berry.log").write_text(
            "2026-04-23 10:00:00 [INFO] foo: Start\n"
            "2026-04-23 10:00:01 [INFO] bar: Running\n",
            encoding="utf-8",
        )
        h = LogCommandHandler(log_dir=d)
        result = h.execute("log", "log errors")
        assert result.success is True
        assert "keine Einträge" in result.text

    def test_invalid_command(self, handler):
        result = handler.execute("log", "log foo bar baz")
        assert result.success is False
        assert "Nutze" in result.text

    def test_unknown_command(self, handler):
        result = handler.execute("foo", "foo")
        assert result.success is False
        assert "Unbekannter Command" in result.text


# ---------------------------------------------------------------------------
# Length limit
# ---------------------------------------------------------------------------

class TestLengthLimit:
    def test_long_log_gets_truncated(self, tmp_path: Path):
        """Sehr lange Responses werden auf MAX_RESPONSE_CHARS gekürzt."""
        d = tmp_path / "logs"
        d.mkdir()
        # 50 Zeilen à ~200 Zeichen → >10000
        long_lines = [
            f"2026-04-23 10:00:{i:02d} [ERROR] x: " + ("A" * 200)
            for i in range(50)
        ]
        (d / "elder_berry.log").write_text(
            "\n".join(long_lines) + "\n", encoding="utf-8",
        )
        h = LogCommandHandler(log_dir=d)
        result = h.execute("log", "log 50")
        assert result.success is True
        assert "[...gekürzt]" in result.text
        # Response <= MAX_RESPONSE_CHARS + Truncation-Marker
        assert len(result.text) < 4100


# ---------------------------------------------------------------------------
# Handler-API (simple_commands, patterns, keywords)
# ---------------------------------------------------------------------------

class TestHandlerAPI:
    def test_simple_commands(self, handler):
        assert "log" in handler.simple_commands

    def test_patterns(self, handler):
        assert len(handler.patterns) == 1
        pattern, cmd, use_orig, use_search = handler.patterns[0]
        assert cmd == "log"
        assert use_orig is False
        assert use_search is False

    def test_keywords(self, handler):
        kw = handler.keywords
        assert "log" in kw
        assert "fehlermeldungen" in kw["log"]

    def test_command_descriptions(self, handler):
        descs = handler.command_descriptions
        assert len(descs) == 4
        assert any("errors" in d for d in descs)
        assert any("warnings" in d for d in descs)
        assert any("security" in d for d in descs)
