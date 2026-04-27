"""Tests for NextcloudFilesClient (WebDAV operations, all mocked)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from elder_berry.tools.nextcloud_files import (
    MAX_UPLOAD_SIZE_BYTES,
    NextcloudAuthError,
    NextcloudConnectionError,
    NextcloudError,
    NextcloudFilesClient,
)

# ── Fixtures ────────────────────────────────────────────────────────────

SAMPLE_PROPFIND_RESPONSE = """\
<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/files/saleria/</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>saleria</d:displayname>
        <d:resourcetype><d:collection/></d:resourcetype>
        <d:getcontentlength/>
        <d:getlastmodified>Sat, 29 Mar 2026 10:00:00 GMT</d:getlastmodified>
      </d:prop>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/saleria/Dokumente/</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>Dokumente</d:displayname>
        <d:resourcetype><d:collection/></d:resourcetype>
        <d:getcontentlength/>
        <d:getlastmodified>Sat, 29 Mar 2026 09:00:00 GMT</d:getlastmodified>
      </d:prop>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/saleria/report.pdf</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>report.pdf</d:displayname>
        <d:resourcetype/>
        <d:getcontentlength>12345</d:getcontentlength>
        <d:getlastmodified>Sat, 29 Mar 2026 08:30:00 GMT</d:getlastmodified>
      </d:prop>
    </d:propstat>
  </d:response>
</d:multistatus>"""

SAMPLE_PROPFIND_EMPTY = """\
<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/files/saleria/empty/</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>empty</d:displayname>
        <d:resourcetype><d:collection/></d:resourcetype>
        <d:getcontentlength/>
        <d:getlastmodified>Sat, 29 Mar 2026 10:00:00 GMT</d:getlastmodified>
      </d:prop>
    </d:propstat>
  </d:response>
</d:multistatus>"""

SAMPLE_SHARE_RESPONSE = """\
<?xml version="1.0"?>
<ocs>
  <data>
    <url>https://cloud.example.com/s/abc123XYZ</url>
  </data>
</ocs>"""


@pytest.fixture()
def secret_store():
    store = MagicMock()
    store.get_or_none.side_effect = lambda key: {
        "nextcloud_url": "https://cloud.example.com",
        "nextcloud_user": "saleria",
        "nextcloud_app_password": "secret-app-pw",
    }.get(key)
    return store


@pytest.fixture()
def client(secret_store):
    return NextcloudFilesClient(secret_store=secret_store)


@pytest.fixture()
def no_creds_store():
    store = MagicMock()
    store.get_or_none.return_value = None
    return store


# ── Credentials & Availability ──────────────────────────────────────────


def test_init_from_secret_store(client):
    assert client._url == "https://cloud.example.com"
    assert client._user == "saleria"
    assert client._password == "secret-app-pw"


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_is_available_success(mock_req, client):
    mock_req.return_value = MagicMock(status_code=207)
    assert client.is_available() is True


def test_is_available_no_credentials(no_creds_store):
    c = NextcloudFilesClient(secret_store=no_creds_store)
    assert c.is_available() is False


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_is_available_server_unreachable(mock_req, client):
    mock_req.side_effect = httpx.ConnectError("refused")
    assert client.is_available() is False


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_is_available_timeout(mock_req, client):
    mock_req.side_effect = httpx.TimeoutException("timeout")
    assert client.is_available() is False


# ── Upload ──────────────────────────────────────────────────────────────


@patch("elder_berry.tools.nextcloud_files.httpx.request")
@patch("elder_berry.tools.nextcloud_files.httpx.put")
def test_upload_success(mock_put, mock_req, client, tmp_path):
    test_file = tmp_path / "report.pdf"
    test_file.write_bytes(b"PDF content")
    mock_req.return_value = MagicMock(status_code=201)  # MKCOL
    mock_put.return_value = MagicMock(status_code=201)

    result = client.upload(test_file, "Dokumente/report.pdf")

    assert result == "Dokumente/report.pdf"
    mock_put.assert_called_once()
    assert "Dokumente/report.pdf" in mock_put.call_args[0][0]


@patch("elder_berry.tools.nextcloud_files.httpx.request")
@patch("elder_berry.tools.nextcloud_files.httpx.put")
def test_upload_creates_directories(mock_put, mock_req, client, tmp_path):
    test_file = tmp_path / "data.csv"
    test_file.write_bytes(b"csv data")
    mock_req.return_value = MagicMock(status_code=201)  # MKCOL
    mock_put.return_value = MagicMock(status_code=201)

    client.upload(test_file, "deep/nested/dir/data.csv")

    # Should create deep/, deep/nested/, deep/nested/dir/
    assert mock_req.call_count == 3
    for call in mock_req.call_args_list:
        assert call[0][0] == "MKCOL"


def test_upload_file_not_found(client):
    with pytest.raises(FileNotFoundError, match="nicht gefunden"):
        client.upload(Path("/nonexistent/file.txt"), "dest.txt")


def test_upload_file_too_large(client, tmp_path):
    big_file = tmp_path / "huge.bin"
    big_file.write_bytes(b"x")
    # Mock the size check
    with patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value = MagicMock(st_size=MAX_UPLOAD_SIZE_BYTES + 1)
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "is_file", return_value=True):
                with pytest.raises(NextcloudError, match="zu groß"):
                    client.upload(big_file, "huge.bin")


@patch("elder_berry.tools.nextcloud_files.httpx.request")
@patch("elder_berry.tools.nextcloud_files.httpx.put")
def test_upload_server_error(mock_put, mock_req, client, tmp_path):
    test_file = tmp_path / "file.txt"
    test_file.write_bytes(b"data")
    mock_req.return_value = MagicMock(status_code=201)  # MKCOL
    mock_put.return_value = MagicMock(status_code=500)

    with pytest.raises(NextcloudError, match="HTTP 500"):
        client.upload(test_file, "file.txt")


@patch("elder_berry.tools.nextcloud_files.httpx.request")
@patch("elder_berry.tools.nextcloud_files.httpx.put")
def test_upload_auth_error(mock_put, mock_req, client, tmp_path):
    test_file = tmp_path / "file.txt"
    test_file.write_bytes(b"data")
    mock_req.return_value = MagicMock(status_code=201)  # MKCOL
    mock_put.return_value = MagicMock(status_code=401)

    with pytest.raises(NextcloudAuthError):
        client.upload(test_file, "file.txt")


@patch("elder_berry.tools.nextcloud_files.httpx.put")
def test_upload_default_path(mock_put, client, tmp_path):
    test_file = tmp_path / "photo.jpg"
    test_file.write_bytes(b"jpeg")
    mock_put.return_value = MagicMock(status_code=201)

    result = client.upload(test_file, "/")
    assert result == "photo.jpg"


# ── Download ────────────────────────────────────────────────────────────


@patch("elder_berry.tools.nextcloud_files.httpx.get")
def test_download_success(mock_get, client, tmp_path):
    mock_get.return_value = MagicMock(status_code=200, content=b"file data")

    result = client.download("Dokumente/report.pdf", local_dir=tmp_path)

    assert result == tmp_path / "report.pdf"
    assert result.read_bytes() == b"file data"


@patch("elder_berry.tools.nextcloud_files.httpx.get")
def test_download_file_not_found(mock_get, client, tmp_path):
    mock_get.return_value = MagicMock(status_code=404)

    with pytest.raises(NextcloudError, match="nicht gefunden"):
        client.download("missing.txt", local_dir=tmp_path)


@patch("elder_berry.tools.nextcloud_files.httpx.get")
def test_download_custom_dir(mock_get, client, tmp_path):
    custom_dir = tmp_path / "custom"
    mock_get.return_value = MagicMock(status_code=200, content=b"data")

    result = client.download("file.txt", local_dir=custom_dir)

    assert result.parent == custom_dir
    assert result.exists()


# ── List Dir ────────────────────────────────────────────────────────────


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_list_dir_root(mock_req, client):
    mock_req.return_value = MagicMock(
        status_code=207, text=SAMPLE_PROPFIND_RESPONSE
    )

    entries = client.list_dir("/")

    assert len(entries) == 2
    assert entries[0].name == "Dokumente"
    assert entries[0].is_dir is True
    assert entries[1].name == "report.pdf"
    assert entries[1].is_dir is False
    assert entries[1].size == 12345


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_list_dir_subfolder(mock_req, client):
    mock_req.return_value = MagicMock(
        status_code=207, text=SAMPLE_PROPFIND_RESPONSE
    )

    client.list_dir("Dokumente")

    url = mock_req.call_args[1].get("url") or mock_req.call_args[0][1]
    assert "Dokumente/" in url


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_list_dir_empty(mock_req, client):
    mock_req.return_value = MagicMock(
        status_code=207, text=SAMPLE_PROPFIND_EMPTY
    )

    entries = client.list_dir("empty")
    assert entries == []


# ── Search ──────────────────────────────────────────────────────────────


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_search_found(mock_req, client):
    mock_req.return_value = MagicMock(
        status_code=207, text=SAMPLE_PROPFIND_RESPONSE
    )

    results = client.search("report")

    assert len(results) == 1
    assert results[0].name == "report.pdf"


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_search_case_insensitive(mock_req, client):
    mock_req.return_value = MagicMock(
        status_code=207, text=SAMPLE_PROPFIND_RESPONSE
    )

    results = client.search("REPORT")
    assert len(results) == 1


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_search_no_results(mock_req, client):
    mock_req.return_value = MagicMock(
        status_code=207, text=SAMPLE_PROPFIND_RESPONSE
    )

    results = client.search("nonexistent")
    assert results == []


_PROPFIND_SEPARATOR = """\
<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/files/saleria/</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>saleria</d:displayname>
        <d:resourcetype><d:collection/></d:resourcetype>
        <d:getcontentlength/>
        <d:getlastmodified>Sat, 29 Mar 2026 10:00:00 GMT</d:getlastmodified>
      </d:prop>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/saleria/2026-04-08_Haus_PV-Angebot.pdf</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>2026-04-08_Haus_PV-Angebot.pdf</d:displayname>
        <d:resourcetype/>
        <d:getcontentlength>102400</d:getcontentlength>
        <d:getlastmodified>Tue, 08 Apr 2026 14:00:00 GMT</d:getlastmodified>
      </d:prop>
    </d:propstat>
  </d:response>
</d:multistatus>"""


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_search_separator_normalization(mock_req, client):
    """'pv angebot' (space) should match 'PV-Angebot' (hyphen)."""
    mock_req.return_value = MagicMock(
        status_code=207, text=_PROPFIND_SEPARATOR
    )

    results = client.search("pv angebot")
    assert len(results) == 1
    assert "PV-Angebot" in results[0].name


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_search_separator_underscore(mock_req, client):
    """'haus pv' should match 'Haus_PV-Angebot' (underscore + hyphen)."""
    mock_req.return_value = MagicMock(
        status_code=207, text=_PROPFIND_SEPARATOR
    )

    results = client.search("haus pv")
    assert len(results) == 1


# ── Share Link (intern, kein öffentlicher Link) ───────────────────────


_FILEID_PROPFIND_RESPONSE = """\
<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:response>
    <d:href>/remote.php/dav/files/testuser/report.pdf</d:href>
    <d:propstat>
      <d:prop><oc:fileid>12345</oc:fileid></d:prop>
    </d:propstat>
  </d:response>
</d:multistatus>"""


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_share_link_success(mock_request, client):
    mock_request.return_value = MagicMock(
        status_code=207, text=_FILEID_PROPFIND_RESPONSE,
    )

    url = client.share_link("report.pdf")

    assert url == "https://cloud.example.com/f/12345"


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_share_link_not_found(mock_request, client):
    mock_request.return_value = MagicMock(status_code=404)

    with pytest.raises(NextcloudError, match="nicht gefunden"):
        client.share_link("missing.pdf")


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_share_link_auth_error(mock_request, client):
    mock_request.return_value = MagicMock(status_code=403)

    with pytest.raises(NextcloudAuthError):
        client.share_link("file.txt")


# ── mkdir ──────────────────────────────────────────────────────────────


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_mkdir_creates_new_directory(mock_req, client):
    mock_req.return_value = MagicMock(status_code=201)

    result = client.mkdir("Manuale/Elektronik")

    assert result is True
    mock_req.assert_called_once()
    assert mock_req.call_args[0][0] == "MKCOL"


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_mkdir_existing_directory(mock_req, client):
    mock_req.return_value = MagicMock(status_code=405)

    result = client.mkdir("Dokumente")

    assert result is False


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_mkdir_conflict_raises(mock_req, client):
    mock_req.return_value = MagicMock(status_code=409)

    with pytest.raises(NextcloudError, match="MKCOL fehlgeschlagen"):
        client.mkdir("Manuale/Elektronik")


def test_mkdir_no_credentials_raises(no_creds_store):
    c = NextcloudFilesClient(secret_store=no_creds_store)
    with pytest.raises(NextcloudError, match="Credentials"):
        c.mkdir("test")


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_mkdir_auth_error_raises(mock_req, client):
    mock_req.return_value = MagicMock(status_code=401)

    with pytest.raises(NextcloudAuthError):
        client.mkdir("test")


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_mkdir_connection_error(mock_req, client):
    mock_req.side_effect = httpx.ConnectError("refused")

    with pytest.raises(NextcloudConnectionError, match="nicht erreichbar"):
        client.mkdir("test")


# ── delete ─────────────────────────────────────────────────────────────


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_delete_file(mock_req, client):
    mock_req.return_value = MagicMock(status_code=204)

    client.delete("report.pdf")  # should not raise

    mock_req.assert_called_once()
    assert mock_req.call_args[0][0] == "DELETE"


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_delete_directory(mock_req, client):
    mock_req.return_value = MagicMock(status_code=204)

    client.delete("Documents")


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_delete_not_found_is_idempotent(mock_req, client):
    mock_req.return_value = MagicMock(status_code=404)

    client.delete("already-gone.txt")  # should not raise


def test_delete_no_credentials_raises(no_creds_store):
    c = NextcloudFilesClient(secret_store=no_creds_store)
    with pytest.raises(NextcloudError, match="Credentials"):
        c.delete("test")


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_delete_auth_error_raises(mock_req, client):
    mock_req.return_value = MagicMock(status_code=401)

    with pytest.raises(NextcloudAuthError):
        client.delete("test")


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_delete_server_error_raises(mock_req, client):
    mock_req.return_value = MagicMock(status_code=500)

    with pytest.raises(NextcloudError, match="DELETE fehlgeschlagen"):
        client.delete("test")


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_delete_connection_error(mock_req, client):
    mock_req.side_effect = httpx.TimeoutException("timeout")

    with pytest.raises(NextcloudConnectionError, match="nicht erreichbar"):
        client.delete("test")


# ── Move ───────────────────────────────────────────────────────────────


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_move_success_201(mock_req, client):
    mock_req.return_value = MagicMock(status_code=201)

    result = client.move("Eingang/Scan.pdf", "Dokumente/Haus/2026-04-02_Haus_Angebot.pdf")

    assert result == "Dokumente/Haus/2026-04-02_Haus_Angebot.pdf"
    # Finde den MOVE-Aufruf (nach ggf. MKCOL-Aufrufen für Zielordner)
    move_calls = [c for c in mock_req.call_args_list if c[0][0] == "MOVE"]
    assert len(move_calls) == 1
    call_kwargs = move_calls[0]
    assert call_kwargs.kwargs["headers"]["Overwrite"] == "F"
    assert "Dokumente/Haus/2026-04-02_Haus_Angebot.pdf" in call_kwargs.kwargs["headers"]["Destination"]


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_move_success_204(mock_req, client):
    mock_req.return_value = MagicMock(status_code=204)

    result = client.move("Eingang/Scan.pdf", "Dokumente/Haus/Angebot.pdf")

    assert result == "Dokumente/Haus/Angebot.pdf"


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_move_creates_target_dir(mock_req, client):
    """MKCOL wird für Ziel-Ordner aufgerufen bevor MOVE."""
    # MKCOL für "Dokumente" → 405 (existiert), MKCOL für "Dokumente/Haus" → 201,
    # MOVE → 201
    mock_req.side_effect = [
        MagicMock(status_code=405),  # MKCOL Dokumente
        MagicMock(status_code=201),  # MKCOL Dokumente/Haus
        MagicMock(status_code=201),  # MOVE
    ]

    client.move("Eingang/Scan.pdf", "Dokumente/Haus/Angebot.pdf")

    methods = [c[0][0] for c in mock_req.call_args_list]
    assert methods.count("MKCOL") == 2
    assert methods[-1] == "MOVE"


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_move_file_exists_412(mock_req, client):
    mock_req.return_value = MagicMock(status_code=412)

    with pytest.raises(NextcloudError, match="existiert bereits"):
        client.move("Eingang/Scan.pdf", "Dokumente/Haus/Angebot.pdf")


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_move_source_not_found_404(mock_req, client):
    mock_req.return_value = MagicMock(status_code=404)

    with pytest.raises(NextcloudError, match="nicht gefunden"):
        client.move("Eingang/Scan.pdf", "Dokumente/Haus/Angebot.pdf")


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_move_auth_error(mock_req, client):
    mock_req.return_value = MagicMock(status_code=401)

    with pytest.raises(NextcloudAuthError, match="Authentifizierung"):
        client.move("Eingang/Scan.pdf", "Dokumente/Haus/Angebot.pdf")


@patch("elder_berry.tools.nextcloud_files.httpx.request")
def test_move_connection_error(mock_req, client):
    mock_req.side_effect = httpx.TimeoutException("timeout")

    with pytest.raises(NextcloudConnectionError, match="nicht erreichbar"):
        client.move("Eingang/Scan.pdf", "Dokumente/Haus/Angebot.pdf")


def test_move_no_credentials(no_creds_store):
    c = NextcloudFilesClient(secret_store=no_creds_store)

    with pytest.raises(NextcloudError, match="Credentials"):
        c.move("Eingang/Scan.pdf", "Dokumente/Haus/Angebot.pdf")
