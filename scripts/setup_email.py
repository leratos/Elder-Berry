#!/usr/bin/env python3
"""Einrichtung der E-Mail-Credentials für Saleria (IMAP + SMTP).

Verwendung:
    python scripts/setup_email.py

Fragt interaktiv nach IMAP-/SMTP-Host, Benutzername und Passwort,
testet die Verbindungen und speichert alles im SecretStore (verschlüsselt).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from elder_berry.core.secret_store import SecretStore

# Bekannte Provider mit Default-Einstellungen (IMAP-Host, IMAP-Port, SMTP-Host, SMTP-Port)
PROVIDERS = {
    "strato": ("imap.strato.de", 993, "smtp.strato.de", 465),
    "gmx": ("imap.gmx.net", 993, "mail.gmx.net", 465),
    "web.de": ("imap.web.de", 993, "smtp.web.de", 465),
    "gmail": ("imap.gmail.com", 993, "smtp.gmail.com", 465),
    "outlook": ("outlook.office365.com", 993, "smtp.office365.com", 587),
    "t-online": ("secureimap.t-online.de", 993, "securesmtp.t-online.de", 465),
    "ionos": ("imap.ionos.de", 993, "smtp.ionos.de", 465),
    "posteo": ("posteo.de", 993, "posteo.de", 465),
    "mailbox.org": ("imap.mailbox.org", 993, "smtp.mailbox.org", 465),
}


def main() -> None:
    print("═" * 50)
    print("  Elder-Berry – E-Mail Setup (IMAP + SMTP)")
    print("═" * 50)
    print()

    store = SecretStore()

    # Bestehende Konfiguration anzeigen
    existing_host = store.get_or_none("email_imap_host")
    existing_user = store.get_or_none("email_user")
    existing_smtp = store.get_or_none("smtp_host")
    if existing_host and existing_user:
        print(f"  Aktuelle Konfiguration: {existing_user} @ {existing_host}")
        if existing_smtp:
            print(f"  SMTP: {existing_smtp}")
        overwrite = input("  Überschreiben? (j/N): ").strip().lower()
        if overwrite not in ("j", "ja", "y", "yes"):
            print("Abgebrochen.")
            return
        print()

    # Provider-Auswahl
    print("Bekannte Provider:")
    for i, (name, (imap_h, _ip, smtp_h, _sp)) in enumerate(PROVIDERS.items(), 1):
        print(f"  {i}. {name:15s} (IMAP: {imap_h}, SMTP: {smtp_h})")
    print(f"  0. Andere (manuell eingeben)")
    print()

    choice = input("Provider wählen (Nummer oder 0): ").strip()

    if choice == "0" or not choice.isdigit():
        host = input("IMAP-Host: ").strip()
        port_str = input("IMAP-Port (Standard: 993): ").strip()
        port = int(port_str) if port_str else 993
        smtp_host = input("SMTP-Host: ").strip()
        smtp_port_str = input("SMTP-Port (Standard: 465): ").strip()
        smtp_port = int(smtp_port_str) if smtp_port_str else 465
    else:
        idx = int(choice) - 1
        providers_list = list(PROVIDERS.values())
        if 0 <= idx < len(providers_list):
            host, port, smtp_host, smtp_port = providers_list[idx]
            print(f"  → IMAP: {host}:{port}")
            print(f"  → SMTP: {smtp_host}:{smtp_port}")
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

    # SMTP testen
    print()
    print(f"Teste SMTP-Verbindung zu {smtp_host}:{smtp_port} ...")

    smtp_ok = False
    try:
        import smtplib

        if smtp_port == 465:
            smtp_conn = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        else:
            smtp_conn = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            smtp_conn.starttls()
        smtp_conn.login(user, password)
        smtp_conn.quit()
        print("  SMTP-Verbindung erfolgreich!")
        smtp_ok = True

    except smtplib.SMTPAuthenticationError as e:
        print(f"  SMTP-Login fehlgeschlagen: {e}")
        print()
        print("Mögliche Ursachen:")
        print("  - Falsches Passwort")
        print("  - Bei Gmail: App-Passwort nötig")
        print("  - SMTP-Zugang nicht aktiviert")

    except Exception as e:
        print(f"  SMTP-Verbindungsfehler: {e}")
        print(f"  Host '{smtp_host}' erreichbar? Port {smtp_port} korrekt?")

    if not smtp_ok:
        save_smtp = input("\nSMTP trotzdem speichern? (j/N): ").strip().lower()
        if save_smtp not in ("j", "ja"):
            smtp_host = ""
            smtp_port = 0
            print("  SMTP wird nicht gespeichert (E-Mail-Antworten deaktiviert).")

    # Speichern
    print()
    store.set("email_imap_host", host)
    store.set("email_imap_port", str(port))
    store.set("email_user", user)
    store.set("email_password", password)

    if smtp_host:
        store.set("smtp_host", smtp_host)
        store.set("smtp_port", str(smtp_port))

    print("Credentials gespeichert im SecretStore (verschlüsselt).")
    print()
    print("Verwendung in Saleria:")
    print("  mails                → Ungelesene Mails")
    print("  mails 3              → Mails der letzten 3 Tage")
    print("  mail zusammenfassung → Detaillierte Auflistung")
    if smtp_host:
        print("  antworte auf mail 3 ...  → E-Mail-Antwort mit Draft")
        print("  mail antwort 3 sage ... → Antwort generieren lassen")


if __name__ == "__main__":
    main()
