"""NoteCommandHandler -- Wissensdatenbank (Fakten) + Notizen (Nextcloud).

Phase 91-C: Notiz-Commands laufen jetzt gegen die Nextcloud Notes API.
- Fakten-Commands (`merk dir`, `was ist`, `vergiss`) gehen an FactStore
  (lokal, SQLite).
- Notiz-Commands (`notiz:`, `notiz <Kategorie>:`, `notizen`, `notizen
  liste`, `notizen suche`, `notizen kategorien`, `notiz loeschen`) gehen
  an den NextcloudNotesClient (reiner API-Wrapper, kein lokaler Cache).

Categories sind die strukturelle Hauptschublade einer Notiz. Die
Whitelist (siehe ``note_categories.py``) ist eine Soft-Convention: eine
unbekannte Category wird trotzdem akzeptiert, der Handler loggt nur eine
Warning und haengt einen Hinweis an die Matrix-Antwort.

Konzept: docs/concepts/note-nextcloud-replace.md Paragraph 3.4 / 3.5.
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
    user_friendly_error,
)
from elder_berry.tools.note_categories import (
    DEFAULT_CATEGORY,
    KNOWN_CATEGORIES,
    canonical_category,
)
from elder_berry.tools.nextcloud_notes_client import NextcloudNotesError

if TYPE_CHECKING:
    from elder_berry.tools.fact_store import FactStore
    from elder_berry.tools.nextcloud_notes_client import (
        NextcloudNote,
        NextcloudNotesClient,
    )

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# "merk dir: WLAN Buero ist xyz123" oder "merk dir WLAN Buero = xyz"
NOTE_SET_FACT_PATTERN = re.compile(
    r"^(?:bitte\s+)?(?:merk|merke)\s+dir[:\s]+(.+?)\s+(?:ist|=|:)\s+(.+)$",
    re.IGNORECASE,
)

# "notiz: Vermieter heisst Mueller" / "notiz Einkauf: Milch kaufen"
# Optionale Category-Group vor dem Doppelpunkt (Konzept Paragraph 3.5).
# Single-Word-Category -- der ":" ist Pflicht-Trenner, sonst waere
# "notiz Vermieter ..." nicht eindeutig (Category vs. Content).
# DOTALL bleibt erhalten (Phase 90-A, Multi-Line-Notizen).
NOTE_ADD_PATTERN = re.compile(
    r"^(?:bitte\s+)?notiz(?:\s+(?P<category>[\wÄÖÜäöüß\-]+))?\s*:\s*(?P<content>.+)$",
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

# "notizen liste" / "notizen liste Einkauf"
NOTE_LIST_PATTERN = re.compile(
    r"^(?:bitte\s+)?notize?n?\s+liste(?:\s+(?P<category>[\wÄÖÜäöüß\-]+))?\s*$",
    re.IGNORECASE,
)

# "notizen kategorien"
NOTE_CATEGORIES_PATTERN = re.compile(
    r"^(?:bitte\s+)?notize?n?\s+kategorien?\s*$",
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


# ---------------------------------------------------------------------------
# Formatierungs-Helfer
# ---------------------------------------------------------------------------


def _known_categories_text() -> str:
    """Whitelist als sortierte, kommagetrennte Liste fuer Hinweistexte."""
    return ", ".join(sorted(KNOWN_CATEGORIES))


def _count_label(count: int) -> str:
    """'1 Notiz' / 'N Notizen' -- korrekte Pluralform."""
    return f"{count} Notiz" if count == 1 else f"{count} Notizen"


def _format_note_short(note: NextcloudNote) -> str:
    """Kurzform '#<id> [<Kategorie>] <Vorschau>' fuer Listen-Ausgaben.

    Die Vorschau ist die erste nicht-leere Content-Zeile -- bewusst NICHT
    ``note.title``: Nextcloud legt per API erstellte Notizen mit dem
    Platzhalter-Titel "Neue Notiz" an und leitet den Titel nicht aus dem
    Content ab. Die erste Content-Zeile ist die eigentliche Ueberschrift
    (Notes-/Markdown-Konvention). ``note.title`` ist nur Fallback, falls
    der Content komplett leer ist.
    """
    snippet = ""
    for line in note.content.splitlines():
        stripped = line.strip()
        if stripped:
            snippet = stripped
            break
    if not snippet:
        snippet = note.title.strip()
    if len(snippet) > 80:
        snippet = snippet[:77] + "..."
    category = f"[{note.category}] " if note.category else ""
    return f"#{note.id} {category}{snippet}".rstrip()


class NoteCommandHandler(CommandHandler):
    """Handler fuer Wissensdatenbank-Commands (Fakten) + Notizen (Nextcloud)."""

    def __init__(
        self,
        fact_store: FactStore,
        nextcloud_notes: NextcloudNotesClient | None = None,
        default_user_id: str = "",
    ) -> None:
        """
        Args:
            fact_store: FactStore-Instanz fuer die Key-Value-Fakten.
            nextcloud_notes: NextcloudNotesClient fuer die Notizen. ``None``
                -> Notiz-Commands antworten mit ``not_configured``; die
                Fakten-Commands funktionieren trotzdem.
            default_user_id: Fallback-User-ID (Single-User-Projekt).
        """
        self._store = fact_store
        self._notes = nextcloud_notes
        self._default_user_id = default_user_id

    # ------------------------------------------------------------------
    # CommandHandler interface
    # ------------------------------------------------------------------

    @property
    def simple_commands(self) -> set[str]:
        return {"notizen"}

    @property
    def patterns(self) -> list[tuple[re.Pattern[str], str, bool, bool]]:
        # Reihenfolge: spezifische Patterns VOR generischen. note_add ist
        # generisch (``notiz <Kategorie>: <text>``) -- muss nach den
        # spezifischen note_*-Patterns stehen. note_add verlangt zwar
        # einen ":" und frisst dadurch ``notiz loeschen #1`` (kein ":")
        # nicht mehr auf, aber die Reihenfolge bleibt zur Klarheit.
        return [
            (NOTE_SET_FACT_PATTERN, "note_set_fact", False, False),
            (NOTE_CATEGORIES_PATTERN, "note_categories", False, False),
            (NOTE_LIST_PATTERN, "note_list", False, False),
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
            "notiz: <text> / notiz <Kategorie>: <text>: Notiz speichern",
            "notizen / notizen liste <Kategorie>: Notizen anzeigen",
            "notizen suche <begriff>: Notizen durchsuchen",
            "notizen kategorien: Kategorien-Übersicht",
            "notiz löschen #<id>: Notiz löschen",
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
            "note_list": ["notizen liste", "liste notizen"],
            "note_categories": [
                "notizen kategorien",
                "notiz kategorien",
                "welche kategorien",
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
            case "note_add":
                return self._cmd_add(raw_text)
            case "note_search":
                return self._cmd_search(raw_text)
            case "note_delete":
                return self._cmd_delete(raw_text)
            case "note_list" | "notizen":
                return self._cmd_list(command, raw_text)
            case "note_categories":
                return self._cmd_categories()

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
    # Notiz-Commands (NextcloudNotesClient)
    # ------------------------------------------------------------------

    def _unavailable(self, command: str) -> CommandResult:
        """Antwort wenn kein NextcloudNotesClient verdrahtet ist."""
        return self.not_configured(command, "Nextcloud Notes", setup_step=4)

    @staticmethod
    def _api_error(command: str, exc: NextcloudNotesError) -> CommandResult:
        """Wandelt einen NextcloudNotesError in eine User-Antwort um."""
        logger.error("Nextcloud Notes Fehler bei %s: %s", command, exc)
        return CommandResult(
            command=command,
            success=False,
            text=user_friendly_error(exc, "Notizen"),
        )

    def _cmd_add(self, raw_text: str) -> CommandResult:
        """notiz: <text> / notiz <Kategorie>: <text>"""
        if self._notes is None:
            return self._unavailable("note_add")

        match = NOTE_ADD_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="note_add",
                success=False,
                text=(
                    "Text fehlt. Beispiel: notiz: Vermieter heißt Müller "
                    "oder notiz Einkauf: Milch kaufen"
                ),
            )

        content = match.group("content").strip()
        raw_category = match.group("category")
        if raw_category:
            category, is_known = canonical_category(raw_category)
        else:
            category, is_known = DEFAULT_CATEGORY, True

        try:
            note = self._notes.create_note(content, category=category)
        except NextcloudNotesError as exc:
            return self._api_error("note_add", exc)

        text = f"📝 Notiz #{note.id} in '{category}' gespeichert."
        if not is_known:
            logger.warning("Unbekannte Category '%s' verwendet", category)
            text += (
                f"\n⚠ Neue Kategorie '{category}' angelegt. "
                f"Bekannte Kategorien: {_known_categories_text()}."
            )
        return CommandResult(command="note_add", success=True, text=text)

    def _cmd_search(self, raw_text: str) -> CommandResult:
        """notizen suche <query> -- Substring-Suche ueber den Content."""
        if self._notes is None:
            return self._unavailable("note_search")

        match = NOTE_SEARCH_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="note_search",
                success=False,
                text="Suchbegriff fehlt. Beispiel: notizen suche Vermieter",
            )

        query = match.group(1).strip()
        try:
            results = self._notes.search(query, limit=20)
        except NextcloudNotesError as exc:
            return self._api_error("note_search", exc)

        if not results:
            return CommandResult(
                command="note_search",
                success=True,
                text=f"Keine Notizen gefunden für: '{query}'",
            )

        lines = [f"🔍 **{len(results)} Treffer** für '{query}':"]
        for note in results:
            lines.append(f"  {_format_note_short(note)}")

        # Phase 80: voller Content wandert ins Item, damit der Bridge-
        # list_pick ("zeig mir Notiz 1") die Notiz ohne Round-Trip zeigen
        # kann -- Notizen sind klein.
        list_items = [{"id": n.id, "content": n.content} for n in results]

        return CommandResult(
            command="note_search",
            success=True,
            text="\n".join(lines),
            list_items=list_items,
            list_type="note_search",
        )

    def _cmd_list(self, command: str, raw_text: str) -> CommandResult:
        """notizen / notizen liste [<Kategorie>] -- Notizen auflisten."""
        if self._notes is None:
            return self._unavailable(command)

        match = NOTE_LIST_PATTERN.match(raw_text.strip())
        raw_category = match.group("category") if match else None

        category: str | None = None
        hint = ""
        if raw_category:
            category, is_known = canonical_category(raw_category)
            if not is_known:
                hint = (
                    f"\n⚠ Kategorie '{category}' ist nicht in der Whitelist "
                    f"({_known_categories_text()})."
                )

        try:
            notes = self._notes.list_notes(category=category, limit=20)
        except NextcloudNotesError as exc:
            return self._api_error(command, exc)

        scope = f" in '{category}'" if category else ""
        if not notes:
            return CommandResult(
                command=command,
                success=True,
                text=f"Keine Notizen{scope} vorhanden. "
                f"Tipp: 'notiz: ...' legt eine an." + hint,
            )

        lines = [f"📋 **{len(notes)} Notizen{scope}**:"]
        for note in notes:
            lines.append(f"  {_format_note_short(note)}")

        return CommandResult(
            command=command,
            success=True,
            text="\n".join(lines) + hint,
        )

    def _cmd_delete(self, raw_text: str) -> CommandResult:
        """notiz löschen #<id>"""
        if self._notes is None:
            return self._unavailable("note_delete")

        match = NOTE_DELETE_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="note_delete",
                success=False,
                text="Welche Notiz? Beispiel: notiz löschen #3",
            )

        note_id = int(match.group(1))
        try:
            self._notes.delete_note(note_id)
        except NextcloudNotesError as exc:
            if exc.status_code == 404:
                return CommandResult(
                    command="note_delete",
                    success=False,
                    text=f"Notiz #{note_id} nicht gefunden.",
                )
            return self._api_error("note_delete", exc)

        return CommandResult(
            command="note_delete",
            success=True,
            text=f"🗑️ Notiz #{note_id} gelöscht.",
        )

    def _cmd_categories(self) -> CommandResult:
        """notizen kategorien -- Whitelist + freie Categories mit Counts."""
        if self._notes is None:
            return self._unavailable("note_categories")

        try:
            notes = self._notes.list_notes()
        except NextcloudNotesError as exc:
            return self._api_error("note_categories", exc)

        # Count pro Category (case-sensitiv -- Nextcloud-Categories sind es).
        counts: dict[str, int] = {}
        for note in notes:
            if note.category:
                counts[note.category] = counts.get(note.category, 0) + 1

        lines = ["📂 Kategorien:"]
        # Whitelist zuerst -- auch ungenutzte (count 0) anzeigen.
        for category in sorted(KNOWN_CATEGORIES):
            count = counts.pop(category, 0)
            lines.append(f"  • {category} ({_count_label(count)})")
        # Verbleibende = genutzte Categories ausserhalb der Whitelist.
        for category in sorted(counts):
            lines.append(f"  • {category} ({_count_label(counts[category])}) — frei")

        return CommandResult(
            command="note_categories",
            success=True,
            text="\n".join(lines),
        )


# ---------------------------------------------------------------------------
# Phase 77: Plugin-Manifest
# ---------------------------------------------------------------------------

HELP_SECTION_NOTE = """Wissen & Fakten:
  merk dir: <schluessel> ist <wert>  -- Fakt speichern
  was ist <schluessel>?               -- Fakt abrufen
  vergiss <schluessel>                -- Fakt loeschen

Notizen (Nextcloud Notes):
  notiz: <text>                       -- Notiz speichern (Kategorie Allgemein)
  notiz <Kategorie>: <text>           -- Notiz mit Kategorie (z.B. notiz Einkauf: Milch)
  notizen                             -- Alle Notizen anzeigen (max 20)
  notizen liste <Kategorie>           -- Notizen einer Kategorie
  notizen suche <Begriff>             -- Notizen durchsuchen
  notizen kategorien                  -- Kategorien-Uebersicht
  notiz loeschen #<id>                -- Notiz per ID loeschen
  Tipp: Hashtags (#dringend) direkt in den Text -- per Suche auffindbar."""


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    """Konstruiert NoteCommandHandler aus dem HandlerContext.

    Bedingung: ``ctx.fact_store`` muss gesetzt sein -- ohne FactStore
    keine Fakten. ``ctx.nextcloud_notes`` ist optional; fehlt es,
    antworten die Notiz-Commands mit ``not_configured``.
    """
    if ctx.fact_store is None:
        return None
    return NoteCommandHandler(
        fact_store=ctx.fact_store,
        nextcloud_notes=ctx.nextcloud_notes,
        default_user_id=ctx.default_user_id,
    )


PLUGIN = CommandPlugin(
    name="note",
    priority=70,
    category="notizen",
    help_section=HELP_SECTION_NOTE,
    factory=_factory,
)
