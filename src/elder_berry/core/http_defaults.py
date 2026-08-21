"""Zentrale HTTP-Defaults -- vor allem der Elder-Berry-User-Agent.

Hintergrund (Bugfix WAF-User-Agent, Journal elder-berry#1343): Die
ModSecurity-Regel 338800 ("Atomicorp.com WAF Rules: Blocked recon/fuzz UA")
blockt auf dem Strato-/Plesk-Server jeden Request, dessen User-Agent auf der
Recon-Tool-Blockliste steht. Auf dieser Liste steht ``httpx`` -- gemeint ist
ProjectDiscoverys Scanner, getroffen wird aber auch der Default-UA der
Python-Library httpx (``python-httpx/<version>``), weil ``\bhttpx\b`` an der
Bindestrich-Wortgrenze matcht. Ergebnis: HTTP 403 auf jedem httpx-Request
gegen cloud.last-strawberry.com, unabhaengig vom Pfad.

Der Fix ist bewusst client-seitig: Elder-Berry identifiziert sich mit einem
eigenen, sprechenden User-Agent, statt die WAF-Regel zu entschaerfen. Die
Regel bleibt aktiv und tut, was sie soll.

Der Version-Anteil kommt aus ``elder_berry.__version__`` und driftet damit
nicht gegen das Release (anders als die hart kodierte Version in
``tools/web_fetcher.py``).

Bewusste Ausnahmen, die diesen UA NICHT verwenden:
    * ``tools/web_fetcher.py`` -- tarnt sich absichtlich als Browser, weil
      fremde Sites Bot-UAs blocken.
    * ``web/setup_wizard.py`` (Nominatim) -- deren Nutzungsbedingungen
      verlangen einen eigenen, dienstspezifisch identifizierenden UA.

Import-Hinweis: Dieses Modul haengt bewusst nur an ``elder_berry.__version__``
(ein Blatt ohne eigene Imports). Es importiert nichts aus ``core`` und nichts
aus ``tools``/``web``, damit es aus jeder Schicht zirkelfrei nutzbar bleibt.
"""

from __future__ import annotations

from collections.abc import Mapping

from elder_berry import __version__

#: Projekt-URL im UA -- macht den Client fuer fremde Betreiber zuordenbar.
PROJECT_URL = "https://github.com/leratos/Elder-Berry"

#: Der kanonische Elder-Berry-User-Agent.
#:
#: Verifiziert gegen Regel 338800 (Journal elder-berry#1345): identischer
#: Request mit diesem UA liefert HTTP 200, mit ``python-httpx/0.27.0``
#: HTTP 403.
USER_AGENT = f"Elder-Berry/{__version__} (+{PROJECT_URL})"

_UA_HEADER = "User-Agent"


def with_user_agent(headers: Mapping[str, str] | None = None) -> dict[str, str]:
    """Gibt ``headers`` als neues Dict zurueck, ergaenzt um den Elder-Berry-UA.

    Merge, kein Ersetzen: bestehende Header (z.B. ``Authorization`` oder
    ``Content-Type``) bleiben erhalten. Ein Aufrufer, der den UA-Header
    bereits selbst gesetzt hat, behaelt seinen Wert -- so kann eine bewusste
    Abweichung (siehe Modul-Docstring) nicht versehentlich ueberschrieben
    werden.

    Args:
        headers: Bestehende Header oder ``None``.

    Returns:
        Ein neues Dict. ``headers`` wird nicht mutiert, damit ein am
        Aufrufer gecachtes Dict nicht unbemerkt wandert.
    """
    merged = dict(headers or {})
    if not any(key.lower() == _UA_HEADER.lower() for key in merged):
        merged[_UA_HEADER] = USER_AGENT
    return merged
