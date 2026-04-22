"""EmailSender – E-Mails senden via SMTP (Strato, GMX, Gmail, etc.).

Sendet Antworten auf bestehende E-Mails mit korrekten Reply-Headern.
Keine extra Dependencies – nutzt Python-Standardbibliothek (smtplib, email).
"""
from __future__ import annotations

import email.message
import logging
import smtplib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._host = host
        self._user = user
        self._password = password
        self._port = port
        self._use_ssl = use_ssl
        self._sender_name = sender_name

    @classmethod
    def from_secret_store(cls, store: SecretStore) -> EmailSender:
        """Erstellt Client aus SecretStore-Einträgen.

        Erwartet: email_user, email_password
        Optional: email_smtp_host (default smtp.strato.de),
                  email_smtp_port (default 465)
        """
        return cls(
            host=store.get_or_none("email_smtp_host") or "smtp.strato.de",
            user=store.get("email_user"),
            password=store.get("email_password"),
            port=int(store.get_or_none("email_smtp_port") or "465"),
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
                to=to, subject=subject, success=True,
                raw_msg=msg.as_bytes(),
            )
        except smtplib.SMTPAuthenticationError as e:
            logger.error("SMTP Auth-Fehler: %s", e)
            return SentEmail(
                to=to, subject=subject, success=False,
                error=f"Authentifizierung fehlgeschlagen: {e}",
            )
        except smtplib.SMTPException as e:
            logger.error("SMTP-Fehler beim Senden: %s", e)
            return SentEmail(
                to=to, subject=subject, success=False,
                error=f"SMTP-Fehler: {e}",
            )
        except OSError as e:
            logger.error("Verbindungsfehler beim Senden: %s", e)
            return SentEmail(
                to=to, subject=subject, success=False,
                error=f"Verbindungsfehler: {e}",
            )

    def _connect(self) -> smtplib.SMTP_SSL | smtplib.SMTP:
        """Erstellt SMTP-Verbindung und loggt ein."""
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
        msg["From"] = f"{self._sender_name} <{self._user}>"
        msg["To"] = to
        msg["Subject"] = subject

        if cc:
            msg["Cc"] = cc

        # Threading-Header für korrekte Thread-Ansicht im Mail-Client
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references
        elif in_reply_to:
            # Fallback: References = In-Reply-To wenn keine Kette vorhanden
            msg["References"] = in_reply_to

        msg.set_content(body, charset="utf-8")
        return msg
