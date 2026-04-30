#!/usr/bin/env python3
"""Einmaliges OAuth2-Setup für Google Calendar API.

Voraussetzungen:
    1. Google Cloud Console → Projekt erstellen
    2. Calendar API aktivieren
    3. OAuth 2.0 Client-ID erstellen (Desktop-Anwendung)
    4. client_secret.json herunterladen → ~/.elder-berry/google_client_secret.json

Verwendung:
    python scripts/setup_google_oauth.py

Ablauf:
    1. Liest client_secret.json aus ~/.elder-berry/
    2. Öffnet Browser für Google-Login + Berechtigungs-Dialog
    3. Speichert Refresh-Token im SecretStore (verschlüsselt)
    4. client_secret.json kann danach gelöscht werden

Scopes:
    - calendar (Termine lesen + erstellen)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from elder_berry.core.secret_store import SecretStore

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]

CLIENT_SECRET_PATH = Path.home() / ".elder-berry" / "google_client_secret.json"


def main() -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Fehler: google-auth-oauthlib nicht installiert.")
        print("  pip install google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    if not CLIENT_SECRET_PATH.exists():
        print(f"Fehler: {CLIENT_SECRET_PATH} nicht gefunden.")
        print()
        print("Anleitung:")
        print("  1. https://console.cloud.google.com/ → Projekt erstellen")
        print("  2. APIs & Services → Calendar API aktivieren")
        print("  3. Credentials → OAuth 2.0 Client-ID erstellen (Desktop)")
        print(f"  4. JSON herunterladen → {CLIENT_SECRET_PATH}")
        sys.exit(1)

    print("Starte Google OAuth2-Flow...")
    print(f"Scopes: {', '.join(SCOPES)}")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH),
        scopes=SCOPES,
    )
    credentials = flow.run_local_server(port=0)

    # Tokens im SecretStore speichern
    store = SecretStore()
    token_data = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes or SCOPES),
    }
    store.set("google_oauth_tokens", json.dumps(token_data))

    print()
    print("OAuth2-Setup erfolgreich!")
    print(f"  Refresh-Token gespeichert im SecretStore (verschlüsselt)")
    print(f"  Account: {credentials.token[:20]}...")
    print()
    print("Du kannst client_secret.json jetzt löschen (optional).")
    print("Der Refresh-Token reicht für den Dauerbetrieb.")


if __name__ == "__main__":
    main()
