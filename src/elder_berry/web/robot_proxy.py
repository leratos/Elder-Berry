"""Robot-Proxy -- Reverse-Proxy von ``/api/robot/*`` zum RPi5-RobotServer.

Phase 66: Browser auf ``https://fern.example.com`` kann den
RPi5 nicht direkt unter seiner LAN-IP ansprechen
(Mixed-Content-Block, kein LAN-Routing aus dem Internet, CORS auf dem
RobotServer nur Loopback). Saleria reicht die Calls deshalb gleicher
Origin durch:

    Browser  ──HTTPS── nginx ──HTTP── Saleria  ──HTTP── 127.0.0.1:12800
                                       (Tunnel-Endpoint)         │
                                                                 ▼
                                                            RPi5 (LAN)

Vorteile:
- Kein CORS-Problem (Frontend bleibt same-origin gegen Saleria).
- Kein Mixed-Content-Block (HTTPS-Page → relative URL).
- ``X-Saleria-Robot-Token`` wird Server-seitig aus dem SecretStore
  hinzugefuegt -- der Token landet *nicht* im Frontend.
- Funktioniert auch wenn der User nicht im LAN/VPN sitzt.

Schutz: Der Pfad ``/api/robot`` ist Teil der ``DashboardAuthMiddleware
.PROTECTED_PREFIXES``, d.h. ohne gueltiges Login-Cookie kommt nichts
durch.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from elder_berry.core.log_sanitize import safe_log

if TYPE_CHECKING:
    from fastapi import FastAPI

    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

# Defense-in-Depth gegen SSRF (CodeQL py/partial-ssrf): Host kommt
# zwar aus dem SecretStore (Admin-konfiguriert), aber wir validieren
# trotzdem, dass er als http(s)://hostname[:port] parst und der
# upstream_path keine Scheme-Injection (``://``) oder CR/LF enthaelt.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*|"
    r"\d{1,3}(?:\.\d{1,3}){3})$"
)


def _is_safe_host(host: str) -> bool:
    """Validiert raw ``host`` (vor jeder Schema-Mutation).

    Akzeptiert ``hostname[:port][/path]`` ohne Schema oder mit
    ``http(s)://``. Lehnt jede andere Scheme-Vorgabe ab (``file://``,
    ``gopher://``, ``javascript:``, ...). Hostname muss RFC-1035-Pattern
    oder IPv4 sein. Wenn ein Port angegeben ist, muss er numerisch sein
    -- damit faengt der Validator auch Pseudo-Schemes wie
    ``javascript:alert(1)`` ab, die kein ``//`` haben.
    """
    if not host:
        return False
    if "://" in host:
        scheme, _, rest = host.partition("://")
        if scheme.lower() not in ("http", "https"):
            return False
    else:
        rest = host
    # rest = hostname[:port][/path]
    authority = rest.split("/", 1)[0]
    if ":" in authority:
        hostname, _, port = authority.partition(":")
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            return False
    else:
        hostname = authority
    if not hostname:
        return False
    return bool(_HOSTNAME_RE.match(hostname))


def _is_safe_upstream_path(path: str) -> bool:
    """Verhindert Scheme-Injection und Header-Forgery via Path."""
    if "\r" in path or "\n" in path:
        return False
    if "://" in path:
        return False
    return True


ROBOT_TOKEN_HEADER = "X-Saleria-Robot-Token"

ROBOT_HOST_KEY = "robot_host"
ROBOT_AUTH_TOKEN_KEY = "robot_auth_token"

# Default-Timeout fuer Proxy-Calls. Harmony-Hub-Aufrufe koennen ein paar
# Sekunden brauchen, deshalb grosszuegig. Browser-Frontend hat eigene
# Polling-Logik und kann mit hoeheren Latenzen umgehen.
DEFAULT_TIMEOUT = httpx.Timeout(connect=3.0, read=20.0, write=10.0, pool=5.0)

# Header die NICHT vom Client durchgereicht werden duerfen.
# - Hop-by-hop-Header (RFC 7230): Verbindungs-spezifisch
# - host: Sonst sieht der RPi5 fern.example.com statt 127.0.0.1
# - cookie: Saleria-Session-Cookie hat auf dem RPi5 nichts zu suchen
# - x-saleria-robot-token: Wird vom Proxy selbst gesetzt (aus SecretStore)
# - content-length: Wird von httpx aus dem Body neu errechnet
_BLOCKED_REQUEST_HEADERS = frozenset(
    {
        "host",
        "cookie",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "x-saleria-robot-token",
    }
)

# Headers, die NICHT zurueck zum Client gehen.
# - Hop-by-hop wie oben
# - set-cookie: RobotServer setzt keine Cookies, defensiv weglassen
# - access-control-*: CORS-Header werden von der CORS-Middleware
#   im Saleria-FastAPI selbst gesetzt; doppelte Header = Browser-Konfusion
_BLOCKED_RESPONSE_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "set-cookie",
        "access-control-allow-origin",
        "access-control-allow-credentials",
        "access-control-allow-methods",
        "access-control-allow-headers",
        "access-control-expose-headers",
        "access-control-max-age",
    }
)


def _filter_request_headers(
    headers: dict[str, str],
    token: str | None,
) -> dict[str, str]:
    """Baut die Header-Map fuer den Upstream-Request."""
    out = {
        k: v for k, v in headers.items() if k.lower() not in _BLOCKED_REQUEST_HEADERS
    }
    if token:
        out[ROBOT_TOKEN_HEADER] = token
    return out


def _filter_response_headers(headers) -> dict[str, str]:
    """Baut die Header-Map fuer die Antwort an den Browser."""
    return {
        k: v for k, v in headers.items() if k.lower() not in _BLOCKED_RESPONSE_HEADERS
    }


def register_robot_proxy_routes(
    app: FastAPI,
    secret_store: SecretStore,
    *,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
) -> None:
    """Registriert ``/api/robot/{path:path}`` als Reverse-Proxy zum RPi5.

    Parameters
    ----------
    app : FastAPI
        Die Saleria-Settings-Dashboard-App.
    secret_store : SecretStore
        Quelle fuer ``robot_host`` und ``robot_auth_token``. Wenn
        ``robot_host`` leer ist, antwortet der Proxy mit 503.
    timeout : httpx.Timeout
        Timeout fuer Upstream-Calls.
    """

    @app.api_route(
        "/api/robot/{upstream_path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    )
    async def robot_proxy(upstream_path: str, request: Request) -> Response:
        host = secret_store.get_or_none(ROBOT_HOST_KEY)
        if not host or not host.strip():
            return JSONResponse(
                {
                    "error": (
                        "robot_host nicht konfiguriert -- bitte im "
                        "Settings-Dashboard unter 'Infrastruktur' setzen."
                    ),
                    "code": "no_robot_host",
                },
                status_code=503,
            )
        host = host.strip()
        # SSRF Defense-in-Depth: host stammt aus dem SecretStore, aber
        # wir validieren das Format hier nochmal -- damit kann selbst ein
        # versehentlicher Eintrag wie ``file:///etc/passwd`` keinen
        # Request ausloesen. Validator laeuft auf dem rohen host VOR
        # rstrip + Schema-Mutation, sonst wuerde ``http://`` zu ``http:``
        # geschrumpft und ``file:///`` zu ``http://file:/``.
        if not _is_safe_host(host):
            logger.warning(
                "Robot-Proxy: ungueltiger robot_host: %s",
                safe_log(host),
            )
            return JSONResponse(
                {
                    "error": "robot_host hat ein ungueltiges Format.",
                    "code": "invalid_robot_host",
                },
                status_code=503,
            )
        if not _is_safe_upstream_path(upstream_path):
            logger.warning(
                "Robot-Proxy: ungueltiger upstream_path: %s",
                safe_log(upstream_path),
            )
            return JSONResponse(
                {
                    "error": "Ungueltiger Pfad.",
                    "code": "invalid_path",
                },
                status_code=400,
            )

        # Trailing-Slash entfernen + robot_host kann mit oder ohne Schema
        # gespeichert sein. Wir zwingen http://, weil der RobotServer
        # kein TLS terminiert.
        host = host.rstrip("/")
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"

        token = secret_store.get_or_none(ROBOT_AUTH_TOKEN_KEY)
        # Token ist optional -- wenn der RobotServer keinen verlangt
        # (z.B. Test-Setups), funktioniert der Proxy ohne. In Produktion
        # sollte er gesetzt sein, sonst gibt der RobotServer 401.

        target_url = f"{host}/{upstream_path}"
        if request.url.query:
            target_url = f"{target_url}?{request.url.query}"

        body = await request.body()
        headers = _filter_request_headers(dict(request.headers), token)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                upstream = await client.request(
                    request.method,
                    target_url,
                    headers=headers,
                    content=body,
                )
        except httpx.ConnectError as exc:
            logger.warning(
                "Robot-Proxy: Connection zu %s fehlgeschlagen: %s",
                safe_log(target_url),
                exc,
            )
            return JSONResponse(
                {
                    "error": (
                        f"RPi5 nicht erreichbar ueber {host} -- "
                        "SSH-Tunnel down oder RobotServer offline."
                    ),
                    "code": "rpi5_unreachable",
                },
                status_code=502,
            )
        except httpx.TimeoutException:
            logger.warning(
                "Robot-Proxy: Timeout fuer %s",
                safe_log(target_url),
            )
            return JSONResponse(
                {
                    "error": "Timeout zum RPi5.",
                    "code": "rpi5_timeout",
                },
                status_code=504,
            )
        except httpx.RequestError:
            logger.exception(
                "Robot-Proxy: Request-Fehler fuer %s",
                safe_log(target_url),
            )
            return JSONResponse(
                {
                    "error": "Proxy-Fehler beim Weiterleiten an den RPi5.",
                    "code": "proxy_error",
                },
                status_code=502,
            )

        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=_filter_response_headers(upstream.headers),
            media_type=upstream.headers.get("content-type"),
        )
