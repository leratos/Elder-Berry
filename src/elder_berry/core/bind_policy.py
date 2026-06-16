"""Bind-/Token-Policy fuer netz-exponierte Server (fail-closed).

Phase 103 (S1): Die fail-closed-Logik existierte bisher nur in
``scripts/start_rpi5.py`` (Phase 64 H-2) und konnte von anderen
Server-Einstiegspunkten (Robot-Simulator, AgentServer) nicht ohne fragilen
``scripts``-Import wiederverwendet werden. Sie lebt jetzt hier, an einer
Stelle, parametrisiert auf Server-Label + Token-Env-Name.

Leitidee: Ein Server, der **kein** Token erzwingt, darf nur auf einem
Loopback-Interface binden. Soll er auf einem Nicht-Loopback-Interface binden
(``0.0.0.0``, ``::``, LAN-IP), aber es ist kein Token gesetzt, wird der Start
abgebrochen (statt nur gewarnt -- Warnungen werden im systemd-Log uebersehen).

Der Logger wird vom Aufrufer injiziert, damit caplog-/Log-Assertions am
jeweiligen Modul-Logger haengen bleiben (z. B. ``elder_berry.rpi5``).
"""

from __future__ import annotations

import ipaddress
import logging
import sys

# ``localhost`` ist kein IP-Literal -> Sonderfall. ``127.0.0.0/8`` und ``::1``
# werden ueber ipaddress.is_loopback erkannt.
_LOOPBACK_NAMES = frozenset({"localhost"})


def is_loopback_host(host: str) -> bool:
    """True wenn ``host`` nur ueber Loopback erreichbar ist.

    Akzeptiert ``localhost``, ``127.0.0.0/8``, ``::1``. ``0.0.0.0`` und
    ``::`` gelten NICHT als Loopback (binden auf alle Interfaces).
    """
    stripped = host.strip().lower().strip("[]")
    if stripped in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(stripped).is_loopback
    except ValueError:
        return False


def enforce_token_policy(
    token: str | None,
    host: str,
    *,
    token_env_name: str,
    server_label: str,
    logger: logging.Logger,
) -> None:
    """Bricht den Start ab, wenn Token fehlt UND Bind nicht Loopback ist.

    Args:
        token: Das (bereits getrimmte) Token oder ``None``/leer.
        host: Der Bind-Host, auf den der Server binden soll.
        token_env_name: Name der Env-Var, die das Token liefert -- erscheint
            im Fix-Hinweis.
        server_label: Sprechendes Label fuer die Log-Zeilen (z. B. ``Robot``).
        logger: Der Logger des Aufrufers (haelt Log-Assertions stabil).

    Raises:
        SystemExit: Exit-Code 2, wenn kein Token gesetzt UND der Host auf einem
        nicht-Loopback-Interface bindet. Exit-Code 2, damit systemd den
        Unterschied zu regulaeren Fehlern (1) sieht.
    """
    if token:
        return
    if is_loopback_host(host):
        logger.warning(
            "%s-Token NICHT konfiguriert -- Server bindet nur auf Loopback "
            "(%s). Fuer Dev/Tests OK, fuer Produktion bitte %s setzen.",
            server_label,
            host,
            token_env_name,
        )
        return
    logger.error(
        "%s-Token NICHT konfiguriert, aber Server soll auf %s "
        "(nicht-Loopback) binden.",
        server_label,
        host,
    )
    logger.error(
        "Alle Endpoints waeren im Netzwerk ungeprueft erreichbar. Abbruch.",
    )
    logger.error(
        "Fix: %s setzen, oder den Server explizit auf 127.0.0.1 (Loopback) "
        "binden.",
        token_env_name,
    )
    sys.exit(2)
