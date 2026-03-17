"""IMAPEmailClient – E-Mails lesen via IMAP (Strato, GMX, Gmail, etc.).

Liest ungelesene E-Mails und bietet Zusammenfassungen.
Keine extra Dependencies – nutzt Python-Standardbibliothek (imaplib, email).

Verwendung:
    client = IMAPEmailClient(
        host="imap.strato.de",
        user="saleria@example.com",
        password="...",
    )
    mails = client.get_unread(max_results=10)
    mails = client.get_recent(days=3, max_results=20)
    summary = client.format_mails(mails)
"""
from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

# Maximale Textlänge pro Mail für Zusammenfassung
MAX_BODY_CHARS = 2000


@dataclass(frozen=True)
class EmailMessage:
    """Eine E-Mail-Nachricht (Zusammenfassung)."""

    subject: str
    """Betreff."""

    sender: str
    """Absender (Name <email> oder nur email)."""

    date: datetime | None
    """Datum der Mail."""

    body_preview: str
    """Textvorschau (gekürzt)."""

    is_unread: bool = True
    """True wenn ungelesen."""

    def format_short(self) -> str:
        """Einzeilige Darstellung."""
        date_str = self.date.strftime("%d.%m. %H:%M") if self.date else "?"
        sender_short = self.sender.split("<")[0].strip().strip('"') or self.sender
        if len(sender_short) > 25:
            sender_short = sender_short[:22] + "..."
        unread = "●" if self.is_unread else "○"
        return f"{unread} {date_str} | {sender_short} | {self.subject}"


class IMAPEmailClient:
    """IMAP E-Mail Client – liest Mails von beliebigem Provider.

    Verbindung wird pro Aufruf aufgebaut und geschlossen (kein Langzeit-Socket).
    """

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        port: int = 993,
        use_ssl: bool = True,
        mailbox: str = "INBOX",
    ) -> None:
        self._host = host
        self._user = user
        self._password = password
        self._port = port
        self._use_ssl = use_ssl
        self._mailbox = mailbox

    @classmethod
    def from_secret_store(cls, store: SecretStore) -> IMAPEmailClient:
        """Erstellt Client aus SecretStore-Einträgen.

        Erwartet: email_imap_host, email_user, email_password
        Optional: email_imap_port (default 993)
        """
        return cls(
            host=store.get("email_imap_host"),
            user=store.get("email_user"),
            password=store.get("email_password"),
            port=int(store.get_or_none("email_imap_port") or "993"),
        )

    def is_available(self) -> bool:
        """Prüft ob IMAP-Verbindung möglich ist."""
        try:
            conn = self._connect()
            conn.logout()
            return True
        except Exception as e:
            logger.debug("IMAP nicht verfügbar: %s", e)
            return False

    def get_unread(self, max_results: int = 10) -> list[EmailMessage]:
        """Holt ungelesene E-Mails.

        Args:
            max_results: Maximale Anzahl Mails.

        Returns:
            Liste von EmailMessage, neueste zuerst.
        """
        return self._fetch_mails("UNSEEN", max_results=max_results, is_unread=True)

    def get_recent(
        self, days: int = 3, max_results: int = 20,
    ) -> list[EmailMessage]:
        """Holt E-Mails der letzten N Tage.

        Args:
            days: Anzahl Tage zurück.
            max_results: Maximale Anzahl Mails.

        Returns:
            Liste von EmailMessage, neueste zuerst.
        """
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        return self._fetch_mails(
            f"SINCE {since}", max_results=max_results, is_unread=False,
        )

    def search(
        self, query: str, max_results: int = 10, days: int = 90,
    ) -> list[EmailMessage]:
        """Sucht E-Mails nach Betreff, Absender oder Body-Inhalt.

        Nutzt IMAP serverseitige Suche (SUBJECT + FROM + BODY als OR).
        BODY durchsucht den gesamten Mail-Text inkl. Signatur.

        Args:
            query: Suchbegriff (wird in SUBJECT, FROM und BODY gesucht).
            max_results: Maximale Anzahl Ergebnisse.
            days: Zeitraum in Tagen (default 90).

        Returns:
            Liste von EmailMessage, neueste zuerst.
        """
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")

        # Einzelne Wörter extrahieren für breitere Suche
        words = query.split()

        if len(words) == 1:
            # Ein Wort: einfache OR-Suche über alle Felder
            criteria = (
                f'(OR OR SUBJECT "{query}" FROM "{query}" BODY "{query}") '
                f'SINCE {since}'
            )
        else:
            # Mehrere Wörter: jedes Wort muss irgendwo vorkommen (OR über Felder)
            # "RK Bedachung" → Mails die "RK" UND "Bedachung" irgendwo enthalten
            word_criteria = []
            for w in words:
                word_criteria.append(
                    f'(OR OR SUBJECT "{w}" FROM "{w}" BODY "{w}")'
                )
            criteria = " ".join(word_criteria) + f" SINCE {since}"

        return self._fetch_mails(criteria, max_results=max_results, is_unread=False)

    def get_unread_count(self) -> int:
        """Anzahl ungelesener Mails."""
        try:
            conn = self._connect()
            conn.select(self._mailbox, readonly=True)
            _, data = conn.search(None, "UNSEEN")
            conn.logout()
            ids = data[0].split() if data[0] else []
            return len(ids)
        except Exception as e:
            logger.error("IMAP unread count fehlgeschlagen: %s", e)
            return -1

    def format_mails(self, mails: list[EmailMessage]) -> str:
        """Formatiert eine Liste von Mails als Text."""
        if not mails:
            return "Keine E-Mails."

        lines = [f"{len(mails)} E-Mail(s):"]
        for m in mails:
            lines.append(f"  {m.format_short()}")
        return "\n".join(lines)

    def format_mails_detailed(self, mails: list[EmailMessage]) -> str:
        """Detaillierte Formatierung mit Body-Preview (für LLM-Zusammenfassung)."""
        if not mails:
            return "Keine E-Mails."

        parts = []
        for i, m in enumerate(mails, 1):
            date_str = m.date.strftime("%d.%m.%Y %H:%M") if m.date else "?"
            part = (
                f"--- Mail {i} ---\n"
                f"Von: {m.sender}\n"
                f"Datum: {date_str}\n"
                f"Betreff: {m.subject}\n"
                f"Inhalt: {m.body_preview}\n"
            )
            parts.append(part)
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Interne Methoden
    # ------------------------------------------------------------------

    def _connect(self) -> imaplib.IMAP4_SSL | imaplib.IMAP4:
        """Erstellt IMAP-Verbindung und loggt ein."""
        if self._use_ssl:
            conn = imaplib.IMAP4_SSL(self._host, self._port)
        else:
            conn = imaplib.IMAP4(self._host, self._port)
        conn.login(self._user, self._password)
        return conn

    def _fetch_mails(
        self,
        search_criteria: str,
        max_results: int,
        is_unread: bool,
    ) -> list[EmailMessage]:
        """Generische Mail-Abfrage.

        Args:
            search_criteria: IMAP-Suchkriterium (z.B. "UNSEEN", "SINCE 01-Jan-2026").
            max_results: Max. Anzahl.
            is_unread: Flag für EmailMessage.is_unread.

        Returns:
            Liste von EmailMessage, neueste zuerst.
        """
        try:
            conn = self._connect()
            conn.select(self._mailbox, readonly=True)

            _, data = conn.search(None, search_criteria)
            msg_ids = data[0].split() if data[0] else []

            # Neueste zuerst, limitieren
            msg_ids = msg_ids[-max_results:]
            msg_ids.reverse()

            mails = []
            for msg_id in msg_ids:
                try:
                    _, msg_data = conn.fetch(msg_id, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    parsed = self._parse_email(raw, is_unread=is_unread)
                    if parsed:
                        mails.append(parsed)
                except Exception as e:
                    logger.debug("Mail %s parsen fehlgeschlagen: %s", msg_id, e)

            conn.logout()
            return mails

        except Exception as e:
            logger.error("IMAP fetch fehlgeschlagen: %s", e)
            return []

    @staticmethod
    def _parse_email(raw: bytes, is_unread: bool = True) -> EmailMessage | None:
        """Parst eine rohe E-Mail in ein EmailMessage-Objekt."""
        msg = email.message_from_bytes(raw)

        # Subject dekodieren
        subject = IMAPEmailClient._decode_header(msg.get("Subject", ""))
        sender = IMAPEmailClient._decode_header(msg.get("From", ""))

        # Datum parsen
        date_str = msg.get("Date", "")
        date = None
        if date_str:
            try:
                parsed = email.utils.parsedate_to_datetime(date_str)
                date = parsed
            except Exception:
                pass

        # Body extrahieren (Text/Plain bevorzugt)
        body = IMAPEmailClient._extract_body(msg)

        return EmailMessage(
            subject=subject or "(Kein Betreff)",
            sender=sender or "(Unbekannt)",
            date=date,
            body_preview=body[:MAX_BODY_CHARS] if body else "",
            is_unread=is_unread,
        )

    @staticmethod
    def _decode_header(raw: str) -> str:
        """Dekodiert MIME-encodierte Header (Subject, From)."""
        if not raw:
            return ""
        parts = email.header.decode_header(raw)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(part)
        return " ".join(decoded)

    @staticmethod
    def _extract_body(msg: email.message.Message) -> str:
        """Extrahiert den Text-Body aus einer E-Mail.

        Bevorzugt text/plain, Fallback auf text/html (Tags entfernt).
        """
        if msg.is_multipart():
            text_parts = []
            html_parts = []
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    text_parts.append(part)
                elif content_type == "text/html":
                    html_parts.append(part)

            # text/plain bevorzugt
            target = text_parts[0] if text_parts else (html_parts[0] if html_parts else None)
            if target:
                return IMAPEmailClient._decode_payload(target)
            return ""
        else:
            return IMAPEmailClient._decode_payload(msg)

    @staticmethod
    def _decode_payload(part: email.message.Message) -> str:
        """Dekodiert den Payload eines MIME-Parts."""
        payload = part.get_payload(decode=True)
        if not payload:
            return ""

        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")

        # HTML-Tags entfernen wenn nötig
        if part.get_content_type() == "text/html":
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

        return text.strip()
