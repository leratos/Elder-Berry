"""Tests für RateLimiter (Phase 59)."""

from __future__ import annotations

import pytest

from elder_berry.web.rate_limiter import RateLimiter


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def make_limiter(max_attempts=3, window=60, lockout=120):
    return RateLimiter(
        max_attempts=max_attempts,
        window_seconds=window,
        lockout_seconds=lockout,
        name="test",
    )


# ---------------------------------------------------------------------------
# Konstruktor-Validierung
# ---------------------------------------------------------------------------


def test_invalid_max_attempts():
    with pytest.raises(ValueError, match="max_attempts"):
        RateLimiter(max_attempts=0, window_seconds=60, lockout_seconds=60)


def test_invalid_window():
    with pytest.raises(ValueError, match="window_seconds"):
        RateLimiter(max_attempts=3, window_seconds=0, lockout_seconds=60)


def test_invalid_lockout():
    with pytest.raises(ValueError, match="lockout_seconds"):
        RateLimiter(max_attempts=3, window_seconds=60, lockout_seconds=0)


# ---------------------------------------------------------------------------
# Happy Path – Versuche unterhalb des Limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowed_below_limit():
    limiter = make_limiter(max_attempts=3)
    # Zwei Fehlversuche – beide erlaubt
    assert await limiter.check_and_record("1.2.3.4", now=1000.0) is True
    assert await limiter.check_and_record("1.2.3.4", now=1001.0) is True
    assert await limiter.is_blocked("1.2.3.4", now=1001.0) is False


@pytest.mark.asyncio
async def test_different_keys_independent():
    limiter = make_limiter(max_attempts=2)
    await limiter.check_and_record("192.168.1.1", now=1000.0)
    # 1.1 braucht noch einen Versuch für Lockout, 1.2 ist unberührt
    assert await limiter.is_blocked("192.168.1.2", now=1001.0) is False


# ---------------------------------------------------------------------------
# Lockout bei Überschreitung
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lockout_triggered_at_max():
    limiter = make_limiter(max_attempts=3, window=60, lockout=120)
    now = 1000.0
    # Drei Fehlversuche → dritter löst Lockout aus (return False)
    assert await limiter.check_and_record("ip", now=now) is True
    assert await limiter.check_and_record("ip", now=now + 1) is True
    result = await limiter.check_and_record("ip", now=now + 2)
    assert result is False
    assert await limiter.is_blocked("ip", now=now + 3) is True


@pytest.mark.asyncio
async def test_blocked_during_lockout():
    limiter = make_limiter(max_attempts=2, lockout=300)
    await limiter.check_and_record("ip", now=1000.0)
    await limiter.check_and_record("ip", now=1001.0)  # → Lockout
    # Alle weiteren Checks während Lockout → False
    for t in [1002, 1050, 1200, 1299]:
        assert await limiter.check_and_record("ip", now=float(t)) is False


@pytest.mark.asyncio
async def test_lockout_expires():
    limiter = make_limiter(max_attempts=2, lockout=300)
    await limiter.check_and_record("ip", now=1000.0)
    await limiter.check_and_record("ip", now=1001.0)  # → Lockout bis 1301
    assert await limiter.is_blocked("ip", now=1300.0) is True
    assert await limiter.is_blocked("ip", now=1301.5) is False
    # Nach Ablauf: neue Versuche wieder erlaubt
    assert await limiter.check_and_record("ip", now=1302.0) is True


# ---------------------------------------------------------------------------
# Sliding-Window – alte Versuche fallen raus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sliding_window_resets_old_attempts():
    limiter = make_limiter(max_attempts=3, window=60, lockout=300)
    # Zwei Versuche bei t=1000
    await limiter.check_and_record("ip", now=1000.0)
    await limiter.check_and_record("ip", now=1001.0)
    # Bei t=1070 sind beide außerhalb des 60s-Fensters → Counter auf 1 nach neuem Versuch
    assert await limiter.check_and_record("ip", now=1070.0) is True
    assert await limiter.is_blocked("ip", now=1071.0) is False


# ---------------------------------------------------------------------------
# Reset bei erfolgreichem Login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_clears_attempts():
    limiter = make_limiter(max_attempts=3)
    await limiter.check_and_record("ip", now=1000.0)
    await limiter.check_and_record("ip", now=1001.0)
    await limiter.reset("ip")
    # Nach Reset: kann wieder 3 Mal versuchen
    assert await limiter.check_and_record("ip", now=1002.0) is True
    assert await limiter.check_and_record("ip", now=1003.0) is True
    assert await limiter.is_blocked("ip", now=1003.0) is False


@pytest.mark.asyncio
async def test_reset_nonexistent_key_is_noop():
    limiter = make_limiter()
    await limiter.reset("ghost")  # kein Fehler


# ---------------------------------------------------------------------------
# is_blocked ohne vorherige Versuche
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_blocked_fresh_key():
    limiter = make_limiter()
    assert await limiter.is_blocked("new_ip") is False


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


def test_properties():
    limiter = RateLimiter(
        max_attempts=5, window_seconds=120, lockout_seconds=600, name="login"
    )
    assert limiter.max_attempts == 5
    assert limiter.window_seconds == 120
    assert limiter.lockout_seconds == 600
    assert limiter.name == "login"


# ---------------------------------------------------------------------------
# Cleanup – veraltete Einträge werden entfernt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_removes_stale():
    limiter = make_limiter(max_attempts=2, window=60, lockout=120)
    # Lockout auslösen bei t=0
    await limiter.check_and_record("ip", now=0.0)
    await limiter.check_and_record("ip", now=1.0)  # → Lockout bis t=121
    assert "ip" in limiter._data

    # Cleanup-Interval überschreiten und weit in die Zukunft springen
    limiter._last_cleanup = 0.0
    # t=500 ist weit nach Lockout-Ablauf + Window-Ablauf
    await limiter.check_and_record("other_ip", now=500.0)
    # "ip" sollte bereinigt worden sein
    assert "ip" not in limiter._data
