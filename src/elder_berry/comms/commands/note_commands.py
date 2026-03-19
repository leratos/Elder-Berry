"""NoteCommandHandler – Notizen & Wissensdatenbank Commands.

Verwaltet:
- merk dir: <key> ist/=: <wert> → Key-Value-Fakt speichern
- notiz: <text>                   → Freitext-Notiz speichern
- was ist <key>?                  → KV-Fakt abrufen (Miss → LLM-Fallthrough)
- notizen suche <query>           → Volltextsuche
- notizen                         → Alle Notizen auflisten
- notiz löschen #<id>             → Notiz per ID löschen
- vergiss <key>                   → KV-Fakt per Key löschen
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.tools.note_store import NoteStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# "merk dir: WLAN Büro ist xyz123" oder "merk dir WLAN Büro = xyz"
NOTE_SET_FACT_PATTERN = re.compile(
    r"^(?:merk|merke)\s+dir[:\s]+(.+?)\s+(?:ist|=|:)\s+(.+)$",
    re.IGNORECASE,
)

# "notiz: Vermieter heißt Müller"
NOTE_ADD_PATTERN = re.compile(
    r"^notiz[:\s]+(.+)$",
    re.IGNORECASE,
)

# "was ist das WLAN Passwort?" oder "was ist WLAN Büro"
NOTE_GET_FACT_PATTERN = re.compile(
    r"^was\s+ist\s+(?:(?:der|die|das|mein[e]?)\s+)?(.+?)\??\s*$",
    re.IGNORECASE,
)

# "notizen suche Vermieter"
NOTE_SEARCH_PATTERN = re.compile(
    r"^notize?n?\s+suche\s+(.+)$",
    re.IGNORECASE,
)

# "notiz löschen #3" oder "notiz löschen 3"
NOTE_DELETE_PATTERN = re.compile(
    r"^notiz(?:en)?\s+(?:löschen|lösche|entferne?)\s+#?(\d+)$",
    re.IGNORECASE,
)

# "vergiss WLAN Passwort Büro"
NOTE_DELETE_FACT_PATTERN = re.compile(
    r"^vergiss\s+(.+)$",
    re.IGNORECASE,
)


class NoteCommandHandler(CommandHandler):
    """Handler für Notizen & Wissensdatenbank Commands."""

    def __init__(
        self,
        note_store: NoteStore,
        default_user_id: str = "",
    ) -> None:
        """
        Args:
            note_store: NoteStore-Instanz.
            default_user_id: Fallback-User-ID (Single-User-Projekt).
                Wird verwendet wenn execute() keinen user_id-Kontext hat.
        """
        self._store = note_store
        self._default_user_id = default_user_id

    # ------------------------------------------------------------------
    # CommandHandler interface
    # ------------------------------------------------------------------

    @property
    def simple_commands(self) -> set[str]:
        return {"notizen"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (NOTE_SET_FACT_PATTERN, "note_set_fact", False, False),
            (NOTE_ADD_PATTERN, "note_add", False, False),
            (NOTE_SEARCH_PATTERN, "note_search", False, False),
            (NOTE_DELETE_PATTERN, "note_delete", False, False),
            (NOTE_DELETE_FACT_PATTERN, "note_delete_fact", False, False),
            # note_get_fact zuletzt: "was ist" ist sehr allgemein
            (NOTE_GET_FACT_PATTERN, "note_get_fact", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "merk dir: <schlüssel> ist <wert>: Fakt speichern",
            "notiz: <text>: Freitext-Notiz speichern",
            "was ist <schlüssel>?: Fakt abrufen",
            "notizen suche <begriff>: Notizen durchsuchen",
            "notizen: Alle Notizen anzeigen",
            "notiz löschen #<id> / vergiss <schlüssel>: Notiz/Fakt löschen",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "note_set_fact": [
                "merk dir", "merke dir", "speicher dir",
                "denk dran", "speichere",
            ],
            "note_add": ["notiz:", "notiere", "schreib auf"],
            "note_get_fact": [
                "was ist", "was war", "wie heißt", "wie lautet",
                "weißt du noch", "wann ist", "wer ist",
                "erinnerst du dich",
            ],
            "note_search": [
                "notizen suche", "notiz suche", "suche in notizen",
                "durchsuche notizen",
            ],
            "notizen": ["notizen", "alle notizen", "meine notizen"],
            "note_delete": ["notiz löschen", "lösche notiz"],
            "note_delete_fact": ["vergiss"],
        }

    def execute(self, command: str, raw_text: str, user_id: str = "") -> CommandResult:
        """Führt einen erkannten Command aus.

        Args:
            command: Normalisierter Command-Name.
            raw_text: Originaler Nachrichtentext.
            user_id: Matrix-User-ID (optional, Fallback auf default_user_id).

        Returns:
            CommandResult. Bei note_get_fact-Miss: success=False für LLM-Fallthrough.
        """
        uid = user_id or self._default_user_id

        match command:
            case "note_set_fact":
                return self._cmd_set_fact(raw_text, uid)
            case "note_add":
                return self._cmd_add_note(raw_text, uid)
            case "note_get_fact":
                return self._cmd_get_fact(raw_text, uid)
            case "note_search":
                return self._cmd_search(raw_text, uid)
            case "notizen":
                return self._cmd_list(uid)
            case "note_delete":
                return self._cmd_delete(raw_text)
            case "note_delete_fact":
                return self._cmd_delete_fact(raw_text, uid)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Notiz-Command: {command}",
        )

    # ------------------------------------------------------------------
    # Command-Implementierungen
    # ------------------------------------------------------------------

    def _cmd_set_fact(self, raw_text: str, user_id: str) -> CommandResult:
        """merk dir: <key> ist <wert>"""
        match = NOTE_SET_FACT_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="note_set_fact",
                success=False,
                text="Format: merk dir: <schlüssel> ist <wert>",
            )

        key = match.group(1).strip()
        value = match.group(2).strip()

        # Prüfe ob bereits vorhanden (für Feedback)
        existing = self._store.get_fact(user_id, key)
        note = self._store.set_fact(user_id, key, value)

        if existing:
            return CommandResult(
                command="note_set_fact",
                success=True,
                text=(
                    f"✏️ Aktualisiert: **{note.key}** = {value}\n"
                    f"_(vorher: {existing.content})_"
                ),
            )
        return CommandResult(
            command="note_set_fact",
            success=True,
            text=f"🔑 Gemerkt: **{note.key}** = {value}",
        )

    def _cmd_add_note(self, raw_text: str, user_id: str) -> CommandResult:
        """notiz: <freitext>"""
        match = NOTE_ADD_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="note_add",
                success=False,
                text="Format: notiz: <text>",
            )

        content = match.group(1).strip()
        note = self._store.add_note(user_id, content)
        return CommandResult(
            command="note_add",
            success=True,
            text=f"📝 Notiz #{note.id} gespeichert.",
        )

    def _cmd_get_fact(self, raw_text: str, user_id: str) -> CommandResult:
        """was ist <key>? → KV-Lookup, Miss → success=False (LLM-Fallthrough)."""
        match = NOTE_GET_FACT_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="note_get_fact", success=False, text=None)

        key = match.group(1).strip()
        note = self._store.get_fact(user_id, key)

        if note is None:
            # Kein Treffer → LLM-Fallthrough (success=False, kein Text)
            return CommandResult(command="note_get_fact", success=False, text=None)

        return CommandResult(
            command="note_get_fact",
            success=True,
            text=f"🔑 **{note.key}**: {note.content}",
        )

    def _cmd_search(self, raw_text: str, user_id: str) -> CommandResult:
        """notizen suche <query>"""
        match = NOTE_SEARCH_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="note_search",
                success=False,
                text="Format: notizen suche <begriff>",
            )

        query = match.group(1).strip()
        results = self._store.search(user_id, query)

        if not results:
            return CommandResult(
                command="note_search",
                success=True,
                text=f"Keine Notizen gefunden für: '{query}'",
            )

        lines = [f"🔍 **{len(results)} Treffer** für '{query}':"]
        for note in results:
            lines.append(f"  {note.format_short()}")

        return CommandResult(
            command="note_search",
            success=True,
            text="\n".join(lines),
        )

    def _cmd_list(self, user_id: str) -> CommandResult:
        """notizen → Alle Notizen (max 20)"""
        notes = self._store.list_all(user_id)

        if not notes:
            return CommandResult(
                command="notizen",
                success=True,
                text="Keine Notizen vorhanden. Tipp: 'merk dir: ...' oder 'notiz: ...'",
            )

        lines = [f"📋 **{len(notes)} Notizen**:"]
        for note in notes:
            lines.append(f"  {note.format_short()}")

        return CommandResult(
            command="notizen",
            success=True,
            text="\n".join(lines),
        )

    def _cmd_delete(self, raw_text: str) -> CommandResult:
        """notiz löschen #<id>"""
        match = NOTE_DELETE_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="note_delete",
                success=False,
                text="Format: notiz löschen #<id>",
            )

        note_id = int(match.group(1))
        deleted = self._store.delete(note_id)

        if deleted:
            return CommandResult(
                command="note_delete",
                success=True,
                text=f"🗑️ Notiz #{note_id} gelöscht.",
            )
        return CommandResult(
            command="note_delete",
            success=False,
            text=f"Notiz #{note_id} nicht gefunden.",
        )

    def _cmd_delete_fact(self, raw_text: str, user_id: str) -> CommandResult:
        """vergiss <key>"""
        match = NOTE_DELETE_FACT_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="note_delete_fact",
                success=False,
                text="Format: vergiss <schlüssel>",
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
