"""Phase 95 E0: Keyword-Konflikt-Audit.

Prüft, dass kein Keyword in mehreren Handlern für unterschiedliche
Commands registriert ist, ohne dass der Konflikt deklariert wurde.

Erlaubte Dopplungen stehen in EXPECTED_KEYWORD_CONFLICTS:
    {keyword: {command_a, command_b}}

Findet dieser Test neue Doppelungen → entweder EXPECTED_KEYWORD_CONFLICTS
ergänzen (mit Kommentar, warum die Kollision akzeptabel ist) oder das
Keyword aus einem der Handler entfernen.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock

from elder_berry.comms.commands.base import CommandMatchCandidate, HandlerContext
from elder_berry.comms.commands.registry import load_plugins
from elder_berry.comms.remote_commands import RemoteCommandHandler


# Erlaubte Keyword-Dopplungen: keyword -> Menge erlaubter Commands.
# Eine Dopplung ist "erlaubt", wenn beide Commands relevant sind und die
# Prioritäts-Reihenfolge das Routing korrekt auflöst.
EXPECTED_KEYWORD_CONFLICTS: dict[str, set[str]] = {
    # Lautstärke: System-Handler (volume) und Harmony-Handler kollisieren –
    # Harmony (prio=62) gewinnt via Pattern-Match, System via Keyword.
    "lauter": {"volume", "harmony_volume_up"},
    "leiser": {"volume", "harmony_volume_down"},
    # "musik an" ist Keyword in System (play) und Harmony (harmony_activity_on).
    # Harmony gewinnt via Pattern-Match (prio=62 < prio=10 irrelevant, da pattern).
    "musik an": {"play", "harmony_activity_on"},
    # "wer ist" ist Keyword in NoteHandler (note_get_fact) und ContactHandler
    # (contact_who).  Contact gewinnt via Pattern-Match.
    "wer ist": {"note_get_fact", "contact_who"},
}


EXPECTED_KEYWORD_ROUTING_CONFLICTS: dict[str, dict[str, object]] = {
    "lauter": {
        "winner": "harmony_volume_up",
        "losers": {"volume"},
        "reason": "Harmony-Pattern gewinnt gegen System-Keyword.",
    },
    "leiser": {
        "winner": "harmony_volume_down",
        "losers": {"volume"},
        "reason": "Harmony-Pattern gewinnt gegen System-Keyword.",
    },
    "musik an": {
        "winner": "harmony_activity_on",
        "losers": {"play"},
        "reason": "Harmony-Pattern gewinnt gegen System-Keyword.",
    },
    "wer ist max mustermann": {
        "winner": "contact_who",
        "losers": {"note_get_fact"},
        "reason": "Contact-Pattern gewinnt gegen Note-Keyword.",
    },
}


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
    best: dict[str, CommandMatchCandidate] = {}
    for cand in candidates:
        current = best.get(cand.command)
        if current is None or _candidate_sort_key(cand) < _candidate_sort_key(current):
            best[cand.command] = cand
    return best


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
        web_fetcher=MagicMock(),
        search_client=MagicMock(),
        document_reader=MagicMock(),
        gym_client=MagicMock(),
        carddav_sync=MagicMock(),
    )


def test_no_undeclared_keyword_command_duplicates() -> None:
    """Kein Keyword darf für zwei verschiedene Commands registriert sein.

    Erlaubte Ausnahmen stehen in EXPECTED_KEYWORD_CONFLICTS.
    Neue Kollisionen müssen dort eingetragen werden – mit Begründung.
    """
    plugins = load_plugins()
    ctx = _full_mock_ctx()

    # keyword -> list[(plugin_name, command)]
    keyword_to_commands: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for plugin in plugins:
        handler = plugin.factory(ctx)
        if handler is None:
            continue
        for command, keywords in handler.keywords.items():
            for kw in keywords:
                keyword_to_commands[kw].append((plugin.name, command))

    violations: list[str] = []
    for keyword, registrations in keyword_to_commands.items():
        # Alle beteiligten Commands
        commands = {cmd for _, cmd in registrations}
        if len(commands) <= 1:
            continue  # kein Konflikt

        allowed = EXPECTED_KEYWORD_CONFLICTS.get(keyword, set())
        # Kollision ist OK, wenn alle beteiligten Commands in der Allowlist stehen
        if commands <= allowed:
            continue

        plugins_str = ", ".join(f"{p}/{c}" for p, c in registrations)
        violations.append(
            f"Keyword '{keyword}' → mehrere Commands: {commands} "
            f"(Plugins: {plugins_str}) – nicht in EXPECTED_KEYWORD_CONFLICTS"
        )

    assert not violations, (
        "Nicht deklarierte Keyword-Konflikte:\n" + "\n".join(violations)
    )


def test_all_keywords_are_strings() -> None:
    """Alle Keyword-Einträge müssen Strings sein (kein None, kein leerer String)."""
    plugins = load_plugins()
    ctx = _full_mock_ctx()

    bad: list[str] = []
    for plugin in plugins:
        handler = plugin.factory(ctx)
        if handler is None:
            continue
        for command, keywords in handler.keywords.items():
            for kw in keywords:
                if not isinstance(kw, str) or not kw.strip():
                    bad.append(
                        f"{plugin.name}/{command}: ungültiges Keyword {kw!r}"
                    )

    assert not bad, "Ungültige Keyword-Einträge:\n" + "\n".join(bad)


def test_keyword_map_matches_handler_keywords() -> None:
    """KEYWORD_MAP des Orchestrators muss mit handler.keywords übereinstimmen.

    Stellt sicher, dass _build_keyword_map() keinen Handler übersieht.
    """
    from elder_berry.comms.remote_commands import RemoteCommandHandler

    rch = RemoteCommandHandler(ctx=_full_mock_ctx())

    # Alle Keywords direkt aus den Handlern sammeln
    direct: dict[str, str] = {}
    for handler in rch._handlers:
        for command, keywords in handler.keywords.items():
            for kw in keywords:
                direct[kw] = command

    km = rch.keyword_map
    # km ist command-indexed: {command: [keywords]}.
    # Für den Vergleich müssen wir einen Reverse-Lookup aufbauen.
    all_kw_in_km = {kw for keywords in km.values() for kw in keywords}
    missing = {kw for kw in direct if kw not in all_kw_in_km}
    assert not missing, f"Keywords fehlen in keyword_map: {missing}"


def test_expected_keyword_conflicts_resolve_as_documented() -> None:
    """Prueft bekannte Keyword-Konflikte ueber collect_candidates/route_command.

    Jeder Konfliktfall muss:
    - mehr als einen Command-Kandidaten liefern,
    - mindestens einen Keyword-Kandidaten enthalten,
    - den dokumentierten winner/losers-Ausgang zeigen.
    """
    handler = RemoteCommandHandler(ctx=_full_mock_ctx())

    for text, expected in EXPECTED_KEYWORD_ROUTING_CONFLICTS.items():
        candidates = handler.collect_candidates(text)
        best_by_command = _best_candidate_per_command(candidates)
        assert len(best_by_command) > 1, (
            f"'{text}' sollte mehr als einen Command-Kandidaten liefern, "
            f"aber hat nur: {list(best_by_command)}"
        )
        assert any(c.source == "keyword" for c in candidates), (
            f"'{text}' sollte mindestens einen Keyword-Kandidaten haben, "
            f"hat aber nur: {[(c.command, c.source) for c in candidates]}"
        )

        routed = handler.route_command(text)
        assert routed is not None
        assert routed.command == expected["winner"], (
            f"'{text}': winner='{routed.command}', erwartet "
            f"'{expected['winner']}' ({expected['reason']})"
        )

        losers = {
            command for command in best_by_command if command != routed.command
        }
        assert losers == expected["losers"], (
            f"'{text}': losers={losers}, erwartet {expected['losers']} "
            f"({expected['reason']})"
        )
