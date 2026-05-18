"""Tests fuer NextcloudNotesClient -- HTTP komplett gemockt (httpx.Client)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from elder_berry.tools.nextcloud_notes_client import (
    NextcloudNote,
    NextcloudNotesClient,
    NextcloudNotesError,
)

_HTTPX_CLIENT = "elder_berry.tools.nextcloud_notes_client.httpx.Client"


# ── Helpers ──────────────────────────────────────────────────────────


def _make_secret_store(**overrides):
    """Mock-SecretStore mit Nextcloud-Credentials (Keys wie CalDAV)."""
    defaults = {
        "nextcloud_url": "https://cloud.example.com",
        "nextcloud_user": "testuser",
        "nextcloud_app_password": "secret123",
    }
    defaults.update(overrides)

    store = MagicMock()
    store.get.side_effect = lambda key: defaults[key]
    store.get_or_none.side_effect = lambda key: defaults.get(key)
    return store


def _make_response(status_code=200, json_data=None, json_error=False):
    """Mock-httpx.Response mit status_code + json()."""
    resp = MagicMock()
    resp.status_code = status_code
    if json_error:
        resp.json.side_effect = ValueError("Expecting value")
    else:
        resp.json.return_value = json_data
    return resp


def _install_client(mock_client_cls, *, response=None, request_side_effect=None):
    """Verdrahtet den gemockten ``httpx.Client``-Context-Manager.

    Gibt den inneren Client-Mock zurueck (das ``as client``-Objekt),
    auf dem ``.request`` inspiziert werden kann.
    """
    client = MagicMock()
    cm = mock_client_cls.return_value
    cm.__enter__.return_value = client
    cm.__exit__.return_value = False
    if request_side_effect is not None:
        client.request.side_effect = request_side_effect
    else:
        client.request.return_value = response
    return client


def _note_json(note_id=1, content="Testnotiz", category="", modified=1000, title=None):
    """Ein API-Notiz-Objekt wie es Nextcloud Notes v1 liefert."""
    return {
        "id": note_id,
        "etag": "etag-%d" % note_id,
        "modified": modified,
        "title": title if title is not None else content.split("\n")[0],
        "content": content,
        "category": category,
        "favorite": False,
    }


# ── Konstruktion ─────────────────────────────────────────────────────


class TestConstruction:
    def test_credentials_loaded(self):
        client = NextcloudNotesClient(_make_secret_store())
        assert client._has_credentials is True

    def test_api_base(self):
        client = NextcloudNotesClient(_make_secret_store())
        assert client._api_base == (
            "https://cloud.example.com/index.php/apps/notes/api/v1/"
        )

    def test_api_base_strips_trailing_slash(self):
        store = _make_secret_store(nextcloud_url="https://cloud.example.com/")
        client = NextcloudNotesClient(store)
        assert client._api_base == (
            "https://cloud.example.com/index.php/apps/notes/api/v1/"
        )

    def test_auth_tuple(self):
        client = NextcloudNotesClient(_make_secret_store())
        assert client._auth == ("testuser", "secret123")

    def test_missing_credentials(self):
        store = _make_secret_store(nextcloud_app_password=None)
        client = NextcloudNotesClient(store)
        assert client._has_credentials is False

    def test_request_without_credentials_raises(self):
        store = _make_secret_store(nextcloud_url=None)
        client = NextcloudNotesClient(store)
        with pytest.raises(NextcloudNotesError):
            client.list_notes()

    def test_custom_timeout(self):
        client = NextcloudNotesClient(_make_secret_store(), timeout=3.0)
        assert client._timeout == 3.0


# ── is_available ─────────────────────────────────────────────────────


class TestIsAvailable:
    @patch(_HTTPX_CLIENT)
    def test_available_true(self, mock_client_cls):
        _install_client(mock_client_cls, response=_make_response(200, []))
        client = NextcloudNotesClient(_make_secret_store())
        assert client.is_available() is True

    def test_available_no_credentials(self):
        store = _make_secret_store(nextcloud_user=None)
        client = NextcloudNotesClient(store)
        assert client.is_available() is False

    @patch(_HTTPX_CLIENT)
    def test_available_server_error(self, mock_client_cls):
        _install_client(mock_client_cls, response=_make_response(500))
        client = NextcloudNotesClient(_make_secret_store())
        assert client.is_available() is False

    @patch(_HTTPX_CLIENT)
    def test_available_transport_error(self, mock_client_cls):
        _install_client(
            mock_client_cls,
            request_side_effect=httpx.ConnectError("boom"),
        )
        client = NextcloudNotesClient(_make_secret_store())
        assert client.is_available() is False


# ── list_notes ───────────────────────────────────────────────────────


class TestListNotes:
    @patch(_HTTPX_CLIENT)
    def test_empty(self, mock_client_cls):
        client_mock = _install_client(mock_client_cls, response=_make_response(200, []))
        client = NextcloudNotesClient(_make_secret_store())
        assert client.list_notes() == []
        client_mock.request.assert_called_once_with(
            "GET", "notes", params=None, json=None
        )

    @patch(_HTTPX_CLIENT)
    def test_filled(self, mock_client_cls):
        payload = [
            _note_json(1, "Erste Notiz", modified=2000),
            _note_json(2, "Zweite Notiz", modified=1000),
        ]
        _install_client(mock_client_cls, response=_make_response(200, payload))
        client = NextcloudNotesClient(_make_secret_store())
        notes = client.list_notes()
        assert len(notes) == 2
        assert all(isinstance(n, NextcloudNote) for n in notes)
        assert notes[0].content == "Erste Notiz"

    @patch(_HTTPX_CLIENT)
    def test_sorted_by_modified_desc(self, mock_client_cls):
        payload = [
            _note_json(1, "alt", modified=1000),
            _note_json(2, "neu", modified=3000),
            _note_json(3, "mittel", modified=2000),
        ]
        _install_client(mock_client_cls, response=_make_response(200, payload))
        client = NextcloudNotesClient(_make_secret_store())
        notes = client.list_notes()
        assert [n.id for n in notes] == [2, 3, 1]

    @patch(_HTTPX_CLIENT)
    def test_category_param(self, mock_client_cls):
        client_mock = _install_client(mock_client_cls, response=_make_response(200, []))
        client = NextcloudNotesClient(_make_secret_store())
        client.list_notes(category="Einkauf")
        client_mock.request.assert_called_once_with(
            "GET", "notes", params={"category": "Einkauf"}, json=None
        )

    @patch(_HTTPX_CLIENT)
    def test_limit(self, mock_client_cls):
        payload = [_note_json(i, "n%d" % i, modified=i * 100) for i in range(1, 6)]
        _install_client(mock_client_cls, response=_make_response(200, payload))
        client = NextcloudNotesClient(_make_secret_store())
        notes = client.list_notes(limit=2)
        assert len(notes) == 2
        # Sortiert desc -> hoechste modified zuerst
        assert [n.id for n in notes] == [5, 4]

    @patch(_HTTPX_CLIENT)
    def test_not_a_list_raises(self, mock_client_cls):
        _install_client(mock_client_cls, response=_make_response(200, {"id": 1}))
        client = NextcloudNotesClient(_make_secret_store())
        with pytest.raises(NextcloudNotesError):
            client.list_notes()

    @patch(_HTTPX_CLIENT)
    def test_modified_parsed_to_utc_datetime(self, mock_client_cls):
        _install_client(
            mock_client_cls,
            response=_make_response(200, [_note_json(1, "x", modified=1700000000)]),
        )
        client = NextcloudNotesClient(_make_secret_store())
        note = client.list_notes()[0]
        assert note.modified == datetime.fromtimestamp(1700000000, tz=timezone.utc)


# ── get_note ─────────────────────────────────────────────────────────


class TestGetNote:
    @patch(_HTTPX_CLIENT)
    def test_get(self, mock_client_cls):
        client_mock = _install_client(
            mock_client_cls,
            response=_make_response(200, _note_json(76, "Hallo", category="Arbeit")),
        )
        client = NextcloudNotesClient(_make_secret_store())
        note = client.get_note(76)
        assert note.id == 76
        assert note.category == "Arbeit"
        client_mock.request.assert_called_once_with(
            "GET", "notes/76", params=None, json=None
        )


# ── create_note ──────────────────────────────────────────────────────


class TestCreateNote:
    @patch(_HTTPX_CLIENT)
    def test_create_with_category(self, mock_client_cls):
        client_mock = _install_client(
            mock_client_cls,
            response=_make_response(200, _note_json(5, "Milch", category="Einkauf")),
        )
        client = NextcloudNotesClient(_make_secret_store())
        note = client.create_note("Milch", category="Einkauf")
        assert note.id == 5
        client_mock.request.assert_called_once_with(
            "POST",
            "notes",
            params=None,
            json={"content": "Milch", "category": "Einkauf"},
        )

    @patch(_HTTPX_CLIENT)
    def test_create_without_category(self, mock_client_cls):
        client_mock = _install_client(
            mock_client_cls,
            response=_make_response(200, _note_json(5, "Milch")),
        )
        client = NextcloudNotesClient(_make_secret_store())
        client.create_note("Milch")
        # Kein category-Key wenn nicht uebergeben
        _, kwargs = client_mock.request.call_args
        assert kwargs["json"] == {"content": "Milch"}

    @patch(_HTTPX_CLIENT)
    def test_create_omits_title(self, mock_client_cls):
        client_mock = _install_client(
            mock_client_cls,
            response=_make_response(200, _note_json(5, "Milch")),
        )
        client = NextcloudNotesClient(_make_secret_store())
        client.create_note("Milch", category="Einkauf")
        _, kwargs = client_mock.request.call_args
        # title leitet der Server ab -- darf nicht im Body stehen
        assert "title" not in kwargs["json"]


# ── update_note ──────────────────────────────────────────────────────


class TestUpdateNote:
    @patch(_HTTPX_CLIENT)
    def test_update_content_only(self, mock_client_cls):
        client_mock = _install_client(
            mock_client_cls,
            response=_make_response(200, _note_json(7, "neu")),
        )
        client = NextcloudNotesClient(_make_secret_store())
        client.update_note(7, content="neu")
        client_mock.request.assert_called_once_with(
            "PUT", "notes/7", params=None, json={"content": "neu"}
        )

    @patch(_HTTPX_CLIENT)
    def test_update_category_only(self, mock_client_cls):
        client_mock = _install_client(
            mock_client_cls,
            response=_make_response(200, _note_json(7, "x", category="Privat")),
        )
        client = NextcloudNotesClient(_make_secret_store())
        client.update_note(7, category="Privat")
        _, kwargs = client_mock.request.call_args
        assert kwargs["json"] == {"category": "Privat"}

    @patch(_HTTPX_CLIENT)
    def test_update_both(self, mock_client_cls):
        client_mock = _install_client(
            mock_client_cls,
            response=_make_response(200, _note_json(7, "neu", category="Privat")),
        )
        client = NextcloudNotesClient(_make_secret_store())
        client.update_note(7, content="neu", category="Privat")
        _, kwargs = client_mock.request.call_args
        assert kwargs["json"] == {"content": "neu", "category": "Privat"}

    @patch(_HTTPX_CLIENT)
    def test_update_empty_string_category_sent(self, mock_client_cls):
        # category="" ist gueltig (Kategorie entfernen) -- nicht dasselbe
        # wie category=None (nicht aendern).
        client_mock = _install_client(
            mock_client_cls,
            response=_make_response(200, _note_json(7, "x")),
        )
        client = NextcloudNotesClient(_make_secret_store())
        client.update_note(7, category="")
        _, kwargs = client_mock.request.call_args
        assert kwargs["json"] == {"category": ""}

    def test_update_nothing_raises(self):
        client = NextcloudNotesClient(_make_secret_store())
        with pytest.raises(ValueError):
            client.update_note(7)


# ── delete_note ──────────────────────────────────────────────────────


class TestDeleteNote:
    @patch(_HTTPX_CLIENT)
    def test_delete_204(self, mock_client_cls):
        client_mock = _install_client(mock_client_cls, response=_make_response(204))
        client = NextcloudNotesClient(_make_secret_store())
        result = client.delete_note(7)
        assert result is None
        client_mock.request.assert_called_once_with(
            "DELETE", "notes/7", params=None, json=None
        )

    @patch(_HTTPX_CLIENT)
    def test_delete_200_also_ok(self, mock_client_cls):
        _install_client(mock_client_cls, response=_make_response(200))
        client = NextcloudNotesClient(_make_secret_store())
        assert client.delete_note(7) is None


# ── search ───────────────────────────────────────────────────────────


class TestSearch:
    @patch(_HTTPX_CLIENT)
    def test_search_match(self, mock_client_cls):
        payload = [
            _note_json(1, "Milch kaufen", modified=2000),
            _note_json(2, "Brot kaufen", modified=1000),
        ]
        _install_client(mock_client_cls, response=_make_response(200, payload))
        client = NextcloudNotesClient(_make_secret_store())
        hits = client.search("milch")
        assert [n.id for n in hits] == [1]

    @patch(_HTTPX_CLIENT)
    def test_search_case_insensitive(self, mock_client_cls):
        payload = [_note_json(1, "Vermieter Mueller", modified=1000)]
        _install_client(mock_client_cls, response=_make_response(200, payload))
        client = NextcloudNotesClient(_make_secret_store())
        assert len(client.search("VERMIETER")) == 1

    @patch(_HTTPX_CLIENT)
    def test_search_no_match(self, mock_client_cls):
        payload = [_note_json(1, "Milch kaufen", modified=1000)]
        _install_client(mock_client_cls, response=_make_response(200, payload))
        client = NextcloudNotesClient(_make_secret_store())
        assert client.search("xyz") == []

    @patch(_HTTPX_CLIENT)
    def test_search_with_category_filter(self, mock_client_cls):
        client_mock = _install_client(mock_client_cls, response=_make_response(200, []))
        client = NextcloudNotesClient(_make_secret_store())
        client.search("milch", category="Einkauf")
        # category-Filter geht serverseitig an GET /notes
        client_mock.request.assert_called_once_with(
            "GET", "notes", params={"category": "Einkauf"}, json=None
        )

    @patch(_HTTPX_CLIENT)
    def test_search_limit(self, mock_client_cls):
        payload = [
            _note_json(i, "kaufen %d" % i, modified=i * 100) for i in range(1, 6)
        ]
        _install_client(mock_client_cls, response=_make_response(200, payload))
        client = NextcloudNotesClient(_make_secret_store())
        assert len(client.search("kaufen", limit=2)) == 2


# ── list_categories ──────────────────────────────────────────────────


class TestListCategories:
    @patch(_HTTPX_CLIENT)
    def test_dedup_and_sorted(self, mock_client_cls):
        payload = [
            _note_json(1, "a", category="Einkauf", modified=1000),
            _note_json(2, "b", category="Arbeit", modified=2000),
            _note_json(3, "c", category="Einkauf", modified=3000),
        ]
        _install_client(mock_client_cls, response=_make_response(200, payload))
        client = NextcloudNotesClient(_make_secret_store())
        assert client.list_categories() == ["Arbeit", "Einkauf"]

    @patch(_HTTPX_CLIENT)
    def test_empty_category_excluded(self, mock_client_cls):
        payload = [
            _note_json(1, "a", category="", modified=1000),
            _note_json(2, "b", category="Projekt", modified=2000),
        ]
        _install_client(mock_client_cls, response=_make_response(200, payload))
        client = NextcloudNotesClient(_make_secret_store())
        assert client.list_categories() == ["Projekt"]

    @patch(_HTTPX_CLIENT)
    def test_no_notes(self, mock_client_cls):
        _install_client(mock_client_cls, response=_make_response(200, []))
        client = NextcloudNotesClient(_make_secret_store())
        assert client.list_categories() == []


# ── Fehlerfaelle ─────────────────────────────────────────────────────


class TestErrors:
    @patch(_HTTPX_CLIENT)
    def test_401_unauthorized(self, mock_client_cls):
        _install_client(mock_client_cls, response=_make_response(401))
        client = NextcloudNotesClient(_make_secret_store())
        with pytest.raises(NextcloudNotesError) as exc:
            client.list_notes()
        assert exc.value.status_code == 401

    @patch(_HTTPX_CLIENT)
    def test_404_not_found(self, mock_client_cls):
        _install_client(mock_client_cls, response=_make_response(404))
        client = NextcloudNotesClient(_make_secret_store())
        with pytest.raises(NextcloudNotesError) as exc:
            client.get_note(999)
        assert exc.value.status_code == 404

    @patch(_HTTPX_CLIENT)
    def test_500_server_error(self, mock_client_cls):
        _install_client(mock_client_cls, response=_make_response(500))
        client = NextcloudNotesClient(_make_secret_store())
        with pytest.raises(NextcloudNotesError) as exc:
            client.list_notes()
        assert exc.value.status_code == 500

    @patch(_HTTPX_CLIENT)
    def test_500_does_not_retry(self, mock_client_cls):
        # HTTP-Status-Fehler ist kein Transport-Fehler -> kein Retry.
        client_mock = _install_client(mock_client_cls, response=_make_response(500))
        client = NextcloudNotesClient(_make_secret_store())
        with pytest.raises(NextcloudNotesError):
            client.list_notes()
        assert client_mock.request.call_count == 1

    @patch(_HTTPX_CLIENT)
    def test_transport_error_retry_succeeds(self, mock_client_cls):
        # Erster Versuch Transport-Fehler, Retry liefert Response.
        client_mock = _install_client(
            mock_client_cls,
            request_side_effect=[
                httpx.ConnectError("boom"),
                _make_response(200, []),
            ],
        )
        client = NextcloudNotesClient(_make_secret_store())
        assert client.list_notes() == []
        assert client_mock.request.call_count == 2

    @patch(_HTTPX_CLIENT)
    def test_transport_error_retry_fails(self, mock_client_cls):
        client_mock = _install_client(
            mock_client_cls,
            request_side_effect=httpx.ConnectTimeout("timeout"),
        )
        client = NextcloudNotesClient(_make_secret_store())
        with pytest.raises(NextcloudNotesError) as exc:
            client.list_notes()
        assert exc.value.status_code is None
        assert client_mock.request.call_count == 2

    @patch(_HTTPX_CLIENT)
    def test_invalid_json(self, mock_client_cls):
        _install_client(mock_client_cls, response=_make_response(200, json_error=True))
        client = NextcloudNotesClient(_make_secret_store())
        with pytest.raises(NextcloudNotesError):
            client.list_notes()

    @patch(_HTTPX_CLIENT)
    def test_parse_note_missing_id(self, mock_client_cls):
        _install_client(
            mock_client_cls,
            response=_make_response(200, [{"content": "ohne id"}]),
        )
        client = NextcloudNotesClient(_make_secret_store())
        with pytest.raises(NextcloudNotesError):
            client.list_notes()

    @patch(_HTTPX_CLIENT)
    def test_parse_note_not_a_dict(self, mock_client_cls):
        _install_client(
            mock_client_cls,
            response=_make_response(200, ["nur ein string"]),
        )
        client = NextcloudNotesClient(_make_secret_store())
        with pytest.raises(NextcloudNotesError):
            client.list_notes()
