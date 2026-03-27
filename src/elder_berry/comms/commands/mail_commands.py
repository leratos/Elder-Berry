"""MailCommandHandler -- E-Mail-Commands (IMAP + SMTP Reply) als eigenstaendiger Handler.

Commands:
- mails / mails <N> / mail zusammenfassung
- mail suche <Begriff>
- mail anhang <ID>
- mail <ID> / mail #<ID>
- antworte auf #<ID> <Anweisung>  (Phase 28: Email-Reply)
"""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.core.anthropic_client import AnthropicClient
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

# Regex für Mail-Antwort (Phase 28):
# "antworte auf #123 positiv", "antworte auf mail 456 dass es nicht geht"
# "beantworte mail #123 mit einer zusage", "mail #123 antworten: text"
MAIL_REPLY_PATTERN = re.compile(
    r"(?:antworte?\s+(?:auf\s+)?(?:mail\s*)?#?(\d+)\s+(.*)"
    r"|(?:gib|schreib)\s+(?:auf\s+)?(?:die\s+)?mail\s*#?(\d+)\s+(?:eine?\s+)?(.*)"
    r"|(?:beantworte?)\s+(?:die\s+)?mail\s*#?(\d+)\s+(?:mit\s+)?(.*)"
    r"|mail\s*#?(\d+)\s+(?:antworten|beantworten)(?::\s*|\s+)(.*))",
    re.IGNORECASE | re.DOTALL,
)

# Regex für Draft-Änderung (intern von Bridge genutzt):
# Bridge schickt "#<id> <neue anweisung>"
MAIL_REPLY_MODIFY_PATTERN = re.compile(
    r"^#(\d+)\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)

# System-Prompt für Email-Draft-Generierung via Claude API
EMAIL_SYSTEM_PROMPT = """Du bist Saleria, eine virtuelle Assistentin.
Du schreibst E-Mail-Antworten im Auftrag deines Nutzers.

Regeln:
- Schreibe auf Deutsch, es sei denn die Original-Mail ist auf Englisch
- Passe den Formalitätsgrad an die Original-Mail an
  (förmlich → förmlich, locker → locker)
- Keine Signatur einfügen (wird vom Mail-Client ergänzt)
- Keine Betreffzeile generieren (wird automatisch gesetzt)
- Halte die Antwort knapp und auf den Punkt
- Beginne NICHT mit "Betreff:" oder "An:" – nur den reinen Antworttext
- Wenn der Nutzer "positiv" sagt: freundliche Zusage
- Wenn der Nutzer "negativ" oder "absagen" sagt: höfliche Absage
- Wenn der Nutzer spezifische Formulierungen vorgibt: nutze diese
"""

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
        anthropic_client: AnthropicClient | None = None,
    ) -> None:
        self._email_client = email_client
        self._anthropic = anthropic_client

    # -- CommandHandler interface ------------------------------------------

    @property
    def simple_commands(self) -> set[str]:
        return {"mails"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        # MAIL_REPLY_PATTERN vor MAIL_ID_PATTERN (sonst matcht "antworte auf mail #123"
        # als "mail #123" via MAIL_ID_PATTERN)
        return [
            (MAIL_REPLY_PATTERN, "mail_reply", False, True),
            (MAIL_REPLY_MODIFY_PATTERN, "mail_reply_modify", False, False),
            (MAIL_ID_PATTERN, "mail_by_id", False, False),
            (MAIL_ATTACHMENT_PATTERN, "mail_attachment", False, True),
            (MAIL_SEARCH_PATTERN, "mail_search", False, True),
            (MAILS_DAYS_PATTERN, "mails", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "mails: Ungelesene E-Mails anzeigen",
            "mails <N>: E-Mails der letzten N Tage",
            "mail suche <begriff>: E-Mails nach Betreff/Absender durchsuchen",
            "mail <ID>: Einzelne Mail anzeigen (z.B. mail 99)",
            "mail anhang <ID>: Anhänge einer Mail senden",
            "mail zusammenfassung: LLM-Zusammenfassung ungelesener Mails",
            "antworte auf #<ID> <Anweisung>: Email-Antwort generieren",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "mails": [
                "neue mails", "ungelesene mails", "emails",
                "e-mails", "posteingang", "post", "nachrichten",
                "eingang", "hab ich mails", "gibt es neue mails",
                "sind mails da", "mails checken", "mail check",
            ],
            "mail_summary": [
                "mail zusammenfassung", "mails zusammenfassung",
                "fasse mails zusammen", "mails zusammenfassen",
            ],
            "mail_reply": [
                "antworte auf mail", "beantworte mail",
                "antwort auf die mail", "mail beantworten",
                "gib auf die mail", "schreib auf die mail",
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
        if command == "mail_reply":
            return self._cmd_mail_reply(raw_text)
        if command == "mail_reply_modify":
            return self._cmd_mail_reply_modify(raw_text)

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

    # -- Phase 28: Email-Reply Commands -----------------------------------

    def _cmd_mail_reply(self, raw_text: str) -> CommandResult:
        """Generiert einen Email-Antwort-Draft via Claude API.

        Gibt CommandResult mit pending_confirmation=True zurück.
        Die Bridge zeigt den Draft und wartet auf Bestätigung.
        """
        if not self._email_client:
            return CommandResult(
                command="mail_reply", success=False,
                text="E-Mail nicht konfiguriert.",
            )
        if not self._anthropic:
            return CommandResult(
                command="mail_reply", success=False,
                text="Claude API nicht konfiguriert (ANTHROPIC_API_KEY fehlt).",
            )

        msg_id, instruction = self._parse_reply_args(raw_text)
        if not msg_id:
            return CommandResult(
                command="mail_reply", success=False,
                text="Format: antworte auf #<ID> <Anweisung>\n"
                     "Beispiel: antworte auf #4523 positiv, bedanke dich",
            )

        try:
            original = self._email_client.get_by_uid(msg_id)
        except Exception as e:
            logger.error("Mail UID %s abrufen fehlgeschlagen: %s", msg_id, e)
            return CommandResult(
                command="mail_reply", success=False,
                text=f"Mail #{msg_id} konnte nicht abgerufen werden: {e}",
            )

        if not original:
            return CommandResult(
                command="mail_reply", success=False,
                text=f"Mail #{msg_id} nicht gefunden.",
            )

        try:
            draft = self._generate_draft(original, instruction)
        except Exception as e:
            logger.error("Draft-Generierung fehlgeschlagen: %s", e)
            return CommandResult(
                command="mail_reply", success=False,
                text=f"Draft-Generierung fehlgeschlagen: {type(e).__name__}",
            )

        subject = original.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        reply_to = self._extract_email_address(original.sender)

        display_text = (
            f"\U0001f4e7 Entwurf für Antwort auf #{msg_id}:\n"
            f"An: {reply_to}\n"
            f"Betreff: {subject}\n"
            f"---\n"
            f"{draft}\n"
            f"---\n"
            f"\u2705 'ja' zum Senden / \u274c 'nein' zum Verwerfen / "
            f"'ändern: <Anweisung>' zum Anpassen"
        )

        return CommandResult(
            command="mail_reply",
            success=True,
            text=display_text,
            pending_confirmation=True,
            pending_data={
                "msg_id": msg_id,
                "to": reply_to,
                "subject": subject,
                "draft_text": draft,
                "in_reply_to": original.message_id,
                "references": original.references or original.message_id,
                "original_instruction": instruction,
            },
        )

    def _cmd_mail_reply_modify(self, raw_text: str) -> CommandResult:
        """Generiert einen neuen Draft mit geänderter Anweisung.

        raw_text kommt von der Bridge als "#<id> <neue anweisung>".
        """
        if not self._email_client or not self._anthropic:
            return CommandResult(
                command="mail_reply_modify", success=False,
                text="E-Mail oder Claude API nicht konfiguriert.",
            )

        match = MAIL_REPLY_MODIFY_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="mail_reply_modify", success=False,
                text="Ungültiges Format für Änderung.",
            )

        msg_id = match.group(1)
        new_instruction = match.group(2)

        try:
            original = self._email_client.get_by_uid(msg_id)
        except Exception as e:
            logger.error("Mail UID %s abrufen fehlgeschlagen: %s", msg_id, e)
            return CommandResult(
                command="mail_reply_modify", success=False,
                text=f"Mail #{msg_id} konnte nicht abgerufen werden: {e}",
            )

        if not original:
            return CommandResult(
                command="mail_reply_modify", success=False,
                text=f"Mail #{msg_id} nicht gefunden.",
            )

        try:
            draft = self._generate_draft(original, new_instruction)
        except Exception as e:
            logger.error("Draft-Änderung fehlgeschlagen: %s", e)
            return CommandResult(
                command="mail_reply_modify", success=False,
                text=f"Draft-Änderung fehlgeschlagen: {type(e).__name__}",
            )

        subject = original.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        reply_to = self._extract_email_address(original.sender)

        display_text = (
            f"\U0001f4e7 Geänderter Entwurf für #{msg_id}:\n"
            f"An: {reply_to}\n"
            f"Betreff: {subject}\n"
            f"---\n"
            f"{draft}\n"
            f"---\n"
            f"\u2705 'ja' zum Senden / \u274c 'nein' zum Verwerfen / "
            f"'ändern: <Anweisung>' zum Anpassen"
        )

        return CommandResult(
            command="mail_reply_modify",
            success=True,
            text=display_text,
            pending_confirmation=True,
            pending_data={
                "msg_id": msg_id,
                "to": reply_to,
                "subject": subject,
                "draft_text": draft,
                "in_reply_to": original.message_id,
                "references": original.references or original.message_id,
                "original_instruction": new_instruction,
            },
        )

    def _generate_draft(self, original, instruction: str) -> str:
        """Generiert einen Email-Draft via Claude Sonnet 4.6.

        Args:
            original: Die Original-Mail auf die geantwortet wird.
            instruction: Anweisung des Nutzers (z.B. "positiv, bedanke dich").

        Returns:
            Generierter Antworttext.

        Raises:
            RuntimeError: Bei API-Fehlern.
        """
        date_str = (
            original.date.strftime("%d.%m.%Y %H:%M") if original.date else "?"
        )
        prompt = (
            f"Original-Mail:\n"
            f"Von: {original.sender}\n"
            f"Datum: {date_str}\n"
            f"Betreff: {original.subject}\n"
            f"Inhalt:\n{original.body_preview}\n\n"
            f"---\n"
            f"Anweisung des Nutzers: {instruction}\n\n"
            f"Schreibe jetzt die Antwort-Mail (nur den Body, keine Header)."
        )
        return self._anthropic.generate(prompt, system=EMAIL_SYSTEM_PROMPT)

    def _parse_reply_args(self, raw_text: str) -> tuple[str, str]:
        """Extrahiert Mail-ID und Anweisung aus dem Command-Text.

        Returns:
            Tuple (msg_id, instruction) oder ("", "") wenn nicht parsebar.
        """
        match = MAIL_REPLY_PATTERN.search(raw_text.strip())
        if not match:
            return ("", "")

        # 4 alternative Gruppen im Pattern (je 2: id + instruction)
        for i in range(1, 8, 2):
            msg_id = match.group(i)
            instruction = match.group(i + 1)
            if msg_id and instruction:
                return (msg_id.strip(), instruction.strip())

        return ("", "")

    @staticmethod
    def _extract_email_address(sender: str) -> str:
        """Extrahiert die Email-Adresse aus einem Sender-String.

        "Max Mustermann <max@example.com>" → "max@example.com"
        "max@example.com" → "max@example.com"
        """
        match = re.search(r"<([^>]+)>", sender)
        if match:
            return match.group(1)
        return sender.strip()
