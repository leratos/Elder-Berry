"""Tests für CameraCommandHandler – Parsing und Ausführung."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.camera_commands import (
    CAMERA_DESCRIBE_PATTERN,
    CameraCommandHandler,
)
from elder_berry.comms.remote_commands import RemoteCommandHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def handler():
    """CameraCommandHandler ohne Dependencies."""
    return CameraCommandHandler()


@pytest.fixture
def mock_robot():
    """Mock-RobotClient der JPEG-Bytes liefert."""
    robot = MagicMock()
    # Minimales JPEG (nur Header): wird von _save_temp_jpeg geschrieben
    robot.capture_image.return_value = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    return robot


@pytest.fixture
def mock_anthropic():
    """Mock-AnthropicClient mit describe_image()."""
    client = MagicMock()
    client.is_available.return_value = True
    client.describe_image.return_value = "Ich sehe einen Schreibtisch mit Monitor."
    return client


@pytest.fixture
def handler_with_robot(mock_robot):
    return CameraCommandHandler(robot_client=mock_robot)


@pytest.fixture
def handler_full(mock_robot, mock_anthropic):
    return CameraCommandHandler(
        robot_client=mock_robot,
        anthropic_client=mock_anthropic,
    )


@pytest.fixture
def remote_handler():
    """RemoteCommandHandler mit minimalen Dependencies."""
    return RemoteCommandHandler()


# ---------------------------------------------------------------------------
# Parsing: Simple Commands
# ---------------------------------------------------------------------------

class TestCameraCommandParsing:
    def test_parse_foto(self, remote_handler):
        """6. 'foto' wird als Command erkannt."""
        assert remote_handler.parse_command("foto") == "foto"

    def test_parse_kamera(self, remote_handler):
        """7. 'kamera' wird als Command erkannt."""
        assert remote_handler.parse_command("kamera") == "kamera"

    def test_parse_kamerabild(self, remote_handler):
        """8. 'kamerabild' wird als Command erkannt."""
        assert remote_handler.parse_command("kamerabild") == "kamerabild"

    def test_parse_was_siehst_du(self, remote_handler):
        """9. 'was siehst du' -> camera_describe."""
        assert remote_handler.parse_command("was siehst du") == "camera_describe"

    def test_parse_was_siehst_du_kontext(self, remote_handler):
        """10. 'was siehst du auf meinem schreibtisch' -> camera_describe."""
        assert remote_handler.parse_command("was siehst du auf meinem schreibtisch") == "camera_describe"

    def test_parse_schau_mal(self, remote_handler):
        """11. 'schau mal was da liegt' -> camera_describe."""
        assert remote_handler.parse_command("schau mal was da liegt") == "camera_describe"

    def test_parse_guck_mal(self, remote_handler):
        """12. 'guck mal ob jemand da ist' -> camera_describe."""
        assert remote_handler.parse_command("guck mal ob jemand da ist") == "camera_describe"


# ---------------------------------------------------------------------------
# Parsing: Keywords
# ---------------------------------------------------------------------------

class TestCameraKeywordParsing:
    def test_keyword_mach_ein_foto(self, remote_handler):
        """13. 'mach ein foto' -> foto (Keyword-Match)."""
        assert remote_handler.parse_command("mach ein foto") == "foto"

    def test_keyword_was_siehst_du(self, remote_handler):
        """14. 'kannst du sehen was da ist' -> camera_describe (Keyword)."""
        assert remote_handler.parse_command("kannst du sehen was da ist") == "camera_describe"


# ---------------------------------------------------------------------------
# Execution: Fehlerszenarien
# ---------------------------------------------------------------------------

class TestCameraCommandExecution:
    def test_foto_no_robot(self, handler):
        """15. robot_client=None -> Fehler 'RobotClient nicht verfügbar'."""
        result = handler.execute("foto", "foto")
        assert result.success is False
        assert "RobotClient nicht verfügbar" in result.text

    def test_foto_capture_returns_none(self):
        """16. capture_image() gibt None -> Fehler."""
        robot = MagicMock()
        robot.capture_image.return_value = None
        h = CameraCommandHandler(robot_client=robot)
        result = h.execute("foto", "foto")
        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_foto_success(self, handler_with_robot):
        """17. Mock-Robot gibt JPEG -> image_path gesetzt, success=True."""
        result = handler_with_robot.execute("foto", "foto")
        assert result.success is True
        assert result.image_path is not None
        assert result.image_path.suffix == ".jpg"
        assert result.image_path.exists()
        # Cleanup
        result.image_path.unlink(missing_ok=True)

    def test_describe_no_anthropic(self, handler_with_robot):
        """18. Kein AnthropicClient -> nur Foto, kein Vision-Text."""
        result = handler_with_robot.execute("camera_describe", "was siehst du")
        assert result.success is True
        assert result.image_path is not None
        assert "Vision-Analyse nicht verfügbar" in result.text
        # Cleanup
        result.image_path.unlink(missing_ok=True)

    def test_describe_success(self, handler_full, mock_anthropic):
        """19. Mock-Robot + Mock-Anthropic -> Beschreibung + Bild."""
        result = handler_full.execute("camera_describe", "was siehst du")
        assert result.success is True
        assert result.image_path is not None
        assert "Schreibtisch" in result.text
        mock_anthropic.describe_image.assert_called_once()
        # Cleanup
        result.image_path.unlink(missing_ok=True)

    def test_describe_vision_error(self, mock_robot, mock_anthropic):
        """20. Vision wirft Exception -> Foto gesendet, Fehlertext."""
        mock_anthropic.describe_image.side_effect = RuntimeError("API down")
        h = CameraCommandHandler(
            robot_client=mock_robot,
            anthropic_client=mock_anthropic,
        )
        result = h.execute("camera_describe", "was siehst du")
        assert result.success is True
        assert result.image_path is not None
        assert "Kamera-Analyse" in result.text
        # Cleanup
        result.image_path.unlink(missing_ok=True)

    def test_describe_with_context(self, handler_full, mock_anthropic):
        """21. 'was siehst du auf dem tisch' -> Kontext in Prompt enthalten."""
        result = handler_full.execute("camera_describe", "was siehst du auf dem tisch")
        assert result.success is True
        # Prüfen dass describe_image mit Kontext-Prompt aufgerufen wurde
        call_kwargs = mock_anthropic.describe_image.call_args
        prompt = call_kwargs.kwargs.get("prompt") or call_kwargs[1].get("prompt") or call_kwargs[0][1]
        assert "auf dem tisch" in prompt.lower()
        # Cleanup
        result.image_path.unlink(missing_ok=True)

    def test_foto_temp_file_is_jpeg(self, handler_with_robot):
        """22. Temp-Datei endet auf .jpg und enthält JPEG-Header."""
        result = handler_with_robot.execute("foto", "foto")
        assert result.image_path.suffix == ".jpg"
        content = result.image_path.read_bytes()
        assert content[:2] == b"\xff\xd8"
        # Cleanup
        result.image_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Keine Kollision mit Screenshot
# ---------------------------------------------------------------------------

class TestCameraNoCollision:
    def test_no_collision_with_screenshot(self, remote_handler):
        """23. 'screenshot' wird NICHT als Kamera-Command erkannt."""
        cmd = remote_handler.parse_command("screenshot")
        assert cmd != "foto"
        assert cmd != "kamera"
        assert cmd != "camera_describe"
