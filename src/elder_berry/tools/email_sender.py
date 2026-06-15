"""EmailSender – E-Mails senden via SMTP (Strato, GMX, Gmail, etc.).

Sendet Antworten auf bestehende E-Mails mit korrekten Reply-Headern.
Keine extra Dependencies – nutzt Python-Standardbibliothek (smtplib, email).
"""

from __future__ import annotations

import email.message
import logging
import smtplib
from dataclasses import dataclass
from email.utils import formataddr
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


def _scrub_header(value: str) -> str:
    """Phase 100-B (D3): entfernt CR/LF aus Header-Werten.

    Belt-and-Suspenders gegen Header-Injection: die stdlib foldet zwar, aber
    angreiferkontrollierte Werte (Betreff aus eingehender Mail, ab Phase 100-C
    der konfigurierbare Anzeigename) sollen keine Steuerzeichen in die Header
    tragen.
    """
    return value.replace("\r", " ").replace("\n", " ").strip()


@dataclass(frozen=True)
class SentEmail:
    """Ergebnis eines gesendeten Emails."""

    to: str
    subject: str
    success: bool
    error: str = ""
    raw_msg: bytes = b""


class EmailSender:
    """SMTP E-Mail Client – sendet Mails über beliebigen Provider.

    Verbindung wird pro Aufruf aufgebaut und geschlossen (kein Langzeit-Socket).
    """

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        port: int = 465,
        use_ssl: bool = True,
        sender_name: str = "Saleria",
        signature: str = "",
    ) -> None:
        self._host = host
        self._user = user
        self._password = password
        self._port = port
        self._use_ssl = use_ssl
        self._sender_name = sender_name
        # Phase 100-C: optionale Signatur, wird unter den Body gehaengt.
        self._signature = signature

    @classmethod
    def from_secret_store(cls, store: SecretStore) -> EmailSender:
        """Erstellt Client aus SecretStore-Einträgen.

        Erwartet: email_user, email_password
        Optional: smtp_host (default smtp.strato.de),
                  smtp_port (default 465),
                  email_sender_name (default "Saleria"),
                  email_signature (Phase 100-C)

        Phase 100-A (D1): liest smtp_host/smtp_port -- die Keys, die
        Setup-Wizard, Settings-Dashboard und scripts/setup_email.py
        tatsaechlich schreiben (secrets_registry.py:204/211). Frueher
        wurden hier email_smtp_host/email_smtp_port gelesen, die nirgends
        geschrieben werden -> jeder Nicht-Strato-Nutzer fiel still auf den
        smtp.strato.de-Fallback zurueck.

        Phase 100-A Folge (PR #311 Codex P2): use_ssl wird aus dem Port
        abgeleitet -- Port 465 = implizites SSL (SMTP_SSL), sonst (587/25/...)
        STARTTLS. Spiegelt die Heuristik des Setup-Tests
        (web/setup_tests.py: SMTP_SSL nur bei 465). Ohne das wuerde ein
        587-Setup (Outlook/Gmail) nach dem D1-Fix faelschlich SMTP_SSL(587)
        versuchen und beim Senden scheitern, obwohl der Setup-Test gruen ist.
        """
        port = int(store.get_or_none("smtp_port") or "465")
        return cls(
            host=store.get_or_none("smtp_host") or "smtp.strato.de",
            user=store.get("email_user"),
            password=store.get("email_password"),
            port=port,
            use_ssl=port == 465,
            sender_name=store.get_or_none("email_sender_name") or "Saleria",
            signature=store.get_or_none("email_signature") or "",
        )

    def is_available(self) -> bool:
        """Prüft ob SMTP-Verbindung möglich ist."""
        try:
            conn = self._connect()
            conn.quit()
            return True
        except Exception as e:
            logger.debug("SMTP nicht verfügbar: %s", e)
            return False

    def send_reply(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str = "",
        references: str = "",
        cc: str = "",
    ) -> SentEmail:
        """Sendet eine Antwort-Email mit korrekten Threading-Headern.

        Args:
            to: Empfänger-Adresse.
            subject: Betreff (sollte mit "Re: " beginnen).
            body: Klartext-Body der Antwort.
            in_reply_to: Message-ID der Original-Mail (für Threading).
            references: References-Header der Original-Mail (für Threading).
            cc: Optionale CC-Adresse(n), kommagetrennt.

        Returns:
            SentEmail mit Ergebnis.
        """
        try:
            msg = self._build_reply_message(
                to=to,
                subject=subject,
                body=body,
                in_reply_to=in_reply_to,
                references=references,
                cc=cc,
            )
            conn = self._connect()
            conn.send_message(msg)
            conn.quit()
            logger.info("Email gesendet an %s: %s", to, subject)
            return SentEmail(
                to=to,
                subject=subject,
                success=True,
                raw_msg=msg.as_bytes(),
            )
        except smtplib.SMTPAuthenticationError as e:
            logger.error("SMTP Auth-Fehler: %s", e)
            return SentEmail(
                to=to,
                subject=subject,
                success=False,
                error=f"Authentifizierung fehlgeschlagen: {e}",
            )
        except smtplib.SMTPException as e:
            logger.error("SMTP-Fehler beim Senden: %s", e)
            return SentEmail(
                to=to,
                subject=subject,
                success=False,
                error=f"SMTP-Fehler: {e}",
            )
        except OSError as e:
            logger.error("Verbindungsfehler beim Senden: %s", e)
            return SentEmail(
                to=to,
                subject=subject,
                success=False,
                error=f"Verbindungsfehler: {e}",
            )

    def _connect(self) -> smtplib.SMTP_SSL | smtplib.SMTP:
        """Erstellt SMTP-Verbindung und loggt ein."""
        conn: smtplib.SMTP_SSL | smtplib.SMTP
        if self._use_ssl:
            conn = smtplib.SMTP_SSL(self._host, self._port, timeout=30)
        else:
            conn = smtplib.SMTP(self._host, self._port, timeout=30)
            conn.starttls()
        conn.login(self._user, self._password)
        return conn

    def _build_reply_message(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str,
        references: str,
        cc: str,
    ) -> email.message.EmailMessage:
        """Baut eine RFC-konforme Reply-Email zusammen.

        Setzt korrekte Header für Email-Threading:
        - In-Reply-To: Message-ID der Original-Mail
        - References: Message-ID-Kette für Thread-Ansicht
        - From: "Saleria <user@domain>"
        """
        msg = email.message.EmailMessage()
        # Phase 100-C Folge (PR #311 Codex P2): formataddr quotet einen
        # Anzeigenamen mit RFC-Sonderzeichen (Komma, <>, ...) korrekt, sonst
        # zerlegt send_message den From-Header in eine Adressliste und nimmt
        # den falschen Envelope-Sender. CR/LF vorher rausscrubben.
        msg["From"] = formataddr((_scrub_header(self._sender_name), self._user))
        msg["To"] = _scrub_header(to)
        msg["Subject"] = _scrub_header(subject)

        if cc:
            msg["Cc"] = _scrub_header(cc)

        # Threading-Header für korrekte Thread-Ansicht im Mail-Client
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references
        elif in_reply_to:
            # Fallback: References = In-Reply-To wenn keine Kette vorhanden
            msg["References"] = in_reply_to

        # Phase 100-C: Signatur (statischer Config-Text, NICHT vom LLM erzeugt)
        # mit RFC-3676-Delimiter "-- \n" anhaengen. Kein neuer Injection-Vektor,
        # da nicht aus Mail-Inhalt abgeleitet.
        full_body = f"{body}\n\n-- \n{self._signature}" if self._signature else body
        msg.set_content(full_body, charset="utf-8")
        return msg
