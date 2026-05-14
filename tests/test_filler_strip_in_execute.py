"""Tests: Filler-Strip im execute()-Pfad (X4a, 2026-05-12).

Konzept: docs/concepts/filler-strip-in-execute.md (Option X4a).

Hintergrund (Codex-Reviewer P2 am 2026-05-11):
``parse_command`` strippt fuehrende Filler vor dem Pattern-Match, aber
``Bridge.handle_remote_command`` reicht den ORIGINALEN ``msg.body`` an
``execute()`` durch. Die ``_cmd_*``-Methoden re-parsen den Text mit
demselben Pattern -- ohne Filler-Strip im execute-Pfad faellt der
Re-Parse durch, obwohl das Routing erkannt hatte was gemeint war.

Loesung (X4a): zentraler Prefix-Strip in
``RemoteCommandHandler.execute()`` via ``_strip_filler_prefix`` (NICHT
``_strip_fillers``, der auch Suffix-Filler entfernt und User-Content
verstuemmeln wuerde).

Die Tests pruefen:

1. ``_strip_filler_prefix`` direkt -- Prefix-Strip wirkt, Suffix bleibt.
2. ``execute()`` reicht den prefix-gestrippten Text an Sub-Handler.
3. Asymmetrie zwischen ``_strip_fillers`` und ``_strip_filler_prefix``
   ist gewollt und dokumentiert (Suffix-Schutz fuer User-Content).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from elder_berry.comms.remote_commands import (
    RemoteCommandHandler,
    _strip_filler_prefix,
    _strip_fillers,
)


# ---------------------------------------------------------------------------
# Helper-Unit-Tests: _strip_filler_prefix
# ---------------------------------------------------------------------------


class TestStripFillerPrefix:
    """``_strip_filler_prefix`` strippt nur am Anfang, nicht am Ende."""

    def test_strips_simple_prefix(self) -> None:
        assert _strip_filler_prefix("bitte notiz löschen #1") == "notiz löschen #1"

    def test_strips_multi_word_prefix(self) -> None:
        assert _strip_filler_prefix("kannst du mir mal notiz löschen #1") == (
            "notiz löschen #1"
        )

    def test_strips_zeig_mir_prefix(self) -> None:
        assert _strip_filler_prefix("zeig mir mal status") == "status"

    def test_strips_iteratively(self) -> None:
        """'bitte zeig mir mal status' -> 'bitte' + 'zeig mir mal' -> 'status'.

        Der iterative Loop greift mehrfach: erst 'bitte', dann 'zeig mir mal'.
        """
        assert _strip_filler_prefix("bitte zeig mir mal status") == "status"

    def test_preserves_suffix_filler_in_user_content(self) -> None:
        """KERN-VERHALTEN: Suffix-Filler bleiben erhalten -- sonst
        wuerde User-Content verstuemmelt.

        Vor X4a hatte das ein Codex-Reviewer P2 angemerkt: naive Nutzung
        von _strip_fillers (Prefix + Suffix) wuerde 'clip: hallo bitte'
        zu 'clip: hallo' machen, also den eigentlichen Clipboard-Inhalt
        kuerzen.
        """
        assert _strip_filler_prefix("clip: hallo bitte") == "clip: hallo bitte"
        assert _strip_filler_prefix("notiz: meld dich mal") == "notiz: meld dich mal"
        assert _strip_filler_prefix("cloud suche bitte") == "cloud suche bitte"

    def test_strips_prefix_keeps_suffix(self) -> None:
        """Prefix + User-Content + Suffix-Token: Prefix weg, Suffix bleibt."""
        assert _strip_filler_prefix("bitte clip: hallo bitte") == "clip: hallo bitte"
        assert (
            _strip_filler_prefix("kannst du mir notiz: meld dich mal")
            == "notiz: meld dich mal"
        )

    def test_empty_or_whitespace_returns_original(self) -> None:
        """Fallback wie _strip_fillers: leer nach Strip -> Original-Text."""
        assert _strip_filler_prefix("") == ""
        assert _strip_filler_prefix("   ") == ""

    def test_only_filler_returns_original_stripped(self) -> None:
        """'bitte' allein -> nichts mehr da, Fallback liefert Originaltext."""
        # _strip_filler_prefix: 'bitte' wird gestrippt -> "", Fallback
        # returnt text.strip() = "bitte" (Original).
        assert _strip_filler_prefix("bitte") == "bitte"

    def test_idempotent(self) -> None:
        """Doppel-Strip ist no-op (wichtig: parse_command hat schon
        gestrippt, execute() strippt erneut)."""
        once = _strip_filler_prefix("bitte notiz löschen #1")
        twice = _strip_filler_prefix(once)
        assert once == twice == "notiz löschen #1"

    def test_no_filler_returns_unchanged(self) -> None:
        """Texte ohne Filler bleiben unangetastet."""
        assert _strip_filler_prefix("notiz löschen #1") == "notiz löschen #1"
        assert _strip_filler_prefix("clip: irgendwas") == "clip: irgendwas"


# ---------------------------------------------------------------------------
# Asymmetrie-Dokumentation: _strip_fillers vs. _strip_filler_prefix
# ---------------------------------------------------------------------------


class TestAsymmetryWithStripFillers:
    """Die beiden Helper haben unterschiedliches Verhalten am Suffix --
    das ist gewollt und der Grund warum X4a den Prefix-only-Helper nutzt.
    """

    def test_strip_fillers_kills_suffix_strip_filler_prefix_does_not(self) -> None:
        text = "clip: hallo bitte"
        # _strip_fillers (Prefix + Suffix) -> Suffix wird abgeschnitten.
        assert _strip_fillers(text) == "clip: hallo"
        # _strip_filler_prefix (nur Prefix) -> Suffix bleibt.
        assert _strip_filler_prefix(text) == "clip: hallo bitte"

    def test_both_strip_same_prefix(self) -> None:
        """Beide entfernen Prefix-Filler identisch."""
        text = "kannst du mir mal status"
        assert _strip_fillers(text) == _strip_filler_prefix(text) == "status"


# ---------------------------------------------------------------------------
# Bridge-Integration: execute() reicht prefix-gestrippten Text durch
# ---------------------------------------------------------------------------


class TestExecuteStripsFillerPrefix:
    """``RemoteCommandHandler.execute()`` ruft den Prefix-Strip vor der
    Delegation an Sub-Handler. Sub-Handler bekommen also einen
    prefix-bereinigten Text und koennen ihren Re-Parse-Schritt
    erfolgreich machen.
    """

    def test_execute_strips_bitte_prefix_before_handler(self) -> None:
        """'bitte vergiss WLAN' -> _cmd_delete_fact bekommt 'vergiss WLAN'.

        Phase 91-A: ``note_delete`` ist ein Stub; wir testen den Filler-
        Strip stattdessen ueber ``note_delete_fact`` (FactStore-Pfad,
        Re-Parse-Verhalten identisch)."""
        store = MagicMock()
        store.delete_fact.return_value = True
        h = RemoteCommandHandler(fact_store=store)

        result = h.execute("note_delete_fact", "bitte vergiss WLAN")

        assert result.success is True
        store.delete_fact.assert_called_once()
        # 2. Argument an delete_fact ist der normalisierte Key.
        assert store.delete_fact.call_args[0][1] == "WLAN"

    def test_execute_strips_multi_word_filler_before_handler(self) -> None:
        """'kannst du mir mal vergiss WLAN' funktioniert genauso."""
        store = MagicMock()
        store.delete_fact.return_value = True
        h = RemoteCommandHandler(fact_store=store)

        result = h.execute("note_delete_fact", "kannst du mir mal vergiss WLAN")

        assert result.success is True
        store.delete_fact.assert_called_once()
        assert store.delete_fact.call_args[0][1] == "WLAN"

    def test_execute_preserves_suffix_in_user_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """clip-Schreib-Befehl mit Suffix-Filler im Content: der
        Suffix-Token landet im Clipboard, weil execute() KEINEN
        Suffix-Strip macht.

        Vor X4a war das der Hauptpunkt der Codex-P2-Anmerkung gegen
        das urspruengliche X4-Konzept.

        Hinweis: pyperclip ist in den optionalen "windows"-extras --
        nicht jede Test-Umgebung hat es (z.B. CI ohne windows-extras,
        RPi5). importorskip macht den Test umgebungs-tolerant. Der
        Suffix-Schutz wird unabhaengig auch von
        TestStripFillerPrefix.test_preserves_suffix_filler_in_user_content
        und TestAsymmetryWithStripFillers verifiziert.
        """
        pyperclip = pytest.importorskip("pyperclip")

        captured: list[str] = []
        monkeypatch.setattr(pyperclip, "copy", lambda s: captured.append(s))

        h = RemoteCommandHandler()

        # User-Intention: Clipboard soll 'hallo bitte' enthalten.
        # parse_command hat 'clip_write' erkannt. execute() reicht
        # 'clip: hallo bitte' an _cmd_clipboard_write durch -- der
        # Re-Parse extrahiert 'hallo bitte'.
        result = h.execute("clip_write", "clip: hallo bitte")

        assert result.success is True
        assert captured == ["hallo bitte"], (
            f"Suffix-Token verloren: erwartet ['hallo bitte'], gekriegt {captured!r}"
        )

    def test_execute_without_filler_unchanged(self) -> None:
        """Texte ohne Filler-Prefix gehen unangetastet durch."""
        store = MagicMock()
        store.delete_fact.return_value = True
        h = RemoteCommandHandler(fact_store=store)

        result = h.execute("note_delete_fact", "vergiss WLAN")

        assert result.success is True
        store.delete_fact.assert_called_once()

    def test_execute_help_paths_not_affected(self) -> None:
        """Hilfe-Commands werden vor dem Handler-Lookup behandelt und
        sind nicht text-abhaengig. Sollten weiterhin funktionieren."""
        h = RemoteCommandHandler()

        result = h.execute("hilfe", "bitte hilfe")

        assert result.command == "hilfe"
        assert result.success is True

    def test_execute_unknown_command_unchanged(self) -> None:
        """Unbekannte Commands liefern weiterhin den Fallback-Fehler."""
        h = RemoteCommandHandler()
        result = h.execute("nonexistent_command", "bitte text")
        assert result.success is False
        assert "Unbekannter Command" in (result.text or "")


# ---------------------------------------------------------------------------
# Bridge-Roundtrip: parse_command + execute zusammen
# ---------------------------------------------------------------------------


class TestParseAndExecuteRoundtrip:
    """End-to-End-Test fuer den Bridge-Pfad: parse_command erkennt
    auch bei Filler-Prefix das richtige Command, execute() strippt
    den Filler, _cmd_*-Re-Parse gelingt.
    """

    def test_kannst_du_mir_mal_notiz_loeschen(self) -> None:
        """Phase 91-A: ``notiz loeschen #3`` routet weiter zu note_delete
        (Pattern unveraendert), execute() liefert aber den Stub."""
        store = MagicMock()
        h = RemoteCommandHandler(fact_store=store)

        text = "kannst du mir mal notiz löschen #3"

        # 1. parse_command erkennt note_delete (nutzt _strip_fillers intern).
        command = h.parse_command(text)
        assert command == "note_delete"

        # 2. execute(command, raw_text) -- liefert in Phase 91-A einen
        # Stub-Response (success=False, "Umstellung"-Text). Wichtig:
        # FactStore wurde NICHT modifiziert.
        result = h.execute(command, text)

        assert result.success is False
        assert "Umstellung" in (result.text or "")
        store.delete_fact.assert_not_called()
