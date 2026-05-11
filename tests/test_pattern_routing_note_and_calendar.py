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
