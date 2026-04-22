"""Tests für IMAPEmailClient.copy_to_sent_folder + _detect_sent_folder."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from elder_berry.tools.email_client import IMAPEmailClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client() -> IMAPEmailClient:
    return IMAPEmailClient(
        host="imap.example.com",
        user="test@example.com",
        password="secret",
        port=993,
    )


SAMPLE_MSG = (
    b"From: Test <test@example.com>\r\n"
    b"To: recipient@example.com\r\n"
    b"Subject: Re: Test\r\n"
    b"\r\n"
    b"Hallo!\r\n"
)


# ---------------------------------------------------------------------------
# copy_to_sent_folder
# ---------------------------------------------------------------------------

class TestCopyToSentFolder:
    @patch.object(IMAPEmailClient, "_connect")
    @patch.object(IMAPEmailClient, "_detect_sent_folder", return_value="Sent")
    def test_success_auto_detect(self, mock_detect, mock_connect, client):
        mock_conn = MagicMock()
        mock_conn.append.return_value = ("OK", [b"APPEND completed"])
        mock_connect.return_value = mock_conn

        result = client.copy_to_sent_folder(SAMPLE_MSG)

        assert result is True
        mock_detect.assert_called_once_with(mock_conn)
        mock_conn.append.assert_called_once_with(
            "Sent", "\\Seen", None, SAMPLE_MSG,
        )
        mock_conn.logout.assert_called_once()

    @patch.object(IMAPEmailClient, "_connect")
    def test_success_explicit_folder(self, mock_connect, client):
        mock_conn = MagicMock()
        mock_conn.append.return_value = ("OK", [b"done"])
        mock_connect.return_value = mock_conn

        result = client.copy_to_sent_folder(SAMPLE_MSG, sent_folder="INBOX.Sent")

        assert result is True
        mock_conn.append.assert_called_once_with(
            "INBOX.Sent", "\\Seen", None, SAMPLE_MSG,
        )

    @patch.object(IMAPEmailClient, "_connect")
    @patch.object(IMAPEmailClient, "_detect_sent_folder", return_value="")
    def test_no_sent_folder_found(self, mock_detect, mock_connect, client):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        result = client.copy_to_sent_folder(SAMPLE_MSG)

        assert result is False
        mock_conn.append.assert_not_called()
        mock_conn.logout.assert_called_once()

    @patch.object(IMAPEmailClient, "_connect")
    @patch.object(IMAPEmailClient, "_detect_sent_folder", return_value="Sent")
    def test_append_failure(self, mock_detect, mock_connect, client):
        mock_conn = MagicMock()
        mock_conn.append.return_value = ("NO", [b"Permission denied"])
        mock_connect.return_value = mock_conn

        result = client.copy_to_sent_folder(SAMPLE_MSG)

        assert result is False

    @patch.object(IMAPEmailClient, "_connect")
    def test_connection_error(self, mock_connect, client):
        mock_connect.side_effect = OSError("Connection refused")

        result = client.copy_to_sent_folder(SAMPLE_MSG)

        assert result is False


# ---------------------------------------------------------------------------
# _detect_sent_folder
# ---------------------------------------------------------------------------

class TestDetectSentFolder:
    def test_finds_sent_via_list_attribute(self):
        mock_conn = MagicMock()
        mock_conn.list.return_value = ("OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\Sent \\HasNoChildren) "/" "Sent"',
            b'(\\Trash \\HasNoChildren) "/" "Trash"',
        ])

        result = IMAPEmailClient._detect_sent_folder(mock_conn)

        assert result == "Sent"

    def test_finds_gesendet_via_list_attribute(self):
        mock_conn = MagicMock()
        mock_conn.list.return_value = ("OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\Sent \\HasNoChildren) "/" "Gesendet"',
        ])

        result = IMAPEmailClient._detect_sent_folder(mock_conn)

        assert result == "Gesendet"

    def test_fallback_to_known_names(self):
        mock_conn = MagicMock()
        # LIST liefert kein \Sent-Attribut
        mock_conn.list.return_value = ("OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Drafts"',
        ])
        # select("Sent") OK, alle anderen fehlschlagen
        def mock_select(folder, readonly=True):
            if folder == "Sent":
                return ("OK", [b"42"])
            raise Exception(f"No such folder: {folder}")

        mock_conn.select.side_effect = mock_select
        mock_conn.close.return_value = ("OK", [])

        result = IMAPEmailClient._detect_sent_folder(mock_conn)

        assert result == "Sent"

    def test_fallback_inbox_sent(self):
        mock_conn = MagicMock()
        mock_conn.list.return_value = ("OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
        ])

        def mock_select(folder, readonly=True):
            if folder == "INBOX.Sent":
                return ("OK", [b"5"])
            raise Exception(f"No such folder: {folder}")

        mock_conn.select.side_effect = mock_select
        mock_conn.close.return_value = ("OK", [])

        result = IMAPEmailClient._detect_sent_folder(mock_conn)

        assert result == "INBOX.Sent"

    def test_no_folder_found(self):
        mock_conn = MagicMock()
        mock_conn.list.return_value = ("OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
        ])
        mock_conn.select.side_effect = Exception("No such folder")

        result = IMAPEmailClient._detect_sent_folder(mock_conn)

        assert result == ""

    def test_list_exception_falls_through(self):
        mock_conn = MagicMock()
        mock_conn.list.side_effect = Exception("LIST failed")
        # Fallback: Sent existiert
        def mock_select(folder, readonly=True):
            if folder == "Sent":
                return ("OK", [b"1"])
            raise Exception("nope")

        mock_conn.select.side_effect = mock_select
        mock_conn.close.return_value = ("OK", [])

        result = IMAPEmailClient._detect_sent_folder(mock_conn)

        assert result == "Sent"
