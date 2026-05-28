"""NextcloudCookbookClient -- Nextcloud Cookbook API + WebDAV write path.

Read-path via Cookbook REST API:
    GET /api/v1/recipes
    GET /api/v1/search/{query}
    GET /api/v1/recipes/{id}

Write-path via WebDAV JSON upload into /Recipes plus API reindex:
    PUT /remote.php/dav/files/<user>/Recipes/<slug>.json
    POST /api/v1/reindex

Credentials come from SecretStore keys already used for Nextcloud:
    nextcloud_url, nextcloud_user, nextcloud_app_password
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

_API_PATH = "index.php/apps/cookbook/api/v1"
_RECIPES_DIR = "Recipes"


class NextcloudCookbookError(Exception):
    """Domain error for Nextcloud Cookbook operations."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class CookbookRecipeSummary:
    """Compact recipe view used for list/search/index."""

    recipe_id: str
    name: str
    category: str
    keywords: list[str]
    tools: list[str]


class NextcloudCookbookClient:
    """HTTP/WebDAV client for Nextcloud Cookbook."""

    _RETRIABLE_ERRORS = (httpx.TransportError,)

    def __init__(self, secret_store: SecretStore, timeout: float = 10.0) -> None:
        self._url = secret_store.get_or_none("nextcloud_url")
        self._user = secret_store.get_or_none("nextcloud_user")
        self._password = secret_store.get_or_none("nextcloud_app_password")
        self._recipes_dir_override = self._normalize_dir_name(
            secret_store.get_or_none("nextcloud_cookbook_folder")
        )
        self._recipes_dir_cached: str | None = None
        self._timeout = timeout

    @property
    def _has_credentials(self) -> bool:
        return bool(self._url and self._user and self._password)

    @property
    def _api_base(self) -> str:
        url = (self._url or "").rstrip("/")
        return f"{url}/{_API_PATH}/"

    @property
    def _webdav_base(self) -> str:
        url = (self._url or "").rstrip("/")
        return f"{url}/remote.php/dav/files/{self._user}/"

    @property
    def _auth(self) -> tuple[str, str]:
        return (self._user or "", self._password or "")

    def is_available(self) -> bool:
        if not self._has_credentials:
            return False
        try:
            self.list_recipes(limit=1)
            return True
        except NextcloudCookbookError:
            return False

    def _send_api(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        with httpx.Client(
            base_url=self._api_base,
            auth=self._auth,
            timeout=self._timeout,
        ) as client:
            return client.request(method, path, params=params, json=json_body)

    def _request_api(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        if not self._has_credentials:
            raise NextcloudCookbookError("Nextcloud credentials not configured")

        try:
            resp = self._send_api(
                method,
                path,
                params=params,
                json_body=json_body,
            )
        except self._RETRIABLE_ERRORS as exc:
            logger.warning(
                "Cookbook transport error, retry with fresh connection: %s",
                exc,
            )
            try:
                resp = self._send_api(
                    method,
                    path,
                    params=params,
                    json_body=json_body,
                )
            except self._RETRIABLE_ERRORS as exc2:
                raise NextcloudCookbookError(
                    "Cookbook unreachable: %s" % exc2
                ) from exc2

        if resp.status_code >= 400:
            raise NextcloudCookbookError(
                "Cookbook API error (HTTP %d)" % resp.status_code,
                status_code=resp.status_code,
            )
        return resp

    @staticmethod
    def _json(resp: httpx.Response) -> Any:
        try:
            return resp.json()
        except ValueError as exc:
            raise NextcloudCookbookError("Cookbook returned invalid JSON") from exc

    @staticmethod
    def _extract_recipe_id(item: dict[str, Any]) -> str:
        for key in ("recipe_id", "id", "recipeId"):
            if key in item and item[key] is not None:
                return str(item[key])
        raise NextcloudCookbookError("Recipe object without id")

    @classmethod
    def _parse_summary(cls, item: Any) -> CookbookRecipeSummary:
        if not isinstance(item, dict):
            raise NextcloudCookbookError("Unexpected recipe summary format")
        recipe_id = cls._extract_recipe_id(item)
        name = str(item.get("name") or item.get("title") or "").strip()
        category = str(item.get("category") or "").strip()
        keywords_raw = item.get("keywords") or []
        tools_raw = item.get("tools") or []
        keywords = (
            [str(x) for x in keywords_raw] if isinstance(keywords_raw, list) else []
        )
        tools = [str(x) for x in tools_raw] if isinstance(tools_raw, list) else []
        return CookbookRecipeSummary(
            recipe_id=recipe_id,
            name=name,
            category=category,
            keywords=keywords,
            tools=tools,
        )

    def list_recipes(self, limit: int = 200) -> list[CookbookRecipeSummary]:
        resp = self._request_api("GET", "recipes")
        data = self._json(resp)
        if not isinstance(data, list):
            raise NextcloudCookbookError("Unexpected list response format")
        out: list[CookbookRecipeSummary] = []
        for item in data:
            try:
                out.append(self._parse_summary(item))
            except NextcloudCookbookError:
                continue
        return out[:limit]

    def search_recipes(
        self,
        query: str,
        limit: int = 20,
    ) -> list[CookbookRecipeSummary]:
        q = query.strip()
        if not q:
            return []
        path = "search/%s" % quote(q, safe="")
        resp = self._request_api("GET", path)
        data = self._json(resp)
        if not isinstance(data, list):
            raise NextcloudCookbookError("Unexpected search response format")
        out: list[CookbookRecipeSummary] = []
        for item in data:
            try:
                out.append(self._parse_summary(item))
            except NextcloudCookbookError:
                continue
        return out[:limit]

    def get_recipe(self, recipe_id: str) -> dict[str, Any]:
        rid = str(recipe_id).strip()
        if not rid:
            raise NextcloudCookbookError("Recipe id is required")
        resp = self._request_api("GET", f"recipes/{rid}")
        data = self._json(resp)
        if not isinstance(data, dict):
            raise NextcloudCookbookError("Unexpected recipe detail format")
        return data

    @staticmethod
    def _slugify(name: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
        return slug or "recipe"

    def _webdav_put(self, remote_path: str, payload: str) -> None:
        url = f"{self._webdav_base}{remote_path.lstrip('/')}"
        try:
            resp = httpx.request(
                "PUT",
                url,
                auth=self._auth,
                headers={"Content-Type": "application/json; charset=utf-8"},
                content=payload.encode("utf-8"),
                timeout=self._timeout,
            )
        except self._RETRIABLE_ERRORS as exc:
            raise NextcloudCookbookError("WebDAV upload failed: %s" % exc) from exc

        if resp.status_code in (401, 403):
            raise NextcloudCookbookError(
                "Cookbook auth failed (HTTP %d)" % resp.status_code,
                status_code=resp.status_code,
            )
        if resp.status_code >= 400:
            raise NextcloudCookbookError(
                "Cookbook upload failed (HTTP %d)" % resp.status_code,
                status_code=resp.status_code,
            )

    def _webdav_exists(self, remote_path: str) -> bool:
        """Checks whether a target path already exists via WebDAV PROPFIND."""
        url = f"{self._webdav_base}{remote_path.lstrip('/')}"
        try:
            resp = httpx.request(
                "PROPFIND",
                url,
                auth=self._auth,
                headers={"Depth": "0"},
                timeout=self._timeout,
            )
        except self._RETRIABLE_ERRORS as exc:
            raise NextcloudCookbookError("WebDAV check failed: %s" % exc) from exc

        if resp.status_code in (200, 207):
            return True
        if resp.status_code == 404:
            return False
        if resp.status_code in (401, 403):
            raise NextcloudCookbookError(
                "Cookbook auth failed (HTTP %d)" % resp.status_code,
                status_code=resp.status_code,
            )
        raise NextcloudCookbookError(
            "Cookbook existence check failed (HTTP %d)" % resp.status_code,
            status_code=resp.status_code,
        )

    @staticmethod
    def _normalize_dir_name(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().strip("/")
        if not normalized:
            return None
        return normalized

    def _resolve_recipes_dir(self) -> str:
        if self._recipes_dir_override:
            return self._recipes_dir_override
        if self._recipes_dir_cached:
            return self._recipes_dir_cached

        configured_dir: str | None = None
        try:
            resp = self._request_api("GET", "config")
            data = self._json(resp)
            if isinstance(data, dict):
                for key in ("recipeFolder", "recipesFolder", "folder"):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        configured_dir = value
                        break
        except NextcloudCookbookError:
            configured_dir = None

        self._recipes_dir_cached = (
            self._normalize_dir_name(configured_dir) or _RECIPES_DIR
        )
        return self._recipes_dir_cached

    @staticmethod
    def _join_remote_path(folder: str, file_name: str) -> str:
        folder_clean = folder.strip().strip("/")
        file_clean = file_name.strip().lstrip("/")
        if not folder_clean:
            return file_clean
        return str(PurePosixPath(folder_clean) / file_clean)

    def _resolve_unique_remote_path(self, folder: str, file_name: str) -> str:
        """Returns a unique target path, keeping existing recipes untouched."""
        candidate = self._join_remote_path(folder, file_name)
        if not self._webdav_exists(candidate):
            return candidate

        stem, sep, suffix = file_name.rpartition(".")
        if not sep:
            stem = file_name
            suffix = ""

        for idx in range(2, 10_000):
            numbered = f"{stem}-{idx}"
            if suffix:
                numbered = f"{numbered}.{suffix}"
            candidate = self._join_remote_path(folder, numbered)
            if not self._webdav_exists(candidate):
                return candidate

        raise NextcloudCookbookError(
            "Could not resolve unique recipe filename after many attempts"
        )

    def trigger_reindex(self) -> None:
        # Reindex can be slightly flaky right after upload; retry a few times.
        last_exc: NextcloudCookbookError | None = None
        for _ in range(3):
            try:
                self._request_api("POST", "reindex")
                return
            except NextcloudCookbookError as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc

    def save_recipe(
        self,
        recipe_json: dict[str, Any],
        *,
        filename: str | None = None,
    ) -> str:
        if not isinstance(recipe_json, dict):
            raise NextcloudCookbookError("Recipe payload must be an object")

        recipes_dir = self._resolve_recipes_dir()
        name = str(recipe_json.get("name") or recipe_json.get("title") or "recipe")
        file_name = (filename or f"{self._slugify(name)}.json").strip()
        if not file_name:
            file_name = "recipe.json"
        remote_path = self._resolve_unique_remote_path(recipes_dir, file_name)

        try:
            payload = json.dumps(recipe_json, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as exc:
            raise NextcloudCookbookError("Recipe JSON is not serializable") from exc

        self._webdav_put(remote_path, payload)
        self.trigger_reindex()
        return remote_path
