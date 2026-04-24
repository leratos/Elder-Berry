"""URL-Validator -- Schutz vor SSRF auf private/loopback/metadata-IPs.

Fuer alle Stellen, an denen eine URL aus unvertrauter Quelle (Matrix-User,
LLM-Tool-Call, externer Webhook) vom Server abgerufen wird. Blockiert:

- Nicht-http(s)-Schemata (file://, gopher://, ftp://, ...)
- Private IPv4-Bereiche (10/8, 172.16/12, 192.168/16, 169.254/16)
- Loopback (127/8, ::1)
- Link-Local (169.254/16, fe80::/10)
- Multicast, reserved, unspecified
- IPv4-mapped IPv6, die auf die obigen Bereiche zeigen

TOCTOU-Hinweis: Zwischen DNS-Resolution hier und dem spaeteren httpx-Call
kann sich die Aufloesung aendern. Fuer den aktuellen Use-Case (unmittelbar
folgender Fetch, keine langen Caches) ist der Schutz ausreichend. Fuer
hoeheres Schutzniveau muesste httpx gegen die bereits resolvte IP sprechen
(--> nicht in diesem Scope).
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class UnsafeUrlError(ValueError):
    """URL zeigt auf eine nicht-oeffentliche IP oder nutzt ein verbotenes Schema."""


_ALLOWED_SCHEMES = frozenset({"http", "https"})


def ensure_public_url(url: str, *, allow_loopback: bool = False) -> str:
    """Validiert, dass eine URL auf eine oeffentlich routbare IP zeigt.

    Parameters
    ----------
    url : str
        Die zu pruefende URL.
    allow_loopback : bool
        Wenn True, werden 127.0.0.0/8 und ::1 erlaubt. Default False.
        Gedacht fuer Tests oder bewusst auf Loopback konfigurierte lokale
        Services (dann aber lieber separate Code-Pfade nutzen).

    Returns
    -------
    str
        Die Eingabe-URL (unveraendert, nach strip), wenn Validierung
        erfolgreich.

    Raises
    ------
    UnsafeUrlError
        Wenn URL leer, Schema nicht http(s), Host fehlt, DNS-Aufloesung
        scheitert, oder eine aufgeloeste IP nicht oeffentlich ist.
    """
    if not url or not url.strip():
        raise UnsafeUrlError("URL ist leer.")

    normalized = url.strip()
    parsed = urlparse(normalized)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(
            f"Schema '{parsed.scheme}' nicht erlaubt. "
            f"Erlaubt: {', '.join(sorted(_ALLOWED_SCHEMES))}."
        )

    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL enthaelt keinen Host.")

    try:
        addrinfo = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(
            f"Host '{host}' nicht aufloesbar: {exc}"
        ) from exc

    if not addrinfo:
        raise UnsafeUrlError(f"Host '{host}' liefert keine IP-Adresse.")

    for info in addrinfo:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            # getaddrinfo liefert immer gueltige IPs, aber robust bleiben.
            continue

        if _is_forbidden(ip, allow_loopback=allow_loopback):
            raise UnsafeUrlError(
                f"URL '{normalized}' zeigt auf nicht-oeffentliche IP {ip}."
            )

    return normalized


def _is_forbidden(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    allow_loopback: bool,
) -> bool:
    """True wenn die IP nicht oeffentlich routbar ist.

    Prueft auch IPv4-mapped IPv6 (``::ffff:10.0.0.1``), die sonst durch
    ``is_private`` auf der IPv6-Seite nicht erkannt werden.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_forbidden(ip.ipv4_mapped, allow_loopback=allow_loopback)

    if ip.is_loopback:
        return not allow_loopback
    if ip.is_private:
        return True
    if ip.is_link_local:
        return True
    if ip.is_multicast:
        return True
    if ip.is_reserved:
        return True
    if ip.is_unspecified:
        return True
    return False
