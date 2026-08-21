"""Verbindungstests für den Setup-Wizard.

Jede Methode testet einen externen Dienst und gibt ein dict zurück:
    {"success": True/False, ...details}
"""

from __future__ import annotations

import asyncio
import imaplib
import ipaddress
import logging
import platform
import re
import shutil
import smtplib
import socket
import ssl
import subprocess
from typing import Any
from urllib.parse import urlparse

import httpx

from elder_berry.core.http_defaults import with_user_agent
from elder_berry.core.log_sanitize import safe_log

logger = logging.getLogger(__name__)


class InvalidExternalURLError(ValueError):
    """URL ist fuer externe Verbindungstests nicht zulaessig.

    ``code`` kennzeichnet die Reject-Kategorie und erlaubt sichere
    User-Meldungen ohne Echo des User-Inputs (CodeQL py/stack-trace-exposure).
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


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

# Kategorisierte User-Meldungen ohne User-Input-Echo. Werden in
# test_nextcloud anhand des Reject-Codes ausgewaehlt.
_URL_ERROR_MESSAGES: dict[str, str] = {
    "missing": "Ungültige Nextcloud-URL: URL fehlt.",
    "scheme": "Ungültige Nextcloud-URL: ungültiges Schema (nur http/https erlaubt).",
    "userinfo": "Ungültige Nextcloud-URL: Userinfo (user:pw@) ist nicht erlaubt.",
    "no_host": "Ungültige Nextcloud-URL: kein Hostname.",
    "bad_host": "Ungültige Nextcloud-URL: ungültiges Hostname-Format.",
    "blocked": "Ungültige Nextcloud-URL: interne/Loopback-/Metadata-Adresse "
    "ist nicht erlaubt.",
}


# Bekannte Cloud-Metadata-Adressen, die in KEINE der is_*-Kategorien fallen.
# IPv4-Link-Local 169.254.169.254 ist bereits via ``is_link_local`` abgedeckt;
# die IPv6-IMDS-ULA (AWS) dagegen ist ``is_private`` und wuerde sonst -- wie
# das fuers LAN bewusst erlaubte RFC-4193 -- durchrutschen.
_BLOCKED_METADATA_IPS = frozenset(
    {
        ipaddress.ip_address("fd00:ec2::254"),  # AWS IPv6 Instance Metadata
    }
)


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True, wenn die IP eine SSRF-gefaehrliche interne Adresse ist.

    Blockiert Loopback, Link-Local (169.254/16 inkl. Cloud-Metadata
    169.254.169.254), Unspecified (0.0.0.0/::), Multicast, Reserved sowie
    bekannte IPv6-Metadata-Endpunkte (:data:`_BLOCKED_METADATA_IPS`).

    Bewusst NICHT blockiert: private RFC-1918-/CGNAT-Ranges (10/8, 172.16/12,
    192.168/16, 100.64/10). Elder-Berry-Nutzer hosten Nextcloud/Mail legitim
    im LAN oder via VPN (Tailscale) -- ein Block dort waere ein Funktions-
    verlust (vgl. Test ``test_accepts_valid_http_urls`` mit 192.168.1.10).
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if ip in _BLOCKED_METADATA_IPS:
        return True
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
    )


def _literal_host_blocked(host: str) -> bool:
    """Sync, non-blocking: True, wenn ``host`` ein IP-Literal aus einer
    blockierten Range ist. Macht KEIN DNS und ist damit event-loop-sicher."""
    try:
        return _ip_is_blocked(ipaddress.ip_address(host))
    except ValueError:
        return False


async def _assert_host_allowed(host: str) -> None:
    """Wirft :class:`InvalidExternalURLError`, wenn ``host`` intern aufloest.

    IP-Literale werden sofort (sync, non-blocking) geprueft. DNS-Namen werden
    via ``getaddrinfo`` in einem Worker-Thread aufgeloest -- NICHT auf dem
    Event-Loop, damit ein langsamer/haengender Resolver die Server-Coroutinen
    nicht blockiert -- und jede Adresse wird geprueft (faengt z. B.
    ``metadata.google.internal`` -> 169.254.169.254). Nicht aufloesbare Namen
    werden durchgelassen -- ein DNS-Fehler ist kein SSRF-Gewinn, und der
    eigentliche Verbindungsversuch laeuft dann ohnehin ins Leere.

    Limit: Validierungs-Zeitpunkt-Check; ein spaeteres DNS-Rebinding (andere
    Antwort beim eigentlichen connect) kann theoretisch abweichen (bekannte
    TOCTOU-Schwaeche, ``follow_redirects`` ist am httpx-Client zusaetzlich
    deaktiviert).
    """
    if not isinstance(host, str) or not host:
        raise InvalidExternalURLError("Ungueltiger Hostname.", code="bad_host")
    if _literal_host_blocked(host):
        raise InvalidExternalURLError(
            "Interne/Loopback-/Metadata-Adresse ist nicht erlaubt.",
            code="blocked",
        )
    try:
        ipaddress.ip_address(host)
        return  # war ein (erlaubtes) IP-Literal -> kein DNS noetig
    except ValueError:
        pass
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except socket.gaierror:
        return
    for info in infos:
        try:
            resolved = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _ip_is_blocked(resolved):
            raise InvalidExternalURLError(
                "Hostname zeigt auf eine interne/Metadata-Adresse.",
                code="blocked",
            )


def _validate_external_url(url: str) -> str:
    """Prueft ein User-Input-URL fuer externe Tests (SSRF-Schutz).

    Akzeptiert nur http/https mit gueltigem Hostname oder IPv4. Lehnt
    Userinfo (``user:pw@``), leere Hosts und URL-Encoded-Tricks ab.
    Wirft :class:`InvalidExternalURLError` bei Verstoessen.
    """
    if not isinstance(url, str) or not url.strip():
        raise InvalidExternalURLError("URL fehlt.", code="missing")
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise InvalidExternalURLError(
            f"Ungueltiges URL-Schema: {parsed.scheme!r}. "
            "Erlaubt sind nur http und https.",
            code="scheme",
        )
    if parsed.username or parsed.password:
        raise InvalidExternalURLError(
            "URL darf keine Userinfo (user:pw@) enthalten.",
            code="userinfo",
        )
    host = parsed.hostname or ""
    if not host:
        raise InvalidExternalURLError("URL hat keinen Hostname.", code="no_host")
    if not _HOSTNAME_RE.match(host):
        raise InvalidExternalURLError(
            f"Hostname {host!r} hat ein ungueltiges Format.",
            code="bad_host",
        )
    # Sync: IP-Literale sofort blocken (kein DNS -> event-loop-sicher). Die
    # DNS-Namen-Aufloesung macht der async-Aufrufer via _assert_host_allowed.
    if _literal_host_blocked(host):
        raise InvalidExternalURLError(
            "Interne/Loopback-/Metadata-Adresse ist nicht erlaubt.",
            code="blocked",
        )
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
            # DNS-Namen zusaetzlich off-loop aufloesen + gegen interne Ziele
            # pruefen (IP-Literale hat _validate_external_url schon geblockt).
            await _assert_host_allowed(urlparse(safe_url).hostname or "")
        except InvalidExternalURLError as exc:
            logger.warning("Nextcloud-URL-Validierung fehlgeschlagen: %s", exc)
            return {
                **results,
                "success": False,
                "error": _URL_ERROR_MESSAGES.get(exc.code, "Ungültige Nextcloud-URL."),
            }
        auth = (user, password)
        base = safe_url.rstrip("/")
        async with httpx.AsyncClient(
            timeout=10,
            follow_redirects=False,
            headers=with_user_agent(),
        ) as client:
            # WebDAV -- isoliert: Fehler einer Probe darf die anderen nicht abbrechen.
            try:
                r = await client.request(
                    "PROPFIND",
                    f"{base}/remote.php/dav/files/{user}/",
                    auth=auth,
                    headers={"Depth": "0"},
                )
                results["webdav"] = r.status_code in (207, 200)
            except httpx.HTTPError as exc:
                logger.debug("WebDAV-Probe fehlgeschlagen: %s", safe_log(exc))
            # CalDAV -- isoliert: Fehler einer Probe darf die anderen nicht abbrechen.
            try:
                r = await client.request(
                    "PROPFIND",
                    f"{base}/remote.php/dav/calendars/{user}/",
                    auth=auth,
                    headers={"Depth": "0"},
                )
                results["caldav"] = r.status_code in (207, 200)
            except httpx.HTTPError as exc:
                logger.debug("CalDAV-Probe fehlgeschlagen: %s", safe_log(exc))
            # CardDAV -- isoliert: Fehler einer Probe darf die anderen nicht abbrechen.
            try:
                r = await client.request(
                    "PROPFIND",
                    f"{base}/remote.php/dav/addressbooks/users/{user}/",
                    auth=auth,
                    headers={"Depth": "0"},
                )
                results["carddav"] = r.status_code in (207, 200)
            except httpx.HTTPError as exc:
                logger.debug("CardDAV-Probe fehlgeschlagen: %s", safe_log(exc))
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
        # SSRF-Schutz: Mail-Hosts duerfen nicht auf interne/Loopback-/Metadata-
        # Adressen zeigen (gleiche Policy wie Nextcloud, privates LAN bleibt
        # erlaubt). Greift, weil imap/smtp_host aus dem unauthentifizierten
        # First-Run-Wizard-Body stammen.
        for mail_host in (imap_host, smtp_host):
            try:
                await _assert_host_allowed(mail_host)
            except InvalidExternalURLError:
                # Host bewusst NICHT mitloggen: CodeQL stuft aus dem SecretStore
                # gelesene Werte pauschal als "secret" ein (clear-text-logging),
                # und der konkrete Host ist fuer das Audit-Log unerheblich.
                # Faengt zugleich nicht-String-Hosts (z. B. JSON-Liste) ab,
                # bevor getaddrinfo() mit einem TypeError abbricht.
                logger.warning("Mail-Host abgelehnt: ungueltig oder intern.")
                result["success"] = False
                result["error"] = (
                    "Mail-Host ungültig oder interne/Loopback-Adresse "
                    "(nicht erlaubt)."
                )
                return result
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
            # Host nicht mitloggen (SecretStore-Wert -> CodeQL clear-text-logging);
            # safe_log(e) strippt CR/LF gegen Log-Injection (Host kann in der
            # Exception-Message stecken).
            logger.error("IMAP-Test fehlgeschlagen: %s", safe_log(e))
        # SMTP
        try:
            ctx = ssl.create_default_context()
            srv: smtplib.SMTP_SSL | smtplib.SMTP
            if smtp_port == 465:
                srv = smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx)
            else:
                srv = smtplib.SMTP(smtp_host, smtp_port)
                srv.starttls(context=ctx)
            srv.login(user, password)
            srv.quit()
            result["smtp"] = True
        except Exception as e:
            # Siehe IMAP-Zweig: Host nicht loggen, Exception via safe_log.
            logger.error("SMTP-Test fehlgeschlagen: %s", safe_log(e))
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
