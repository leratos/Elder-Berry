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
            _response(404, None),  # subfolder existence check: missing → new
            _response(201, None),  # MKCOL creates subfolder
            _response(201, None),  # PUT recipe.json
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

    assert path == "Recipes/moscow-mule/recipe.json"


def test_reindex_retry_then_fail_raises():
    with patch(_HTTPX_REQUEST) as mock_request, patch(_HTTPX_CLIENT) as mock_client_cls:
        mock_request.side_effect = [
            _response(404, None),  # subfolder existence check
            _response(201, None),  # MKCOL
            _response(201, None),  # PUT recipe.json
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
            _response(404, None),  # subfolder existence check
            _response(201, None),  # MKCOL
            _response(201, None),  # PUT recipe.json
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
    assert path.endswith("/recipe.json")


def test_save_recipe_does_not_overwrite_existing_file():
    with patch(_HTTPX_REQUEST) as mock_request, patch(_HTTPX_CLIENT) as mock_client_cls:
        mock_request.side_effect = [
            _response(207, None),  # Recipes/carbonara/ already exists
            _response(404, None),  # Recipes/carbonara-2/ is free
            _response(201, None),  # MKCOL Recipes/carbonara-2/
            _response(201, None),  # PUT recipe.json
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

    assert path == "Recipes/carbonara-2/recipe.json"


def test_normalize_dir_name_variants():
    client = NextcloudCookbookClient(_secret_store())
    assert client._normalize_dir_name(None) is None
    assert client._normalize_dir_name("  ") is None
    assert client._normalize_dir_name("/Recipes/") == "Recipes"


def test_resolve_recipes_dir_prefers_secret_override():
    client = NextcloudCookbookClient(
        _secret_store(nextcloud_cookbook_folder="MyFolder")
    )
    client._request_api = MagicMock(side_effect=AssertionError("must not call API"))
    assert client._resolve_recipes_dir() == "MyFolder"


def test_resolve_recipes_dir_uses_config_api_and_caches():
    client = NextcloudCookbookClient(_secret_store())
    client._request_api = MagicMock(return_value=_response(200, {"folder": "X"}))
    client._json = MagicMock(return_value={"folder": "X"})

    assert client._resolve_recipes_dir() == "X"
    # second call uses cache
    assert client._resolve_recipes_dir() == "X"
    client._request_api.assert_called_once()


def test_resolve_recipes_dir_falls_back_on_config_error():
    client = NextcloudCookbookClient(_secret_store())
    client._request_api = MagicMock(side_effect=NextcloudCookbookError("boom"))
    assert client._resolve_recipes_dir() == "Recipes"


def test_join_remote_path_handles_slashes():
    client = NextcloudCookbookClient(_secret_store())
    assert client._join_remote_path("Recipes", "a.json") == "Recipes/a.json"
    assert client._join_remote_path("/Recipes/", "/a.json") == "Recipes/a.json"


def test_webdav_exists_status_branches():
    client = NextcloudCookbookClient(_secret_store())
    with patch(_HTTPX_REQUEST) as mock_request:
        mock_request.return_value = _response(207, None)
        assert client._webdav_exists("Recipes/a.json") is True

        mock_request.return_value = _response(404, None)
        assert client._webdav_exists("Recipes/a.json") is False


def test_webdav_exists_auth_error_raises():
    client = NextcloudCookbookClient(_secret_store())
    with patch(_HTTPX_REQUEST) as mock_request:
        mock_request.return_value = _response(401, None)
        with pytest.raises(NextcloudCookbookError):
            client._webdav_exists("Recipes/a.json")


def test_webdav_exists_generic_error_raises():
    client = NextcloudCookbookClient(_secret_store())
    with patch(_HTTPX_REQUEST) as mock_request:
        mock_request.return_value = _response(500, None)
        with pytest.raises(NextcloudCookbookError):
            client._webdav_exists("Recipes/a.json")


def test_resolve_unique_subdir_many_collisions():
    client = NextcloudCookbookClient(_secret_store())
    client._webdav_exists = MagicMock(side_effect=[True, True, False])
    path = client._resolve_unique_subdir("Recipes", "x")
    assert path == "Recipes/x-3"


def test_resolve_unique_subdir_free_on_first_try():
    client = NextcloudCookbookClient(_secret_store())
    client._webdav_exists = MagicMock(return_value=False)
    path = client._resolve_unique_subdir("Recipes", "x")
    assert path == "Recipes/x"


def test_save_recipe_with_blank_filename_falls_back_to_recipe_json_name():
    with patch(_HTTPX_REQUEST) as mock_request, patch(_HTTPX_CLIENT) as mock_client_cls:
        mock_request.side_effect = [
            _response(404, None),  # subfolder existence check
            _response(201, None),  # MKCOL
            _response(201, None),  # PUT recipe.json
        ]
        _install_httpx_client(mock_client_cls, response=_response(200, {"ok": True}))

        client = NextcloudCookbookClient(_secret_store())
        path = client.save_recipe(
            {
                "@context": "https://schema.org",
                "@type": "Recipe",
                "name": "Fallback Name",
                "recipeIngredient": ["A"],
                "recipeInstructions": ["B"],
            },
            filename=" ",
        )

    assert path.endswith("/recipe.json")
