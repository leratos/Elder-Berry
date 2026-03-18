"""MailCommandHandler -- E-Mail-Commands (IMAP) als eigenstaendiger Handler.

Commands:
- mails / mails <N> / mail zusammenfassung
- mail suche <Begriff>
- mail anhang <ID>
- mail <ID> / mail #<ID>
"""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.tools.email_client import IMAPEmailClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Regex fuer Mails mit Tage-Angabe: "mails 5" (letzte 5 Tage)
MAILS_DAYS_PATTERN = re.compile(
    r"^mails?\s+(\d{1,2})$",
    re.IGNORECASE,
)

# Regex fuer Mail-Suche: "mail suche Rechnung", "suche die mail mit Rechnung von Alux"
MAIL_SEARCH_PATTERN = re.compile(
    r"(?:mails?\s+(?:suche?|finde?|such)\s+(.+)"
    r"|(?:suche?|finde?)\s+(?:mir\s+)?(?:bitte\s+)?(?:die\s+)?(?:mail|email|e-mail)\s+"
    r"(?:mit\s+(?:der\s+)?)?(?:von\s+)?(.+)"
    r"|(?:suche?|finde?)\s+(?:.+?\s+)?(?:in\s+)?(?:meinen?\s+)?(?:mails?|emails?)\s+"
    r"(?:nach\s+|von\s+)?(.+))",
    re.IGNORECASE,
)

# Regex fuer Mail-Anhang: "mail anhang 12345", "anhang von mail 12345"
MAIL_ATTACHMENT_PATTERN = re.compile(
    r"(?:mails?\s+anh(?:ang|änge?)\s+(\d+)"
    r"|anh(?:ang|änge?)\s+(?:von\s+)?(?:mail|email)\s+(\d+)"
    r"|mail\s+(\d+)\s+anh(?:ang|änge?))",
    re.IGNORECASE,
)

# Regex fuer Mail per ID: "mail 99", "mail #99", "fasse mail #99 zusammen", "zeig mail 99"
MAIL_ID_PATTERN = re.compile(
    r"(?:(?:fasse?|zeig|lies|hole?|öffne)\s+)?mail\s*#?(\d+)(?:\s+(?:zusammen|zusammenfassung|details|anzeigen))?$",
    re.IGNORECASE,
)


class MailCommandHandler(CommandHandler):
    """Handler fuer E-Mail-Commands (IMAP)."""

    def __init__(
        self,
        email_client: IMAPEmailClient | None = None,
    ) -> None:
        self._email_client = email_client

    # -- CommandHandler interface ------------------------------------------

    @property
    def simple_commands(self) -> set[str]:
        return {"mails"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        # MAIL_ID_PATTERN first (most specific), then attachment, search, days
        return [
            (MAIL_ID_PATTERN, "mail_by_id", False, False),
            (MAIL_ATTACHMENT_PATTERN, "mail_attachment", False, True),
            (MAIL_SEARCH_PATTERN, "mail_search", False, True),
            (MAILS_DAYS_PATTERN, "mails", False, False),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "mails": [
                "neue mails", "ungelesene mails", "emails",
                "e-mails", "posteingang",
            ],
            "mail_summary": [
                "mail zusammenfassung", "mails zusammenfassung",
                "fasse mails zusammen",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "mails" or command == "mail_summary":
            return self._cmd_mails(raw_text)
        if command == "mail_search":
            return self._cmd_mail_search(raw_text)
        if command == "mail_attachment":
            return self._cmd_mail_attachment(raw_text)
        if command == "mail_by_id":
            return self._cmd_mail_by_id(raw_text)

        return CommandResult(
            command=command, success=False,
            text=f"Unbekannter Mail-Command: {command}",
        )

    # -- Command implementations ------------------------------------------

    def _cmd_mails(self, raw_text: str) -> CommandResult:
        """E-Mails abfragen (ungelesen oder letzte N Tage)."""
        if not self._email_client:
            return CommandResult(
                command="mails",
                success=False,
                text="E-Mail nicht konfiguriert.\n"
                     "Setup: SecretStore().set('email_imap_host', 'imap.strato.de') etc.",
            )

        normalized = raw_text.strip().lower()
        match = MAILS_DAYS_PATTERN.match(normalized)

        try:
            if "zusammenfassung" in normalized:
                mails = self._email_client.get_unread(max_results=10)
                if not mails:
                    return CommandResult(
                        command="mails", success=True,
                        text="Keine ungelesenen E-Mails.",
                    )
                text = self._email_client.format_mails_detailed(mails)
                return CommandResult(command="mails", success=True, text=text)

            if match:
                days = int(match.group(1))
                mails = self._email_client.get_recent(days=days)
                label = f"E-Mails der letzten {days} Tage"
            else:
                mails = self._email_client.get_unread(max_results=15)
                label = "Ungelesene E-Mails"

            count = len(mails)
            text = f"{label} ({count}):\n{self._email_client.format_mails(mails)}"
            return CommandResult(command="mails", success=True, text=text)

        except Exception as e:
            logger.error("E-Mail-Abfrage fehlgeschlagen: %s", e)
            return CommandResult(
                command="mails",
                success=False,
                text=f"E-Mail-Fehler: {e}",
            )

    def _cmd_mail_search(self, raw_text: str) -> CommandResult:
        """E-Mails nach Betreff/Absender durchsuchen."""
        if not self._email_client:
            return CommandResult(
                command="mail_search", success=False,
                text="E-Mail nicht konfiguriert.",
            )

        match = MAIL_SEARCH_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(
                command="mail_search", success=False,
                text="Format: mail suche <Begriff>",
            )

        # Drei alternative Gruppen im Pattern
        query = (match.group(1) or match.group(2) or match.group(3) or "").strip()
        try:
            mails = self._email_client.search(query, max_results=10)
            if not mails:
                return CommandResult(
                    command="mail_search", success=True,
                    text=f"Keine Mails gefunden für '{query}'.",
                )

            # Kurzliste für den User
            text = f"Suche '{query}' ({len(mails)} Treffer):\n"
            text += self._email_client.format_mails(mails)
            # Detailliert für die Chat-History (LLM kann Body zusammenfassen)
            history = f"Suche '{query}' ({len(mails)} Treffer):\n"
            history += self._email_client.format_mails_detailed(mails)
            return CommandResult(
                command="mail_search", success=True,
                text=text, history_text=history,
            )

        except Exception as e:
            logger.error("Mail-Suche fehlgeschlagen: %s", e)
            return CommandResult(
                command="mail_search", success=False,
                text=f"Mail-Suche fehlgeschlagen: {e}",
            )

    def _cmd_mail_attachment(self, raw_text: str) -> CommandResult:
        """Anhänge einer E-Mail per UID abrufen und als temp-Dateien bereitstellen."""
        if not self._email_client:
            return CommandResult(
                command="mail_attachment", success=False,
                text="E-Mail nicht konfiguriert.",
            )

        match = MAIL_ATTACHMENT_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(
                command="mail_attachment", success=False,
                text="Format: mail anhang <Mail-ID>",
            )

        # Drei alternative Gruppen im Pattern
        msg_id = (match.group(1) or match.group(2) or match.group(3) or "").strip()
        if not msg_id:
            return CommandResult(
                command="mail_attachment", success=False,
                text="Keine Mail-ID angegeben.",
            )

        try:
            attachments = self._email_client.get_attachments(msg_id)

            if not attachments:
                return CommandResult(
                    command="mail_attachment", success=True,
                    text=f"Keine Anhänge in Mail #{msg_id}.",
                )

            # Anhänge als temp-Dateien speichern
            temp_paths: list[Path] = []
            names: list[str] = []
            for filename, data in attachments:
                suffix = Path(filename).suffix or ".bin"
                tmp = tempfile.NamedTemporaryFile(
                    suffix=suffix, prefix=f"mail_{msg_id}_",
                    delete=False,
                )
                tmp.write(data)
                tmp.close()
                temp_paths.append(Path(tmp.name))
                names.append(filename)

            text = (
                f"{len(attachments)} Anhang/Anhänge aus Mail #{msg_id}:\n"
                + "\n".join(f"  \U0001f4ce {n}" for n in names)
            )
            return CommandResult(
                command="mail_attachment",
                success=True,
                text=text,
                file_paths=temp_paths,
            )

        except Exception as e:
            logger.error("Mail-Anhang fehlgeschlagen (UID %s): %s", msg_id, e)
            return CommandResult(
                command="mail_attachment", success=False,
                text=f"Anhang abrufen fehlgeschlagen: {e}",
            )

    def _cmd_mail_by_id(self, raw_text: str) -> CommandResult:
        """Einzelne Mail per UID abrufen (Body als history_text für LLM-Kontext)."""
        if not self._email_client:
            return CommandResult(
                command="mail_by_id", success=False,
                text="E-Mail nicht konfiguriert.",
            )

        match = MAIL_ID_PATTERN.match(raw_text.strip().lower())
        if not match:
            return CommandResult(
                command="mail_by_id", success=False,
                text="Format: mail <ID> (z.B. mail 99 oder mail #99)",
            )

        msg_id = match.group(1)

        try:
            mail = self._email_client.get_by_uid(msg_id)

            if not mail:
                return CommandResult(
                    command="mail_by_id", success=False,
                    text=f"Mail #{msg_id} nicht gefunden.",
                )

            date_str = mail.date.strftime("%d.%m.%Y %H:%M") if mail.date else "?"
            short_text = (
                f"\U0001f4e7 Mail #{msg_id}:\n"
                f"  Von: {mail.sender}\n"
                f"  Datum: {date_str}\n"
                f"  Betreff: {mail.subject}"
            )

            # Vollständiger Body für LLM-Kontext (Chat-History)
            detail_text = (
                f"--- Mail #{msg_id} ---\n"
                f"Von: {mail.sender}\n"
                f"Datum: {date_str}\n"
                f"Betreff: {mail.subject}\n"
                f"Inhalt:\n{mail.body_preview}\n"
            )

            return CommandResult(
                command="mail_by_id",
                success=True,
                text=short_text,
                history_text=detail_text,
            )

        except Exception as e:
            logger.error("Mail UID %s abrufen fehlgeschlagen: %s", msg_id, e)
            return CommandResult(
                command="mail_by_id", success=False,
                text=f"Mail abrufen fehlgeschlagen: {e}",
            )
