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
from typing import TYPE_CHECKING, Any

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandPlugin,
    CommandResult,
    HandlerContext,
    user_friendly_error,
)

if TYPE_CHECKING:
    from elder_berry.llm.anthropic_client import AnthropicClient
    from elder_berry.tools.contact_store import ContactStore
    from elder_berry.tools.email_client import EmailMessage, IMAPEmailClient

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

# Regex fuer Mail löschen:
# "lösche mail #123", "mail löschen #123", "lösche die mail", "mail löschen"
# "lösch die mail #456", "entferne mail 789", "lösche mail 2"
# "lösche den 2. mail" (Index-basiert aus letztem Ergebnis)
# Neu: "mail #5 löschen", "lösche mail 5" (Verb vorne), "mail 5 löschen" (ID dann Verb)
MAIL_DELETE_PATTERN = re.compile(
    r"(?:bitte\s+)?"
    r"(?:mails?\s+(?:löschen|lösche|lösch|entferne[n]?)\s*#?(\d+)?"
    r"|(?:lösche?|lösch|entferne?)\s+(?:die\s+|den\s+\d+\.\s+)?(?:mail|email|e-mail)\s*#?(\d+)?"
    r"|(?:lösche?|lösch|entferne?)\s+(?:die\s+)?(?:letzte\s+)?mail"
    r"|mail\s*#?(\d+)\s+(?:löschen|lösche|lösch|entferne[n]?))"
    r"$",
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
        anthropic_client: AnthropicClient | None = None,
        contact_store: ContactStore | None = None,
        default_user_id: str = "",
    ) -> None:
        self._email_client = email_client
        self._anthropic = anthropic_client
        self._contacts = contact_store
        self._default_user_id = default_user_id
        self._last_mails: list[EmailMessage] = []

    # -- CommandHandler interface ------------------------------------------

    @property
    def simple_commands(self) -> set[str]:
        return {"mails"}

    @property
    def patterns(self) -> list[tuple[re.Pattern[str], str, bool, bool]]:
        # MAIL_REPLY_PATTERN vor MAIL_ID_PATTERN (sonst matcht "antworte auf mail #123"
        # als "mail #123" via MAIL_ID_PATTERN)
        return [
            (MAIL_REPLY_PATTERN, "mail_reply", False, True),
            (MAIL_REPLY_MODIFY_PATTERN, "mail_reply_modify", False, False),
            (MAIL_DELETE_PATTERN, "mail_delete", False, False),
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
            "lösche mail #<ID>: Mail löschen (oder: lösche die mail → letzte abgerufene)",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "mails": [
                "neue mails",
                "ungelesene mails",
                "emails",
                "e-mails",
                "posteingang",
                "post",
                "nachrichten",
                "eingang",
                "hab ich mails",
                "gibt es neue mails",
                "sind mails da",
                "mails checken",
                "mail check",
                "post abholen",
                "neue nachrichten",
            ],
            "mail_summary": [
                "mail zusammenfassung",
                "mails zusammenfassung",
                "fasse mails zusammen",
                "mails zusammenfassen",
            ],
            "mail_search": [
                "mail suche",
                "suche die mail",
                "finde mails",
                "mail finden",
                "mails durchsuchen",
            ],
            "mail_reply": [
                "antworte auf mail",
                "beantworte mail",
                "antwort auf die mail",
                "mail beantworten",
                "gib auf die mail",
                "schreib auf die mail",
            ],
            "mail_delete": [
                "lösche die mail",
                "mail löschen",
                "lösch die mail",
                "entferne die mail",
                "lösche die email",
                "email löschen",
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
        if command == "mail_delete":
            return self._cmd_mail_delete(raw_text)
        if command == "mail_reply":
            return self._cmd_mail_reply(raw_text)
        if command == "mail_reply_modify":
            return self._cmd_mail_reply_modify(raw_text)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Mail-Command: {command}",
        )

    # -- Command implementations ------------------------------------------

    def _cmd_mails(self, raw_text: str) -> CommandResult:
        """E-Mails abfragen (ungelesen oder letzte N Tage)."""
        if not self._email_client:
            return self.not_configured("mails", "E-Mail", setup_step=5)

        normalized = raw_text.strip().lower()
        match = MAILS_DAYS_PATTERN.match(normalized)

        try:
            if "zusammenfassung" in normalized:
                mails = self._email_client.get_unread(max_results=10)
                if not mails:
                    return CommandResult(
                        command="mails",
                        success=True,
                        text="Keine ungelesenen E-Mails.",
                    )
                self._last_mails = mails
                text = self._email_client.format_mails_detailed(mails)
                return CommandResult(
                    command="mails",
                    success=True,
                    text=text,
                    list_items=_mails_to_list_items(mails),
                    list_type="mail_inbox",
                )

            if match:
                days = int(match.group(1))
                mails = self._email_client.get_recent(days=days)
                label = f"E-Mails der letzten {days} Tage"
            else:
                mails = self._email_client.get_unread(max_results=15)
                label = "Ungelesene E-Mails"

            self._last_mails = mails
            count = len(mails)
            text = f"{label} ({count}):\n{self._email_client.format_mails(mails)}"
            list_items = _mails_to_list_items(mails)
            return CommandResult(
                command="mails",
                success=True,
                text=text,
                list_items=list_items if list_items else None,
                list_type="mail_inbox" if list_items else None,
            )

        except Exception as e:
            logger.error("E-Mail-Abfrage fehlgeschlagen: %s", e)
            return CommandResult(
                command="mails",
                success=False,
                text=user_friendly_error(e, "E-Mail"),
            )

    def _cmd_mail_search(self, raw_text: str) -> CommandResult:
        """E-Mails nach Betreff/Absender durchsuchen."""
        if not self._email_client:
            return self.not_configured("mail_search", "E-Mail", setup_step=5)

        match = MAIL_SEARCH_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(
                command="mail_search",
                success=False,
                text="Suchbegriff fehlt. Beispiel: mail suche Rechnung",
            )

        # Drei alternative Gruppen im Pattern
        query = (match.group(1) or match.group(2) or match.group(3) or "").strip()
        try:
            mails = self._email_client.search(query, max_results=10)
            if not mails:
                return CommandResult(
                    command="mail_search",
                    success=True,
                    text=f"Keine Mails gefunden für '{query}'.",
                )

            self._last_mails = mails
            # Kurzliste für den User
            text = f"Suche '{query}' ({len(mails)} Treffer):\n"
            text += self._email_client.format_mails(mails)
            # Detailliert für die Chat-History (LLM kann Body zusammenfassen)
            history = f"Suche '{query}' ({len(mails)} Treffer):\n"
            history += self._email_client.format_mails_detailed(mails)
            return CommandResult(
                command="mail_search",
                success=True,
                text=text,
                history_text=history,
                list_items=_mails_to_list_items(mails),
                list_type="mail_inbox",
            )

        except Exception as e:
            logger.error("Mail-Suche fehlgeschlagen: %s", e)
            return CommandResult(
                command="mail_search",
                success=False,
                text=user_friendly_error(e, "Mail-Suche"),
            )

    def _cmd_mail_attachment(self, raw_text: str) -> CommandResult:
        """Anhänge einer E-Mail per UID abrufen und als temp-Dateien bereitstellen."""
        if not self._email_client:
            return self.not_configured("mail_attachment", "E-Mail", setup_step=5)

        match = MAIL_ATTACHMENT_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(
                command="mail_attachment",
                success=False,
                text="Mail-ID fehlt. Beispiel: mail anhang 123",
            )

        # Drei alternative Gruppen im Pattern
        msg_id = (match.group(1) or match.group(2) or match.group(3) or "").strip()
        if not msg_id:
            return CommandResult(
                command="mail_attachment",
                success=False,
                text="Keine Mail-ID angegeben.",
            )

        try:
            attachments = self._email_client.get_attachments(msg_id)

            if not attachments:
                return CommandResult(
                    command="mail_attachment",
                    success=True,
                    text=f"Keine Anhänge in Mail #{msg_id}.",
                )

            # Anhänge als temp-Dateien speichern
            temp_paths: list[Path] = []
            names: list[str] = []
            for filename, data in attachments:
                suffix = Path(filename).suffix or ".bin"
                tmp = tempfile.NamedTemporaryFile(
                    suffix=suffix,
                    prefix=f"mail_{msg_id}_",
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
                command="mail_attachment",
                success=False,
                text=user_friendly_error(e, "Anhang abrufen"),
            )

    def _cmd_mail_by_id(self, raw_text: str) -> CommandResult:
        """Einzelne Mail per UID abrufen (Body als history_text für LLM-Kontext)."""
        if not self._email_client:
            return self.not_configured("mail_by_id", "E-Mail", setup_step=5)

        match = MAIL_ID_PATTERN.match(raw_text.strip().lower())
        if not match:
            return CommandResult(
                command="mail_by_id",
                success=False,
                text="Format: mail <ID> (z.B. mail 99 oder mail #99)",
            )

        msg_id = match.group(1)

        try:
            mail = self._email_client.get_by_uid(msg_id)

            if not mail:
                return CommandResult(
                    command="mail_by_id",
                    success=False,
                    text=f"Mail #{msg_id} nicht gefunden.",
                )

            self._last_mails = [mail]

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
                command="mail_by_id",
                success=False,
                text=user_friendly_error(e, "Mail abrufen"),
            )

    # -- Mail-Delete Command ------------------------------------------------

    def _cmd_mail_delete(self, raw_text: str) -> CommandResult:
        """Mail per UID oder letzte abgerufene Mail löschen."""
        if not self._email_client:
            return self.not_configured("mail_delete", "E-Mail", setup_step=5)

        match = MAIL_DELETE_PATTERN.match(raw_text.strip())
        msg_id = None
        if match:
            # Drei alternative Gruppen: (1) "mail löschen #123", (2) "lösche mail #123",
            # (3) "mail #5 löschen"
            msg_id = match.group(1) or match.group(2) or match.group(3)

        if msg_id:
            return self._delete_mail_by_uid(msg_id)

        # Keine ID angegeben → letzte abgerufene Mail
        if not self._last_mails:
            return CommandResult(
                command="mail_delete",
                success=False,
                text="Keine Mail zum Löschen. Ruf erst Mails ab "
                "(z.B. 'mails' oder 'mail #123').",
            )

        if len(self._last_mails) == 1:
            mail = self._last_mails[0]
            return self._delete_mail_by_uid(mail.msg_id)

        return CommandResult(
            command="mail_delete",
            success=False,
            text=f"Welche? Es gibt {len(self._last_mails)} Mails.\n"
            "Sag z.B. 'lösche mail #123' mit der ID aus der Liste.",
        )

    def _delete_mail_by_uid(self, msg_id: str) -> CommandResult:
        """Löscht eine einzelne Mail per UID."""
        if not msg_id:
            return CommandResult(
                command="mail_delete",
                success=False,
                text="Keine Mail-ID angegeben.",
            )

        # Narrowing aus Line 460 ueber das lange Method-Body wieder herstellen.
        assert self._email_client is not None
        try:
            self._email_client.delete(msg_id)
        except Exception as e:
            logger.error("Mail UID %s löschen fehlgeschlagen: %s", msg_id, e)
            return CommandResult(
                command="mail_delete",
                success=False,
                text=user_friendly_error(e, "Mail löschen"),
            )

        # Aus _last_mails entfernen
        self._last_mails = [m for m in self._last_mails if m.msg_id != msg_id]
        return CommandResult(
            command="mail_delete",
            success=True,
            text=f"Mail #{msg_id} gelöscht.",
        )

    # -- Phase 28: Email-Reply Commands -----------------------------------

    def _cmd_mail_reply(self, raw_text: str) -> CommandResult:
        """Generiert einen Email-Antwort-Draft via Claude API.

        Gibt CommandResult mit pending_confirmation=True zurück.
        Die Bridge zeigt den Draft und wartet auf Bestätigung.
        """
        if not self._email_client:
            return self.not_configured("mail_reply", "E-Mail", setup_step=5)
        if not self._anthropic:
            return self.not_configured("mail_reply", "Claude API", setup_step=2)

        msg_id, instruction = self._parse_reply_args(raw_text)
        if not msg_id:
            return CommandResult(
                command="mail_reply",
                success=False,
                text="Format: antworte auf #<ID> <Anweisung>\n"
                "Beispiel: antworte auf #4523 positiv, bedanke dich",
            )

        try:
            original = self._email_client.get_by_uid(msg_id)
        except Exception as e:
            logger.error("Mail UID %s abrufen fehlgeschlagen: %s", msg_id, e)
            return CommandResult(
                command="mail_reply",
                success=False,
                text=user_friendly_error(e, f"Mail #{msg_id}"),
            )

        if not original:
            return CommandResult(
                command="mail_reply",
                success=False,
                text=f"Mail #{msg_id} nicht gefunden.",
            )

        try:
            draft = self._generate_draft(original, instruction)
        except Exception as e:
            logger.error("Draft-Generierung fehlgeschlagen: %s", e)
            return CommandResult(
                command="mail_reply",
                success=False,
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
        if not self._email_client:
            return self.not_configured("mail_reply_modify", "E-Mail", setup_step=5)
        if not self._anthropic:
            return self.not_configured("mail_reply_modify", "Claude API", setup_step=2)

        match = MAIL_REPLY_MODIFY_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="mail_reply_modify",
                success=False,
                text="Ungültiges Format für Änderung.",
            )

        msg_id = match.group(1)
        new_instruction = match.group(2)

        try:
            original = self._email_client.get_by_uid(msg_id)
        except Exception as e:
            logger.error("Mail UID %s abrufen fehlgeschlagen: %s", msg_id, e)
            return CommandResult(
                command="mail_reply_modify",
                success=False,
                text=user_friendly_error(e, f"Mail #{msg_id}"),
            )

        if not original:
            return CommandResult(
                command="mail_reply_modify",
                success=False,
                text=f"Mail #{msg_id} nicht gefunden.",
            )

        try:
            draft = self._generate_draft(original, new_instruction)
        except Exception as e:
            logger.error("Draft-Änderung fehlgeschlagen: %s", e)
            return CommandResult(
                command="mail_reply_modify",
                success=False,
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

    def _generate_draft(self, original: EmailMessage, instruction: str) -> str:
        """Generiert einen Email-Draft via Claude Sonnet 4.6.

        Args:
            original: Die Original-Mail auf die geantwortet wird.
            instruction: Anweisung des Nutzers (z.B. "positiv, bedanke dich").

        Returns:
            Generierter Antworttext.

        Raises:
            RuntimeError: Bei API-Fehlern.
        """
        date_str = original.date.strftime("%d.%m.%Y %H:%M") if original.date else "?"
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
        # Caller (_cmd_mail_reply) filtert "if not self._anthropic: return".
        assert self._anthropic is not None
        # Kontakt-Lookup per Absender-Email (Phase 29)
        system = EMAIL_SYSTEM_PROMPT
        if self._contacts and self._default_user_id:
            sender_email = self._extract_email_address(original.sender)
            contact = self._contacts.find_by_email(
                self._default_user_id,
                sender_email,
            )
            if contact:
                system += f"\n\nKontext zum Empfänger:\n{contact.format_for_llm()}\n"

        return self._anthropic.generate(prompt, system=system)

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


# ---------------------------------------------------------------------------
# Phase 80 Etappe 3: list_items fuer ConversationListStore
# ---------------------------------------------------------------------------


def _mails_to_list_items(mails: list[EmailMessage]) -> list[dict[str, Any]]:
    """Wandelt EmailMessages in list_items fuer den ConversationListStore.

    Reihenfolge entspricht 1:1 der User-sichtbaren Nummerierung in ``text``,
    damit "lies Mail 3" eindeutig auf items[2] zeigt (1-basiert via Store).
    """
    return [
        {
            "from": m.sender,
            "subject": m.subject,
            "msg_id": m.msg_id,
            "date": m.date.isoformat() if m.date else "",
        }
        for m in mails
    ]


# ---------------------------------------------------------------------------
# Phase 77: Plugin-Manifest
# ---------------------------------------------------------------------------

HELP_SECTION_MAIL = """E-Mail:
  mails / mails 5 -- Ungelesene E-Mails (mit Tage-Filter)
  mail suche <Begriff> -- Mails durchsuchen
  mail <ID> / mail #<ID> -- Mail anzeigen
  mail anhang <ID> -- Anhaenge senden
  mail zusammenfassung -- LLM-Zusammenfassung
  antworte auf #<ID> <Anweisung> -- Email-Antwort generieren
  loesche mail #<ID> / loesche die mail"""


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    return MailCommandHandler(
        email_client=ctx.email_client,
        anthropic_client=ctx.anthropic_client,
        contact_store=ctx.contact_store,
        default_user_id=ctx.default_user_id,
    )


PLUGIN = CommandPlugin(
    name="mail",
    priority=20,
    category="mail",
    help_section=HELP_SECTION_MAIL,
    factory=_factory,
    conflicts=("calendar",),
)
