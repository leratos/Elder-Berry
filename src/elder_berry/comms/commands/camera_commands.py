"""CameraCommandHandler -- Kamera-Befehle (Foto, Vision-Analyse)."""

from __future__ import annotations

import base64
import logging
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandPlugin,
    CommandResult,
    HandlerContext,
    user_friendly_error,
)

if TYPE_CHECKING:
    from elder_berry.llm.anthropic_client import AnthropicClient
    from elder_berry.robot.client import RobotClient

logger = logging.getLogger(__name__)

# Regex: "was siehst du <kontext>", "beschreibe was vor dir ist"
CAMERA_DESCRIBE_PATTERN = re.compile(
    r"^(?:was\s+siehst\s+du|was\s+sieht\s+die\s+kamera|beschreibe\s+was"
    r"|schau\s+(?:mal\s+)?(?:was|ob)|guck\s+(?:mal\s+)?(?:was|ob))"
    r"(?:\s+(.+))?$",
    re.IGNORECASE,
)


class CameraCommandHandler(CommandHandler):
    """Handler für Kamera-Befehle (Foto aufnehmen, Vision-Analyse)."""

    def __init__(
        self,
        robot_client: RobotClient | None = None,
        anthropic_client: AnthropicClient | None = None,
    ) -> None:
        self._robot = robot_client
        self._anthropic = anthropic_client

    @property
    def simple_commands(self) -> set[str]:
        return {"foto", "kamera", "kamerabild"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (CAMERA_DESCRIBE_PATTERN, "camera_describe", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "foto / kamera: Foto mit der Kamera aufnehmen",
            "was siehst du [kontext]: Kamerabild aufnehmen + Vision-Analyse",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "foto": [
                "mach ein foto",
                "nimm ein bild auf",
                "kamerabild",
                "fotografier",
                "knips",
                "mach ein bild",
            ],
            "camera_describe": [
                "was siehst du",
                "was sieht die kamera",
                "schau mal was",
                "schau mal ob",
                "guck mal was",
                "guck mal ob",
                "was ist vor dir",
                "kannst du sehen",
                "siehst du was",
                "zeig mir was du siehst",
                "beschreibe deine umgebung",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command in ("foto", "kamera", "kamerabild"):
            return self._cmd_foto()

        if command == "camera_describe":
            return self._cmd_describe(raw_text)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Command: {command}",
        )

    def _capture_image(self) -> tuple[bytes | None, str | None]:
        """Nimmt ein Bild auf. Gibt (jpeg_bytes, error_text) zurück."""
        if not self._robot:
            return None, "RobotClient nicht verfügbar (RPi5 nicht verbunden)."

        try:
            jpeg_bytes = self._robot.capture_image()
        except Exception as e:
            logger.error("Kamera-Capture fehlgeschlagen: %s", e)
            return None, f"Kamera-Fehler: {e}"

        if jpeg_bytes is None:
            return None, "Kamera nicht verfügbar oder Capture fehlgeschlagen."

        return jpeg_bytes, None

    def _save_temp_jpeg(self, jpeg_bytes: bytes) -> Path:
        """Speichert JPEG-Bytes als temp-Datei."""
        tmp = tempfile.NamedTemporaryFile(
            suffix=".jpg",
            prefix="camera_",
            delete=False,
        )
        tmp_path = Path(tmp.name)
        tmp.write(jpeg_bytes)
        tmp.close()
        return tmp_path

    def _cmd_foto(self) -> CommandResult:
        """Nimmt ein Foto auf und sendet es an Matrix."""
        jpeg_bytes, error = self._capture_image()
        if error:
            return CommandResult(command="foto", success=False, text=error)

        tmp_path = self._save_temp_jpeg(jpeg_bytes)

        return CommandResult(
            command="foto",
            success=True,
            text="Foto aufgenommen.",
            image_path=tmp_path,
        )

    def _cmd_describe(self, raw_text: str) -> CommandResult:
        """Nimmt ein Foto auf, analysiert es per Vision API und beschreibt es.

        Wenn kein AnthropicClient verfügbar: nur Foto ohne Beschreibung.
        """
        jpeg_bytes, error = self._capture_image()
        if error:
            return CommandResult(
                command="camera_describe",
                success=False,
                text=error,
            )

        tmp_path = self._save_temp_jpeg(jpeg_bytes)

        # Ohne Vision-API: nur Bild senden
        if not self._anthropic or not self._anthropic.is_available():
            return CommandResult(
                command="camera_describe",
                success=True,
                text="Foto aufgenommen. (Vision-Analyse nicht verfügbar – "
                "AnthropicClient fehlt oder kein API-Key)",
                image_path=tmp_path,
            )

        # Vision-Analyse
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")

        # Kontext aus dem Befehl extrahieren (optional)
        match = CAMERA_DESCRIBE_PATTERN.match(raw_text.strip().lower())
        extra_context = ""
        if match and match.group(1):
            extra_context = match.group(1).strip()

        prompt = "Beschreibe kurz und präzise was du auf diesem Kamerabild siehst."
        if extra_context:
            prompt = (
                f"Der Nutzer fragt: '{extra_context}'. "
                f"Beantworte die Frage basierend auf dem Kamerabild. "
                f"Sei kurz und präzise."
            )

        system = (
            "Du bist Saleria, eine virtuelle Assistentin. "
            "Du beschreibst was die Kamera sieht. "
            "Antworte auf Deutsch, kurz und natürlich."
        )

        try:
            description = self._anthropic.describe_image(
                image_base64=b64,
                prompt=prompt,
                system=system,
            )
        except Exception as e:
            logger.error("Vision-Analyse fehlgeschlagen: %s", e)
            return CommandResult(
                command="camera_describe",
                success=True,
                text=user_friendly_error(e, "Kamera-Analyse"),
                image_path=tmp_path,
            )

        return CommandResult(
            command="camera_describe",
            success=True,
            text=description,
            image_path=tmp_path,
        )


# ---------------------------------------------------------------------------
# Phase 77: Plugin-Manifest
# ---------------------------------------------------------------------------

HELP_SECTION_CAMERA = """Kamera:
  foto / kamera -- Foto aufnehmen und senden
  was siehst du [kontext] -- Kamerabild + KI-Beschreibung"""


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    return CameraCommandHandler(
        robot_client=ctx.robot_client,
        anthropic_client=ctx.anthropic_client,
    )


PLUGIN = CommandPlugin(
    name="camera",
    priority=64,
    category="avatar",
    help_section=HELP_SECTION_CAMERA,
    factory=_factory,
)
