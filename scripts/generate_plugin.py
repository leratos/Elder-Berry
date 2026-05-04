"""Phase 77 Etappe 3: Wizard zum Erzeugen eines neuen Plugins.

Aufruf:
    python scripts/generate_plugin.py

Fragt interaktiv nach Plugin-Name, Priority und Kategorie und erzeugt
auf Basis von ``docs/templates/plugin_template.py.template`` eine neue
Plugin-Datei. Standardziel ist ``~/.elder-berry/plugins/<name>.py``
(User-Plugin); per ``--builtin`` wird stattdessen
``src/elder_berry/comms/commands/<name>_commands.py`` erzeugt.

Zero-Dependency-Wizard (stdlib only).
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from string import Template

logger = logging.getLogger(__name__)

# Repo-Root vom Skript aus -- generate_plugin.py liegt in scripts/.
REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "docs" / "templates" / "plugin_template.py.template"

USER_PLUGIN_DIR = Path.home() / ".elder-berry" / "plugins"
BUILTIN_DIR = REPO_ROOT / "src" / "elder_berry" / "comms" / "commands"

# Aus help_sections.CATEGORY_LABELS gespiegelt. Wir importieren NICHT
# direkt, damit der Wizard auch ohne installiertes Package laeuft (z.B.
# nach git clone vor `pip install -e .`).
KNOWN_CATEGORIES: dict[str, str] = {
    "basis": "Status, Screenshot, Hilfe",
    "medien": "Audio, Musik, Lautstaerke",
    "avatar": "Avatar, Kamera, Selfie",
    "dateien": "Clipboard, Senden, Download",
    "cloud": "Nextcloud, Ablage, PDF",
    "kalender": "Termine, Suche, Erstellen",
    "mail": "Mails, Suche, Antworten",
    "fitness": "Berry-Gym, Training, PRs",
    "wetter": "Wetter, Timer, Erinnerungen, Briefing",
    "notizen": "Notizen & Wissensdatenbank",
    "kontakte": "Kontaktbuch + Sync",
    "todos": "Aufgabenliste",
    "smart-home": "Harmony Hub, Drehteller",
    "web": "Web-Suche, Dokumente, Computer Use, Routen",
    "system": "Prozesse, Git, Docker, Update, Selfcheck",
    "diagnose": "Log-Zugriff fuer Remote-Debugging",
}

PLUGIN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _to_class_name(plugin_name: str) -> str:
    """``my_plugin`` -> ``MyPlugin``."""
    return "".join(part.capitalize() for part in plugin_name.split("_"))


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        print("(Pflichtfeld -- bitte antworten)")


def _ask_int(prompt: str, default: int) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            print(f"(Bitte ganze Zahl, nicht '{raw}')")


def _ask_category(default: str = "basis") -> str:
    print("\nVerfuegbare Kategorien:")
    for key, label in KNOWN_CATEGORIES.items():
        print(f"  {key:<12} -- {label}")
    while True:
        cat = _ask("Kategorie", default=default)
        if cat in KNOWN_CATEGORIES:
            return cat
        print(
            f"(Unbekannt: '{cat}'. Neue Kategorien zuerst in "
            "help_sections.CATEGORY_LABELS eintragen.)"
        )


def _validate_plugin_name(name: str) -> str:
    if not PLUGIN_NAME_RE.match(name):
        raise ValueError(
            f"Ungueltiger Plugin-Name '{name}'. "
            "Nur snake_case (a-z, 0-9, _), beginnend mit Buchstaben."
        )
    return name


def _resolve_target(plugin_name: str, builtin: bool, force: bool) -> Path:
    if builtin:
        target_dir = BUILTIN_DIR
        target = target_dir / f"{plugin_name}_commands.py"
    else:
        target_dir = USER_PLUGIN_DIR
        target = target_dir / f"{plugin_name}.py"

    target_dir.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        raise FileExistsError(
            f"Datei existiert schon: {target}. "
            "Mit --force ueberschreiben oder anderen Namen waehlen."
        )
    return target


def _render(
    plugin_name: str,
    handler_name: str,
    category: str,
    priority: int,
    summary: str,
) -> str:
    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    return Template(template_text).substitute(
        PLUGIN_NAME=plugin_name,
        PLUGIN_NAME_UPPER=plugin_name.upper(),
        HANDLER_NAME=handler_name,
        CATEGORY=category,
        PRIORITY=str(priority),
        SUMMARY=summary,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Erzeugt ein neues CommandPlugin aus dem Template."
    )
    parser.add_argument(
        "--builtin",
        action="store_true",
        help="Ins Repo schreiben (src/elder_berry/comms/commands/) statt User-Dir.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Existierende Datei ueberschreiben.",
    )
    parser.add_argument(
        "--name",
        help="Plugin-Name (snake_case). Wenn weggelassen: interaktiv.",
    )
    args = parser.parse_args(argv)

    if not TEMPLATE_PATH.exists():
        print(f"Template nicht gefunden: {TEMPLATE_PATH}", file=sys.stderr)
        return 2

    print("=== Elder-Berry Plugin-Wizard (Phase 77) ===\n")

    if args.name:
        plugin_name = _validate_plugin_name(args.name)
    else:
        while True:
            try:
                plugin_name = _validate_plugin_name(_ask("Plugin-Name (snake_case)"))
                break
            except ValueError as exc:
                print(f"({exc})")

    handler_name = _to_class_name(plugin_name)
    summary = _ask("Kurzbeschreibung", default=f"{handler_name}-Plugin")
    category = _ask_category()
    priority = _ask_int("Priority (10-99)", default=50)
    if not 0 <= priority <= 99:
        print(f"(Warnung: Priority {priority} ausserhalb 0-99 -- ist das gewollt?)")

    try:
        target = _resolve_target(plugin_name, builtin=args.builtin, force=args.force)
    except FileExistsError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1

    rendered = _render(
        plugin_name=plugin_name,
        handler_name=handler_name,
        category=category,
        priority=priority,
        summary=summary,
    )
    target.write_text(rendered, encoding="utf-8")

    print(f"\nFertig: {target}")
    if args.builtin:
        print(
            "\nNaechste Schritte (Builtin):"
            "\n  1. mypy + pytest laufen lassen (test_plugin_registry.py erwartet "
            "den neuen Namen in EXPECTED_PLUGIN_NAMES)."
            "\n  2. Falls neue Kategorie: Eintrag in CATEGORY_LABELS + HELP_SECTIONS."
            "\n  3. Branch + commit + PR."
        )
    else:
        print(
            "\nNaechste Schritte (User-Plugin):"
            "\n  1. Datei oeffnen und execute()-Logik implementieren."
            "\n  2. Saleria neu starten -- Plugin wird beim Start geladen."
            "\n  3. 'hilfe' in Element zeigt die neue Sektion."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
