"""Tests: core.http_defaults -- zentraler Elder-Berry-User-Agent.

Hintergrund: Journal elder-berry#1343 (ModSecurity-Regel 338800 blockt den
httpx-Default-UA) und #1345 (der hier gebaute UA-String ist gegen die Regel
verifiziert: 403 mit ``python-httpx/*``, 200 mit dem Elder-Berry-UA).
"""

from __future__ import annotations

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
