"""Tests für die LipSyncDriver (Phase 83.4): Random + Amplitude.

Geltungsbereich: nur lokaler Playback-Modus (§0.2/B1). Hier wird das
Driver-Verhalten isoliert geprüft (Bucket-Mapping, Stille-Pausen, Komponenten-
Existenz-Guard, parametrisiertes Random-Bestandsverhalten).
"""

from __future__ import annotations

import random

import pytest

from elder_berry.avatar.lip_sync import (
    AmplitudeLipSyncDriver,
    RandomLipSyncDriver,
)
from elder_berry.core.audio_analyzer import AmplitudeTrack


# ---------------------------------------------------------------------------
# RandomLipSyncDriver – parametrisiertes Bestandsverhalten (§4.4)
# ---------------------------------------------------------------------------


class TestRandomLipSyncDriver:
    def _driver(self, seed: int = 1, interval: float = 0.18) -> RandomLipSyncDriver:
        return RandomLipSyncDriver(
            keys=["mouth_neutral_close", "mouth_tiny", "mouth_open"],
            weights=[0.5, 0.3, 0.2],
            interval=interval,
            jitter=0.0,
            rng=random.Random(seed),
        )

    def test_starts_on_first_key(self):
        d = self._driver()
        d.start(0.0)
        assert d.mouth_at(0.0) == "mouth_neutral_close"

    def test_no_switch_before_interval(self):
        d = self._driver(interval=0.18)
        d.start(0.0)
        first = d.mouth_at(0.0)
        # Noch innerhalb des Intervalls → gleicher Mund.
        assert d.mouth_at(0.1) == first

    def test_switches_after_interval(self):
        d = self._driver(interval=0.18)
        d.start(0.0)
        d.mouth_at(0.0)
        # Nach Ablauf des Intervalls fällt eine (gewichtete) neue Wahl.
        switched = d.mouth_at(0.2)
        assert switched in {"mouth_neutral_close", "mouth_tiny", "mouth_open"}

    def test_deterministic_with_seeded_rng(self):
        a = self._driver(seed=42)
        b = self._driver(seed=42)
        a.start(0.0)
        b.start(0.0)
        seq_a = [a.mouth_at(t) for t in (0.0, 0.2, 0.4, 0.6, 0.8)]
        seq_b = [b.mouth_at(t) for t in (0.0, 0.2, 0.4, 0.6, 0.8)]
        assert seq_a == seq_b  # gleicher Seed → identische Sequenz

    def test_start_resets_to_first_key(self):
        d = self._driver()
        d.start(0.0)
        d.mouth_at(0.0)
        d.mouth_at(0.2)  # evtl. gewechselt
        d.start(10.0)
        assert d.mouth_at(10.0) == "mouth_neutral_close"

    def test_jitter_varies_next_interval(self):
        d = RandomLipSyncDriver(
            keys=["a", "b"],
            weights=[0.5, 0.5],
            interval=0.18,
            jitter=0.03,
            rng=random.Random(7),
        )
        d.start(0.0)
        # Verhalten bleibt valide (nur a/b), Jitter darf nicht crashen.
        assert d.mouth_at(0.0) in {"a", "b"}
        assert d.mouth_at(0.5) in {"a", "b"}

    def test_empty_keys_raises(self):
        with pytest.raises(ValueError):
            RandomLipSyncDriver(keys=[], weights=[])

    def test_works_without_weights(self):
        d = RandomLipSyncDriver(keys=["x"], interval=0.18, jitter=0.0)
        d.start(0.0)
        assert d.mouth_at(0.0) == "x"
        assert d.mouth_at(1.0) == "x"


# ---------------------------------------------------------------------------
# AmplitudeLipSyncDriver – Bucket-Mapping (§4.2)
# ---------------------------------------------------------------------------


class TestAmplitudeBucketMapping:
    def _driver(self, samples, duration_ms, **kw) -> AmplitudeLipSyncDriver:
        track = AmplitudeTrack(samples=samples, duration_ms=duration_ms)
        d = AmplitudeLipSyncDriver(track, **kw)
        d.start(0.0)
        return d

    def test_all_five_buckets(self):
        # 5 Samples à 50ms → je ein Bucket-Repräsentant.
        d = self._driver([0.0, 0.1, 0.3, 0.6, 0.9], duration_ms=250)
        assert d.mouth_at(0.00) == "mouth_neutral_close"  # 0.0
        assert d.mouth_at(0.05) == "mouth_tiny"  # 0.1
        assert d.mouth_at(0.10) == "mouth_halfopen"  # 0.3
        assert d.mouth_at(0.15) == "mouth_open"  # 0.6
        assert d.mouth_at(0.20) == "mouth_wide"  # 0.9

    def test_bucket_boundaries_inclusive_lower(self):
        # Genau auf der unteren (inklusiven) Grenze.
        d = self._driver([0.05, 0.20, 0.45, 0.75], duration_ms=200)
        assert d.mouth_at(0.00) == "mouth_tiny"  # 0.05
        assert d.mouth_at(0.05) == "mouth_halfopen"  # 0.20
        assert d.mouth_at(0.10) == "mouth_open"  # 0.45
        assert d.mouth_at(0.15) == "mouth_wide"  # 0.75

    def test_silence_pauses_close_mouth(self):
        # Stille zwischen lauten Phasen → geschlossener Mund (§4.2/§4.4).
        d = self._driver([0.9, 0.0, 0.9], duration_ms=150)
        assert d.mouth_at(0.00) == "mouth_wide"
        assert d.mouth_at(0.05) == "mouth_neutral_close"  # Stille
        assert d.mouth_at(0.10) == "mouth_wide"

    def test_index_clamps_to_last_sample(self):
        d = self._driver([0.0, 0.0, 0.9], duration_ms=150)
        # Weit hinter dem Track-Ende → letztes Sample (0.9 → wide).
        assert d.mouth_at(100.0) == "mouth_wide"

    def test_negative_elapsed_uses_first_sample(self):
        d = self._driver([0.9, 0.0], duration_ms=100)
        # now < start_time → idx 0.
        assert d.mouth_at(-5.0) == "mouth_wide"

    def test_empty_track_returns_fallback(self):
        d = self._driver([], duration_ms=0)
        assert d.mouth_at(0.0) == "mouth_neutral_close"


# ---------------------------------------------------------------------------
# AmplitudeLipSyncDriver – Komponenten-Existenz-Guard (§0.6)
# ---------------------------------------------------------------------------


class TestAmplitudeComponentGuard:
    def _wide_driver(self, available) -> AmplitudeLipSyncDriver:
        track = AmplitudeTrack(samples=[0.9], duration_ms=50)
        d = AmplitudeLipSyncDriver(track, available_components=available)
        d.start(0.0)
        return d

    def test_missing_key_falls_back(self):
        # mouth_wide fehlt → Guard liefert den Fallback (kein leerer Blit, §0.6).
        d = self._wide_driver(available={"mouth_neutral_close"})
        assert d.mouth_at(0.0) == "mouth_neutral_close"

    def test_present_key_kept(self):
        d = self._wide_driver(available={"mouth_wide", "mouth_neutral_close"})
        assert d.mouth_at(0.0) == "mouth_wide"

    def test_no_guard_when_components_none(self):
        # available_components=None → kein Guard, Key wird unverändert geliefert.
        d = self._wide_driver(available=None)
        assert d.mouth_at(0.0) == "mouth_wide"

    def test_neither_key_nor_fallback_available_returns_key(self):
        # Renderer no-op't den fehlenden Blit; der Driver liefert den Key zurück.
        d = self._wide_driver(available={"something_else"})
        assert d.mouth_at(0.0) == "mouth_wide"
