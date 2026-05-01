"""Tests für Nextcloud File-Hub (Phase 39).

Testet: File-Output über NC + Share-Link, Inhaltssuche, Fallback auf Matrix.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from elder_berry.comms.commands.cloud_commands import (
    CLOUD_CONTENT_SEARCH_PATTERN,
    CloudCommandHandler,
)
from elder_berry.comms.message_handlers import BridgeMessageHandler
from elder_berry.tools.nextcloud_files import NextcloudFilesClient

USER = "@test:matrix.org"


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def nc_client() -> MagicMock:
    mock = MagicMock(spec=NextcloudFilesClient)
    mock.upload.return_value = "Saleria/2026-03/test.pdf"
    mock.share_link.return_value = "https://cloud.example.com/s/abc123"
    mock.search_content.return_value = [
        {
            "name": "Mietvertrag.pdf",
            "path": "Dokumente/Mietvertrag.pdf",
            "excerpt": "...monatliche Miete beträgt 850 EUR...",
        },
        {
            "name": "Rechnung_2026.pdf",
            "path": "Rechnungen/Rechnung_2026.pdf",
            "excerpt": "...Rechnung Nr. 4711...",
        },
    ]
    return mock


def _make_handler(nc_client: MagicMock | None = None) -> BridgeMessageHandler:
    channel = AsyncMock()
    channel.send_text = AsyncMock()
    channel.send_file = AsyncMock()
    return BridgeMessageHandler(
        channel=channel,
        assistant=MagicMock(),
        audio_pipeline=MagicMock(),
        chat_history=MagicMock(),
        pending=MagicMock(),
        nextcloud_files=nc_client,
    )


# ── File-Hub Tests ────────────────────────────────────────────────────


class TestFileHub:
    """Tests für _send_file_via_nc_or_matrix."""

    def test_file_uploaded_to_nc_and_shared(
        self,
        nc_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Datei wird auf NC hochgeladen und Share-Link gesendet."""
        handler = _make_handler(nc_client)
        test_file = tmp_path / "report.pdf"
        test_file.write_text("dummy")

        asyncio.run(
            handler._send_file_via_nc_or_matrix(
                "!room:test",
                test_file,
            )
        )

        nc_client.upload.assert_called_once()
        nc_client.share_link.assert_called_once()
        handler._channel.send_text.assert_called_once()
        text = handler._channel.send_text.call_args[0][1]
        assert "report.pdf" in text
        assert "https://cloud.example.com/s/abc123" in text

    def test_fallback_to_matrix_when_nc_unavailable(
        self,
        tmp_path: Path,
    ) -> None:
        """Ohne NC-Client wird die Datei direkt per Matrix gesendet."""
        handler = _make_handler(None)
        test_file = tmp_path / "report.pdf"
        test_file.write_text("dummy")

        asyncio.run(
            handler._send_file_via_nc_or_matrix(
                "!room:test",
                test_file,
            )
        )

        handler._channel.send_file.assert_called_once_with(
            "!room:test",
            test_file,
        )

    def test_fallback_to_matrix_on_nc_error(
        self,
        nc_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Bei NC-Upload-Fehler → Fallback auf Matrix."""
        nc_client.upload.side_effect = Exception("Connection refused")
        handler = _make_handler(nc_client)
        test_file = tmp_path / "report.pdf"
        test_file.write_text("dummy")

        asyncio.run(
            handler._send_file_via_nc_or_matrix(
                "!room:test",
                test_file,
            )
        )

        handler._channel.send_file.assert_called_once()

    def test_cleanup_after_nc_upload(
        self,
        nc_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Mit cleanup=True wird die Datei nach NC-Upload gelöscht."""
        handler = _make_handler(nc_client)
        test_file = tmp_path / "temp.pdf"
        test_file.write_text("dummy")
        assert test_file.exists()

        asyncio.run(
            handler._send_file_via_nc_or_matrix(
                "!room:test",
                test_file,
                cleanup=True,
            )
        )

        assert not test_file.exists()


# ── Content Search Pattern Tests ──────────────────────────────────────


class TestContentSearchPattern:
    def test_cloud_inhalt(self) -> None:
        m = CLOUD_CONTENT_SEARCH_PATTERN.match("cloud inhalt Mietvertrag")
        assert m is not None
        assert m.group(1) == "Mietvertrag"

    def test_cloud_durchsuche(self) -> None:
        m = CLOUD_CONTENT_SEARCH_PATTERN.match("cloud durchsuche Rechnung 2026")
        assert m is not None
        assert m.group(1) == "Rechnung 2026"

    def test_cloud_volltext(self) -> None:
        m = CLOUD_CONTENT_SEARCH_PATTERN.match("cloud volltext Mietvertrag")
        assert m is not None

    def test_no_match_cloud_suche(self) -> None:
        """cloud suche darf NICHT als content search matchen."""
        assert CLOUD_CONTENT_SEARCH_PATTERN.match("cloud suche test") is None


# ── Content Search Execution Tests ────────────────────────────────────


class TestContentSearchExecution:
    def test_content_search_results(self, nc_client: MagicMock) -> None:
        handler = CloudCommandHandler(nextcloud_files=nc_client)
        r = handler.execute("cloud_content_search", "cloud inhalt Mietvertrag")
        assert r.success
        assert "2 Treffer" in r.text
        assert "Mietvertrag.pdf" in r.text
        assert "850 EUR" in r.text

    def test_content_search_no_results(self, nc_client: MagicMock) -> None:
        nc_client.search_content.return_value = []
        handler = CloudCommandHandler(nextcloud_files=nc_client)
        r = handler.execute("cloud_content_search", "cloud inhalt Galaxie")
        assert r.success
        assert "Keine Dateien" in r.text

    def test_content_search_no_nc(self) -> None:
        handler = CloudCommandHandler(nextcloud_files=None)
        r = handler.execute("cloud_content_search", "cloud inhalt test")
        assert not r.success
        assert "nicht konfiguriert" in r.text

    def test_content_search_error(self, nc_client: MagicMock) -> None:
        nc_client.search_content.side_effect = Exception("Server error")
        handler = CloudCommandHandler(nextcloud_files=nc_client)
        r = handler.execute("cloud_content_search", "cloud inhalt test")
        assert not r.success
        assert "❌" in r.text


# ── NC Upload + Share Tests ───────────────────────────────────────────


class TestUploadToNcAndShare:
    def test_upload_path_includes_month(
        self,
        nc_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Upload-Pfad enthält Saleria/YYYY-MM/dateiname."""
        handler = _make_handler(nc_client)
        test_file = tmp_path / "doc.pdf"
        test_file.write_text("dummy")

        link = asyncio.run(handler._upload_to_nc_and_share(test_file))

        assert link == "https://cloud.example.com/s/abc123"
        upload_call = nc_client.upload.call_args
        remote_path = upload_call[0][1]
        assert remote_path.startswith("Saleria/")
        assert "doc.pdf" in remote_path

    def test_returns_none_on_error(
        self,
        nc_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Bei Fehler → None (Fallback wird vom Caller gehandelt)."""
        nc_client.upload.side_effect = Exception("Disk full")
        handler = _make_handler(nc_client)
        test_file = tmp_path / "doc.pdf"
        test_file.write_text("dummy")

        link = asyncio.run(handler._upload_to_nc_and_share(test_file))
        assert link is None
