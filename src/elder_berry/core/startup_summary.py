"""StartupSummary – Komponenten-Status-Übersicht beim Saleria-Start (Phase 52.2).

Sammelt während der ``init_*``-Aufrufe in ``scripts/start_saleria.py`` den
Status jeder Komponente und rendert am Ende eine ASCII-Box. Die Summary
kann zusätzlich als Markdown-Nachricht via Matrix verschickt werden.

Eigene Datei statt Inline-Funktion in ``start_saleria.py``, damit die
Klasse testbar ist und später für ein ``/api/status``-Endpoint
wiederverwendet werden kann.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["ok", "warn", "fail"]

_STATUS_GLYPHS: dict[Status, str] = {
    "ok": "✓",
    "warn": "⚠",
    "fail": "✗",
}

_VALID_STATUS: frozenset[str] = frozenset(_STATUS_GLYPHS.keys())


@dataclass(frozen=True)
class _SummaryEntry:
    component: str
    status: Status
    detail: str = ""


@dataclass
class StartupSummary:
    """Sammelt und rendert den Startup-Status von Saleria-Komponenten.

    Beispiel
    --------
    >>> summary = StartupSummary()
    >>> summary.add("LLM", "ok", "Anthropic (Sonnet 4.6)")
    >>> summary.add("Email", "warn", "nicht konfiguriert")
    >>> print(summary.render())
    """

    title: str = "Saleria – Startup Summary"
    _entries: list[_SummaryEntry] = field(default_factory=list)

    def add(self, component: str, status: Status, detail: str = "") -> None:
        """Fügt einen Komponenten-Status hinzu.

        Parameters
        ----------
        component
            Anzeigename der Komponente (z.B. "LLM", "Matrix", "Tower").
        status
            ``"ok"``, ``"warn"`` oder ``"fail"``.
        detail
            Optionaler Detail-Text, der hinter dem Komponenten-Namen
            erscheint.
        """
        if status not in _VALID_STATUS:
            raise ValueError(
                f"Ungültiger Status '{status}'. Erlaubt: {sorted(_VALID_STATUS)}",
            )
        if not component or not component.strip():
            raise ValueError("component darf nicht leer sein.")
        self._entries.append(
            _SummaryEntry(component=component.strip(), status=status, detail=detail.strip()),
        )

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> tuple[_SummaryEntry, ...]:
        return tuple(self._entries)

    def counts(self) -> dict[Status, int]:
        """Anzahl Einträge pro Status."""
        result: dict[Status, int] = {"ok": 0, "warn": 0, "fail": 0}
        for entry in self._entries:
            result[entry.status] += 1
        return result

    def has_failures(self) -> bool:
        return any(e.status == "fail" for e in self._entries)

    def render(self, width: int | None = None) -> str:
        """Rendert die Summary als ASCII-Box.

        Parameters
        ----------
        width
            Optionale feste Breite des Inhalts (ohne Rahmen). Wenn None,
            wird die Breite an den längsten Eintrag angepasst (mind. 36).
        """
        lines = self._format_lines()
        content_width = max((len(line) for line in lines), default=0)
        title_width = len(self.title)
        content_width = max(content_width, title_width, 36)
        if width is not None:
            content_width = max(width, title_width)

        top = "╔" + "═" * (content_width + 2) + "╗"
        sep = "╠" + "═" * (content_width + 2) + "╣"
        bottom = "╚" + "═" * (content_width + 2) + "╝"
        title_line = "║ " + self.title.center(content_width) + " ║"

        if not lines:
            empty = "║ " + "(keine Komponenten)".center(content_width) + " ║"
            return "\n".join([top, title_line, sep, empty, bottom])

        body = [
            "║ " + line.ljust(content_width) + " ║"
            for line in lines
        ]
        return "\n".join([top, title_line, sep, *body, bottom])

    def _format_lines(self) -> list[str]:
        result = []
        for entry in self._entries:
            glyph = _STATUS_GLYPHS[entry.status]
            if entry.detail:
                result.append(f"{glyph} {entry.component}: {entry.detail}")
            else:
                result.append(f"{glyph} {entry.component}")
        return result

    def to_matrix_message(self) -> str:
        """Rendert die Summary als Markdown-Nachricht für Matrix.

        Verwendet eine kompakte Liste statt der ASCII-Box, weil
        Code-Blöcke in Matrix-Clients monospace gerendert werden.
        """
        if not self._entries:
            return f"**{self.title}**\n\n_(keine Komponenten erfasst)_"
        body_lines = [f"**{self.title}**", ""]
        for entry in self._entries:
            glyph = _STATUS_GLYPHS[entry.status]
            line = f"- {glyph} **{entry.component}**"
            if entry.detail:
                line += f": {entry.detail}"
            body_lines.append(line)
        counts = self.counts()
        body_lines.append("")
        body_lines.append(
            f"_{counts['ok']} ok · {counts['warn']} warn · {counts['fail']} fail_",
        )
        return "\n".join(body_lines)
