"""Phase 95 E0: Routing-Corpus-Test.

Simuliert das Kandidaten-Routing für eine kuratierte Menge von Eingaben
und prüft, ob der gewählte Command dem Erwarteten entspricht.

Markierungen:
  "smoke"          – sollte immer korrekt routen (Regression-Guard)
  "negative"       – darf NICHT gerouted werden (→ None)
    "known_conflict" – bekannte Mehrdeutigkeit; aktuell durch Priority/Gates gelöst

=== SIMULATION-BEFUNDE (Phase 95) ===

F1  MultiStopRouteCommandHandler: Factory benötigt `multi_stop_route_planner`
    und `route_session_store` im HandlerContext – ohne diese Dienste liefert
    `_factory()` None und der Handler wird nicht geladen. Im Test-Kontext
    müssen diese als MagicMock gesetzt werden; in Produktion werden sie über
    den echten HandlerContext bereitgestellt.
    → Korrektur: `_full_mock_ctx()` um beide Felder ergänzt (Session 50f3b1e3).

F2  HOW_TO_PATTERN (^wie\\s+mache\\s+ich\\s+(.+)$) ist zu breit: auch
    "wie mache ich das" (generisches Nachfragen ohne Rezept-Intent) matcht
    → recipe_lookup.  Konzept §P2 unterschätzt das Ausmaß des False-Positive.
    → Korrektur: Stopp-Wortliste oder Mindest-Substanz-Check ("das", "es"
      als Platzhalter blockieren).

F3  keyword_map ist command-indexiert ({command: [keywords]}), nicht
    keyword-indexiert.  Der ursprüngliche Testausdruck `kw not in km`
    (wo km command-indexed ist) lieferte immer True für Keyword-Strings.
    → Korrektur: Reverse-Lookup aufbauen: {kw for kws in km.values() for kw in kws}.

F4  Keyword-Konflikte zwischen System- und Harmony-Handler für "lauter",
    "leiser", "musik an" sowie zwischen Note- und Contact-Handler für
    "wer ist" existieren, waren aber nicht in EXPECTED_KEYWORD_CONFLICTS
    deklariert.

F5  [behoben] collect_candidates dedupliziert Commands vor der Keyword-Stufe,
    sodass ein bereits per Pattern gefundener Command nicht noch einmal als
    Keyword-Kandidat auftaucht. Das reduziert Rauschen in Logs und Tests.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from elder_berry.comms.commands.base import CommandMatchCandidate, HandlerContext
from elder_berry.comms.remote_commands import RemoteCommandHandler


# ---------------------------------------------------------------------------
# Corpus-Definition
# ---------------------------------------------------------------------------
# Format: (text, expected_command_or_None, label, comment)
# label: "smoke" | "negative" | "known_conflict"

CORPUS: list[tuple[str, str | None, str, str]] = [
    # ------------------------------------------------------------------
    # Smoke-Tests: positive Fälle die immer funktionieren sollten
    # ------------------------------------------------------------------
    ("status", "status", "smoke", "Simple-Command"),
    ("wetter morgen", "wetter", "smoke", "Wetter-Pattern"),
    ("lösche erinnerung 3", "reminder_delete", "smoke", "Reminder vor Calendar"),
    ("mails", "mails", "smoke", "Mail Simple-Command"),
    ("git status", "git", "smoke", "GitHandler: alle git-Subcommands als 'git'"),
    ("docker ps", "docker", "smoke", "DockerHandler: alle docker-Subcommands als 'docker'"),
    ("wie mache ich carbonara", "recipe_lookup", "smoke", "Recipe-Intent HOW_TO"),
    ("was ist das wlan passwort", "note_get_fact", "smoke", "Fakt-Abfrage"),
    ("merk dir wlan büro ist xyz123", "note_set_fact", "smoke", "Fakt-Speichern"),
    ("notizen suche kennwort", "note_search", "smoke", "Notiz-Suche"),
    ("termine woche", "termine", "smoke", "CalendarHandler: Termin-Pattern → 'termine'"),
    ("lösche alle termine", "termin_delete", "smoke", "Calendar-Delete mit Marker"),
    ("termin: Zahnarzt morgen 14:00", "termin_create", "smoke", "Termin erstellen"),
    # ------------------------------------------------------------------
    # Negative-Samples: darf NICHT gerouted werden (→ None)
    # ------------------------------------------------------------------
    ("lösch alle", None, "negative", "Zu unspezifisch – kein Domain-Marker"),
    (
        "speichere es bitte als notiz ab",
        None,
        "negative",
        "Kein Pattern/Keyword-Match ohne Doppelpunkt",
    ),
    # ------------------------------------------------------------------
    # Known Conflicts: gelöst durch Priority, aber Kollision existiert
    # ------------------------------------------------------------------
    (
        "lauter",
        "harmony_volume_up",
        "known_conflict",
        "System(volume) + Harmony(harmony_volume_up) – Harmony (prio=62) schlägt System (prio=10) via Pattern-Match",
    ),
    (
        "wer ist max mustermann",
        "contact_who",
        "known_conflict",
        "Note(note_get_fact) + Contact(contact_who) – Contact-Pattern gewinnt über Note-Keyword",
    ),
    (
        "wann ist lisa geburtstag",
        "contact_field_query",
        "known_conflict",
        "Contact-Feldabfrage gewinnt über die generische Note-Faktfrage",
    ),
    (
        "was ist die adresse von max mustermann",
        "contact_field_query",
        "known_conflict",
        "Contact-Feldabfrage gewinnt über die generische Note-Faktfrage",
    ),
    # ------------------------------------------------------------------
    # Negative HOW_TO-Faelle: generische Nachfragen dürfen nicht auf
    # recipe_lookup routen.
    # ------------------------------------------------------------------
    (
        "wie mache ich das",
        None,
        "negative",
        "Generisches HOW_TO ohne Rezept-Substanz soll nicht als Rezept gelten",
    ),
    (
        "wie mache ich das?",
        None,
        "negative",
        "Generisches HOW_TO mit Satzzeichen soll nicht als Rezept gelten",
    ),
    (
        "wie mache ich das, bitte?",
        None,
        "negative",
        "Generisches HOW_TO mit Hoeflichkeitsendung soll nicht als Rezept gelten",
    ),
    (
        "ich muss von zuhause zu nadine und dann zu lisa",
        "multi_stop_route",
        "smoke",
        "MultiStopRouteCommandHandler: Multi-Stop-Absicht wird korrekt erkannt",
    ),
    (
        "ich muss von zuhause zu nadine und dann lisa",
        "route_from_to",
        "smoke",
        "Unvollstaendiges 'und dann' darf nicht auf multi_stop_route gehen.",
    ),
    (
        "plane route nach leipzig",
        "route_plan",
        "smoke",
        "Single-Stop bleibt bei RouteCommandHandler; Multi-Stop-Gate blockt Catch-All.",
    ),
    (
        "notiz route: ich muss nach leipzig, vorher lisa abholen",
        "note_add",
        "known_conflict",
        "Explizite Notiz darf nicht vom breiten multi_stop_route-Search uebersteuert werden.",
    ),
    (
        "wie mache ich ein backup",
        None,
        "negative",
        "System-Task darf nicht als Rezept-Intent erkannt werden",
    ),
    (
        "wie mache ich ein backup?",
        None,
        "negative",
        "Backup-HOW_TO mit Satzzeichen darf nicht als Rezept-Intent erkannt werden",
    ),
    (
        "wie mache ich ein backup, bitte?",
        None,
        "negative",
        "Backup-HOW_TO mit Hoeflichkeitsendung darf nicht als Rezept-Intent erkannt werden",
    ),
    (
        "wie mache ich das perfekte risotto",
        "recipe_lookup",
        "smoke",
        "Substanz nach 'das' darf nicht pauschal geblockt werden",
    ),
    (
        "wie mache ich einen screenshot",
        "screenshot",
        "smoke",
        "Screenshot-Frage darf nicht als Rezept-Intent erkannt werden; System-Command ist erlaubt",
    ),
    (
        "wie mache ich einen screenshot?",
        "screenshot",
        "smoke",
        "Screenshot-HOW_TO mit Satzzeichen darf nicht als Rezept-Intent erkannt werden",
    ),
    (
        "wie mache ich einen screenshot, bitte?",
        "screenshot",
        "smoke",
        "Screenshot-HOW_TO mit Hoeflichkeitsendung darf nicht als Rezept-Intent erkannt werden",
    ),
]


EXPECTED_CANDIDATE_CONFLICTS: dict[str, dict[str, object]] = {
    "wer ist max mustermann": {
        "winner": "contact_who",
        "losers": {"note_get_fact"},
        "sources": {"pattern_match", "keyword"},
        "reason": "Contact-Pattern gewinnt gegen Note-Keyword.",
    },
    "wann ist lisa geburtstag": {
        "winner": "contact_field_query",
        "losers": {"note_get_fact"},
        "sources": {"pattern_match", "keyword"},
        "reason": "Kontakt-Feldabfrage gewinnt gegen Note-Keyword.",
    },
    "was ist die adresse von max mustermann": {
        "winner": "contact_field_query",
        "losers": {"note_get_fact"},
        "sources": {"pattern_match"},
        "reason": "Kontakt-Feldabfrage gewinnt gegen Note-Keyword.",
    },
}


_SOURCE_ORDER: dict[str, int] = {
    "simple": 0,
    "pattern_match": 1,
    "pattern_search": 2,
    "keyword": 3,
}


def _candidate_sort_key(candidate: CommandMatchCandidate) -> tuple[int, int, int]:
    c = candidate
    return (-c.confidence, _SOURCE_ORDER[c.source], c.priority)


def _best_candidate_per_command(
    candidates: list[CommandMatchCandidate],
) -> dict[str, CommandMatchCandidate]:
    best: dict[str, CommandMatchCandidate] = {}
    for cand in candidates:
        current = best.get(cand.command)
        if current is None or _candidate_sort_key(cand) < _candidate_sort_key(current):
            best[cand.command] = cand
    return best


def _corpus_params() -> list[pytest.param]:
    """Wandelt CORPUS-Einträge in pytest.param um."""
    params = []
    for text, expected, label, comment in CORPUS:
        p_id = f"{label}:{text[:50]}"
        params.append(pytest.param(text, expected, label, comment, id=p_id))
    return params


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _full_mock_ctx() -> HandlerContext:
    return HandlerContext(
        project_root=Path("."),
        secret_store=MagicMock(),
        default_user_id="@test:matrix",
        system_monitor=MagicMock(),
        controller=MagicMock(),
        download_dir=Path("."),
        avatar_renderer=MagicMock(),
        send_file_allowed_roots=(Path("."),),
        audio_router=MagicMock(),
        computer_use=MagicMock(),
        robot_client=MagicMock(),
        tower_agent=MagicMock(),
        anthropic_client=MagicMock(),
        weather=MagicMock(),
        reminder_store=MagicMock(),
        briefing_scheduler=MagicMock(),
        email_client=MagicMock(),
        calendar=MagicMock(),
        fact_store=MagicMock(),
        contact_store=MagicMock(),
        task_client=MagicMock(),
        pending_store=MagicMock(),
        nextcloud_files=MagicMock(),
        document_classifier=MagicMock(),
        stirling_pdf=MagicMock(),
        route_planner=MagicMock(),
        multi_stop_route_planner=MagicMock(),
        route_session_store=MagicMock(),
        web_fetcher=MagicMock(),
        search_client=MagicMock(),
        document_reader=MagicMock(),
        gym_client=MagicMock(),
        carddav_sync=MagicMock(),
    )


@pytest.fixture(scope="module")
def handler() -> RemoteCommandHandler:
    return RemoteCommandHandler(ctx=_full_mock_ctx())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected,label,comment", _corpus_params())
def test_routing_corpus(
    handler: RemoteCommandHandler,
    text: str,
    expected: str | None,
    label: str,
    comment: str,
) -> None:
    """Corpus-Test: parse_command soll für jeden Eintrag das Erwartete liefern."""
    result = handler.parse_command(text)
    assert result == expected, (
        f"[{label}] '{text}' → '{result}', erwartet '{expected}' ({comment})"
    )


def test_collect_candidates_multi_candidate_log(
    handler: RemoteCommandHandler,
) -> None:
    """Bekannte Konflikte muessen winner/losers/source-Mix stabil zeigen."""
    for text, expected in EXPECTED_CANDIDATE_CONFLICTS.items():
        candidates = handler.collect_candidates(text)
        best_by_command = _best_candidate_per_command(candidates)
        assert len(best_by_command) > 1, (
            f"Erwartet Mehrdeutigkeit fuer '{text}', "
            f"aber nur {len(best_by_command)} Command-Kandidat(en): "
            f"{[(c.command, c.source) for c in candidates]}"
        )

        chosen = handler.choose_candidate(candidates)
        assert chosen is not None
        assert chosen.command == expected["winner"], (
            f"'{text}': winner='{chosen.command}', erwartet "
            f"'{expected['winner']}' ({expected['reason']})"
        )

        losers = {cmd for cmd in best_by_command if cmd != chosen.command}
        assert losers == expected["losers"], (
            f"'{text}': losers={losers}, erwartet {expected['losers']} "
            f"({expected['reason']})"
        )

        actual_sources = {c.source for c in candidates}
        assert expected["sources"] <= actual_sources, (
            f"'{text}': sources={actual_sources}, erwartet mindestens "
            f"{expected['sources']} ({expected['reason']})"
        )


def test_route_command_returns_routed_command(
    handler: RemoteCommandHandler,
) -> None:
    """route_command soll für einen erkannten Command ein RoutedCommand liefern."""
    routed = handler.route_command("status")
    assert routed is not None
    assert routed.command == "status"
    assert routed.candidate.source == "simple"
    assert routed.candidate.confidence == 100


def test_route_command_returns_none_for_unknown(
    handler: RemoteCommandHandler,
) -> None:
    """route_command soll None für nicht erkannten Text liefern."""
    routed = handler.route_command("blablabla xyz komplett unbekannt")
    assert routed is None


def test_candidates_confidence_hierarchy(
    handler: RemoteCommandHandler,
) -> None:
    """Simple-Commands haben höhere Konfidenz als Pattern-Matches."""
    simple_candidates = handler.collect_candidates("status")
    pattern_candidates = handler.collect_candidates("wetter morgen")

    simple = [c for c in simple_candidates if c.source == "simple"]
    assert simple, "Keine Simple-Kandidaten für 'status'"
    assert simple[0].confidence == 100

    pattern = [c for c in pattern_candidates if c.source == "pattern_match"]
    assert pattern, "Keine Pattern-Kandidaten für 'wetter morgen'"
    assert pattern[0].confidence == 90
    assert all(c.confidence < 100 for c in pattern)


def test_multi_stop_keyword_candidate_rejected_without_route_intro(
    handler: RemoteCommandHandler,
) -> None:
    """Deckt den Keyword-Gate-False-Pfad in collect_candidates ab."""
    candidates = handler.collect_candidates("unterwegs tanken")
    assert all(c.command != "multi_stop_route" for c in candidates)


def test_multi_stop_keyword_candidate_boosted_when_gate_true(
    handler: RemoteCommandHandler,
) -> None:
    """Deckt den Keyword-Gate-True-Pfad inkl. Confidence-Boost ab."""
    text = "nach leipzig unterwegs tanken"
    candidates = handler.collect_candidates(text)
    multi_stop = [
        c for c in candidates if c.command == "multi_stop_route" and c.source == "keyword"
    ]
    assert multi_stop, "Erwartet multi_stop_route als Keyword-Kandidat"
    assert max(c.confidence for c in multi_stop) == 95
