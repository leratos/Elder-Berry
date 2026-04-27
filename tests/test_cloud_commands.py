"""Tests for CloudCommandHandler (Nextcloud commands via Matrix)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.cloud_commands import (
    CLOUD_DOWNLOAD_PATTERN,
    CLOUD_LINK_PATTERN,
    CLOUD_LIST_PATTERN,
    CLOUD_SEARCH_PATTERN,
    CLOUD_UPLOAD_PATTERN,
    NEXTCLOUD_SETUP_PATTERN,
    CloudCommandHandler,
    _NC_TARGET_DIRS,
)
from elder_berry.tools.nextcloud_files import NextcloudFile


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def nc_client():
    return MagicMock()


@pytest.fixture()
def handler(nc_client):
    return CloudCommandHandler(nextcloud_files=nc_client)


@pytest.fixture()
def handler_no_nc():
    return CloudCommandHandler(nextcloud_files=None)


# ── Pattern Matching ────────────────────────────────────────────────────


def test_cloud_upload_pattern_windows():
    m = CLOUD_UPLOAD_PATTERN.match("cloud upload C:\\Users\\user\\report.pdf")
    assert m is not None
    assert m.group(1) == "C:\\Users\\user\\report.pdf"


def test_cloud_upload_pattern_linux():
    m = CLOUD_UPLOAD_PATTERN.match("cloud upload /home/user/report.pdf")
    assert m is not None
    assert m.group(1) == "/home/user/report.pdf"


def test_cloud_upload_pattern_with_dest():
    m = CLOUD_UPLOAD_PATTERN.match("cloud upload C:\\file.txt Backup/file.txt")
    assert m is not None
    assert m.group(1) == "C:\\file.txt"
    assert m.group(2) == "Backup/file.txt"


def test_cloud_download_pattern():
    m = CLOUD_DOWNLOAD_PATTERN.match("cloud download Dokumente/report.pdf")
    assert m is not None
    assert m.group(1) == "Dokumente/report.pdf"


def test_cloud_list_pattern_no_folder():
    m = CLOUD_LIST_PATTERN.match("cloud dateien")
    assert m is not None
    assert m.group(1) is None


def test_cloud_list_pattern_with_folder():
    m = CLOUD_LIST_PATTERN.match("cloud ls Dokumente")
    assert m is not None
    assert m.group(1) == "Dokumente"


def test_cloud_list_pattern_list_variant():
    m = CLOUD_LIST_PATTERN.match("cloud list Bilder")
    assert m is not None
    assert m.group(1) == "Bilder"


def test_cloud_search_pattern():
    m = CLOUD_SEARCH_PATTERN.match("cloud suche report")
    assert m is not None
    assert m.group(1) == "report"


def test_cloud_search_pattern_find():
    m = CLOUD_SEARCH_PATTERN.match("cloud find budget")
    assert m is not None


def test_cloud_link_pattern():
    m = CLOUD_LINK_PATTERN.match("cloud link Dokumente/report.pdf")
    assert m is not None
    assert m.group(1) == "Dokumente/report.pdf"


def test_cloud_link_pattern_share():
    m = CLOUD_LINK_PATTERN.match("cloud share report.pdf")
    assert m is not None


def test_cloud_link_pattern_teile():
    m = CLOUD_LINK_PATTERN.match("cloud teile bild.png")
    assert m is not None


def test_no_collision_with_existing_patterns():
    """Ensure 'cloud ...' doesn't match patterns from other handlers."""
    from elder_berry.comms.commands.file_commands import (
        CLIP_WRITE_PATTERN,
        DOWNLOAD_PATTERN,
        SEND_FILE_PATTERN,
    )

    cloud_texts = [
        "cloud upload C:\\test.txt",
        "cloud download test.txt",
        "cloud dateien",
        "cloud suche test",
        "cloud link test.txt",
    ]

    other_patterns = [CLIP_WRITE_PATTERN, SEND_FILE_PATTERN, DOWNLOAD_PATTERN]
    for text in cloud_texts:
        for pattern in other_patterns:
            assert pattern.match(text) is None, (
                f"'{text}' unexpectedly matched {pattern.pattern}"
            )
            assert pattern.search(text) is None, (
                f"'{text}' unexpectedly search-matched {pattern.pattern}"
            )


# ── Execution: No Nextcloud ─────────────────────────────────────────────


def test_upload_no_nextcloud(handler_no_nc):
    result = handler_no_nc.execute("cloud_upload", "cloud upload C:\\test.txt")
    assert result.success is False
    assert "nicht konfiguriert" in result.text


def test_download_no_nextcloud(handler_no_nc):
    result = handler_no_nc.execute("cloud_download", "cloud download test.txt")
    assert result.success is False
    assert "nicht konfiguriert" in result.text


# ── Execution: Upload ───────────────────────────────────────────────────


def test_upload_success(handler, nc_client, tmp_path):
    test_file = tmp_path / "report.pdf"
    test_file.write_bytes(b"PDF content")
    nc_client.upload.return_value = "Saleria/report.pdf"

    result = handler.execute(
        "cloud_upload", f"cloud upload {test_file}"
    )

    assert result.success is True
    assert "Hochgeladen" in result.text
    assert "Saleria/report.pdf" in result.text


def test_upload_file_not_found(handler):
    result = handler.execute(
        "cloud_upload", "cloud upload C:\\nonexistent\\file.txt"
    )
    assert result.success is False
    assert "nicht gefunden" in result.text


# ── Execution: Download ─────────────────────────────────────────────────


def test_download_success(handler, nc_client, tmp_path):
    dl_path = tmp_path / "report.pdf"
    dl_path.write_bytes(b"data")
    nc_client.download.return_value = dl_path

    result = handler.execute("cloud_download", "cloud download Dokumente/report.pdf")

    assert result.success is True
    assert "Heruntergeladen" in result.text
    assert result.file_path == dl_path


# ── Execution: List ─────────────────────────────────────────────────────


def test_list_success(handler, nc_client):
    nc_client.list_dir.return_value = [
        NextcloudFile("Dokumente", "Dokumente", True, 0, ""),
        NextcloudFile("report.pdf", "report.pdf", False, 12345, ""),
    ]

    result = handler.execute("cloud_list", "cloud dateien")

    assert result.success is True
    assert "\U0001f4c1 Dokumente/" in result.text
    assert "\U0001f4c4 report.pdf" in result.text
    assert "12.1 KB" in result.text


def test_list_empty(handler, nc_client):
    nc_client.list_dir.return_value = []

    result = handler.execute("cloud_list", "cloud dateien")

    assert result.success is True
    assert "leer" in result.text


def test_list_truncated(handler, nc_client):
    entries = [
        NextcloudFile(f"file_{i}.txt", f"file_{i}.txt", False, 100, "")
        for i in range(25)
    ]
    nc_client.list_dir.return_value = entries

    result = handler.execute("cloud_list", "cloud dateien")

    assert result.success is True
    assert "(und 5 weitere)" in result.text


# ── Execution: Search ───────────────────────────────────────────────────


def test_search_success(handler, nc_client):
    nc_client.search.return_value = [
        NextcloudFile("report.pdf", "Dokumente/report.pdf", False, 5000, ""),
    ]
    nc_client.share_link.return_value = "https://cloud.example.com/s/abc123"

    result = handler.execute("cloud_search", "cloud suche report")

    assert result.success is True
    assert "report.pdf" in result.text
    assert "https://cloud.example.com/s/abc123" in result.text


def test_search_no_results(handler, nc_client):
    nc_client.search.return_value = []

    result = handler.execute("cloud_search", "cloud suche xyz")

    assert result.success is True
    assert "Keine Ergebnisse" in result.text


# ── Execution: Share Link ───────────────────────────────────────────────


def test_share_link_success(handler, nc_client):
    nc_client.share_link.return_value = "https://cloud.example.com/s/abc123"

    result = handler.execute("cloud_link", "cloud link report.pdf")

    assert result.success is True
    assert "https://cloud.example.com/s/abc123" in result.text


# ── command_descriptions ────────────────────────────────────────────────


def test_cloud_commands_in_help(handler):
    descs = handler.command_descriptions
    assert len(descs) == 7
    assert any("upload" in d for d in descs)
    assert any("download" in d for d in descs)
    assert any("dateien" in d for d in descs)
    assert any("suche" in d for d in descs)
    assert any("inhalt" in d for d in descs)
    assert any("link" in d for d in descs)
    assert any("nextcloud ein" in d for d in descs)


# ── Pattern: Nextcloud Setup ───────────────────────────────────────────


def test_setup_pattern_richte_nextcloud_ein():
    assert NEXTCLOUD_SETUP_PATTERN.search("richte nextcloud ein") is not None


def test_setup_pattern_nextcloud_setup():
    assert NEXTCLOUD_SETUP_PATTERN.search("nextcloud setup") is not None


def test_setup_pattern_nextcloud_dash_setup():
    assert NEXTCLOUD_SETUP_PATTERN.search("nextcloud-setup") is not None


def test_setup_pattern_cloud_einrichten():
    assert NEXTCLOUD_SETUP_PATTERN.search("cloud einrichten") is not None


def test_setup_pattern_case_insensitive():
    assert NEXTCLOUD_SETUP_PATTERN.search("Richte Nextcloud Ein") is not None


def test_setup_pattern_no_false_positive():
    assert NEXTCLOUD_SETUP_PATTERN.search("cloud suche nextcloud") is None


# ── Execution: Nextcloud Setup ─────────────────────────────────────────


def test_setup_no_nextcloud(handler_no_nc):
    result = handler_no_nc.execute("nextcloud_setup", "richte nextcloud ein")
    assert result.success is False
    assert "nicht konfiguriert" in result.text


def test_setup_returns_confirmation_request(handler, nc_client):
    nc_client.list_dir.return_value = [
        NextcloudFile("Documents", "Documents", True, 0, ""),
        NextcloudFile("Photos", "Photos", True, 0, ""),
        NextcloudFile("Nextcloud.png", "Nextcloud.png", False, 1000, ""),
        NextcloudFile("MyStuff", "MyStuff", True, 0, ""),
    ]

    result = handler.execute("nextcloud_setup", "richte nextcloud ein")

    assert result.success is True
    assert result.pending_confirmation is True
    assert result.pending_data is not None
    assert "Bestätigen?" in result.text


def test_setup_lists_only_existing_defaults(handler, nc_client):
    nc_client.list_dir.return_value = [
        NextcloudFile("Documents", "Documents", True, 0, ""),
        NextcloudFile("MyStuff", "MyStuff", True, 0, ""),
    ]

    result = handler.execute("nextcloud_setup", "richte nextcloud ein")

    assert result.pending_data["to_delete"] == ["Documents"]
    # Non-default "MyStuff" should not be in delete list
    assert "MyStuff" not in result.pending_data["to_delete"]


def test_setup_empty_root_skips_delete(handler, nc_client):
    nc_client.list_dir.return_value = []

    result = handler.execute("nextcloud_setup", "richte nextcloud ein")

    assert result.pending_data["to_delete"] == []
    assert "nichts zu löschen" in result.text


def test_setup_pending_data_contains_target_dirs(handler, nc_client):
    nc_client.list_dir.return_value = []

    result = handler.execute("nextcloud_setup", "richte nextcloud ein")

    assert result.pending_data["to_create"] == list(_NC_TARGET_DIRS)


def test_setup_parent_before_child_order():
    """Verify _NC_TARGET_DIRS has parents before children."""
    seen = set()
    for d in _NC_TARGET_DIRS:
        if "/" in d:
            parent = d.rsplit("/", 1)[0]
            assert parent in seen, (
                f"Parent '{parent}' must appear before child '{d}'"
            )
        seen.add(d)


def test_setup_list_dir_error(handler, nc_client):
    nc_client.list_dir.side_effect = Exception("server down")

    result = handler.execute("nextcloud_setup", "richte nextcloud ein")

    assert result.success is False
    assert "Nextcloud" in result.text
