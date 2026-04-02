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
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient

logger = logging.getLogger(__name__)

INBOX_FOLDER = "Eingang"

FILING_PATTERN = re.compile(
    r"^(?:cloud\s+aufr[aä]umen|r[aä]um\s+cloud\s+auf|eingang\s+aufr[aä]umen)$",
    re.IGNORECASE,
)

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
    ) -> None:
        self._nc = nextcloud_files
        self._classifier = document_classifier
        self._pending = pending_store

    # ── CommandHandler Interface ──────────────────────────────────────────

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (FILING_PATTERN, "cloud_aufräumen", False, False),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "cloud_aufräumen": [
                "aufräumen", "eingang aufräumen", "räum cloud auf",
                "cloud aufräumen", "ablegen",
            ],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "cloud aufräumen: Dateien im Eingang klassifizieren und ablegen",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command != "cloud_aufräumen":
            return CommandResult(
                command=command, success=False,
                text=f"Unbekannter Filing-Command: {command}",
            )

        if self._nc is None:
            return CommandResult(
                command=command, success=False,
                text="Nextcloud nicht konfiguriert.",
            )
        if self._classifier is None:
            return CommandResult(
                command=command, success=False,
                text="Dokument-Analyse nicht verfügbar (Ollama fehlt).",
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

    # ── Bestätigungs-Handling ────────────────────────────────────────────

    def handle_confirm(self, action: PendingAction, user_id: str) -> CommandResult:
        """User hat 'ja' gesagt → Datei verschieben."""
        source = action.data["source_path"]
        target = action.data["suggestion"]["target_folder"]
        filename = action.data["suggestion"]["filename"]
        dest = f"{target}/{filename}"

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

        # Nächste Datei?
        remaining = action.data.get("remaining_files", [])
        if remaining:
            return self._process_remaining(remaining, dest)

        return CommandResult(
            command="cloud_aufräumen", success=True,
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

        remaining = action.data.get("remaining_files", [])
        if remaining:
            return self._process_remaining(remaining)

        return CommandResult(
            command="cloud_aufräumen", success=True,
            text="✅ Eingang abgearbeitet.",
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
