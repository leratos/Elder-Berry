"""Phase 77 Etappe 3: Pattern-Konflikt-Detector als CI-Test.

Pre-Flight-Check: prueft ~20 typische Sample-Inputs gegen alle 23
Builtin-Plugins. Wenn zwei Plugins denselben Text matchen wuerden:

- Das Plugin mit niedrigerer ``priority`` gewinnt zur Laufzeit
  (siehe ``RemoteCommandHandler.parse_command``).
- Damit das in Ordnung ist, MUSS das Sekundaer-Plugin in
  ``primary.conflicts`` stehen -- so wird der Konflikt im Manifest
  dokumentiert und beim Code-Review sichtbar.
- Sonst ist es eine unbeabsichtigte Kollision, die behoben werden
  muss (Pattern verschaerfen oder Priority anpassen).

Das ist Konzept §6, mit zwei Anpassungen gegenueber dem Pseudocode:

1. Statt ``plugin.factory(...)`` (Ellipse, strict-mypy unfreundlich)
   nutzen wir einen Mock-Context-Helper, der alle 19+ Services als
   ``MagicMock`` setzt. So liefern auch conditional Plugins
   (note/contact/todo/route) einen Handler.
2. Wir mirroren die echte Matching-Logik aus
   ``RemoteCommandHandler.parse_command``: ``stripped.lower()`` fuer
   normale Patterns, ``text.strip()`` fuer ``use_original_text=True``,
   ``pattern.search`` fuer ``use_search=True`` sonst ``pattern.match``.

Test ist NICHT strict-mypy-geprueft (analog test_plugin_registry.py).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from elder_berry.comms.commands.base import CommandHandler, HandlerContext
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
        note_store=MagicMock(),
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


def _matches_for_input(handler: CommandHandler, raw: str) -> list[str]:
    """Liefert alle command-Namen, die dieser Handler fuer ``raw`` matcht.

    Mirroring von ``RemoteCommandHandler.parse_command``:
    - Simple-Commands: exact-match auf normalisierten Text.
    - Pattern-Match: original Text wenn use_original_text, sonst lower.
                     pattern.search wenn use_search, sonst pattern.match.
    """
    matches: list[str] = []
    normalized = raw.strip().lower()
    if normalized in handler.simple_commands:
        matches.append(normalized)
    for pattern, command, use_original, use_search in handler.patterns:
        check_text = raw.strip() if use_original else normalized
        match_fn = pattern.search if use_search else pattern.match
        if match_fn(check_text):
            matches.append(command)
    return matches


def test_no_undeclared_pattern_collisions() -> None:
    """Stellt sicher, dass jede Pattern-Kollision in plugin.conflicts steht.

    Bricht der Test: entweder das Sekundaer-Plugin in conflicts des
    Primaer-Plugins eintragen (wenn die Kollision gewollt ist und die
    Priority sie sauber aufloest), oder das Pattern verschaerfen, oder
    die Priority anpassen. NICHT einfach den Sample-Input loeschen --
    der ist da, damit kuenftige PRs nicht erneut in dasselbe Loch
    fallen.
    """
    plugins = load_plugins()  # bereits priority-sortiert
    ctx = _full_mock_ctx()

    # Plugin-Name -> Handler-Instanz (nur jene, deren Factory != None)
    handlers_by_plugin: dict[str, CommandHandler] = {}
    for plugin in plugins:
        handler = plugin.factory(ctx)
        if handler is not None:
            handlers_by_plugin[plugin.name] = handler
    plugin_by_name = {p.name: p for p in plugins}

    collisions: list[str] = []
    for text in SAMPLE_INPUTS:
        # Pro Plugin nur EIN Match (das erste in handler.patterns / das
        # simple_command). Mehrere Treffer innerhalb desselben Plugins
        # sind Handler-interne Reihenfolge, kein Plugin-Konflikt.
        first_per_plugin: list[tuple[str, str, int]] = []
        seen_plugins: set[str] = set()
        for plugin in plugins:
            if plugin.name in seen_plugins:
                continue
            handler = handlers_by_plugin.get(plugin.name)
            if handler is None:
                continue
            cmds = _matches_for_input(handler, text)
            if not cmds:
                continue
            first_per_plugin.append((plugin.name, cmds[0], plugin.priority))
            seen_plugins.add(plugin.name)
        if len(first_per_plugin) <= 1:
            continue

        primary_name, primary_cmd, primary_prio = first_per_plugin[0]
        primary_plugin = plugin_by_name[primary_name]
        secondary = first_per_plugin[1:]
        for sname, scmd, sprio in secondary:
            if sname not in primary_plugin.conflicts:
                collisions.append(
                    f"'{text}': primaer={primary_name}/{primary_cmd}"
                    f"(prio={primary_prio}), sekundaer={sname}/{scmd}"
                    f"(prio={sprio}) -- nicht in {primary_name}.conflicts"
                )

    assert not collisions, (
        "Pattern-Kollisionen ohne conflicts-Deklaration:\n" + "\n".join(collisions)
    )


def test_sample_inputs_actually_match_something() -> None:
    """Sanity-Check: jeder Sample-Input muss MINDESTENS einen Handler treffen.

    Sonst ist der Input falsch geschrieben und der Konflikt-Test prueft
    nichts. Faellt der hier durch: Sample-Input fixen oder durch einen
    treffenden ersetzen.
    """
    plugins = load_plugins()
    ctx = _full_mock_ctx()
    handlers = [h for p in plugins if (h := p.factory(ctx)) is not None]

    unmatched: list[str] = []
    for text in SAMPLE_INPUTS:
        if not any(_matches_for_input(h, text) for h in handlers):
            unmatched.append(text)
    assert not unmatched, f"Sample-Inputs ohne Match: {unmatched}"
