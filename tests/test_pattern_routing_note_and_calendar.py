"""Tests: Pattern-Routing-Bugs in Note- und Calendar-Handlern (2026-05-11).

Zwei Bugs, die im Phase-82-Smoketest aufgefallen sind:

1. "Notiz löschen #1" wurde als neue Notiz angelegt -- NOTE_ADD_PATTERN
   matchte "notiz <text>" mit text="löschen #1", und stand in der
   patterns-Liste VOR NOTE_DELETE_PATTERN. Fix: Reihenfolge umgedreht,
   spezifische Patterns vor generischen.

2. "Lösch alle" wurde als "alle Termine löschen" interpretiert --
   TERMIN_DELETE_PATTERN hatte beide ``termin``-Marker in derselben
   Alternative optional. Fix: zweite Alternative aufgesplittet in
   zwei Sub-Alternativen, jeweils mit Pflicht-``termin`` an einer
   der zwei Positionen.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from elder_berry.comms.remote_commands import RemoteCommandHandler


# ---------------------------------------------------------------------------
# Bug 1: NoteCommandHandler -- Pattern-Reihenfolge
# ---------------------------------------------------------------------------


def _handler_with_notes() -> RemoteCommandHandler:
    """NoteCommandHandler braucht einen NoteStore -- Mock reicht fuer
    parse_command-Routing (kein execute hier)."""
    return RemoteCommandHandler(note_store=MagicMock())


class TestNotePatternRouting:
    """Spezifische Note-Patterns muessen vor NOTE_ADD_PATTERN matchen."""

    def test_notiz_loeschen_routes_to_delete(self) -> None:
        """Bug-Reproducer: 'notiz löschen #1' soll als note_delete erkannt
        werden, NICHT als note_add mit text='löschen #1'."""
        h = _handler_with_notes()
        assert h.parse_command("notiz löschen #1") == "note_delete"
        # Mit "lösche" statt "löschen"
        assert h.parse_command("notiz lösche #2") == "note_delete"
        # Mit "entferne"
        assert h.parse_command("notiz entferne 3") == "note_delete"

    def test_notiz_loeschen_case_insensitive(self) -> None:
        """'Notiz löschen #1' (Großbuchstabe) muss auch matchen."""
        h = _handler_with_notes()
        assert h.parse_command("Notiz löschen #1") == "note_delete"
        assert h.parse_command("NOTIZ LÖSCHEN #5") == "note_delete"

    def test_notizen_suche_routes_to_search(self) -> None:
        """'notizen suche X' muss note_search treffen, nicht note_add."""
        h = _handler_with_notes()
        assert h.parse_command("notizen suche Vermieter") == "note_search"
        # Singular auch
        assert h.parse_command("notiz suche Pizza") == "note_search"

    def test_notiz_add_still_works_for_legit_freetext(self) -> None:
        """Regression-Schutz: legitime ``notiz: <text>`` und
        ``notiz <text>`` muessen weiter note_add treffen."""
        h = _handler_with_notes()
        assert h.parse_command("notiz: Vermieter heißt Müller") == "note_add"
        assert h.parse_command("notiz Vermieter heißt Müller") == "note_add"
        # Mit "bitte"-Prefix
        assert h.parse_command("bitte notiz: Termin morgen") == "note_add"

    def test_bitte_prefix_routes_and_executes_correctly(self) -> None:
        """Codex-Reviewer P2 (2026-05-11): parse_command strippt 'bitte'
        VOR dem Pattern-Match, aber execute() bekommt den rohen Text mit
        'bitte ...' drin. Ohne (?:bitte\\s+)?-Prefix in DELETE/SEARCH/
        DELETE_FACT-Patterns wuerde der Re-Parse in _cmd_* fehlschlagen
        und 'Welche Notiz?'/'Suchbegriff fehlt' zurueckliefern -- obwohl
        das Routing korrekt erkannt hatte.

        Test prueft beide Stufen:
        1. parse_command erkennt das richtige Command.
        2. Der Pattern-Re-Parse im _cmd_* (mit rohem Text) gelingt.
        """
        h = _handler_with_notes()
        # Stufe 1: Routing
        assert h.parse_command("bitte notiz löschen #1") == "note_delete"
        assert h.parse_command("bitte notizen suche Pizza") == "note_search"
        assert h.parse_command("bitte vergiss WLAN") == "note_delete_fact"

        # Stufe 2: Pattern-Re-Parse gelingt (matchet auf rohem Text)
        from elder_berry.comms.commands.note_commands import (
            NOTE_DELETE_FACT_PATTERN,
            NOTE_DELETE_PATTERN,
            NOTE_SEARCH_PATTERN,
        )

        assert NOTE_DELETE_PATTERN.match("bitte notiz löschen #1") is not None
        assert NOTE_SEARCH_PATTERN.match("bitte notizen suche Pizza") is not None
        assert NOTE_DELETE_FACT_PATTERN.match("bitte vergiss WLAN") is not None

    def test_notiz_add_with_loeschen_in_text_does_not_match_delete(self) -> None:
        """Edge: ``notiz: löschen meines Accounts ueberlegen`` -- der
        text enthaelt 'löschen' aber es ist kein Delete-Befehl (Doppelpunkt
        nach 'notiz', dann freier Text). Soll note_add treffen.
        """
        h = _handler_with_notes()
        # Mit Doppelpunkt ist die Intention eindeutig Freitext.
        assert (
            h.parse_command("notiz: löschen meines Accounts ueberlegen") == "note_add"
        )

    def test_multiline_notiz_routes_to_note_add(self) -> None:
        """Phase 90-A: ``notiz: <multi-line content>`` (Saleria-Smoketest
        2026-05-13, Moscow-Mule-Einkaufsliste) muss auf note_add routen.
        Vor 90-A: NOTE_ADD_PATTERN ohne re.DOTALL matchte NICHT --
        parse_command lieferte None und Saleria halluzinierte 'Gespeichert!'.
        """
        h = _handler_with_notes()
        assert (
            h.parse_command("notiz: Einkaufsliste\n- Vodka\n- Limette\n- Ginger Beer")
            == "note_add"
        )
        # Mit bitte-Prefix bleibt's auch korrekt.
        assert h.parse_command("bitte notiz: Liste\nA\nB") == "note_add"

    def test_multiline_notiz_does_not_eat_note_delete(self) -> None:
        """Phase 90-A Restrisiko 2: DOTALL macht NOTE_ADD_PATTERN
        greedy-ueber-Zeilengrenzen. ``notiz löschen #1`` muss weiter zu
        note_delete routen, NICHT zu note_add (NOTE_DELETE_PATTERN steht
        in der patterns-Liste VOR NOTE_ADD_PATTERN -- diese Reihenfolge
        schuetzt vor dem Catch-All-Charakter von NOTE_ADD).
        """
        h = _handler_with_notes()
        # Einzeilig (bestehender Fall, hier nur als Reminder):
        assert h.parse_command("notiz löschen #1") == "note_delete"
        # Notizen-Suche bleibt note_search, nicht note_add:
        assert h.parse_command("notizen suche Vermieter") == "note_search"


# ---------------------------------------------------------------------------
# Bug 2: CalendarCommandHandler -- TERMIN_DELETE_PATTERN
# ---------------------------------------------------------------------------


def _handler_with_calendar() -> RemoteCommandHandler:
    """CalendarHandler braucht einen GoogleCalendarClient -- Mock reicht."""
    return RemoteCommandHandler(calendar=MagicMock())


class TestTerminDeletePatternRouting:
    """TERMIN_DELETE_PATTERN darf nur matchen wenn 'termin' explizit
    im Text steht. 'lösch alle' alleine darf NICHT zum Termin-Delete
    routen -- der LLM soll entscheiden, was geloescht werden soll.
    """

    def test_loesch_alle_does_not_match_termin_delete(self) -> None:
        """Bug-Reproducer: 'lösch alle' soll NICHT auf termin_delete
        routen -- ohne 'termin'-Marker ist unklar was gemeint ist.
        """
        h = _handler_with_calendar()
        assert h.parse_command("lösch alle") is None
        # Auch die anderen Verb-Varianten
        assert h.parse_command("lösche alle") is None
        assert h.parse_command("entferne alle") is None
        assert h.parse_command("storniere alle") is None

    def test_loesch_alle_termine_still_matches(self) -> None:
        """Regression-Schutz: 'lösche alle termine' muss weiter
        termin_delete treffen (Alt B mit termin-Marker)."""
        h = _handler_with_calendar()
        assert h.parse_command("lösche alle termine") == "termin_delete"
        assert h.parse_command("lösch alle termine") == "termin_delete"
        assert h.parse_command("entferne alle termine") == "termin_delete"

    def test_loesche_den_2_termin_matches(self) -> None:
        """'lösche den 2. termin' bleibt termin_delete (Alt C)."""
        h = _handler_with_calendar()
        assert h.parse_command("lösche den 2. termin") == "termin_delete"
        assert h.parse_command("lösche den 5. termin") == "termin_delete"

    def test_loesche_termin_with_title_matches(self) -> None:
        """'lösche termin Zahnarzt' bleibt termin_delete (Alt B mit text)."""
        h = _handler_with_calendar()
        assert h.parse_command("lösche termin Zahnarzt") == "termin_delete"

    def test_loesche_title_termin_matches(self) -> None:
        """'lösche zahnarzt termin' bleibt termin_delete (Alt C)."""
        h = _handler_with_calendar()
        assert h.parse_command("lösche zahnarzt termin") == "termin_delete"

    def test_termin_loeschen_id_matches(self) -> None:
        """'termin löschen abc123' bleibt termin_delete (Alt A)."""
        h = _handler_with_calendar()
        assert h.parse_command("termin löschen abc123") == "termin_delete"
        assert h.parse_command("termine lösche xyz") == "termin_delete"
