"""Phase 67 -- Public-Readiness-Audit.

Sucht im Repo nach Daten, die einer Veroeffentlichung im Weg stehen
oder Rueckschluesse auf die echte Infrastruktur geben:

  * Eigene Domains (last-strawberry.com und Subdomains)
  * LAN-IPs (192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12)
  * Persoenliche IDs (E-Mail, Vornamen, Matrix-User-IDs)
  * Hostnames (h2724315, elderberry)
  * Absolute Server-Pfade (/var/www/vhosts/, /home/lera/, /opt/Elder-Berry/)
  * SSH-User-Spuren (lera@host, ssh-Befehle)

Ausgabe: Markdown-Bericht ``docs/public-readiness-audit.md`` (kann via
``--out`` umgeleitet werden). Skript ist read-only -- aendert nichts.

Aufruf::

    .venv/Scripts/python.exe scripts/check_public_readiness.py
    .venv/Scripts/python.exe scripts/check_public_readiness.py --out -        # stdout
    .venv/Scripts/python.exe scripts/check_public_readiness.py --json        # maschinenlesbar

Die Patterns sind bewusst eng -- generische Internet-IPs (8.8.8.8) und
RFC-Beispiele (example.com) werden nicht gemeldet. Wenn du etwas neues
hinzufuegst, das im Repo gefunden werden soll, ergaenze die
``CATEGORIES``-Liste unten.
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
    ".docker", ".lock", ".sql", ".jinja", ".jinja2", ".j2",
})

# Dateien ohne Endung, die wir trotzdem als Text behandeln.
_TEXT_FILENAMES: frozenset[str] = frozenset({
    "Dockerfile", "Makefile", "LICENSE", "README", "CHANGELOG",
    ".gitignore", ".dockerignore", ".env",
})

# Dateien, die wir komplett ueberspringen (z.B. dieses Skript selbst,
# der Audit-Output, Lockfiles -- die sind nur Pinning-Snapshots).
_SKIP_FILES: frozenset[str] = frozenset({
    Path(__file__).name,
    "public-readiness-audit.md",
    "public-readiness-audit.json",
})


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


CATEGORIES: tuple[Category, ...] = (
    Category(
        key="domain",
        label="Eigene Domain",
        description="last-strawberry.com und Subdomains",
        # Negative-Lookbehind verhindert dass "fakelast-strawberry.com"
        # matchen wuerde -- die Domain muss am Wort beginnen.
        patterns=(_ci(r"\b(?:[\w-]+\.)*last-strawberry\.com\b"),),
        severity="high",
        recommendation=(
            "Konstanten extrahieren -> als Beispiel-Default ('example.com') "
            "oder via SecretStore/ENV. Tests sollten Beispieldomain nutzen."
        ),
    ),
    Category(
        key="lan_ip",
        label="LAN-IP",
        description="Private IPv4-Bereiche (192.168/16, 10/8, 172.16/12)",
        patterns=(
            re.compile(
                # 192.168.x.x (Heimnetz)
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
    ),
    Category(
        key="email_pii",
        label="Persoenliche E-Mail / Namen",
        description="E-Mail-Adressen, Vornamen, identifizierbare User-IDs",
        patterns=(
            _ci(r"\bmarcus(?:@|\b\.\w+@)"),
            _ci(r"\bsfi-kohtz\b"),
            # "lera" als Wort, nicht als Substring von "general" o.ae.
            _ci(r"(?<![a-zA-Z])lera(?![a-zA-Z])"),
            # E-Mail-Pattern allgemein, aber nur wenn Domain unsere ist
            _ci(r"[\w.-]+@[\w.-]*last-strawberry\.com"),
        ),
        severity="high",
        recommendation=(
            "Komplett entfernen. Beispielwerte: 'user@example.com', "
            "'admin'. CLAUDE.md/MEMORY.md gehoeren u.U. nicht ins "
            "Public-Repo."
        ),
    ),
    Category(
        key="matrix_id",
        label="Matrix-User-/Room-ID",
        description="@user:matrix.last-strawberry.com, !room:server",
        patterns=(
            _ci(r"@[\w-]+:[\w.-]+\.\w{2,}"),
            _ci(r"![\w-]+:[\w.-]+\.\w{2,}"),
        ),
        severity="high",
        recommendation=(
            "Beispielwerte: '@bot:matrix.example.com', "
            "'!roomid:matrix.example.com'."
        ),
    ),
    Category(
        key="hostname",
        label="Konkreter Hostname",
        description="h2724315, elderberry, andere Geraete-Namen",
        patterns=(
            _ci(r"\bh2724315\b"),
            # 'elderberry' ist Projekt-relevant -- nur als Hostname
            # melden, wenn typische Konfig-Kontexte da sind.
            _ci(r"\belderberry\b(?:\s*systemd|@elderberry)"),
        ),
        severity="medium",
        recommendation=(
            "Konkrete Hostnames neutralisieren. 'tower-host', 'rpi5-host' "
            "als Defaults."
        ),
    ),
    Category(
        key="server_path",
        label="Absoluter Server-Pfad",
        description="/var/www/vhosts/, /home/lera/, /opt/Elder-Berry/",
        patterns=(
            _ci(r"/var/www/vhosts/[\w.-]+/[\w./-]*"),
            _ci(r"/home/lera(?:/[\w./-]*)?"),
            _ci(r"/opt/Elder-Berry(?:/[\w./-]*)?"),
        ),
        severity="medium",
        recommendation=(
            "Path.home() / Pfad-Konstanten / ENV nutzen. Niemand sollte "
            "in deinem Repo-Code wissen, dass dein Server-Hosting-Anbieter "
            "Plesk-Pfade verwendet."
        ),
    ),
    Category(
        key="ssh_user",
        label="SSH-User-Spur",
        description="lera@host, ssh ... -i ~/.ssh/...",
        patterns=(
            _ci(r"\blera@[\w.-]+\b"),
            _ci(r"\bssh\s+(?:[-\w]+\s+)*lera@"),
        ),
        severity="high",
        recommendation=(
            "User-Namen durch Platzhalter ('user@host', '<your-user>') "
            "ersetzen, oder die Stelle nach docs/setup-tunnel.md "
            "auslagern."
        ),
    ),
)


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
    path: Path, repo_root: Path, results: dict[str, CategoryStats],
) -> None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    rel_path = str(path.relative_to(repo_root)).replace("\\", "/")

    for line_num, line in enumerate(content.splitlines(), start=1):
        for cat in CATEGORIES:
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


def _format_markdown(results: dict[str, CategoryStats], repo_root: Path) -> str:
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
    for cat in CATEGORIES:
        s = results[cat.key]
        out.append(
            f"| {s.label} | {s.severity} | {len(s.findings)} | "
            f"{len(s.files_affected)} |"
        )
    out.append(f"| **Gesamt** | | **{total}** | |")
    out.append("")

    # Pro Kategorie ein eigener Abschnitt
    for cat in CATEGORIES:
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


def _format_json(results: dict[str, CategoryStats]) -> str:
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
        for cat in CATEGORIES
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 67: Public-Readiness Audit.",
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

    results: dict[str, CategoryStats] = {
        cat.key: CategoryStats(
            label=cat.label,
            severity=cat.severity,
            description=cat.description,
            recommendation=cat.recommendation,
        )
        for cat in CATEGORIES
    }

    ignored = _gitignored_paths(repo_root)
    files_scanned = 0
    for path in _walk_repo(repo_root, ignored=ignored):
        _scan_file(path, repo_root, results)
        files_scanned += 1

    formatter = _format_json if args.json else _format_markdown
    text = formatter(results) if args.json else formatter(results, repo_root)

    if args.out == "-":
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
