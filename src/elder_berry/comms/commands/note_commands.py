"""NoteCommandHandler -- Wissensdatenbank (Fakten) + Notiz-Stubs.

Phase 91-A: NoteStore wurde gesplittet.
- Fakten-Commands (`merk dir`, `was ist`, `vergiss`) gehen jetzt an
  FactStore (lokal, SQLite).
- Notiz-Commands (`notiz:`, `notizen`, `notizen suche`, `notiz loeschen`)
  liefern einen Stub bis Phase 91-B/C den NextcloudNotesClient ausrollt.

Stub-Begruendung: Etappen 1 und 2 werden bewusst in getrennten Branches
gefahren (Konzept docs/concepts/note-nextcloud-replace.md §4.1).
Production-Luecke ist akzeptiert, weil Saleria in Testphase ohne
produktive Notizen laeuft (Lera-Freigabe 2026-05-13).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandPlugin,
    CommandResult,
    HandlerContext,
)

if TYPE_CHECKING:
    from elder_berry.tools.fact_store import FactStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# "merk dir: WLAN Buero ist xyz123" oder "merk dir WLAN Buero = xyz"
NOTE_SET_FACT_PATTERN = re.compile(
    r"^(?:bitte\s+)?(?:merk|merke)\s+dir[:\s]+(.+?)\s+(?:ist|=|:)\s+(.+)$",
    re.IGNORECASE,
)

# "notiz: Vermieter heisst Mueller"
# DOTALL bleibt erhalten (Phase 90-A, Multi-Line-Notizen).
NOTE_ADD_PATTERN = re.compile(
    r"^(?:bitte\s+)?notiz[:\s]+(.+)$",
    re.IGNORECASE | re.DOTALL,
)

# "was ist das WLAN Passwort?" / "wie lautet die Adresse"
# Negative Lookahead schuetzt Domain-Keywords vor Abfangen.
_DOMAIN_WORDS = r"wetter|termin|mail|todo|kontakt|erinnerung|timer"
NOTE_GET_FACT_PATTERN = re.compile(
    r"^(?:bitte\s+)?"
    r"(?:was\s+ist\s+(?!(?:(?:der|die|das|mein[e]?)\s+)?(?:" + _DOMAIN_WORDS + r")\b)"
    r"(?:(?:der|die|das|mein[e]?)\s+)?(.+?)"
    r"|wie\s+lautet\s+(?!(?:(?:der|die|das|mein[e]?)\s+)?(?:" + _DOMAIN_WORDS + r")\b)"
    r"(?:(?:der|die|das|mein[e]?)\s+)?(.+?))"
    r"\??\s*$",
    re.IGNORECASE,
)

# "notizen suche Vermieter"
NOTE_SEARCH_PATTERN = re.compile(
    r"^(?:bitte\s+)?notize?n?\s+suche\s+(.+)$",
    re.IGNORECASE,
)

# "notiz loeschen #3" oder "notiz loeschen 3"
NOTE_DELETE_PATTERN = re.compile(
    r"^(?:bitte\s+)?notiz(?:en)?\s+(?:löschen|lösche|entferne?)\s+#?(\d+)$",
    re.IGNORECASE,
)

# "vergiss WLAN Passwort Buero"
NOTE_DELETE_FACT_PATTERN = re.compile(
    r"^(?:bitte\s+)?vergiss\s+(.+)$",
    re.IGNORECASE,
)

_STUB_TEXT = (
    "📝 Notizen-Backend in Umstellung -- kommt in Phase 91-B/C "
    "(Nextcloud Notes API). Fakten (`merk dir`, `was ist`, `vergiss`) "
    "funktionieren weiterhin."
)


class NoteCommandHandler(CommandHandler):
    """Handler fuer Wissensdatenbank-Commands (Fakten) + Notiz-Stubs."""

    def __init__(
        self,
        fact_store: FactStore,
        default_user_id: str = "",
    ) -> None:
        """
        Args:
            fact_store: FactStore-Instanz.
            default_user_id: Fallback-User-ID (Single-User-Projekt).
        """
        self._store = fact_store
        self._default_user_id = default_user_id

    # ------------------------------------------------------------------
    # CommandHandler interface
    # ------------------------------------------------------------------

    @property
    def simple_commands(self) -> set[str]:
        return {"notizen"}

    @property
    def patterns(self) -> list[tuple[re.Pattern[str], str, bool, bool]]:
        # Reihenfolge: spezifische Patterns VOR generischen.
        # note_add ist generisch -- muss nach den spezifischen note_*-Patterns
        # stehen, sonst frisst es sie auf (z.B. ``notiz loeschen #1`` als
        # neue Notiz mit Inhalt "loeschen #1").
        return [
            (NOTE_SET_FACT_PATTERN, "note_set_fact", False, False),
            (NOTE_DELETE_PATTERN, "note_delete", False, False),
            (NOTE_SEARCH_PATTERN, "note_search", False, False),
            (NOTE_DELETE_FACT_PATTERN, "note_delete_fact", False, False),
            (NOTE_ADD_PATTERN, "note_add", False, False),
            (NOTE_GET_FACT_PATTERN, "note_get_fact", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "merk dir: <schlüssel> ist <wert>: Fakt speichern",
            "was ist <schlüssel>?: Fakt abrufen",
            "vergiss <schlüssel>: Fakt löschen",
            "notiz: <text>: (in Umstellung, kommt in Phase 91-B/C)",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "note_set_fact": [
                "merk dir",
                "merke dir",
                "speicher dir",
                "denk dran",
                "speichere",
            ],
            "note_add": ["notiz:", "notiere", "schreib auf"],
            "note_get_fact": [
                "was ist",
                "was war",
                "wie heißt",
                "wie lautet",
                "weißt du noch",
                "wann ist",
                "wer ist",
                "erinnerst du dich",
            ],
            "note_search": [
                "notizen suche",
                "notiz suche",
                "suche in notizen",
                "durchsuche notizen",
            ],
            "notizen": ["notizen", "alle notizen", "meine notizen"],
            "note_delete": ["notiz löschen", "lösche notiz"],
            "note_delete_fact": ["vergiss"],
        }

    def execute(self, command: str, raw_text: str, user_id: str = "") -> CommandResult:
        """Fuehrt einen erkannten Command aus."""
        uid = user_id or self._default_user_id

        match command:
            case "note_set_fact":
                return self._cmd_set_fact(raw_text, uid)
            case "note_get_fact":
                return self._cmd_get_fact(raw_text, uid)
            case "note_delete_fact":
                return self._cmd_delete_fact(raw_text, uid)
            case "note_add" | "note_search" | "note_delete" | "notizen":
                return self._cmd_notes_stub(command)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Notiz-Command: {command}",
        )

    # ------------------------------------------------------------------
    # Fakten-Commands (FactStore)
    # ------------------------------------------------------------------

    def _cmd_set_fact(self, raw_text: str, user_id: str) -> CommandResult:
        """merk dir: <key> ist <wert>"""
        match = NOTE_SET_FACT_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="note_set_fact",
                success=False,
                text="Nicht erkannt. Beispiel: merk dir: WLAN Passwort ist abc123",
            )

        key = match.group(1).strip()
        value = match.group(2).strip()

        existing = self._store.get_fact(user_id, key)
        fact = self._store.set_fact(user_id, key, value)

        if existing:
            return CommandResult(
                command="note_set_fact",
                success=True,
                text=(
                    f"✏️ Aktualisiert: **{fact.key}** = {value}\n"
                    f"_(vorher: {existing.content})_"
                ),
            )
        return CommandResult(
            command="note_set_fact",
            success=True,
            text=f"🔑 Gemerkt: **{fact.key}** = {value}",
        )

    def _cmd_get_fact(self, raw_text: str, user_id: str) -> CommandResult:
        """was ist <key>? -> KV-Lookup, Miss -> fallthrough ans LLM."""
        match = NOTE_GET_FACT_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="note_get_fact",
                success=False,
                fallthrough=True,
            )

        key = (match.group(1) or match.group(2) or "").strip()
        fact = self._store.get_fact(user_id, key)

        if fact is None:
            return CommandResult(
                command="note_get_fact",
                success=False,
                fallthrough=True,
            )

        return CommandResult(
            command="note_get_fact",
            success=True,
            text=f"🔑 **{fact.key}**: {fact.content}",
        )

    def _cmd_delete_fact(self, raw_text: str, user_id: str) -> CommandResult:
        """vergiss <key>"""
        match = NOTE_DELETE_FACT_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="note_delete_fact",
                success=False,
                text="Was soll ich vergessen? Beispiel: vergiss WLAN Passwort",
            )

        key = match.group(1).strip()
        deleted = self._store.delete_fact(user_id, key)

        if deleted:
            return CommandResult(
                command="note_delete_fact",
                success=True,
                text=f"🗑️ Fakt '{key}' vergessen.",
            )
        return CommandResult(
            command="note_delete_fact",
            success=False,
            text=f"Kein Fakt '{key}' gefunden.",
        )

    # ------------------------------------------------------------------
    # Notiz-Commands (Stub bis Phase 91-B/C)
    # ------------------------------------------------------------------

    def _cmd_notes_stub(self, command: str) -> CommandResult:
        """Stub fuer alle Notiz-Commands bis NextcloudNotesClient gerollt ist."""
        logger.info("Notiz-Command '%s' gestubbt (Phase 91-A)", command)
        return CommandResult(
            command=command,
            success=False,
            text=_STUB_TEXT,
        )


# ---------------------------------------------------------------------------
# Phase 77: Plugin-Manifest
# ---------------------------------------------------------------------------

HELP_SECTION_NOTE = """Wissen & Fakten:
  merk dir: <schluessel> ist <wert>  -- Fakt speichern
  was ist <schluessel>?               -- Fakt abrufen
  vergiss <schluessel>                -- Fakt loeschen

Notizen:
  notiz: <text>                       -- (in Umstellung, kommt in Phase 91-B/C)
  notizen / notizen suche / loeschen  -- (in Umstellung)"""


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    """Konstruiert NoteCommandHandler aus dem HandlerContext.

    Bedingung: ``ctx.fact_store`` muss gesetzt sein -- ohne FactStore
    keine Fakten.
    """
    if ctx.fact_store is None:
        return None
    return NoteCommandHandler(
        fact_store=ctx.fact_store,
        default_user_id=ctx.default_user_id,
    )


PLUGIN = CommandPlugin(
    name="note",
    priority=70,
    category="notizen",
    help_section=HELP_SECTION_NOTE,
    factory=_factory,
)
