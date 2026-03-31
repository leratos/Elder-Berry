"""NextcloudFilesClient – WebDAV-Client for Nextcloud file operations.

Supports upload, download, directory listing, search and share-link creation.
Uses httpx for HTTP and xml.etree.ElementTree for WebDAV XML parsing.

Credentials are read from SecretStore:
    nextcloud_url, nextcloud_user, nextcloud_app_password
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB

# WebDAV namespace
_DAV_NS = "DAV:"
_DAV = f"{{{_DAV_NS}}}"

_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<d:propfind xmlns:d="DAV:">'
    "<d:prop>"
    "<d:getlastmodified/>"
    "<d:getcontentlength/>"
    "<d:resourcetype/>"
    "<d:displayname/>"
    "</d:prop>"
    "</d:propfind>"
)


# ── Exceptions ──────────────────────────────────────────────────────────


class NextcloudError(Exception):
    """General Nextcloud operation error."""


class NextcloudConnectionError(NextcloudError):
    """Server unreachable or network error."""


class NextcloudAuthError(NextcloudError):
    """Authentication failed (401/403)."""


# ── DTOs ────────────────────────────────────────────────────────────────


@dataclass
class NextcloudFile:
    """Represents a file or directory on Nextcloud."""

    name: str
    path: str
    is_dir: bool
    size: int
    modified: str


# ── Client ──────────────────────────────────────────────────────────────


class NextcloudFilesClient:
    """WebDAV client for Nextcloud file operations."""

    def __init__(self, secret_store: SecretStore) -> None:
        self._url = secret_store.get_or_none("nextcloud_url")
        self._user = secret_store.get_or_none("nextcloud_user")
        self._password = secret_store.get_or_none("nextcloud_app_password")

    @property
    def _has_credentials(self) -> bool:
        return bool(self._url and self._user and self._password)

    @property
    def _webdav_base(self) -> str:
        """WebDAV base URL for the user's file root."""
        url = (self._url or "").rstrip("/")
        return f"{url}/remote.php/dav/files/{self._user}/"

    @property
    def _auth(self) -> tuple[str, str]:
        return (self._user or "", self._password or "")

    def is_available(self) -> bool:
        """Check if credentials are present and the server is reachable."""
        if not self._has_credentials:
            return False
        try:
            resp = httpx.request(
                "PROPFIND",
                self._webdav_base,
                auth=self._auth,
                headers={
                    "Content-Type": "application/xml",
                    "Depth": "0",
                },
                content=_PROPFIND_BODY,
                timeout=10.0,
            )
            return resp.status_code in (200, 207)
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
        except Exception as exc:
            logger.warning("Nextcloud availability check failed: %s", exc)
            return False

    def _webdav_url(self, remote_path: str) -> str:
        """Build the full WebDAV URL for a remote path."""
        clean = remote_path.strip("/")
        return f"{self._webdav_base}{clean}" if clean else self._webdav_base

    def _ensure_directories(self, remote_path: str) -> None:
        """Create intermediate directories via MKCOL if needed."""
        parts = remote_path.strip("/").split("/")
        # Only create parent directories, not the file itself
        if len(parts) <= 1:
            return
        for i in range(1, len(parts)):
            dir_path = "/".join(parts[:i])
            url = self._webdav_url(dir_path) + "/"
            try:
                resp = httpx.request(
                    "MKCOL",
                    url,
                    auth=self._auth,
                    timeout=10.0,
                )
                # 201=created, 405=already exists – both fine
                if resp.status_code not in (201, 405):
                    logger.debug("MKCOL %s → %d", dir_path, resp.status_code)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                raise NextcloudConnectionError(
                    f"Server nicht erreichbar: {exc}"
                ) from exc

    def _check_auth_error(self, resp: httpx.Response) -> None:
        """Raise NextcloudAuthError for 401/403 responses."""
        if resp.status_code in (401, 403):
            raise NextcloudAuthError(
                f"Authentifizierung fehlgeschlagen (HTTP {resp.status_code})"
            )

    def upload(self, local_path: Path, remote_path: str = "/") -> str:
        """Upload a local file to Nextcloud via WebDAV PUT.

        Args:
            local_path: Path to the local file.
            remote_path: Remote path relative to user root.
                If it ends with '/' or is '/', the filename is appended.

        Returns:
            The remote path where the file was stored.

        Raises:
            FileNotFoundError: Local file does not exist.
            NextcloudError: Upload failed.
        """
        if not self._has_credentials:
            raise NextcloudError("Nextcloud-Credentials nicht konfiguriert")

        local_path = Path(local_path)
        if not local_path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {local_path}")
        if not local_path.is_file():
            raise NextcloudError(f"Kein reguläres File: {local_path}")

        size = local_path.stat().st_size
        if size > MAX_UPLOAD_SIZE_BYTES:
            raise NextcloudError(
                f"Datei zu groß ({size / 1024 / 1024:.1f} MB, "
                f"max {MAX_UPLOAD_SIZE_BYTES / 1024 / 1024:.0f} MB)"
            )

        # If remote_path is a directory, append filename
        if remote_path.endswith("/") or remote_path == "/":
            remote_path = remote_path.rstrip("/") + "/" + local_path.name
        remote_path = remote_path.lstrip("/")

        self._ensure_directories(remote_path)

        url = self._webdav_url(remote_path)
        try:
            with open(local_path, "rb") as fh:
                resp = httpx.put(
                    url,
                    auth=self._auth,
                    content=fh.read(),
                    timeout=30.0,
                )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise NextcloudConnectionError(
                f"Server nicht erreichbar: {exc}"
            ) from exc

        self._check_auth_error(resp)
        if resp.status_code not in (200, 201, 204):
            raise NextcloudError(
                f"Upload fehlgeschlagen: HTTP {resp.status_code}"
            )

        logger.info("Upload OK: %s → %s", local_path.name, remote_path)
        return remote_path

    def download(
        self, remote_path: str, local_dir: Path | None = None
    ) -> Path:
        """Download a file from Nextcloud via WebDAV GET.

        Args:
            remote_path: Remote path relative to user root.
            local_dir: Local directory to save to (default ~/Downloads).

        Returns:
            Path to the downloaded local file.

        Raises:
            NextcloudError: Download failed or file not found.
        """
        if not self._has_credentials:
            raise NextcloudError("Nextcloud-Credentials nicht konfiguriert")

        if local_dir is None:
            local_dir = Path.home() / "Downloads"
        local_dir.mkdir(parents=True, exist_ok=True)

        url = self._webdav_url(remote_path)
        try:
            resp = httpx.get(url, auth=self._auth, timeout=30.0)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise NextcloudConnectionError(
                f"Server nicht erreichbar: {exc}"
            ) from exc

        self._check_auth_error(resp)
        if resp.status_code == 404:
            raise NextcloudError(
                f"Datei nicht gefunden: {remote_path}"
            )
        if resp.status_code not in (200,):
            raise NextcloudError(
                f"Download fehlgeschlagen: HTTP {resp.status_code}"
            )

        filename = remote_path.rstrip("/").split("/")[-1]
        local_path = local_dir / filename
        local_path.write_bytes(resp.content)

        logger.info("Download OK: %s → %s", remote_path, local_path)
        return local_path

    def _parse_propfind(self, xml_text: str) -> list[NextcloudFile]:
        """Parse a PROPFIND XML response into NextcloudFile objects."""
        root = ET.fromstring(xml_text)
        results: list[NextcloudFile] = []

        for response in root.findall(f"{_DAV}response"):
            href_el = response.find(f"{_DAV}href")
            if href_el is None or href_el.text is None:
                continue

            propstat = response.find(f"{_DAV}propstat")
            if propstat is None:
                continue
            prop = propstat.find(f"{_DAV}prop")
            if prop is None:
                continue

            # Resource type
            restype = prop.find(f"{_DAV}resourcetype")
            is_dir = (
                restype is not None
                and restype.find(f"{_DAV}collection") is not None
            )

            # Display name
            displayname_el = prop.find(f"{_DAV}displayname")
            name = (
                displayname_el.text
                if displayname_el is not None and displayname_el.text
                else href_el.text.rstrip("/").split("/")[-1]
            )

            # Size
            size_el = prop.find(f"{_DAV}getcontentlength")
            size = int(size_el.text) if size_el is not None and size_el.text else 0

            # Modified
            mod_el = prop.find(f"{_DAV}getlastmodified")
            modified = mod_el.text if mod_el is not None and mod_el.text else ""

            # Path: extract relative path from href
            href = href_el.text
            # href looks like /remote.php/dav/files/user/some/path
            dav_prefix = f"/remote.php/dav/files/{self._user}/"
            if dav_prefix in href:
                rel_path = href.split(dav_prefix, 1)[1]
            else:
                rel_path = href.rstrip("/").split("/")[-1]

            results.append(NextcloudFile(
                name=name,
                path=rel_path.rstrip("/"),
                is_dir=is_dir,
                size=size,
                modified=modified,
            ))

        return results

    def list_dir(self, remote_path: str = "/") -> list[NextcloudFile]:
        """List directory contents via PROPFIND Depth:1.

        Args:
            remote_path: Remote path relative to user root.

        Returns:
            List of NextcloudFile objects (excluding the queried dir itself).
        """
        if not self._has_credentials:
            raise NextcloudError("Nextcloud-Credentials nicht konfiguriert")

        url = self._webdav_url(remote_path)
        if not url.endswith("/"):
            url += "/"

        try:
            resp = httpx.request(
                "PROPFIND",
                url,
                auth=self._auth,
                headers={
                    "Content-Type": "application/xml",
                    "Depth": "1",
                },
                content=_PROPFIND_BODY,
                timeout=10.0,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise NextcloudConnectionError(
                f"Server nicht erreichbar: {exc}"
            ) from exc

        self._check_auth_error(resp)
        if resp.status_code not in (200, 207):
            raise NextcloudError(
                f"Listing fehlgeschlagen: HTTP {resp.status_code}"
            )

        entries = self._parse_propfind(resp.text)
        # First entry is the queried directory itself — skip it
        if entries:
            entries = entries[1:]
        return entries

    def search(self, query: str) -> list[NextcloudFile]:
        """Search for files by name (case-insensitive contains).

        Uses PROPFIND Depth:infinity on root and filters client-side.

        Args:
            query: Search term (matched against filename).

        Returns:
            List of matching NextcloudFile objects.
        """
        if not self._has_credentials:
            raise NextcloudError("Nextcloud-Credentials nicht konfiguriert")

        url = self._webdav_base
        try:
            resp = httpx.request(
                "PROPFIND",
                url,
                auth=self._auth,
                headers={
                    "Content-Type": "application/xml",
                    "Depth": "infinity",
                },
                content=_PROPFIND_BODY,
                timeout=30.0,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise NextcloudConnectionError(
                f"Server nicht erreichbar: {exc}"
            ) from exc

        self._check_auth_error(resp)
        if resp.status_code not in (200, 207):
            raise NextcloudError(
                f"Suche fehlgeschlagen: HTTP {resp.status_code}"
            )

        all_entries = self._parse_propfind(resp.text)
        # Skip the root entry and filter by query
        if all_entries:
            all_entries = all_entries[1:]

        query_lower = query.lower()
        return [e for e in all_entries if query_lower in e.name.lower()]

    def share_link(self, remote_path: str) -> str:
        """Create a public share link via OCS API.

        Args:
            remote_path: Remote path relative to user root.

        Returns:
            Public share URL.

        Raises:
            NextcloudError: Share creation failed.
        """
        if not self._has_credentials:
            raise NextcloudError("Nextcloud-Credentials nicht konfiguriert")

        base_url = (self._url or "").rstrip("/")
        url = f"{base_url}/ocs/v2.php/apps/files_sharing/api/v1/shares"

        try:
            resp = httpx.post(
                url,
                auth=self._auth,
                headers={
                    "OCS-APIRequest": "true",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "path": remote_path if remote_path.startswith("/") else f"/{remote_path}",
                    "shareType": "3",  # public link
                },
                timeout=10.0,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise NextcloudConnectionError(
                f"Server nicht erreichbar: {exc}"
            ) from exc

        self._check_auth_error(resp)
        if resp.status_code == 404:
            raise NextcloudError(
                f"Datei nicht gefunden: {remote_path}"
            )
        if resp.status_code not in (200,):
            raise NextcloudError(
                f"Share-Link fehlgeschlagen: HTTP {resp.status_code}"
            )

        # Parse OCS XML response for <url> element
        try:
            root = ET.fromstring(resp.text)
            # OCS response: <ocs><data><url>...</url></data></ocs>
            url_el = root.find(".//{http://open-collaboration-services.org/ns}url")
            if url_el is None:
                # Try without namespace (Nextcloud sometimes omits it)
                url_el = root.find(".//url")
            if url_el is not None and url_el.text:
                logger.info("Share-Link erstellt: %s", url_el.text)
                return url_el.text
        except ET.ParseError:
            pass

        raise NextcloudError(
            "Share-Link konnte nicht aus der Antwort extrahiert werden"
        )

    def search_content(self, query: str, limit: int = 10) -> list[dict]:
        """Volltextsuche in Dateiinhalten via Nextcloud Unified Search API.

        Nutzt das Full text search - Files Plugin (serverseitig).
        Durchsucht PDF-Text, Office-Dokumente, Textdateien etc.

        Args:
            query: Suchbegriff (wird im Dateiinhalt gesucht).
            limit: Maximale Anzahl Ergebnisse.

        Returns:
            Liste von Dicts mit: name, path, excerpt (Textauszug mit Match).

        Raises:
            NextcloudError: Suche fehlgeschlagen.
        """
        if not self._has_credentials:
            raise NextcloudError("Nextcloud-Credentials nicht konfiguriert")

        base_url = (self._url or "").rstrip("/")
        # Unified Search API (NC 20+)
        url = f"{base_url}/ocs/v2.php/search/providers/fulltextsearch/search"

        try:
            resp = httpx.get(
                url,
                auth=self._auth,
                headers={"OCS-APIRequest": "true"},
                params={"term": query, "limit": limit},
                timeout=30.0,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise NextcloudConnectionError(
                f"Server nicht erreichbar: {exc}",
            ) from exc

        self._check_auth_error(resp)

        if resp.status_code not in (200,):
            raise NextcloudError(
                f"Inhaltssuche fehlgeschlagen: HTTP {resp.status_code}",
            )

        # OCS JSON response parsen
        results: list[dict] = []
        try:
            data = resp.json()
            entries = (
                data.get("ocs", {}).get("data", {}).get("entries", [])
            )
            for entry in entries[:limit]:
                title = entry.get("title", "")
                subline = entry.get("subline", "")
                # resourceUrl enthält den NC-Dateipfad
                resource_url = entry.get("resourceUrl", "")
                results.append({
                    "name": title,
                    "path": subline or resource_url,
                    "excerpt": entry.get("excerpt", subline),
                })
        except (ValueError, KeyError, AttributeError) as exc:
            logger.warning("Inhaltssuche: Antwort-Parsing fehlgeschlagen: %s", exc)

        return results
