"""Phase 95 E0: Routing-Corpus-Test.

Simuliert das Kandidaten-Routing für eine kuratierte Menge von Eingaben
und prüft, ob der gewählte Command dem Erwarteten entspricht.

Markierungen:
  "smoke"          – sollte immer korrekt routen (Regression-Guard)
  "negative"       – darf NICHT gerouted werden (→ None)
  "known_conflict" – bekannte Mehrdeutigkeit; aktuell durch Priority gelöst
  "xfail"          – bekannter Fehler, der noch nicht behoben ist

Wenn ein xfail-Fall unerwartet BESTANDEN wird: Markierung entfernen und
in known_conflict oder smoke umwandeln. Das zeigt, dass der Fix wirkte.

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

F5  collect_candidates erzeugt Duplikate für denselben Command, wenn ein
    Pattern sowohl via Stufe 2b (search) als auch via Stufe 3 (keyword)
    matcht (z. B. "plane route nach leipzig" → 2× route_plan).
    choose_candidate behandelt das korrekt (höchster confidence gewinnt),
    aber die Duplikate erhöhen Rauschen in Logs und Tests.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from elder_berry.comms.commands.base import HandlerContext
from elder_berry.comms.remote_commands import RemoteCommandHandler


# ---------------------------------------------------------------------------
# Corpus-Definition
# ---------------------------------------------------------------------------
# Format: (text, expected_command_or_None, label, comment)
# label: "smoke" | "negative" | "known_conflict" | "xfail"

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
        "ich muss von zuhause zu nadine und dann zu lisa",
        "multi_stop_route",
        "smoke",
        "MultiStopRouteCommandHandler: Multi-Stop-Absicht wird korrekt erkannt",
    ),
    (
        "plane route nach leipzig",
        "multi_stop_route",
        "smoke",
        "MultiStopRouteCommandHandler hat Vorrang vor route_plan (Prio 75 < 76)",
    ),
    (
        "wie mache ich ein backup",
        None,
        "negative",
        "System-Task darf nicht als Rezept-Intent erkannt werden",
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
]


def _corpus_params() -> list[pytest.param]:
    """Wandelt CORPUS-Einträge in pytest.param um; xfail-Einträge erhalten Mark."""
    params = []
    for text, expected, label, comment in CORPUS:
        p_id = f"{label}:{text[:50]}"
        if label == "xfail":
            params.append(
                pytest.param(
                    text,
                    expected,
                    label,
                    comment,
                    id=p_id,
                    marks=pytest.mark.xfail(strict=True, reason=comment),
                )
            )
        else:
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
    """Für bekannte Konflikte muss collect_candidates > 1 Kandidat liefern."""
    conflicts = [
        "plane route nach leipzig",   # route_plan: 2 Kandidaten (pattern_search + keyword)
        "wer ist max mustermann",     # contact_who + note_get_fact
    ]
    for text in conflicts:
        candidates = handler.collect_candidates(text)
        assert len(candidates) > 1, (
            f"Erwartet Mehrdeutigkeit für '{text}', "
            f"aber nur {len(candidates)} Kandidat(en): "
            f"{[(c.command, c.source) for c in candidates]}"
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
