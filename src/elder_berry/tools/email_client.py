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
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


def _uid(
    conn: imaplib.IMAP4,
    command: str,
    *args: object,
) -> tuple[str, list[Any]]:
    """imaplib.IMAP4.uid()-Wrapper (Pattern §10.8 aus Phase-76c-Konzept).

    stdlib-Stub deklariert *args: AnyStr (TypeVar-Constraint, alle Args
    muessen einheitlich str ODER einheitlich bytes sein). CPythons
    echte Implementation in Lib/imaplib.py akzeptiert mixed
    str/bytes/None und encoded selbst (RFC 3501 §6.4.4 erlaubt
    SEARCH None criteria fuer "kein CHARSET"). Kein Bug-Fix noetig --
    runtime-Semantik ist seit Python 2 stabil.
    """
    return conn.uid(command, *args)  # type: ignore[arg-type]


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

    msg_id: str = ""
    """IMAP UID für späteren Zugriff (Anhänge, Details)."""

    message_id: str = ""
    """RFC Message-ID Header (für In-Reply-To bei Replies)."""

    references: str = ""
    """References Header (Message-ID-Kette für Threading)."""

    def format_short(self) -> str:
        """Einzeilige Darstellung."""
        date_str = self.date.strftime("%d.%m. %H:%M") if self.date else "?"
        sender_short = self.sender.split("<")[0].strip().strip('"') or self.sender
        if len(sender_short) > 25:
            sender_short = sender_short[:22] + "..."
        unread = "●" if self.is_unread else "○"
        id_suffix = f" [#{self.msg_id}]" if self.msg_id else ""
        return f"{unread} {date_str} | {sender_short} | {self.subject}{id_suffix}"


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
        self,
        days: int = 3,
        max_results: int = 20,
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
            f"SINCE {since}",
            max_results=max_results,
            is_unread=False,
        )

    def search(
        self,
        query: str,
        max_results: int = 10,
        days: int = 90,
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
                f'(OR OR SUBJECT "{query}" FROM "{query}" BODY "{query}") SINCE {since}'
            )
        else:
            # Mehrere Wörter: jedes Wort muss irgendwo vorkommen (OR über Felder)
            # "RK Bedachung" → Mails die "RK" UND "Bedachung" irgendwo enthalten
            word_criteria = []
            for w in words:
                word_criteria.append(f'(OR OR SUBJECT "{w}" FROM "{w}" BODY "{w}")')
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
            id_info = f" (ID: {m.msg_id})" if m.msg_id else ""
            part = (
                f"--- Mail {i}{id_info} ---\n"
                f"Von: {m.sender}\n"
                f"Datum: {date_str}\n"
                f"Betreff: {m.subject}\n"
                f"Inhalt: {m.body_preview}\n"
            )
            parts.append(part)
        return "\n".join(parts)

    def get_attachments(
        self,
        msg_id: str,
    ) -> list[tuple[str, bytes]]:
        """Holt Anhänge einer E-Mail per IMAP UID.

        Args:
            msg_id: IMAP UID der Mail.

        Returns:
            Liste von (filename, bytes)-Tupeln. Leer wenn keine Anhänge.

        Raises:
            RuntimeError: Wenn Mail nicht gefunden oder Verbindung fehlschlägt.
        """
        try:
            conn = self._connect()
            conn.select(self._mailbox, readonly=True)

            uid_bytes = msg_id.encode() if isinstance(msg_id, str) else msg_id
            _, msg_data = _uid(conn, "fetch", uid_bytes, "(RFC822)")

            if not msg_data or not msg_data[0]:
                conn.logout()
                raise RuntimeError(f"Mail mit UID {msg_id} nicht gefunden")

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            conn.logout()

            attachments: list[tuple[str, bytes]] = []
            for part in msg.walk():
                disposition = part.get("Content-Disposition", "")
                if "attachment" not in disposition:
                    continue

                filename = part.get_filename()
                if filename:
                    # MIME-encodierte Dateinamen dekodieren
                    filename = self._decode_header(filename)
                else:
                    filename = f"attachment_{len(attachments) + 1}"

                payload = cast("bytes | None", part.get_payload(decode=True))
                if payload:
                    attachments.append((filename, payload))

            return attachments

        except RuntimeError:
            raise
        except Exception as e:
            logger.error("Anhänge abrufen fehlgeschlagen (UID %s): %s", msg_id, e)
            raise RuntimeError(f"Anhänge abrufen fehlgeschlagen: {e}") from e

    def get_by_uid(self, msg_id: str) -> EmailMessage | None:
        """Holt eine einzelne Mail per IMAP UID (vollständiger Body).

        Args:
            msg_id: IMAP UID der Mail.

        Returns:
            EmailMessage mit vollem Body oder None wenn nicht gefunden.
        """
        try:
            conn = self._connect()
            conn.select(self._mailbox, readonly=True)

            uid_bytes = msg_id.encode() if isinstance(msg_id, str) else msg_id
            _, msg_data = _uid(conn, "fetch", uid_bytes, "(RFC822)")

            if not msg_data or not msg_data[0]:
                conn.logout()
                return None

            raw = msg_data[0][1]
            conn.logout()

            return self._parse_email(raw, is_unread=False, msg_id=msg_id)

        except Exception as e:
            logger.error("Mail UID %s abrufen fehlgeschlagen: %s", msg_id, e)
            return None

    def delete(self, msg_id: str) -> bool:
        """Löscht eine E-Mail per IMAP UID.

        Setzt das \\Deleted-Flag und führt EXPUNGE aus.

        Args:
            msg_id: IMAP UID der Mail.

        Returns:
            True wenn erfolgreich gelöscht.

        Raises:
            RuntimeError: Bei Verbindungs- oder IMAP-Fehlern.
        """
        try:
            conn = self._connect()
            conn.select(self._mailbox, readonly=False)

            uid_bytes = msg_id.encode() if isinstance(msg_id, str) else msg_id
            result, _ = _uid(conn, "store", uid_bytes, "+FLAGS", "(\\Deleted)")

            if result != "OK":
                conn.logout()
                raise RuntimeError(
                    f"IMAP STORE fehlgeschlagen für UID {msg_id}: {result}"
                )

            conn.expunge()
            conn.logout()
            logger.info("Mail UID %s gelöscht", msg_id)
            return True

        except RuntimeError:
            raise
        except Exception as e:
            logger.error("Mail UID %s löschen fehlgeschlagen: %s", msg_id, e)
            raise RuntimeError(f"Mail löschen fehlgeschlagen: {e}") from e

    def copy_to_sent_folder(
        self,
        msg_bytes: bytes,
        sent_folder: str = "",
    ) -> bool:
        """Kopiert eine gesendete E-Mail in den IMAP Gesendet-Ordner.

        Nutzt IMAP APPEND um die Nachricht mit \\Seen-Flag abzulegen.
        Wenn kein sent_folder angegeben wird, wird der Ordner automatisch
        über XLIST/LIST mit \\Sent-Attribut ermittelt.

        Args:
            msg_bytes: Die vollständige RFC822-Nachricht als Bytes.
            sent_folder: IMAP-Ordnername (z.B. "Sent", "INBOX.Sent").
                         Leer = automatische Erkennung.

        Returns:
            True wenn erfolgreich kopiert.
        """
        try:
            conn = self._connect()

            folder = sent_folder or self._detect_sent_folder(conn)
            if not folder:
                logger.warning(
                    "Gesendet-Ordner nicht gefunden – Mail wird nicht in Sent kopiert"
                )
                conn.logout()
                return False

            result, _ = conn.append(
                folder,
                "\\Seen",
                None,
                msg_bytes,
            )
            conn.logout()

            if result == "OK":
                logger.info(
                    "Mail in Gesendet-Ordner '%s' kopiert",
                    folder,
                )
                return True

            logger.warning(
                "IMAP APPEND in '%s' fehlgeschlagen: %s",
                folder,
                result,
            )
            return False

        except Exception as e:
            logger.warning(
                "Kopie in Gesendet-Ordner fehlgeschlagen: %s",
                e,
            )
            return False

    @staticmethod
    def _detect_sent_folder(
        conn: imaplib.IMAP4_SSL | imaplib.IMAP4,
    ) -> str:
        """Erkennt den Gesendet-Ordner über IMAP LIST-Attribute.

        Sucht nach Ordnern mit \\Sent-Attribut (RFC 6154 / SPECIAL-USE).
        Fallback auf bekannte Namen: Sent, INBOX.Sent, Gesendet.

        Returns:
            Ordnername oder leerer String wenn nicht gefunden.
        """
        # Versuch 1: XLIST / LIST mit Special-Use-Attributen
        try:
            _, data = conn.list()
            if data:
                for item in data:
                    if not item:
                        continue
                    line = (
                        item.decode("utf-8", errors="replace")
                        if isinstance(
                            item,
                            bytes,
                        )
                        else str(item)
                    )
                    if "\\Sent" in line:
                        # Format: '(\\Sent \\HasNoChildren) "/" "Sent"'
                        # Ordnername ist das letzte Element in Anführungszeichen
                        parts = line.rsplit('"', 2)
                        if len(parts) >= 2:
                            return parts[-2]
        except Exception as e:
            logger.debug("IMAP LIST für Sent-Erkennung fehlgeschlagen: %s", e)

        # Versuch 2: Bekannte Ordnernamen direkt prüfen
        for candidate in (
            "Sent",
            "INBOX.Sent",
            "Gesendet",
            "Sent Items",
            "Sent Messages",
        ):
            try:
                result, _ = conn.select(candidate, readonly=True)
                if result == "OK":
                    conn.close()
                    return candidate
            except Exception:
                continue

        return ""

    # ------------------------------------------------------------------
    # Interne Methoden
    # ------------------------------------------------------------------

    def _connect(self) -> imaplib.IMAP4_SSL | imaplib.IMAP4:
        """Erstellt IMAP-Verbindung und loggt ein."""
        conn: imaplib.IMAP4_SSL | imaplib.IMAP4
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

            # UID-basierte Suche (stabiler als Sequenznummern).
            # IMAP SEARCH ist standardmäßig ASCII; bei Umlauten (z.B.
            # "Müller", "über") muss CHARSET UTF-8 + bytes-Criterion
            # verwendet werden, sonst UnicodeEncodeError in imaplib.
            try:
                search_criteria.encode("ascii")
                _, data = _uid(conn, "search", None, search_criteria)
            except UnicodeEncodeError:
                _, data = _uid(
                    conn,
                    "search",
                    "CHARSET",
                    "UTF-8",
                    search_criteria.encode("utf-8"),
                )
            uids = data[0].split() if data[0] else []

            # Neueste zuerst, limitieren
            uids = uids[-max_results:]
            uids.reverse()

            mails = []
            for uid in uids:
                try:
                    _, msg_data = _uid(conn, "fetch", uid, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
                    parsed = self._parse_email(
                        raw,
                        is_unread=is_unread,
                        msg_id=uid_str,
                    )
                    if parsed:
                        mails.append(parsed)
                except Exception as e:
                    logger.debug("Mail UID %s parsen fehlgeschlagen: %s", uid, e)

            conn.logout()
            return mails

        except Exception as e:
            logger.error("IMAP fetch fehlgeschlagen: %s", e)
            return []

    @staticmethod
    def _parse_email(
        raw: bytes,
        is_unread: bool = True,
        msg_id: str = "",
    ) -> EmailMessage | None:
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

        # Reply-Header für Threading extrahieren
        message_id_header = msg.get("Message-ID", "").strip()
        references_header = msg.get("References", "").strip()

        return EmailMessage(
            subject=subject or "(Kein Betreff)",
            sender=sender or "(Unbekannt)",
            date=date,
            body_preview=body[:MAX_BODY_CHARS] if body else "",
            is_unread=is_unread,
            msg_id=msg_id,
            message_id=message_id_header,
            references=references_header,
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
            target = (
                text_parts[0] if text_parts else (html_parts[0] if html_parts else None)
            )
            if target:
                return IMAPEmailClient._decode_payload(target)
            return ""
        else:
            return IMAPEmailClient._decode_payload(msg)

    @staticmethod
    def _decode_payload(part: email.message.Message) -> str:
        """Dekodiert den Payload eines MIME-Parts."""
        # get_payload(decode=True) returnt bytes laut docs (oder None
        # bei multipart). Stub deklariert Message[str,str] | Any | bytes
        # weil get_payload() ueberladen ist; mit decode=True ist nur
        # bytes/None moeglich.
        payload = cast("bytes | None", part.get_payload(decode=True))
        if not payload:
            return ""

        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")

        # HTML-Tags entfernen wenn nötig
        if part.get_content_type() == "text/html":
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

        return text.strip()
