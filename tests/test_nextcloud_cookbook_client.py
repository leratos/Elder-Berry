"""Tests for NextcloudCookbookClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from elder_berry.tools.nextcloud_cookbook_client import (
    NextcloudCookbookClient,
    NextcloudCookbookError,
)

_HTTPX_CLIENT = "elder_berry.tools.nextcloud_cookbook_client.httpx.Client"
_HTTPX_REQUEST = "elder_berry.tools.nextcloud_cookbook_client.httpx.request"


def _secret_store(**overrides):
    defaults = {
        "nextcloud_url": "https://cloud.example.com",
        "nextcloud_user": "alice",
        "nextcloud_app_password": "secret",
    }
    defaults.update(overrides)

    store = MagicMock()
    store.get_or_none.side_effect = lambda key: defaults.get(key)
    return store


def _response(status_code=200, json_data=None, json_error=False):
    resp = MagicMock()
    resp.status_code = status_code
    if json_error:
        resp.json.side_effect = ValueError("bad json")
    else:
        resp.json.return_value = json_data
    return resp


def _install_httpx_client(mock_client_cls, *, response=None, side_effect=None):
    client = MagicMock()
    cm = mock_client_cls.return_value
    cm.__enter__.return_value = client
    cm.__exit__.return_value = False
    if side_effect is not None:
        client.request.side_effect = side_effect
    else:
        client.request.return_value = response
    return client


def test_list_recipes_success():
    payload = [
        {
            "id": 1,
            "name": "Carbonara",
            "category": "Pasta",
            "keywords": ["spaghetti", "ei"],
        }
    ]
    with patch(_HTTPX_CLIENT) as mock_client_cls:
        _install_httpx_client(mock_client_cls, response=_response(200, payload))
        client = NextcloudCookbookClient(_secret_store())
        recipes = client.list_recipes()

    assert len(recipes) == 1
    assert recipes[0].recipe_id == "1"
    assert recipes[0].name == "Carbonara"


def test_search_recipes_encodes_query():
    with patch(_HTTPX_CLIENT) as mock_client_cls:
        inner = _install_httpx_client(mock_client_cls, response=_response(200, []))
        client = NextcloudCookbookClient(_secret_store())
        client.search_recipes("spicy noodles")

    args, _kwargs = inner.request.call_args
    assert args[1] == "search/spicy%20noodles"


def test_get_recipe_success():
    with patch(_HTTPX_CLIENT) as mock_client_cls:
        _install_httpx_client(
            mock_client_cls,
            response=_response(200, {"id": 9, "name": "Soup"}),
        )
        client = NextcloudCookbookClient(_secret_store())
        recipe = client.get_recipe("9")

    assert recipe["id"] == 9


def test_transport_retry_then_success():
    ok_resp = _response(200, [])

    with patch(_HTTPX_CLIENT) as mock_client_cls:
        _install_httpx_client(
            mock_client_cls,
            side_effect=[httpx.ConnectError("boom"), ok_resp],
        )
        client = NextcloudCookbookClient(_secret_store())
        data = client.list_recipes()

    assert data == []


def test_transport_retry_exhausted_raises():
    with patch(_HTTPX_CLIENT) as mock_client_cls:
        _install_httpx_client(
            mock_client_cls,
            side_effect=httpx.ConnectError("boom"),
        )
        client = NextcloudCookbookClient(_secret_store())
        with pytest.raises(NextcloudCookbookError):
            client.list_recipes()


def test_http_error_raises():
    with patch(_HTTPX_CLIENT) as mock_client_cls:
        _install_httpx_client(mock_client_cls, response=_response(500, {}))
        client = NextcloudCookbookClient(_secret_store())
        with pytest.raises(NextcloudCookbookError):
            client.list_recipes()


def test_json_error_raises():
    with patch(_HTTPX_CLIENT) as mock_client_cls:
        _install_httpx_client(
            mock_client_cls,
            response=_response(200, None, json_error=True),
        )
        client = NextcloudCookbookClient(_secret_store())
        with pytest.raises(NextcloudCookbookError):
            client.list_recipes()


def test_save_recipe_uploads_and_reindexes():
    with patch(_HTTPX_REQUEST) as mock_request, patch(_HTTPX_CLIENT) as mock_client_cls:
        mock_request.side_effect = [
            _response(404, None),  # first existence check: file missing
            _response(201, None),  # upload
        ]
        _install_httpx_client(mock_client_cls, response=_response(200, {"ok": True}))

        client = NextcloudCookbookClient(_secret_store())
        path = client.save_recipe(
            {
                "@context": "https://schema.org",
                "@type": "Recipe",
                "name": "Moscow Mule",
                "recipeIngredient": ["Wodka", "Ginger Beer", "Limette"],
                "recipeInstructions": ["Mischen", "Servieren"],
            }
        )

    assert path.startswith("Recipes/")
    assert path.endswith(".json")
    assert "moscow-mule" in path


def test_reindex_retry_then_fail_raises():
    with patch(_HTTPX_REQUEST) as mock_request, patch(_HTTPX_CLIENT) as mock_client_cls:
        mock_request.side_effect = [
            _response(404, None),  # first existence check: file missing
            _response(201, None),  # upload
        ]
        _install_httpx_client(
            mock_client_cls,
            response=_response(500, {}),
        )
        client = NextcloudCookbookClient(_secret_store())

        with pytest.raises(NextcloudCookbookError):
            client.save_recipe(
                {
                    "@context": "https://schema.org",
                    "@type": "Recipe",
                    "name": "Test",
                    "recipeIngredient": ["A"],
                    "recipeInstructions": ["B"],
                }
            )


def test_save_recipe_uses_configured_cookbook_folder_from_secret():
    with patch(_HTTPX_REQUEST) as mock_request, patch(_HTTPX_CLIENT) as mock_client_cls:
        mock_request.side_effect = [
            _response(404, None),  # first existence check: file missing
            _response(201, None),  # upload
        ]
        _install_httpx_client(mock_client_cls, response=_response(200, {"ok": True}))

        client = NextcloudCookbookClient(
            _secret_store(nextcloud_cookbook_folder="MyRecipes")
        )
        path = client.save_recipe(
            {
                "@context": "https://schema.org",
                "@type": "Recipe",
                "name": "Folder Test",
                "recipeIngredient": ["A"],
                "recipeInstructions": ["B"],
            }
        )

    assert path.startswith("MyRecipes/")


def test_save_recipe_does_not_overwrite_existing_file():
    with patch(_HTTPX_REQUEST) as mock_request, patch(_HTTPX_CLIENT) as mock_client_cls:
        mock_request.side_effect = [
            _response(207, None),  # existing: Recipes/carbonara.json
            _response(404, None),  # missing: Recipes/carbonara-2.json
            _response(201, None),  # upload of unique filename
        ]
        _install_httpx_client(mock_client_cls, response=_response(200, {"ok": True}))

        client = NextcloudCookbookClient(_secret_store())
        path = client.save_recipe(
            {
                "@context": "https://schema.org",
                "@type": "Recipe",
                "name": "Carbonara",
                "recipeIngredient": ["A"],
                "recipeInstructions": ["B"],
            }
        )

    assert path == "Recipes/carbonara-2.json"
