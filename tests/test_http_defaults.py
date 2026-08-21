"""Tests: core.http_defaults -- zentraler Elder-Berry-User-Agent.

Hintergrund: Journal elder-berry#1343 (ModSecurity-Regel 338800 blockt den
httpx-Default-UA) und #1345 (der hier gebaute UA-String ist gegen die Regel
verifiziert: 403 mit ``python-httpx/*``, 200 mit dem Elder-Berry-UA).
"""

from __future__ import annotations

import re

from elder_berry import __version__
from elder_berry.core.http_defaults import (
    PROJECT_URL,
    USER_AGENT,
    with_user_agent,
)


# ---------------------------------------------------------------------------
# USER_AGENT
# ---------------------------------------------------------------------------


def test_user_agent_traegt_die_laufende_version():
    """Kein hart kodierter Version-Anteil -- sonst driftet er gegen Releases."""
    assert __version__ in USER_AGENT
    assert USER_AGENT.startswith(f"Elder-Berry/{__version__}")


def test_user_agent_nennt_die_projekt_url():
    """Macht den Client fuer fremde Betreiber zuordenbar."""
    assert PROJECT_URL in USER_AGENT


def test_user_agent_entspricht_dem_verifizierten_string():
    """Exakt der String, der in #1345 gegen die WAF gemessen wurde (HTTP 200)."""
    assert USER_AGENT == (
        f"Elder-Berry/{__version__} (+https://github.com/leratos/Elder-Berry)"
    )


# ---------------------------------------------------------------------------
# with_user_agent -- Merge-Semantik
# ---------------------------------------------------------------------------


def test_with_user_agent_ohne_header():
    assert with_user_agent() == {"User-Agent": USER_AGENT}
    assert with_user_agent(None) == {"User-Agent": USER_AGENT}


def test_with_user_agent_merged_statt_zu_ersetzen():
    """Kernfall gym_data (#1344): der Bearer-Token darf nicht verschwinden."""
    merged = with_user_agent({"Authorization": "Bearer geheim"})

    assert merged["Authorization"] == "Bearer geheim"
    assert merged["User-Agent"] == USER_AGENT


def test_with_user_agent_erhaelt_alle_fremden_header():
    merged = with_user_agent(
        {
            "Authorization": "Bearer geheim",
            "Content-Type": "application/json; charset=utf-8",
            "Depth": "0",
        }
    )

    assert merged["Authorization"] == "Bearer geheim"
    assert merged["Content-Type"] == "application/json; charset=utf-8"
    assert merged["Depth"] == "0"
    assert merged["User-Agent"] == USER_AGENT


def test_with_user_agent_mutiert_das_original_nicht():
    """Aufrufer cachen Header-Dicts (gym_data haelt self._client)."""
    original = {"Authorization": "Bearer geheim"}

    merged = with_user_agent(original)

    assert original == {"Authorization": "Bearer geheim"}
    assert merged is not original


def test_with_user_agent_respektiert_expliziten_ua():
    """Bewusste Abweichungen (web_fetcher-Stil) werden nicht ueberschrieben."""
    merged = with_user_agent({"User-Agent": "Mozilla/5.0 (compatible; X/1.0)"})

    assert merged["User-Agent"] == "Mozilla/5.0 (compatible; X/1.0)"


def test_with_user_agent_erkennt_ua_case_insensitive():
    """HTTP-Header sind case-insensitive -- sonst haetten wir zwei UA-Header."""
    merged = with_user_agent({"user-agent": "Mozilla/5.0 (compatible; X/1.0)"})

    assert merged["user-agent"] == "Mozilla/5.0 (compatible; X/1.0)"
    assert "User-Agent" not in merged


# ---------------------------------------------------------------------------
# Guard gegen ModSecurity-Regel 338800
# ---------------------------------------------------------------------------

# UA-Blockliste der Regel 338800 ("Atomicorp.com WAF Rules: Blocked recon/fuzz
# UA", /etc/apache2/modsecurity.d/rules/tortix/modsec/20_asl_useragents.conf),
# uebernommen aus dem in #1343 protokollierten Regel-Treffer. Gemeint sind
# Recon-/Fuzzing-Tools; "httpx" trifft als Kollateralschaden die
# Python-Library gleichen Namens.
_RULE_338800_BLOCKED_TOKENS = (
    "httpx",
    "nabuu",
    "ffuf",
    "gobuster",
    "feroxbuster",
    "wfuzz",
    "jaeles",
    "zgrab2",
    "commix",
    "xsstrike",
    "kiterunner",
    "katana",
    "kr",
)


def _rule_338800_hits(user_agent: str) -> list[str]:
    """Nachbau der Regel-Semantik: Token an Wortgrenzen, case-insensitive.

    Die Wortgrenze ist der Kern des Befunds -- genau deshalb matcht
    ``\bhttpx\b`` in ``python-httpx/0.27.0`` am Bindestrich.
    """
    return [
        token
        for token in _RULE_338800_BLOCKED_TOKENS
        if re.search(rf"\b{re.escape(token)}\b", user_agent, re.IGNORECASE)
    ]


def test_user_agent_passiert_regel_338800():
    """Der Kern des Bugfixes: unser UA steht auf keiner Blockliste."""
    assert _rule_338800_hits(USER_AGENT) == []


def test_guard_faengt_den_httpx_default_ua():
    """Negativ-Kontrolle -- ohne sie waere der Guard oben vakuum.

    Beweist, dass der Nachbau die Regel wirklich nachbildet: der
    httpx-Default-UA (der Ist-Zustand vor dem Fix) wird erkannt.
    """
    assert _rule_338800_hits("python-httpx/0.27.0") == ["httpx"]
    assert _rule_338800_hits("python-httpx/0.28.1") == ["httpx"]


def test_guard_faengt_auch_andere_blockliste_tokens():
    """Zweite Kontrolle: der Guard haengt nicht allein an 'httpx'."""
    assert _rule_338800_hits("ffuf/2.1.0") == ["ffuf"]
    assert _rule_338800_hits("Mozilla/5.0 (katana)") == ["katana"]


def test_guard_ist_nicht_ueberempfindlich():
    """'https' im UA darf nicht als 'httpx' durchgehen (sonst false positive)."""
    assert _rule_338800_hits("Etwas/1.0 (+https://example.com)") == []
