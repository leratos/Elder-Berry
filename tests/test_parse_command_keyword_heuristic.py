"""Tests: parse_command-Keyword-Heuristik (Phase 82 Hotfix B, 2026-05-10).

Verschaerft Stufe 3 (Keyword-Suche) der ``parse_command``-Pipeline:

1. Length-Cap auf den GESTRIPPTEN Text (nach Filler-Removal):
   Anfragen ueber ``_MAX_KEYWORD_PHRASE_WORDS`` (= 8) Wortern werden
   nicht mehr gegen Keywords gematcht -- sie laufen zum LLM weiter
   (Bridge -> Saleria -> action_sequence usw.).

2. Wort-Boundary statt ``keyword in text``: ``"todoslisten"`` matcht
   nicht mehr das Keyword ``"todos"``.

Hintergrund: Vor diesem Fix wurde ``"erstell 3 Todos fuer Pizza UND
schreib Notiz UND setz Reminder Samstag"`` durch das Keyword
``"todos"`` als Listenanzeige interpretiert -- Saleria sah die
Anfrage nie, action_sequence-Hint blieb wirkungslos.

Test-Hinweis: Die meisten Tests nutzen wol-Keywords (z.B. "tower
aufwecken"), weil der WolCommandHandler unconditional geladen wird
(siehe wol_commands._factory). Der TodoCommandHandler braucht einen
task_client -- der reine Smoketest-Reproducer benutzt deshalb einen
Mock-Client.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from elder_berry.comms.remote_commands import RemoteCommandHandler


# ---------------------------------------------------------------------------
# Length-Cap: ueber 8 Wortern wird Stufe 3 uebersprungen
# ---------------------------------------------------------------------------


class TestKeywordLengthCap:
    def test_smoketest_phrase_returns_none_with_real_todo_keyword(self) -> None:
        """Konkreter Phase-82-Bug-Reproducer mit echtem todo-Handler.

        Vor dem Fix: keyword 'todos' matchte als Substring -> command=
        'todos' -> Listenanzeige. Nach dem Fix: > 8 Worte -> Stufe 3
        skip -> return None -> Bridge geht zum LLM, Saleria entscheidet
        ob action_sequence das richtige Format ist.
        """
        # task_client mock, damit der TodoCommandHandler geladen wird
        # und sein keyword "todos" registriert ist.
        handler = RemoteCommandHandler(task_client=MagicMock())
        text = (
            "erstell 3 Todos für Pizza UND schreib Notiz mit "
            "Rezept-Link UND setz Reminder Samstag"
        )
        assert handler.parse_command(text) is None

    def test_long_phrase_with_wol_keyword_returns_none(self) -> None:
        """Generische Cap-Wirkung: lange Phrase mit Keyword-Substring
        triggert nicht mehr automatisch den Keyword-Match.
        """
        handler = RemoteCommandHandler()
        # Enthaelt "tower aufwecken" -- normalerweise wol-keyword.
        # 11 Wörter (gestrippt) -- sollte ueber Cap fallen.
        text = (
            "wenn der server down ist soll ich dann tower aufwecken "
            "oder neu booten warten"
        )
        assert handler.parse_command(text) is None

    def test_short_keyword_phrase_still_matches(self) -> None:
        """Kurze Anfragen bleiben keyword-matched -- der Hotfix darf
        die bestehende Bequemlichkeit nicht zerstoeren."""
        handler = RemoteCommandHandler()
        # 3 Wörter, klassisches keyword
        assert handler.parse_command("weck tower auf") == "wol"
        # 2 Wörter
        assert handler.parse_command("tower aufwecken") == "wol"

    def test_polite_phrase_passes_after_filler_strip(self) -> None:
        """Hoefliche Variants: Filler werden vor dem Cap-Check abgezogen.

        ``"kannst du mir mal tower aufwecken"`` -> Filler-Strip
        -> ``"tower aufwecken"`` (2 Worte) -> unter Cap -> matcht.
        """
        handler = RemoteCommandHandler()
        result = handler.parse_command("kannst du mir mal tower aufwecken")
        assert result == "wol"

    def test_phrase_just_under_cap_matches(self) -> None:
        """Phrasen knapp unter dem Cap (z.B. 7-8 Wörter) sollen weiter
        keyword-matched werden -- der Cap ist grosszuegig fuer normale
        natuerliche Sprache."""
        handler = RemoteCommandHandler()
        # 7 Wörter, enthaelt wol-keyword "tower aufwecken"
        text = "morgen früh bitte den tower aufwecken danke"
        # Filler "bitte"/"danke" werden gestrippt -> 5 Wörter -> matcht.
        assert handler.parse_command(text) == "wol"

    def test_long_phrase_without_known_keyword_returns_none(self) -> None:
        """Sicherheitsnetz: das Cap aendert nichts fuer Anfragen, die
        eh keinen Keyword-Match haetten."""
        handler = RemoteCommandHandler()
        text = "ich überlege gerade was ich heute mittag essen könnte"
        assert handler.parse_command(text) is None


# ---------------------------------------------------------------------------
# Wort-Boundary: keine Substring-Matches mehr
# ---------------------------------------------------------------------------


class TestKeywordWordBoundary:
    def test_substring_does_not_match_keyword_with_real_todo_keyword(self) -> None:
        """``todoslisten`` ist kein Wort-Match auf ``todos`` -- nur weil
        die Buchstaben drinstehen, ist die Anfrage keine Listen-Anzeige.
        """
        handler = RemoteCommandHandler(task_client=MagicMock())
        # Kunstkonstrukt zur Demo des Wort-Boundary-Schutzes.
        # Single-Wort-Test: muss durch alle parser-Stufen ohne Match.
        assert handler.parse_command("todoslisten") is None

    def test_substring_in_compound_word_does_not_match(self) -> None:
        """``towerstartzeit`` enthaelt ``tower starten``-Substring nur
        in einem Compound, nicht als alleinstehendes Wort.

        Vor dem Fix waere das eine wol-Match-False-Positive gewesen.
        """
        handler = RemoteCommandHandler()
        # Nicht ganz lebensnah, aber reproduziert den Mechanismus.
        # "tower starten" ist ein wol-keyword (2 Wörter); im Substring
        # eines Wortes sollte es nicht greifen.
        assert handler.parse_command("towerstartenrolle") is None

    def test_exact_keyword_with_word_boundary_matches(self) -> None:
        """Standalone Keyword matcht weiter."""
        handler = RemoteCommandHandler()
        # 'tower aufwecken' alleinstehend -> matcht.
        assert handler.parse_command("tower aufwecken") == "wol"

    def test_keyword_at_punctuation_boundary_matches(self) -> None:
        """Keyword neben Satzzeichen ist ein Wort-Match (Komma
        zaehlt als boundary)."""
        handler = RemoteCommandHandler()
        # 4 Wörter, Komma als Wort-Trenner.
        # "tower" ist NICHT alleinstehendes wol-keyword (nur Phrasen
        # wie "tower aufwecken" sind), aber der Test demonstriert das
        # Wort-Boundary-Verhalten an einer Phrase mit Komma.
        result = handler.parse_command("morgen, tower aufwecken bitte")
        assert result == "wol"
