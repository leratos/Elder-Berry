#!/usr/bin/env python3
"""Einrichtung der E-Mail-Credentials für Saleria (IMAP).

Verwendung:
    python scripts/setup_email.py

Fragt interaktiv nach IMAP-Host, Benutzername und Passwort,
testet die Verbindung und speichert alles im SecretStore (verschlüsselt).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from elder_berry.core.secret_store import SecretStore

# Bekannte Provider mit Default-Einstellungen
PROVIDERS = {
    "strato": ("imap.strato.de", 993),
    "gmx": ("imap.gmx.net", 993),
    "web.de": ("imap.web.de", 993),
    "gmail": ("imap.gmail.com", 993),
    "outlook": ("outlook.office365.com", 993),
    "t-online": ("secureimap.t-online.de", 993),
    "ionos": ("imap.ionos.de", 993),
    "posteo": ("posteo.de", 993),
    "mailbox.org": ("imap.mailbox.org", 993),
}


def main() -> None:
    print("═" * 50)
    print("  Elder-Berry – E-Mail Setup (IMAP)")
    print("═" * 50)
    print()

    store = SecretStore()

    # Bestehende Konfiguration anzeigen
    existing_host = store.get_or_none("email_imap_host")
    existing_user = store.get_or_none("email_user")
    if existing_host and existing_user:
        print(f"  Aktuelle Konfiguration: {existing_user} @ {existing_host}")
        overwrite = input("  Überschreiben? (j/N): ").strip().lower()
        if overwrite not in ("j", "ja", "y", "yes"):
            print("Abgebrochen.")
            return
        print()

    # Provider-Auswahl
    print("Bekannte Provider:")
    for i, (name, (host, port)) in enumerate(PROVIDERS.items(), 1):
        print(f"  {i}. {name:15s} ({host})")
    print(f"  0. Andere (manuell eingeben)")
    print()

    choice = input("Provider wählen (Nummer oder 0): ").strip()

    if choice == "0" or not choice.isdigit():
        host = input("IMAP-Host: ").strip()
        port_str = input("IMAP-Port (Standard: 993): ").strip()
        port = int(port_str) if port_str else 993
    else:
        idx = int(choice) - 1
        providers_list = list(PROVIDERS.values())
        if 0 <= idx < len(providers_list):
            host, port = providers_list[idx]
            print(f"  → {host}:{port}")
        else:
            print("Ungültige Auswahl.")
            return

    print()
    user = input("E-Mail-Adresse: ").strip()
    if not user:
        print("Keine E-Mail angegeben. Abgebrochen.")
        return

    password = input("Passwort: ").strip()
    if not password:
        print("Kein Passwort angegeben. Abgebrochen.")
        return

    # Verbindung testen
    print()
    print(f"Teste Verbindung zu {host}:{port} ...")

    try:
        import imaplib
        if port == 993:
            conn = imaplib.IMAP4_SSL(host, port)
        else:
            conn = imaplib.IMAP4(host, port)
        conn.login(user, password)

        # Anzahl Mails im Posteingang
        status, data = conn.select("INBOX", readonly=True)
        total = int(data[0]) if status == "OK" else "?"

        _, unseen_data = conn.search(None, "UNSEEN")
        unseen = len(unseen_data[0].split()) if unseen_data[0] else 0

        conn.logout()

        print(f"  Verbindung erfolgreich!")
        print(f"  Posteingang: {total} Mails ({unseen} ungelesen)")

    except imaplib.IMAP4.error as e:
        print(f"  Login fehlgeschlagen: {e}")
        print()
        print("Mögliche Ursachen:")
        print("  - Falsches Passwort")
        print("  - Bei Gmail: App-Passwort nötig (nicht das normale Passwort)")
        print("  - IMAP nicht aktiviert (Webmail → Einstellungen prüfen)")
        save_anyway = input("\nTrotzdem speichern? (j/N): ").strip().lower()
        if save_anyway not in ("j", "ja"):
            print("Abgebrochen.")
            return

    except Exception as e:
        print(f"  Verbindungsfehler: {e}")
        print(f"  Host '{host}' erreichbar? Port {port} korrekt?")
        save_anyway = input("\nTrotzdem speichern? (j/N): ").strip().lower()
        if save_anyway not in ("j", "ja"):
            print("Abgebrochen.")
            return

    # Speichern
    print()
    store.set("email_imap_host", host)
    store.set("email_imap_port", str(port))
    store.set("email_user", user)
    store.set("email_password", password)

    print("Credentials gespeichert im SecretStore (verschlüsselt).")
    print()
    print("Verwendung in Saleria:")
    print('  mails              → Ungelesene Mails')
    print('  mails 3            → Mails der letzten 3 Tage')
    print('  mail zusammenfassung → Detaillierte Auflistung')


if __name__ == "__main__":
    main()
