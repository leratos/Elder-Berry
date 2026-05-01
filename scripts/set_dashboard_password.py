"""CLI: Dashboard-Passwort setzen oder zurücksetzen (Phase 58).

Verwendung:
    python scripts/set_dashboard_password.py
    python scripts/set_dashboard_password.py --rotate-secret

Das Skript fragt das neue Passwort interaktiv ab (zweimal zur
Bestätigung) und schreibt den bcrypt-Hash in den SecretStore unter
``dashboard_password_hash``.

``--rotate-secret`` invalidiert zusätzlich alle bestehenden Sessions
(Cookie-Signatur-Secret wird neu generiert).
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path

# Repo-Root in PYTHONPATH einbinden, damit `python scripts/...` ohne
# Install-in-Editable-Mode funktioniert.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from elder_berry.core.secret_store import SecretStore  # noqa: E402
from elder_berry.web.dashboard_auth import (  # noqa: E402
    MIN_PASSWORD_LENGTH,
    DashboardAuthManager,
)


def _read_password_twice() -> str:
    pw1 = getpass.getpass("Neues Dashboard-Passwort: ")
    pw2 = getpass.getpass("Bestätigung:               ")
    if pw1 != pw2:
        print("Fehler: Passwörter stimmen nicht überein.", file=sys.stderr)
        sys.exit(2)
    if len(pw1) < MIN_PASSWORD_LENGTH:
        print(
            f"Fehler: Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein.",
            file=sys.stderr,
        )
        sys.exit(2)
    return pw1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Setzt das Dashboard-Passwort im SecretStore.",
    )
    parser.add_argument(
        "--rotate-secret",
        action="store_true",
        help="Zusätzlich Session-Signing-Secret rotieren (loggt alle "
        "bestehenden Sessions aus).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    store = SecretStore()
    auth = DashboardAuthManager(store)

    pw = _read_password_twice()
    auth.set_password(pw)
    print("Dashboard-Passwort gespeichert.")

    if args.rotate_secret:
        auth.rotate_session_secret()
        print(
            "Session-Signing-Secret rotiert – alle bestehenden Sessions sind ungültig."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
