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

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandPlugin,
    CommandResult,
    HandlerContext,
)

if TYPE_CHECKING:
    from elder_berry.tools.note_store import NoteStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# "merk dir: WLAN Büro ist xyz123" oder "merk dir WLAN Büro = xyz"
NOTE_SET_FACT_PATTERN = re.compile(
    r"^(?:bitte\s+)?(?:merk|merke)\s+dir[:\s]+(.+?)\s+(?:ist|=|:)\s+(.+)$",
    re.IGNORECASE,
)

# "notiz: Vermieter heißt Müller"
# DOTALL: ``.`` matcht auch Newlines, damit Multi-Line-Notizen
# (Saleria-Command "notiz: Einkaufsliste\n- Vodka\n- Limette") nicht
# am ersten ``\n`` abgeschnitten werden -- Phase 90-A,
# Lera-Smoketest 2026-05-13 (Moscow-Mule-Einkaufsliste).
NOTE_ADD_PATTERN = re.compile(
    r"^(?:bitte\s+)?notiz[:\s]+(.+)$",
    re.IGNORECASE | re.DOTALL,
)

# "was ist das WLAN Passwort?" oder "was ist WLAN Büro"
# "wie lautet das Passwort?" oder "wie lautet die Adresse"
# Negative Lookahead: Domain-Keywords (wetter, termin, mail, ...) nicht abfangen,
# damit diese an die zuständigen Handler weitergeleitet werden.
# Negative Lookahead: prueft ob nach optionalem Artikel ein Domain-Keyword folgt.
# Steht VOR der optionalen Artikel-Gruppe, damit kein Backtracking den Schutz umgeht.
#
# 2026-05-11 (Codex-Reviewer P2): ``(?:bitte\s+)?``-Prefix in DELETE,
# SEARCH, DELETE_FACT und GET_FACT eingefuegt -- parse_command strippt
# fuehrende Filler bevor es matcht, aber execute() bekommt den rohen
# Text mit "bitte ..." drin. Ohne den Prefix waere der _cmd_*-Re-Parse-
# Schritt mit "bitte" am Anfang fehlgeschlagen. Loesung analog zu
# NOTE_ADD_PATTERN/NOTE_SET_FACT_PATTERN (haben den Prefix schon).
# Hinweis: das deckt NUR "bitte" ab; andere Filler ("kannst du mir mal"
# etc.) brauchen einen breiteren Architektur-Fix -- separates Konzept.
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

# "notiz löschen #3" oder "notiz löschen 3"
NOTE_DELETE_PATTERN = re.compile(
    r"^(?:bitte\s+)?notiz(?:en)?\s+(?:löschen|lösche|entferne?)\s+#?(\d+)$",
    re.IGNORECASE,
)

# "vergiss WLAN Passwort Büro"
NOTE_DELETE_FACT_PATTERN = re.compile(
    r"^(?:bitte\s+)?vergiss\s+(.+)$",
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
    def patterns(self) -> list[tuple[re.Pattern[str], str, bool, bool]]:
        # Reihenfolge: spezifische Patterns VOR generischen.
        # 2026-05-11 (Smoketest-Fix): NOTE_ADD_PATTERN matcht ``notiz <text>``
        # mit beliebigem text -- inkl. ``notiz löschen #1`` und ``notiz suche
        # ...``. Wenn note_add hier vor note_delete/note_search steht, werden
        # diese spezifischen Commands als neue Notiz mit text="löschen #1"
        # bzw. text="suche ..." angelegt. note_set_fact (merk dir: ...) und
        # note_delete_fact (vergiss ...) sind disjunkt zu note_add (anderer
        # Stamm), aber zur Klarheit ebenfalls vorne.
        return [
            (NOTE_SET_FACT_PATTERN, "note_set_fact", False, False),
            (NOTE_DELETE_PATTERN, "note_delete", False, False),
            (NOTE_SEARCH_PATTERN, "note_search", False, False),
            (NOTE_DELETE_FACT_PATTERN, "note_delete_fact", False, False),
            # note_add ist generisch (``notiz <text>``) -- muss NACH den
            # spezifischen Note-Patterns stehen, sonst frisst es sie auf.
            (NOTE_ADD_PATTERN, "note_add", False, False),
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
                text="Nicht erkannt. Beispiel: merk dir: WLAN Passwort ist abc123",
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
                text="Text fehlt. Beispiel: notiz: Vermieter heißt Müller",
            )

        content = match.group(1).strip()
        note = self._store.add_note(user_id, content)
        return CommandResult(
            command="note_add",
            success=True,
            text=f"📝 Notiz #{note.id} gespeichert.",
        )

    def _cmd_get_fact(self, raw_text: str, user_id: str) -> CommandResult:
        """was ist <key>? → KV-Lookup, Miss → fallthrough ans LLM."""
        match = NOTE_GET_FACT_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="note_get_fact",
                success=False,
                fallthrough=True,
            )

        key = (match.group(1) or match.group(2) or "").strip()
        note = self._store.get_fact(user_id, key)

        if note is None:
            # Kein Treffer → LLM-Fallthrough (z.B. "was ist deine meinung")
            return CommandResult(
                command="note_get_fact",
                success=False,
                fallthrough=True,
            )

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
                text="Suchbegriff fehlt. Beispiel: notizen suche Vermieter",
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

        # Phase 80 Etappe 3: voller content wandert ins Item, damit der
        # Bridge-list_pick "zeig mir Notiz 1" ohne Store-Round-Trip die
        # echte Notiz zeigen kann (Konzept-Tabelle nennt content_excerpt;
        # voller content ist hier praktischer, weil Notizen klein sind).
        list_items = [{"id": n.id, "key": n.key, "content": n.content} for n in results]

        return CommandResult(
            command="note_search",
            success=True,
            text="\n".join(lines),
            list_items=list_items,
            list_type="note_search",
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
                text="Welche Notiz? Beispiel: notiz löschen #3",
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


# ---------------------------------------------------------------------------
# Phase 77: Plugin-Manifest
# ---------------------------------------------------------------------------

HELP_SECTION_NOTE = """Notizen & Wissen:
  merk dir: <schluessel> ist <wert>  -- Fakt speichern
  notiz: <text>                       -- Freitext-Notiz speichern
  was ist <schluessel>?               -- Fakt abrufen
  notizen suche <Begriff>             -- Notizen durchsuchen
  notizen                             -- Alle Notizen anzeigen (max 20)
  notiz loeschen #<id>                -- Notiz per ID loeschen
  vergiss <schluessel>                -- KV-Fakt vergessen"""


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    """Konstruiert NoteCommandHandler aus dem HandlerContext.

    Bedingung: ``ctx.note_store`` muss gesetzt sein -- ohne SQLite-Store
    keine Notizen.
    """
    if ctx.note_store is None:
        return None
    return NoteCommandHandler(
        note_store=ctx.note_store,
        default_user_id=ctx.default_user_id,
    )


PLUGIN = CommandPlugin(
    name="note",
    priority=70,
    category="notizen",
    help_section=HELP_SECTION_NOTE,
    factory=_factory,
)
