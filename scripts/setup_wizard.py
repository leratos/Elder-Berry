#!/usr/bin/env python3
"""Standalone-Starter für den Elder-Berry Setup-Wizard.

Startet einen minimalen FastAPI-Server nur mit den Setup-Routes.
Wird von den Bootstrap-Scripts (install.ps1 / install.sh) aufgerufen
oder manuell für Re-Konfiguration.

Verwendung:
    python scripts/setup_wizard.py
    python scripts/setup_wizard.py --port 8090
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import webbrowser
from pathlib import Path
from threading import Timer

# Projektpfad sicherstellen
_PROJECT_ROOT = Path(
    os.environ.get("ELDER_BERRY_HOME", Path(__file__).parent.parent)
).resolve()
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Elder-Berry Setup-Wizard")
    parser.add_argument("--port", type=int, default=8090, help="Port (Default: 8090)")
    parser.add_argument("--no-browser", action="store_true", help="Browser nicht öffnen")
    args = parser.parse_args()

    from elder_berry.core.secret_store import SecretStore

    secret_store = SecretStore()
    url = f"http://localhost:{args.port}/setup"

    print()
    print("=" * 50)
    print("  Elder-Berry Setup-Wizard")
    print(f"  {url}")
    print("=" * 50)
    print()

    if not args.no_browser:
        Timer(1.5, webbrowser.open, args=[url]).start()

    from elder_berry.web.setup_wizard import run_setup_wizard
    run_setup_wizard(secret_store, port=args.port)


if __name__ == "__main__":
    main()
