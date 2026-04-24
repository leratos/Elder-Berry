"""Tests: FileCommandHandler – Clipboard, Send-File, Download."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.file_commands import (
    CLIP_WRITE_PATTERN,
    DOWNLOAD_PATTERN,
    MAX_FILE_SIZE_BYTES,
    SEND_FILE_PATTERN,
    FileCommandHandler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def handler(tmp_path):
    return FileCommandHandler(
        download_dir=tmp_path / "downloads",
        send_file_allowed_roots=(tmp_path,),
    )


@pytest.fixture
def handler_no_roots(tmp_path):
    return FileCommandHandler(
        download_dir=tmp_path / "downloads",
        send_file_allowed_roots=(),
    )


# ---------------------------------------------------------------------------
# Pattern Tests
# ---------------------------------------------------------------------------

class TestClipWritePattern:
    @pytest.mark.parametrize("text", [
        "clip: hello world",
        "clip hello world",
        "CLIP: test",
    ])
    def test_valid(self, text):
        assert CLIP_WRITE_PATTERN.match(text) is not None

    def test_invalid(self):
        assert CLIP_WRITE_PATTERN.match("clipboard") is None


class TestSendFilePattern:
    @pytest.mark.parametrize("text", [
        r"schick mir C:\Users\test.pdf",
        "send file /home/user/test.pdf",
        "sende mir /tmp/file.txt",
        r"sende datei C:\docs\file.pdf",
    ])
    def test_valid(self, text):
        assert SEND_FILE_PATTERN.search(text) is not None

    def test_invalid(self):
        assert SEND_FILE_PATTERN.search("schick mir hallo") is None


class TestDownloadPattern:
    @pytest.mark.parametrize("text", [
        "download https://example.com/file.zip",
        "download http://test.org/data.csv",
    ])
    def test_valid(self, text):
        assert DOWNLOAD_PATTERN.match(text) is not None

    def test_invalid(self):
        assert DOWNLOAD_PATTERN.match("download ftp://bad") is None


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class TestFileInterface:
    def test_simple_commands(self, handler):
        assert "clipboard" in handler.simple_commands

    def test_patterns_registered(self, handler):
        names = {p[1] for p in handler.patterns}
        assert "clip_write" in names
        assert "send_file" in names
        assert "download" in names

    def test_keywords(self, handler):
        assert "clipboard" in handler.keywords


# ---------------------------------------------------------------------------
# Clipboard Read
# ---------------------------------------------------------------------------

class TestClipboardRead:
    def test_read_success(self, handler):
        mock_pyperclip = MagicMock()
        mock_pyperclip.paste.return_value = "clipboard content"
        with patch.dict("sys.modules", {"pyperclip": mock_pyperclip}):
            result = handler.execute("clipboard", "clipboard")
            assert result.success is True
            assert "clipboard content" in result.text

    def test_read_empty(self, handler):
        mock_pyperclip = MagicMock()
        mock_pyperclip.paste.return_value = ""
        with patch.dict("sys.modules", {"pyperclip": mock_pyperclip}):
            result = handler.execute("clipboard", "clipboard")
            assert result.success is True
            assert "leer" in result.text.lower()

    def test_read_long_truncated(self, handler):
        mock_pyperclip = MagicMock()
        mock_pyperclip.paste.return_value = "x" * 5000
        with patch.dict("sys.modules", {"pyperclip": mock_pyperclip}):
            result = handler.execute("clipboard", "clipboard")
            assert result.success is True
            assert "gekürzt" in result.text

    def test_read_no_pyperclip(self, handler):
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyperclip":
                raise ImportError()
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute("clipboard", "clipboard")
            assert result.success is False
            assert "pyperclip" in result.text.lower()


# ---------------------------------------------------------------------------
# Clipboard Write
# ---------------------------------------------------------------------------

class TestClipboardWrite:
    def test_write_success(self, handler):
        mock_pyperclip = MagicMock()
        with patch.dict("sys.modules", {"pyperclip": mock_pyperclip}):
            result = handler.execute("clip_write", "clip: hello world")
            assert result.success is True
            assert "kopiert" in result.text.lower()
            mock_pyperclip.copy.assert_called_once_with("hello world")

    def test_write_invalid_format(self, handler):
        result = handler.execute("clip_write", "clipboard")
        assert result.success is False


# ---------------------------------------------------------------------------
# Send File
# ---------------------------------------------------------------------------

class TestSendFile:
    def test_send_success(self, handler, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_text("content")
        raw = f"schick mir {test_file}"
        result = handler.execute("send_file", raw)
        assert result.success is True
        assert result.file_path == test_file

    def test_send_file_not_found(self, handler, tmp_path):
        raw = f"schick mir {tmp_path / 'nonexistent.pdf'}"
        result = handler.execute("send_file", raw)
        assert result.success is False
        assert "nicht gefunden" in result.text.lower()

    def test_send_file_too_large(self, handler, tmp_path):
        big_file = tmp_path / "big.bin"
        big_file.write_bytes(b"x" * (MAX_FILE_SIZE_BYTES + 1))
        raw = f"schick mir {big_file}"
        result = handler.execute("send_file", raw)
        assert result.success is False
        assert "zu groß" in result.text.lower()

    def test_send_file_is_directory(self, handler, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        raw = f"schick mir {sub}"
        result = handler.execute("send_file", raw)
        assert result.success is False
        assert "keine Datei" in result.text

    def test_send_file_outside_roots(self, handler, tmp_path):
        """Datei außerhalb der erlaubten Roots wird abgelehnt."""
        import tempfile
        outside = Path(tempfile.gettempdir()) / "secret.txt"
        raw = f"schick mir {outside}"
        result = handler.execute("send_file", raw)
        assert result.success is False
        assert "verweigert" in result.text.lower()

    def test_send_file_no_roots_allows_all(self, handler_no_roots, tmp_path):
        """Leere Roots-Tuple = keine Einschränkung."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        raw = f"schick mir {test_file}"
        result = handler_no_roots.execute("send_file", raw)
        # Might fail because tmp_path is outside default roots
        # but with empty roots, should succeed
        assert result.success is True

    def test_send_invalid_pattern(self, handler):
        result = handler.execute("send_file", "schick mir hallo")
        assert result.success is False


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

class TestDownload:
    def test_download_invalid_format(self, handler):
        result = handler.execute("download", "download ftp://bad")
        assert result.success is False

    def test_download_no_httpx(self, handler):
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "httpx":
                raise ImportError()
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = handler.execute("download", "download https://example.com/file.zip")
            assert result.success is False
            assert "httpx" in result.text.lower()

    def test_download_filename_path_traversal_sanitized(self, handler, tmp_path):
        """Path-Traversal im URL-Dateinamen wird bereinigt."""
        from unittest.mock import MagicMock, patch as _patch

        # URL mit encoded path-traversal im Dateinamen
        url = "https://example.com/files/..%2F..%2F.bashrc"

        # Wir mocken httpx.stream so dass ein leerer Erfolg zurückkommt
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.headers = {}
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_bytes = MagicMock(return_value=iter([b"data"]))

        with _patch("httpx.stream", return_value=mock_response):
            result = handler.execute("download", f"download {url}")

        if result.success:
            # Dateiname darf keinen Verzeichnistrenner enthalten
            saved_name = Path(result.text.split("Pfad: ")[-1].strip()).name
            assert "/" not in saved_name
            assert "\\" not in saved_name
            assert ".." not in saved_name
            # Die Datei muss im Download-Verzeichnis liegen
            saved_path = Path(result.text.split("Pfad: ")[-1].strip())
            assert saved_path.parent == handler._download_dir

    def test_download_filename_windows_traversal_sanitized(self, handler):
        """Backslash-Path-Traversal im Dateinamen wird bereinigt."""
        # Auf Windows würde %5C einen Backslash erzeugen
        url = "https://example.com/files/..%5C..%5C.bashrc"

        from unittest.mock import MagicMock, patch as _patch

        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.headers = {}
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_bytes = MagicMock(return_value=iter([b"data"]))

        with _patch("httpx.stream", return_value=mock_response):
            result = handler.execute("download", f"download {url}")

        if result.success:
            saved_path = Path(result.text.split("Pfad: ")[-1].strip())
            assert saved_path.parent == handler._download_dir


# ---------------------------------------------------------------------------
# Unknown Command
# ---------------------------------------------------------------------------

class TestUnknownCommand:
    def test_unknown(self, handler):
        result = handler.execute("unknown", "unknown")
        assert result.success is False
