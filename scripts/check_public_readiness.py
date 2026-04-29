"""Phase 67/71 -- Public-Readiness-Audit.

Sucht im Repo nach Daten, die einer Veroeffentlichung im Weg stehen
oder Rueckschluesse auf die echte Infrastruktur geben:

  * Custom Blocklist (eigene Domains, Hostnames, Namen, Pfade) -- aus
    optionaler Datei ``.public-readiness-blocklist.txt`` im Repo-Root.
  * LAN-IPs (192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12)
  * Matrix-User-/Room-IDs (@user:server, !room:server)

Ausgabe: Markdown-Bericht ``docs/public-readiness-audit.md`` (kann via
``--out`` umgeleitet werden). Skript ist read-only -- aendert nichts.

Aufruf::

    .venv/Scripts/python.exe scripts/check_public_readiness.py
    .venv/Scripts/python.exe scripts/check_public_readiness.py --out -        # stdout
    .venv/Scripts/python.exe scripts/check_public_readiness.py --json        # maschinenlesbar

Konfigurationsdatei
-------------------

Phase 71 hat das Tool generisch gemacht. Maintainer-spezifische
Patterns (eigene Domain, Vorname, Hostname, Server-Pfade) wandern in
``.public-readiness-blocklist.txt`` (gitignored). Format: ein
**Regex-Pattern pro Zeile**, ``#``-Kommentare und Leerzeilen werden
ignoriert. Beispiele und Stil siehe
``.public-readiness-blocklist.example.txt`` (getrackt).

Wenn die Datei fehlt, fallen wir auf zwei generische Default-Patterns
zurueck (``example.com``, ``your-domain.tld``) -- Forks bekommen so
"alles ok" und sehen das Tool als Skeleton. Wer das Tool ernsthaft
nutzt, kopiert die ``.example.txt`` und passt sie an.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Konfiguration: was wird durchsucht
# ---------------------------------------------------------------------------

# Verzeichnisse, die NICHT durchsucht werden (rekursiv).
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", "dist", "build",
    ".claude", ".idea", ".vscode", ".tox", "htmlcov", "coverage",
    "site-packages", ".eggs", "egg-info",
    # Lokale Daten/Outputs, sind in .gitignore und sollen nicht im
    # Public-Audit auftauchen.
    "logs",
})

# Datei-Endungen, die ueberhaupt geprueft werden. Binaerdateien (.png,
# .wav, .pdf, ...) ignorieren wir.
_TEXT_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".htm", ".css",
    ".scss", ".sass", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".conf", ".json", ".md", ".rst", ".txt", ".sh", ".bash", ".zsh",
    ".ps1", ".psm1", ".env", ".example", ".service", ".dockerfile",
    ".docker", ".sql", ".jinja", ".jinja2", ".j2",
})

# Dateien ohne Endung, die wir trotzdem als Text behandeln.
_TEXT_FILENAMES: frozenset[str] = frozenset({
    "Dockerfile", "Makefile", "LICENSE", "README", "CHANGELOG",
    ".gitignore", ".dockerignore", ".env",
})

# Dateien, die wir komplett ueberspringen (z.B. dieses Skript selbst,
# der Audit-Output, die Blocklist selbst).
_SKIP_FILES: frozenset[str] = frozenset({
    Path(__file__).name,
    "public-readiness-audit.md",
    "public-readiness-audit.json",
    ".public-readiness-blocklist.txt",
    ".public-readiness-blocklist.example.txt",
})

# Custom-Blocklist-Datei im Repo-Root.
BLOCKLIST_FILENAME: str = ".public-readiness-blocklist.txt"

# Generische Default-Patterns, wenn keine Blocklist existiert.
# Die sollen in einem frischen Fork "nichts finden", aber das Tool
# als Skeleton sichtbar machen.
DEFAULT_BLOCKLIST_PATTERNS: tuple[str, ...] = (
    r"example\.com",
    r"your-domain\.tld",
)


# ---------------------------------------------------------------------------
# Audit-Kategorien
# ---------------------------------------------------------------------------


@dataclass
class Category:
    """Eine Audit-Kategorie."""
    key: str           # interner Schluessel
    label: str         # Anzeige-Name
    description: str   # was das hier eigentlich findet
    patterns: tuple[re.Pattern[str], ...]
    severity: str      # "high" | "medium" | "low" (was ist das fuer eine Veroeffentlichung)
    recommendation: str


# Helper: case-insensitive compile.
def _ci(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Generische Kategorien -- gelten fuer jeden Fork ohne Konfiguration.
_CATEGORY_LAN_IP: Category = Category(
    key="lan_ip",
    label="LAN-IP",
    description="Private IPv4-Bereiche (192.168/16, 10/8, 172.16/12)",
    patterns=(
        re.compile(
            # 192.168.x.x (Heimnetz). 192.168.1.1 / 192.168.0.1 sind
            # gaengige Doku-Defaults und werden ausgespart.
            r"\b192\.168\.(?!1\.1\b|0\.1\b)\d{1,3}\.\d{1,3}\b"
        ),
        re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
        re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"),
    ),
    severity="medium",
    recommendation=(
        "Konkrete IPs durch Beispiel-Defaults (192.168.1.x) oder "
        "Konfiguration ersetzen."
    ),
)


_CATEGORY_MATRIX_ID: Category = Category(
    key="matrix_id",
    label="Matrix-User-/Room-ID",
    description="@user:matrix.example.com, !room:server",
    patterns=(
        _ci(r"@[\w-]+:[\w.-]+\.\w{2,}"),
        _ci(r"![\w-]+:[\w.-]+\.\w{2,}"),
    ),
    severity="high",
    recommendation=(
        "Beispielwerte: '@bot:matrix.example.com', "
        "'!roomid:matrix.example.com'."
    ),
)


def _build_custom_blocklist_category(
    patterns: tuple[str, ...],
) -> Category:
    """Baut die Kategorie 'custom_blocklist' aus Roh-Patterns.

    Patterns sind regex-Strings (case-insensitive). Compile-Fehler
    werden geloggt und die fehlerhafte Zeile uebersprungen, damit eine
    kaputte Blocklist-Zeile nicht das ganze Audit blockt.
    """
    compiled: list[re.Pattern[str]] = []
    for raw in patterns:
        try:
            compiled.append(_ci(raw))
        except re.error as exc:
            print(
                f"WARN: Blocklist-Pattern '{raw}' ungueltig "
                f"(uebersprungen): {exc}",
                file=sys.stderr,
            )
    return Category(
        key="custom_blocklist",
        label="Custom Blocklist",
        description=(
            "Maintainer-Patterns aus .public-readiness-blocklist.txt "
            "(eigene Domain, Vorname, Hostname, Server-Pfade)."
        ),
        patterns=tuple(compiled),
        severity="high",
        recommendation=(
            "Konkrete Werte durch Beispielwerte ('example.com', "
            "'user@example.com') oder ENV/SecretStore ersetzen. "
            "Stil siehe .public-readiness-blocklist.example.txt."
        ),
    )


def _load_blocklist_patterns(repo_root: Path) -> tuple[str, ...]:
    """Liest ``.public-readiness-blocklist.txt`` und liefert Patterns.

    Format: ein regex-Pattern pro Zeile, case-insensitive. Zeilen mit
    fuehrendem ``#`` sind Kommentare. Inline-Kommentare (alles ab
    ``#`` bis Zeilenende) werden abgeschnitten. Leerzeilen ignoriert.

    Wenn die Datei nicht existiert oder leer ist, geben wir die
    generischen Defaults zurueck (``example.com``, ``your-domain.tld``).
    Damit funktioniert das Tool auch in Forks ohne Konfiguration und
    sagt dort vermutlich "alles ok".
    """
    bl_path = repo_root / BLOCKLIST_FILENAME
    if not bl_path.exists():
        return DEFAULT_BLOCKLIST_PATTERNS
    try:
        text = bl_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"WARN: Blocklist '{bl_path}' nicht lesbar ({exc}). "
            f"Fallback auf Defaults.",
            file=sys.stderr,
        )
        return DEFAULT_BLOCKLIST_PATTERNS
    patterns: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line
        # Inline-Kommentare entfernen.
        hash_pos = line.find("#")
        if hash_pos >= 0:
            line = line[:hash_pos]
        line = line.strip()
        if not line:
            continue
        patterns.append(line)
    if not patterns:
        return DEFAULT_BLOCKLIST_PATTERNS
    return tuple(patterns)


def build_categories(repo_root: Path) -> tuple[Category, ...]:
    """Baut die finale Kategorie-Liste -- generisch + custom Blocklist.

    Public, damit Tests die Liste fuer einen frisch praeparierten
    Repo-Root pruefen koennen.
    """
    custom = _build_custom_blocklist_category(
        _load_blocklist_patterns(repo_root)
    )
    return (custom, _CATEGORY_LAN_IP, _CATEGORY_MATRIX_ID)


# ---------------------------------------------------------------------------
# Audit-Engine
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """Ein einzelner Treffer."""
    category: str
    file: str       # repo-relativer Pfad
    line: int
    excerpt: str    # die Zeile (gekuerzt auf 200 Zeichen)
    match: str      # konkrete Substring


@dataclass
class CategoryStats:
    label: str
    severity: str
    description: str
    recommendation: str
    findings: list[Finding] = field(default_factory=list)
    files_affected: set[str] = field(default_factory=set)


def _is_text_file(path: Path) -> bool:
    if path.name in _TEXT_FILENAMES:
        return True
    return path.suffix.lower() in _TEXT_EXTENSIONS


def _gitignored_paths(root: Path) -> set[Path]:
    """Listet alle Pfade, die laut Git ignoriert werden.

    Public-Readiness ist nur fuer Dateien relevant, die wirklich im
    Git-Repo landen. Lokale Backup-Skripte oder das gitignored
    journal.txt sollen NICHT als Treffer erscheinen, selbst wenn sie
    auf der Festplatte liegen.

    Wenn kein Git-Repo da ist (oder ``git`` fehlt), wird leeres Set
    zurueckgegeben -- dann verhaelt sich das Tool wie vorher.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--ignored",
             "--exclude-standard", "--directory"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return set()
    if result.returncode != 0:
        return set()
    paths: set[Path] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # ls-files liefert relative Pfade mit /-Separator, ggf. mit
        # Trailing-/ fuer Verzeichnisse.
        paths.add((root / line.rstrip("/")).resolve())
    return paths


def _walk_repo(root: Path, ignored: set[Path] | None = None):
    """Yield alle Text-Dateien im Repo (rekursiv, mit Skip-Dir-Filter)."""
    ignored = ignored or set()
    for entry in sorted(root.iterdir()):
        resolved = entry.resolve()
        if resolved in ignored:
            continue
        if entry.is_dir():
            if entry.name in _SKIP_DIRS:
                continue
            yield from _walk_repo(entry, ignored)
        elif entry.is_file():
            if entry.name in _SKIP_FILES:
                continue
            if _is_text_file(entry):
                yield entry


def _scan_file(
    path: Path,
    repo_root: Path,
    results: dict[str, CategoryStats],
    categories: tuple[Category, ...],
) -> None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    rel_path = str(path.relative_to(repo_root)).replace("\\", "/")

    for line_num, line in enumerate(content.splitlines(), start=1):
        for cat in categories:
            for pat in cat.patterns:
                for match in pat.finditer(line):
                    excerpt = line.strip()
                    if len(excerpt) > 200:
                        excerpt = excerpt[:197] + "..."
                    results[cat.key].findings.append(
                        Finding(
                            category=cat.key,
                            file=rel_path,
                            line=line_num,
                            excerpt=excerpt,
                            match=match.group(0),
                        )
                    )
                    results[cat.key].files_affected.add(rel_path)


def _format_markdown(
    results: dict[str, CategoryStats],
    categories: tuple[Category, ...],
    repo_root: Path,
) -> str:
    out: list[str] = []
    out.append("# Public-Readiness Audit")
    out.append("")
    out.append(
        "Generiert von ``scripts/check_public_readiness.py``. Dieser "
        "Bericht ist **read-only** -- die hier gelisteten Stellen "
        "muessen separat refaktoriert werden, bevor das Repo "
        "veroeffentlicht werden kann."
    )
    out.append("")

    # Uebersicht
    total = sum(len(s.findings) for s in results.values())
    out.append("## Uebersicht")
    out.append("")
    out.append("| Kategorie | Severity | Treffer | Dateien |")
    out.append("|---|---|---:|---:|")
    for cat in categories:
        s = results[cat.key]
        out.append(
            f"| {s.label} | {s.severity} | {len(s.findings)} | "
            f"{len(s.files_affected)} |"
        )
    out.append(f"| **Gesamt** | | **{total}** | |")
    out.append("")

    # Pro Kategorie ein eigener Abschnitt
    for cat in categories:
        stats = results[cat.key]
        out.append(f"## {stats.label} ({stats.severity})")
        out.append("")
        out.append(f"_{stats.description}_")
        out.append("")
        out.append(f"**Empfehlung:** {stats.recommendation}")
        out.append("")

        if not stats.findings:
            out.append("Keine Treffer.")
            out.append("")
            continue

        out.append(f"**Treffer: {len(stats.findings)}** in "
                   f"{len(stats.files_affected)} Datei(en).")
        out.append("")
        out.append("| Datei | Zeile | Match | Auszug |")
        out.append("|---|---:|---|---|")
        # Sortiert nach Datei, dann Zeile.
        for f in sorted(stats.findings, key=lambda x: (x.file, x.line)):
            # Markdown-Pipe-Escaping in den Spalten.
            excerpt = f.excerpt.replace("|", "\\|").replace("\n", " ")
            match = f.match.replace("|", "\\|")
            out.append(f"| `{f.file}` | {f.line} | `{match}` | {excerpt} |")
        out.append("")

    out.append("---")
    out.append("")
    out.append(
        "Naechster Schritt: Diesen Report durchgehen und pro Kategorie "
        "entscheiden:"
    )
    out.append("- **entfernen** (Wert war nur fuer dich relevant),")
    out.append(
        "- **Beispielwert** (z.B. ``example.com`` als Default, echter "
        "Wert via ENV/SecretStore),"
    )
    out.append(
        "- **drinlassen** (z.B. wenn 192.168.1.1 ein dokumentiertes "
        "Standard-Beispiel ist)."
    )
    out.append("")
    return "\n".join(out)


def _format_json(
    results: dict[str, CategoryStats],
    categories: tuple[Category, ...],
) -> str:
    payload = {
        cat.key: {
            "label": results[cat.key].label,
            "severity": results[cat.key].severity,
            "description": results[cat.key].description,
            "recommendation": results[cat.key].recommendation,
            "files_affected": sorted(results[cat.key].files_affected),
            "count": len(results[cat.key].findings),
            "findings": [
                {
                    "file": f.file,
                    "line": f.line,
                    "match": f.match,
                    "excerpt": f.excerpt,
                }
                for f in sorted(
                    results[cat.key].findings,
                    key=lambda x: (x.file, x.line),
                )
            ],
        }
        for cat in categories
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 67/71: Public-Readiness Audit.",
    )
    parser.add_argument(
        "--root", default=".",
        help="Repo-Wurzel (default: cwd).",
    )
    parser.add_argument(
        "--out", default="docs/public-readiness-audit.md",
        help="Output-Pfad (relativ zur --root). '-' = stdout.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="JSON statt Markdown ausgeben (nur sinnvoll mit --out=-).",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    if not repo_root.is_dir():
        print(f"FEHLER: --root '{repo_root}' ist kein Verzeichnis.",
              file=sys.stderr)
        return 2

    categories = build_categories(repo_root)

    results: dict[str, CategoryStats] = {
        cat.key: CategoryStats(
            label=cat.label,
            severity=cat.severity,
            description=cat.description,
            recommendation=cat.recommendation,
        )
        for cat in categories
    }

    ignored = _gitignored_paths(repo_root)
    files_scanned = 0
    for path in _walk_repo(repo_root, ignored=ignored):
        _scan_file(path, repo_root, results, categories)
        files_scanned += 1

    if args.json:
        text = _format_json(results, categories)
    else:
        text = _format_markdown(results, categories, repo_root)

    if args.out == "-":
        # Phase 75: Windows-Default-stdout ist CP1252 und kann
        # Box-Drawing-Zeichen (z.B. U+2551) nicht enkodieren. Wir
        # zwingen UTF-8 ueber den binaeren stdout-Stream, damit der
        # pre-push-Hook und CI-Pipes konsistent funktionieren.
        try:
            sys.stdout.buffer.write(text.encode("utf-8"))
            if not text.endswith("\n"):
                sys.stdout.buffer.write(b"\n")
            sys.stdout.flush()
        except AttributeError:
            # Fallback fuer exotische stdout-Wrapper ohne .buffer
            sys.stdout.write(text)
            if not text.endswith("\n"):
                sys.stdout.write("\n")
    else:
        out_path = (repo_root / args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        total = sum(len(s.findings) for s in results.values())
        print(
            f"Audit fertig: {files_scanned} Dateien gescannt, "
            f"{total} Treffer. Bericht: "
            f"{out_path.relative_to(repo_root)}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
