"""Verbindungstests für den Setup-Wizard.

Jede Methode testet einen externen Dienst und gibt ein dict zurück:
    {"success": True/False, ...details}
"""

from __future__ import annotations

import imaplib
import logging
import platform
import re
import shutil
import smtplib
import ssl
import subprocess
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class InvalidExternalURLError(ValueError):
    """URL ist fuer externe Verbindungstests nicht zulaessig."""


# Zulaessige URL-Schemas und Hostname-Format. SSRF-Schutz fuer den
# Setup-Wizard, der unauthenticated im VPN/LAN erreichbar sein kann
# (siehe SECURITY.md M2). Verhindert file://, gopher://, IPv6-Adressen
# ohne Brackets, leere Hostnames und URLs mit Userinfo.
_ALLOWED_SCHEMES = ("http", "https")
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*|"
    r"\d{1,3}(?:\.\d{1,3}){3})$"
)


def _validate_external_url(url: str) -> str:
    """Prueft ein User-Input-URL fuer externe Tests (SSRF-Schutz).

    Akzeptiert nur http/https mit gueltigem Hostname oder IPv4. Lehnt
    Userinfo (``user:pw@``), leere Hosts und URL-Encoded-Tricks ab.
    Wirft :class:`InvalidExternalURLError` bei Verstoessen.
    """
    if not isinstance(url, str) or not url.strip():
        raise InvalidExternalURLError("URL fehlt.")
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise InvalidExternalURLError(
            f"Ungueltiges URL-Schema: {parsed.scheme!r}. "
            "Erlaubt sind nur http und https."
        )
    if parsed.username or parsed.password:
        raise InvalidExternalURLError("URL darf keine Userinfo (user:pw@) enthalten.")
    host = parsed.hostname or ""
    if not host:
        raise InvalidExternalURLError("URL hat keinen Hostname.")
    if not _HOSTNAME_RE.match(host):
        raise InvalidExternalURLError(f"Hostname {host!r} hat ein ungueltiges Format.")
    return url.strip()


# Bekannte E-Mail-Provider (IMAP-Host, IMAP-Port, SMTP-Host, SMTP-Port)
EMAIL_PROVIDERS: dict[str, tuple[str, int, str, int]] = {
    "strato": ("imap.strato.de", 993, "smtp.strato.de", 465),
    "gmx": ("imap.gmx.net", 993, "mail.gmx.net", 465),
    "web.de": ("imap.web.de", 993, "smtp.web.de", 465),
    "gmail": ("imap.gmail.com", 993, "smtp.gmail.com", 465),
    "outlook": ("outlook.office365.com", 993, "smtp.office365.com", 587),
    "t-online": ("secureimap.t-online.de", 993, "securesmtp.t-online.de", 465),
    "ionos": ("imap.ionos.de", 993, "smtp.ionos.de", 465),
    "posteo": ("posteo.de", 993, "posteo.de", 465),
    "mailbox.org": ("imap.mailbox.org", 993, "smtp.mailbox.org", 465),
}


class SetupTests:
    """Verbindungstests für den Setup-Wizard."""

    @staticmethod
    async def test_anthropic(api_key: str) -> dict[str, Any]:
        """Testet Anthropic API Key mit minimalem API-Call."""
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-sonnet-4-6-20250514",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return {"success": True, "model": resp.model}
        except Exception as e:
            logger.error("Anthropic API-Test fehlgeschlagen: %s", e)
            return {
                "success": False,
                "error": "Verbindung fehlgeschlagen – Details im Log.",
            }

    @staticmethod
    async def test_matrix(
        homeserver: str,
        user_id: str,
        token: str,
        room_id: str | None = None,
    ) -> dict[str, Any]:
        """Testet Matrix-Login und optional Raum-Zugriff."""
        try:
            from nio import AsyncClient

            client = AsyncClient(homeserver, user_id)
            client.access_token = token
            resp = await client.whoami()
            result: dict[str, Any] = {"success": True, "user_id": resp.user_id}
            if room_id:
                await client.join(room_id)
                result["room_joined"] = True
            await client.close()
            return result
        except Exception as e:
            logger.error("Matrix-Test fehlgeschlagen: %s", e)
            return {
                "success": False,
                "error": "Matrix-Verbindung fehlgeschlagen – Details im Log.",
            }

    @staticmethod
    async def test_nextcloud(url: str, user: str, password: str) -> dict[str, Any]:
        """Testet WebDAV, CalDAV, CardDAV Erreichbarkeit."""
        results: dict[str, Any] = {
            "webdav": False,
            "caldav": False,
            "carddav": False,
        }
        try:
            safe_url = _validate_external_url(url)
        except InvalidExternalURLError as exc:
            return {
                **results,
                "success": False,
                "error": str(exc),
            }
        auth = (user, password)
        base = safe_url.rstrip("/")
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            # WebDAV
            try:
                r = await client.request(
                    "PROPFIND",
                    f"{base}/remote.php/dav/files/{user}/",
                    auth=auth,
                    headers={"Depth": "0"},
                )
                results["webdav"] = r.status_code in (207, 200)
            except Exception:
                pass
            # CalDAV
            try:
                r = await client.request(
                    "PROPFIND",
                    f"{base}/remote.php/dav/calendars/{user}/",
                    auth=auth,
                    headers={"Depth": "0"},
                )
                results["caldav"] = r.status_code in (207, 200)
            except Exception:
                pass
            # CardDAV
            try:
                r = await client.request(
                    "PROPFIND",
                    f"{base}/remote.php/dav/addressbooks/users/{user}/",
                    auth=auth,
                    headers={"Depth": "0"},
                )
                results["carddav"] = r.status_code in (207, 200)
            except Exception:
                pass
        results["success"] = all(results[k] for k in ("webdav", "caldav", "carddav"))
        return results

    @staticmethod
    async def test_email(
        imap_host: str,
        imap_port: int,
        smtp_host: str,
        smtp_port: int,
        user: str,
        password: str,
    ) -> dict[str, Any]:
        """Testet IMAP- und SMTP-Verbindung."""
        result: dict[str, Any] = {"imap": False, "smtp": False, "unread": 0}
        # IMAP
        try:
            mail = imaplib.IMAP4_SSL(imap_host, imap_port)
            mail.login(user, password)
            mail.select("INBOX")
            _, data = mail.search(None, "UNSEEN")
            result["unread"] = len(data[0].split()) if data[0] else 0
            result["imap"] = True
            mail.logout()
        except Exception as e:
            logger.error("IMAP-Test fehlgeschlagen (%s): %s", imap_host, e)
        # SMTP
        try:
            ctx = ssl.create_default_context()
            if smtp_port == 465:
                srv = smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx)
            else:
                srv = smtplib.SMTP(smtp_host, smtp_port)
                srv.starttls(context=ctx)
            srv.login(user, password)
            srv.quit()
            result["smtp"] = True
        except Exception as e:
            logger.error("SMTP-Test fehlgeschlagen (%s): %s", smtp_host, e)
        result["success"] = result["imap"] and result["smtp"]
        return result

    @staticmethod
    def test_ollama() -> dict[str, Any]:
        """Prüft ob Ollama erreichbar ist und welche Modelle geladen sind."""
        try:
            r = httpx.get("http://localhost:11434/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            return {"success": True, "models": models}
        except Exception:
            return {"success": False, "models": []}

    @staticmethod
    async def test_brave(api_key: str) -> dict[str, Any]:
        """Testet Brave Search API."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": "test"},
                    headers={"X-Subscription-Token": api_key},
                )
            return {"success": r.status_code == 200}
        except Exception as e:
            logger.error("Brave Search-Test fehlgeschlagen: %s", e)
            return {
                "success": False,
                "error": "Brave Search-Verbindung fehlgeschlagen – Details im Log.",
            }

    @staticmethod
    async def test_groq(api_key: str) -> dict[str, Any]:
        """Testet Groq API-Key mit minimalem Request."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            return {"success": r.status_code == 200}
        except Exception as e:
            logger.error("Groq-Test fehlgeschlagen: %s", e)
            return {
                "success": False,
                "error": "Groq-Verbindung fehlgeschlagen – Details im Log.",
            }

    @staticmethod
    async def test_google_maps(api_key: str) -> dict[str, Any]:
        """Testet Google Maps Directions API-Key."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://maps.googleapis.com/maps/api/directions/json",
                    params={
                        "origin": "Berlin",
                        "destination": "Berlin",
                        "key": api_key,
                    },
                )
                data = r.json()
            return {"success": data.get("status") == "OK"}
        except Exception as e:
            logger.error("Google Maps-Test fehlgeschlagen: %s", e)
            return {
                "success": False,
                "error": "Google Maps-Verbindung fehlgeschlagen – Details im Log.",
            }

    @staticmethod
    def check_prerequisites() -> dict[str, Any]:
        """Prüft Systemvoraussetzungen: Python, Git, Ollama."""
        result: dict[str, Any] = {}

        # Python-Version
        result["python"] = platform.python_version()

        # Git
        result["git"] = shutil.which("git") is not None
        if result["git"]:
            try:
                out = subprocess.run(
                    ["git", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                result["git_version"] = out.stdout.strip()
            except Exception:
                result["git_version"] = None

        # Ollama
        ollama_result = SetupTests.test_ollama()
        result["ollama"] = {
            "available": ollama_result["success"],
            "models": ollama_result["models"],
        }

        return result
