"""FilingCommandHandler – Dokumente im Eingang klassifizieren und ablegen.

Command: "cloud aufräumen" / "räum cloud auf" / "eingang aufräumen"
Flow: Eingang listen → pro Datei analysieren → Vorschlag → Bestätigung → MOVE
"""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult
from elder_berry.comms.pending_confirmation import PendingAction
from elder_berry.tools.document_classifier import VALID_CATEGORIES

if TYPE_CHECKING:
    from elder_berry.comms.pending_confirmation import PendingConfirmationStore
    from elder_berry.tools.document_classifier import DocumentClassifier
    from elder_berry.tools.email_client import IMAPEmailClient
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient

logger = logging.getLogger(__name__)

INBOX_FOLDER = "Eingang"

FILING_PATTERN = re.compile(
    r"^(?:cloud\s+aufr[aä]umen|r[aä]um\s+cloud\s+auf|eingang\s+aufr[aä]umen)$",
    re.IGNORECASE,
)

# "anhang ablegen #4523", "leg anhang von #4523 ab", "anhang von mail 4523 ablegen"
FILING_ATTACHMENT_PATTERN = re.compile(
    r"(?:anh(?:ang|änge?)\s+(?:von\s+)?(?:mail\s*)?#?(\d+)\s+ablegen"
    r"|(?:leg|lege)\s+(?:den\s+)?anh(?:ang|änge?)\s+(?:von\s+)?(?:mail\s*)?#?(\d+)\s+ab"
    r"|anh(?:ang|änge?)\s+ablegen\s+(?:von\s+)?(?:mail\s*)?#?(\d+)"
    r"|mail\s*#?(\d+)\s+anh(?:ang|änge?)\s+ablegen)",
    re.IGNORECASE,
)

# Erlaubte Dateitypen für Mail-Anhänge
_ALLOWED_ATTACHMENT_EXTENSIONS = frozenset({".pdf"})

# Bestätigungs- und Skip-Wörter
FILING_CONFIRM = frozenset({"ja", "yes", "passt", "ok", "ablegen"})
FILING_SKIP = frozenset({"überspringen", "skip", "weiter", "nächste"})


class FilingCommandHandler(CommandHandler):
    """Handler für das Aufräumen des Nextcloud-Eingangs."""

    def __init__(
        self,
        nextcloud_files: NextcloudFilesClient | None = None,
        document_classifier: DocumentClassifier | None = None,
        pending_store: PendingConfirmationStore | None = None,
        email_client: IMAPEmailClient | None = None,
    ) -> None:
        self._nc = nextcloud_files
        self._classifier = document_classifier
        self._pending = pending_store
        self._email = email_client

    # ── CommandHandler Interface ──────────────────────────────────────────

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (FILING_PATTERN, "cloud_aufräumen", False, False),
            (FILING_ATTACHMENT_PATTERN, "anhang_ablegen", False, True),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "cloud_aufräumen": [
                "aufräumen", "eingang aufräumen", "räum cloud auf",
                "cloud aufräumen", "ablegen",
            ],
            "anhang_ablegen": [
                "anhang ablegen", "leg anhang ab", "anhänge ablegen",
            ],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "cloud aufräumen: Dateien im Eingang klassifizieren und ablegen",
            "anhang ablegen #<ID>: PDF-Anhänge aus Mail klassifizieren und ablegen",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "anhang_ablegen":
            return self._cmd_anhang_ablegen(raw_text)

        if command != "cloud_aufräumen":
            return CommandResult(
                command=command, success=False,
                text=f"Unbekannter Filing-Command: {command}",
            )

        if self._nc is None:
            return self.not_configured(command, "Nextcloud", setup_step=4)
        if self._classifier is None:
            return CommandResult(
                command=command, success=False,
                text="⚠ Dokument-Analyse nicht verfügbar (Ollama fehlt).",
            )

        return self._cmd_aufräumen()

    # ── Aufräum-Flow ─────────────────────────────────────────────────────

    def _cmd_aufräumen(self) -> CommandResult:
        """Listet den Eingang und startet den Aufräum-Flow."""
        try:
            entries = self._nc.list_dir(INBOX_FOLDER)
        except Exception as exc:
            logger.error("Eingang konnte nicht gelesen werden: %s", exc)
            return CommandResult(
                command="cloud_aufräumen", success=False,
                text=f"Eingang konnte nicht gelesen werden: {exc}",
            )

        # Nur Dateien, keine Ordner
        files = [e for e in entries if not e.is_dir]

        if not files:
            return CommandResult(
                command="cloud_aufräumen", success=True,
                text="📂 Eingang ist leer – nichts zu tun.",
            )

        return self._process_next_file(files, index=0)

    def _process_next_file(
        self, files: list, index: int,
    ) -> CommandResult:
        """Verarbeitet die nächste Datei im Eingang."""
        current = files[index]
        remaining_names = [f.name for f in files[index + 1:]]

        # Download auf Tower (temp)
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="filing_"))
            local_path = self._nc.download(
                f"{INBOX_FOLDER}/{current.name}", tmp_dir,
            )
        except Exception as exc:
            logger.error("Download fehlgeschlagen für %s: %s", current.name, exc)
            return CommandResult(
                command="cloud_aufräumen", success=False,
                text=f"Download fehlgeschlagen: {current.name} – {exc}",
            )

        # Klassifizieren
        suggestion = self._classifier.classify(local_path)

        # Vorschlag-Text
        confidence_hint = ""
        if suggestion.confidence != "high":
            confidence_hint = "\n⚠️ Unsicher – bitte prüfen."

        count_info = ""
        total = len(remaining_names) + 1
        if total > 1:
            count_info = f" (1/{total})"

        text = (
            f"📄 {current.name}{count_info}\n"
            f"→ {suggestion.filename}\n"
            f"→ Ziel: /{suggestion.target_folder}/"
            f"{confidence_hint}\n"
            f"Passt das? (ja / korrigieren / überspringen)"
        )

        return CommandResult(
            command="cloud_aufräumen",
            success=True,
            text=text,
            pending_confirmation=True,
            pending_data={
                "action_type": "filing",
                "source_path": f"{INBOX_FOLDER}/{current.name}",
                "local_temp": str(local_path),
                "suggestion": {
                    "filename": suggestion.filename,
                    "target_folder": suggestion.target_folder,
                },
                "remaining_files": remaining_names,
                "confidence": suggestion.confidence,
            },
        )

    # ── Mail-Anhang ablegen ────────────────────────────────────────────

    def _cmd_anhang_ablegen(self, raw_text: str) -> CommandResult:
        """PDF-Anhänge aus einer Mail klassifizieren und ablegen."""
        if self._nc is None:
            return self.not_configured("anhang_ablegen", "Nextcloud", setup_step=4)
        if self._classifier is None:
            return CommandResult(
                command="anhang_ablegen", success=False,
                text="⚠ Dokument-Analyse nicht verfügbar (Ollama fehlt).",
            )
        if self._email is None:
            return self.not_configured("anhang_ablegen", "E-Mail", setup_step=5)

        match = FILING_ATTACHMENT_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(
                command="anhang_ablegen", success=False,
                text="Format: anhang ablegen #<Mail-ID>",
            )

        msg_id = (
            match.group(1) or match.group(2)
            or match.group(3) or match.group(4) or ""
        ).strip()
        if not msg_id:
            return CommandResult(
                command="anhang_ablegen", success=False,
                text="Keine Mail-ID angegeben.",
            )

        # Anhänge abrufen
        try:
            attachments = self._email.get_attachments(msg_id)
        except Exception as exc:
            logger.error("Mail-Anhänge abrufen fehlgeschlagen (UID %s): %s", msg_id, exc)
            return CommandResult(
                command="anhang_ablegen", success=False,
                text=f"Anhänge abrufen fehlgeschlagen: {exc}",
            )

        if not attachments:
            return CommandResult(
                command="anhang_ablegen", success=True,
                text=f"Keine Anhänge in Mail #{msg_id}.",
            )

        # Nur PDFs filtern
        pdf_attachments = [
            (name, data) for name, data in attachments
            if Path(name).suffix.lower() in _ALLOWED_ATTACHMENT_EXTENSIONS
        ]
        rejected = [
            name for name, _ in attachments
            if Path(name).suffix.lower() not in _ALLOWED_ATTACHMENT_EXTENSIONS
        ]

        if not pdf_attachments:
            rejected_list = ", ".join(rejected)
            return CommandResult(
                command="anhang_ablegen", success=False,
                text=f"Keine PDF-Anhänge in Mail #{msg_id}.\n"
                     f"Abgelehnt (nur PDF erlaubt): {rejected_list}",
            )

        # PDFs als Temp-Dateien speichern und erste klassifizieren
        import tempfile
        temp_files: list[tuple[str, Path]] = []
        for filename, data in pdf_attachments:
            tmp_dir = Path(tempfile.mkdtemp(prefix="filing_mail_"))
            local_path = tmp_dir / filename
            local_path.write_bytes(data)
            temp_files.append((filename, local_path))

        # Info über abgelehnte Dateien
        rejected_info = ""
        if rejected:
            rejected_info = (
                f"\n⚠️ Übersprungen (nur PDF erlaubt): {', '.join(rejected)}"
            )

        # Erste PDF klassifizieren
        first_name, first_path = temp_files[0]
        suggestion = self._classifier.classify(first_path)

        remaining_temp = [
            (name, str(path)) for name, path in temp_files[1:]
        ]

        confidence_hint = ""
        if suggestion.confidence != "high":
            confidence_hint = "\n⚠️ Unsicher – bitte prüfen."

        count_info = ""
        if len(temp_files) > 1:
            count_info = f" (1/{len(temp_files)})"

        text = (
            f"📎 Mail #{msg_id} – {first_name}{count_info}\n"
            f"→ {suggestion.filename}\n"
            f"→ Ziel: /{suggestion.target_folder}/"
            f"{confidence_hint}"
            f"{rejected_info}\n"
            f"Passt das? (ja / korrigieren / überspringen)"
        )

        return CommandResult(
            command="anhang_ablegen",
            success=True,
            text=text,
            pending_confirmation=True,
            pending_data={
                "action_type": "filing",
                "source_type": "mail_attachment",
                "source_path": f"_mail_anhang/{first_name}",
                "local_temp": str(first_path),
                "suggestion": {
                    "filename": suggestion.filename,
                    "target_folder": suggestion.target_folder,
                },
                "remaining_files": [],
                "remaining_attachments": remaining_temp,
                "confidence": suggestion.confidence,
            },
        )

    # ── Bestätigungs-Handling ────────────────────────────────────────────

    def handle_confirm(self, action: PendingAction, user_id: str) -> CommandResult:
        """User hat 'ja' gesagt → Datei verschieben/hochladen."""
        target = action.data["suggestion"]["target_folder"]
        filename = action.data["suggestion"]["filename"]
        dest = f"{target}/{filename}"
        source_type = action.data.get("source_type", "inbox")

        if source_type == "mail_attachment":
            # Mail-Anhang: lokale Datei direkt auf Nextcloud hochladen
            local_path = Path(action.data["local_temp"])
            try:
                self._nc.upload(local_path, dest)
            except Exception as exc:
                logger.error("Upload fehlgeschlagen: %s → %s: %s", local_path, dest, exc)
                return CommandResult(
                    command="anhang_ablegen", success=False,
                    text=f"Upload fehlgeschlagen: {exc}",
                )
        elif source_type == "nc_attachment":
            # Bereits auf NC (z.B. /Saleria/YYYY-MM/) → MOVE ins Ziel
            source = action.data["source_path"]
            try:
                self._nc.move(source, dest)
            except Exception as exc:
                logger.error("MOVE fehlgeschlagen: %s → %s: %s", source, dest, exc)
                return CommandResult(
                    command="anhang_ablegen", success=False,
                    text=f"Verschieben fehlgeschlagen: {exc}",
                )
        else:
            # Eingang: WebDAV MOVE
            source = action.data["source_path"]
            try:
                self._nc.move(source, dest)
            except Exception as exc:
                logger.error("MOVE fehlgeschlagen: %s → %s: %s", source, dest, exc)
                return CommandResult(
                    command="cloud_aufräumen", success=False,
                    text=f"Verschieben fehlgeschlagen: {exc}\n"
                         f"Datei bleibt im Eingang.",
                )

        # Temp-Datei aufräumen
        self._cleanup_temp(action)

        is_attachment = source_type in ("mail_attachment", "nc_attachment")
        command = "anhang_ablegen" if is_attachment else "cloud_aufräumen"

        # Nächste Mail-Anhänge?
        remaining_attachments = action.data.get("remaining_attachments", [])
        if remaining_attachments:
            return self._process_next_attachment(remaining_attachments, filename)

        # Nächste Eingangs-Datei?
        remaining = action.data.get("remaining_files", [])
        if remaining:
            return self._process_remaining(remaining, dest)

        if is_attachment:
            return CommandResult(
                command=command, success=True,
                text=f"✅ Abgelegt: {filename}",
            )

        return CommandResult(
            command=command, success=True,
            text=f"✅ Abgelegt: {filename}\n\n"
                 f"📂 Eingang ist leer. Alle Dateien abgelegt.",
        )

    def handle_correction(
        self, action: PendingAction, hint: str, user_id: str,
    ) -> CommandResult:
        """User hat korrigiert → neuen Vorschlag generieren."""
        local_path = Path(action.data["local_temp"])

        suggestion = self._classifier.classify_with_hint(local_path, hint)

        # PendingAction-Daten aktualisieren
        action.data["suggestion"] = {
            "filename": suggestion.filename,
            "target_folder": suggestion.target_folder,
        }
        action.data["confidence"] = suggestion.confidence

        confidence_hint = ""
        if suggestion.confidence != "high":
            confidence_hint = "\n⚠️ Unsicher – bitte prüfen."

        source_name = action.data["source_path"].split("/")[-1]
        text = (
            f"📄 {source_name}\n"
            f"→ {suggestion.filename}\n"
            f"→ Ziel: /{suggestion.target_folder}/"
            f"{confidence_hint}\n"
            f"Passt das? (ja / korrigieren / überspringen)"
        )

        return CommandResult(
            command="cloud_aufräumen",
            success=True,
            text=text,
            pending_confirmation=True,
            pending_data=action.data,
        )

    def handle_skip(self, action: PendingAction, user_id: str) -> CommandResult:
        """User hat 'überspringen' gesagt → nächste Datei."""
        self._cleanup_temp(action)
        is_mail = action.data.get("source_type") == "mail_attachment"

        # Nächste Mail-Anhänge?
        remaining_attachments = action.data.get("remaining_attachments", [])
        if remaining_attachments:
            return self._process_next_attachment(
                remaining_attachments, "(übersprungen)",
            )

        # Nächste Eingangs-Datei?
        remaining = action.data.get("remaining_files", [])
        if remaining:
            return self._process_remaining(remaining)

        command = "anhang_ablegen" if is_mail else "cloud_aufräumen"
        done_text = "Alle Anhänge abgearbeitet." if is_mail else "Eingang abgearbeitet."
        return CommandResult(
            command=command, success=True,
            text=f"✅ {done_text}",
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _process_remaining(
        self, remaining_names: list[str], last_dest: str | None = None,
    ) -> CommandResult:
        """Listet den Eingang erneut und verarbeitet die nächste Datei."""
        try:
            entries = self._nc.list_dir(INBOX_FOLDER)
        except Exception as exc:
            logger.error("Eingang erneut lesen fehlgeschlagen: %s", exc)
            return CommandResult(
                command="cloud_aufräumen", success=False,
                text=f"Eingang konnte nicht gelesen werden: {exc}",
            )

        files = [e for e in entries if not e.is_dir]
        if not files:
            prefix = f"✅ Abgelegt: {last_dest.split('/')[-1]}\n\n" if last_dest else ""
            return CommandResult(
                command="cloud_aufräumen", success=True,
                text=f"{prefix}📂 Eingang ist leer. Alle Dateien abgelegt.",
            )

        result = self._process_next_file(files, index=0)

        # Erfolgs-Nachricht voranstellen wenn gerade eine Datei abgelegt wurde
        if last_dest and result.text:
            result = CommandResult(
                command=result.command,
                success=result.success,
                text=f"✅ Abgelegt: {last_dest.split('/')[-1]}\n\n{result.text}",
                pending_confirmation=result.pending_confirmation,
                pending_data=result.pending_data,
            )

        return result

    def _process_next_attachment(
        self, remaining: list[tuple], last_filename: str,
    ) -> CommandResult:
        """Klassifiziert den nächsten Mail-Anhang.

        remaining-Elemente sind entweder:
        - (name, local_path_str) – aus _cmd_anhang_ablegen (source_type=mail_attachment)
        - (name, local_path_str, nc_path) – aus Attachment-Menü (source_type=nc_attachment)
        """
        entry = remaining[0]
        name = entry[0]
        path_str = entry[1]
        nc_path = entry[2] if len(entry) > 2 else ""
        rest = remaining[1:]
        local_path = Path(path_str)

        if not local_path.exists():
            logger.warning("Temp-Datei nicht gefunden: %s", path_str)
            if rest:
                return self._process_next_attachment(rest, last_filename)
            return CommandResult(
                command="anhang_ablegen", success=True,
                text=f"✅ Abgelegt: {last_filename}\n\n"
                     f"Alle Anhänge abgearbeitet.",
            )

        suggestion = self._classifier.classify(local_path)

        confidence_hint = ""
        if suggestion.confidence != "high":
            confidence_hint = "\n⚠️ Unsicher – bitte prüfen."

        text = (
            f"✅ Abgelegt: {last_filename}\n\n"
            f"📎 {name}\n"
            f"→ {suggestion.filename}\n"
            f"→ Ziel: /{suggestion.target_folder}/"
            f"{confidence_hint}\n"
            f"Passt das? (ja / korrigieren / überspringen)"
        )

        # nc_attachment wenn NC-Pfad vorhanden (Attachment-Menü), sonst mail_attachment
        source_type = "nc_attachment" if nc_path else "mail_attachment"
        source_path = nc_path if nc_path else f"_mail_anhang/{name}"

        return CommandResult(
            command="anhang_ablegen",
            success=True,
            text=text,
            pending_confirmation=True,
            pending_data={
                "action_type": "filing",
                "source_type": source_type,
                "source_path": source_path,
                "local_temp": path_str,
                "suggestion": {
                    "filename": suggestion.filename,
                    "target_folder": suggestion.target_folder,
                },
                "remaining_files": [],
                "remaining_attachments": rest,
                "confidence": suggestion.confidence,
            },
        )

    @staticmethod
    def _cleanup_temp(action: PendingAction) -> None:
        """Löscht die temporäre Datei."""
        temp_path = action.data.get("local_temp")
        if temp_path:
            try:
                p = Path(temp_path)
                if p.exists():
                    p.unlink()
                # Temp-Verzeichnis auch aufräumen wenn leer
                if p.parent.exists() and not any(p.parent.iterdir()):
                    p.parent.rmdir()
            except OSError as exc:
                logger.debug("Temp-Cleanup fehlgeschlagen: %s", exc)
