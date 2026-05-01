"""OriginCheckMiddleware -- CSRF-Schutz via Origin/Referer-Validierung.

Phase 64 (H-1): Ergaenzt ``SameSite=strict``-Cookies um einen strikten
Origin-Header-Check fuer alle state-changing Methoden (POST, PUT, DELETE,
PATCH). Blockt Requests mit 403, deren Origin- bzw. Referer-Header nicht
in der ``allowed_origins``-Liste steht.

Defense-in-Depth: SameSite=strict verhindert, dass moderne Browser Cookies
ueberhaupt bei Cross-Site-Requests mitschicken. Der Origin-Check greift
zusaetzlich, falls

- der Browser SameSite nicht korrekt enforced (aelter/buggy),
- ein Angreifer nicht-Cookie-basierte Auth nutzt (z.B. Bearer Token im
  Header, der via CORS-Fehler ohnehin nicht gesendet wird, aber Header
  Injection via Flash-Relikte bleibt ein Restrisiko),
- ein zukuenftiger Aufrufer Cookies per ``credentials: "include"`` doch
  mitsenden will.

GET/HEAD/OPTIONS werden nicht geprueft (nicht state-changing). CORS-
Preflights (OPTIONS) kommen ohne Auth-Relevanz durch und werden von der
nachgelagerten CORS-Middleware behandelt.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Iterable

    from starlette.requests import Request

logger = logging.getLogger(__name__)

_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Blockiert state-changing Requests mit fremdem Origin/Referer."""

    def __init__(self, app, allowed_origins: Iterable[str]) -> None:
        super().__init__(app)
        # Normalisierung: wir vergleichen nur scheme://host[:port],
        # nicht den Pfad. Das deckt sich mit dem Browser-Verhalten beim
        # Origin-Header.
        self._allowed: frozenset[str] = frozenset(
            self._normalize(o) for o in allowed_origins if o and o.strip()
        )

    @staticmethod
    def _normalize(origin: str) -> str:
        """Normalisiert auf ``scheme://host[:port]``.

        Schema und Hostname werden kanonisiert; bei HTTP/HTTPS wird der
        jeweilige Default-Port entfernt. Trailing-Slashes und Pfade werden
        ignoriert.
        """
        stripped = origin.strip()
        parsed = urlparse(stripped)
        if parsed.scheme and parsed.netloc:
            try:
                hostname = parsed.hostname
                port = parsed.port
            except ValueError:
                return stripped.rstrip("/")

            if hostname:
                scheme = parsed.scheme.lower()
                host = hostname.lower()
                if ":" in host and not host.startswith("["):
                    host = f"[{host}]"

                default_port = {"http": 80, "https": 443}.get(scheme)
                if port is not None and port != default_port:
                    host = f"{host}:{port}"

                return f"{scheme}://{host}"

        return stripped.rstrip("/")

    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        if method not in _STATE_CHANGING_METHODS:
            return await call_next(request)

        # Origin-Header bevorzugt, Referer als Fallback.
        origin = request.headers.get("origin")
        if origin:
            origin = self._normalize(origin)
        else:
            referer = request.headers.get("referer")
            if referer:
                origin = self._normalize(referer)

        if not origin or origin not in self._allowed:
            client_host = request.client.host if request.client else "unknown"
            logger.warning(
                "CSRF-Block: %s %s von %s -- Origin=%r (erlaubt: %s)",
                method,
                request.url.path,
                client_host,
                origin,
                sorted(self._allowed),
            )
            return JSONResponse(
                {
                    "error": "Origin nicht erlaubt.",
                    "code": "origin_forbidden",
                },
                status_code=403,
            )

        return await call_next(request)
