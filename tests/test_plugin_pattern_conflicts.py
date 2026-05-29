"""Phase 95 E3: Candidate-basierter Routing-Konflikt-Detector.

Der Test nutzt den echten Candidate-Router des Orchestrators:
``collect_candidates()`` + ``choose_candidate()``.

Regeln:
- Mehrdeutigkeiten mit bekanntem Outcome stehen in
    ``EXPECTED_ROUTING_CONFLICTS`` (winner/losers/reason).
- Pattern-vs-Pattern-Konflikte ohne lokale Allowlist sind nur erlaubt,
    wenn das Gewinner-Plugin den Verlierer in ``plugin.conflicts`` deklariert.
- Konflikte mit Keyword-Beteiligung muessen explizit in
    ``EXPECTED_ROUTING_CONFLICTS`` dokumentiert werden.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from elder_berry.comms.commands.base import CommandMatchCandidate, HandlerContext
from elder_berry.comms.remote_commands import RemoteCommandHandler
from elder_berry.comms.commands.registry import load_plugins


# --- Sample-Inputs (Konzept §6 + Priority-Constraints aus 77.2) ----------
# Lowercase, ohne Filler-Words -- so muss die Test-Logik nicht
# _strip_fillers nachbauen. Die Inputs decken die bekannten Konflikt-
# Cluster ab:
#   * lösche-Familie (weather/calendar/mail/note)
#   * schau-/zeig-Familie (mail/camera/turntable/briefing)
#   * Domain-Single-Word-Commands (status, mails, kamera, ...)
#   * Pattern-Commands mit Argumenten
SAMPLE_INPUTS = [
    # lösche-Familie -- die berühmten DELETE-Konflikte
    "lösche erinnerung 3",
    "lösche termin morgen",
    "lösche die mail #5",
    "lösche alle termine",
    # Wetter
    "wetter morgen",
    "wetter woche",
    # Termine
    "erstelle termin zahnarzt morgen 14:00",
    "termine woche",
    "termin suche meeting",
    # Mail
    "mails",
    "mail suche rechnung",
    "antworte auf #5 ja gern",
    # Notizen / Kontakte / Route
    "merk dir wlan büro ist xyz123",
    "notizen suche kennwort",
    "kontakt suche müller",
    "plane route nach leipzig",
    # System / Tooling
    "git status",
    "docker ps",
    "wol",
    "selfcheck",
    "kamera",
    "fernsehen an",
    "log",
    "log errors 50",
]


EXPECTED_ROUTING_CONFLICTS: dict[str, dict[str, object]] = {
    "lösche erinnerung 3": {
        "winner": "reminder_delete",
        "losers": {"termin_delete"},
        "reason": "Reminder-Delete ist spezifischer als generisches Termin-Delete.",
    },
    "lauter": {
        "winner": "harmony_volume_up",
        "losers": {"volume"},
        "reason": "Harmony-Pattern gewinnt gegen System-Keyword.",
    },
    "wer ist max mustermann": {
        "winner": "contact_who",
        "losers": {"note_get_fact"},
        "reason": "Contact-Pattern gewinnt gegen Note-Keyword.",
    },
    "plane route nach leipzig": {
        "winner": "multi_stop_route",
        "losers": {"route_plan"},
        "reason": "Multi-stop hat priorisierten Vorrang vor Single-Route.",
    },
}


def _full_mock_ctx() -> HandlerContext:
    """HandlerContext mit allen Service-Feldern als MagicMock.

    Garantiert, dass alle 23 Plugin-Factories einen Handler liefern --
    auch die conditionals (note/contact/todo/route), deren Factory
    sonst None zurueckgibt.
    """
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


_SOURCE_ORDER: dict[str, int] = {
    "simple": 0,
    "pattern_match": 1,
    "pattern_search": 2,
    "keyword": 3,
}


def _candidate_sort_key(c: CommandMatchCandidate) -> tuple[int, int, int]:
    return (-c.confidence, _SOURCE_ORDER[c.source], c.priority)


def _best_candidate_per_command(
    candidates: list[CommandMatchCandidate],
) -> dict[str, CommandMatchCandidate]:
    """Reduziert Candidate-Liste auf den besten Candidate je Command."""
    best: dict[str, CommandMatchCandidate] = {}
    for cand in candidates:
        current = best.get(cand.command)
        if current is None or _candidate_sort_key(cand) < _candidate_sort_key(current):
            best[cand.command] = cand
    return best


def test_no_undeclared_candidate_collisions() -> None:
    """Stellt sicher, dass Candidate-Konflikte dokumentiert sind.

    - Keyword-Beteiligung => muss in EXPECTED_ROUTING_CONFLICTS stehen.
    - Reiner Pattern/Simple-Konflikt => winner-plugin muss loser-plugin in
      plugin.conflicts auffuehren.
    """
    plugins = load_plugins()  # bereits priority-sortiert
    plugin_by_name = {p.name: p for p in plugins}
    handler = RemoteCommandHandler(ctx=_full_mock_ctx())

    violations: list[str] = []
    for text in SAMPLE_INPUTS:
        candidates = handler.collect_candidates(text)
        best_by_command = _best_candidate_per_command(candidates)
        if len(best_by_command) <= 1:
            continue

        winner = handler.choose_candidate(candidates)
        assert winner is not None
        losers = {
            command: cand
            for command, cand in best_by_command.items()
            if command != winner.command
        }

        expected = EXPECTED_ROUTING_CONFLICTS.get(text)
        if expected is not None:
            assert winner.command == expected["winner"], (
                f"'{text}': winner='{winner.command}', erwartet "
                f"'{expected['winner']}' ({expected['reason']})"
            )
            assert set(losers) == expected["losers"], (
                f"'{text}': losers={set(losers)}, erwartet {expected['losers']} "
                f"({expected['reason']})"
            )
            continue

        winner_plugin = plugin_by_name[winner.plugin_name]
        for loser_command, loser in losers.items():
            # Handler-interne Overlaps (gleiches Plugin) sind kein Plugin-Konflikt.
            if loser.plugin_name == winner.plugin_name:
                continue
            has_keyword_involved = (
                winner.source == "keyword" or loser.source == "keyword"
            )
            if has_keyword_involved:
                violations.append(
                    f"'{text}': winner={winner.command}/{winner.plugin_name}"
                    f"[{winner.source}] vs loser={loser_command}/{loser.plugin_name}"
                    f"[{loser.source}] -- Keyword-Konflikt muss in "
                    "EXPECTED_ROUTING_CONFLICTS dokumentiert werden"
                )
                continue

            if loser.plugin_name not in winner_plugin.conflicts:
                violations.append(
                    f"'{text}': winner={winner.command}/{winner.plugin_name}"
                    f"[{winner.source}] vs loser={loser_command}/{loser.plugin_name}"
                    f"[{loser.source}] -- nicht in "
                    f"{winner.plugin_name}.conflicts"
                )

    assert not violations, (
        "Nicht deklarierte Candidate-Konflikte:\n" + "\n".join(violations)
    )


def test_sample_inputs_actually_match_something() -> None:
    """Sanity-Check: jeder Sample-Input muss MINDESTENS einen Handler treffen.

    Sonst ist der Input falsch geschrieben und der Konflikt-Test prueft
    nichts. Faellt der hier durch: Sample-Input fixen oder durch einen
    treffenden ersetzen.
    """
    unmatched: list[str] = []
    handler = RemoteCommandHandler(ctx=_full_mock_ctx())
    for text in SAMPLE_INPUTS:
        if not handler.collect_candidates(text):
            unmatched.append(text)
    assert not unmatched, f"Sample-Inputs ohne Match: {unmatched}"
