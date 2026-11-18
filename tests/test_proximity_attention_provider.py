"""Tests fuer ProximityAttentionProvider (Phase 111, E3) mit Fake-Sensor/-Uhr."""

from __future__ import annotations

import logging

import pytest

from elder_berry.avatar.attention import AttentionState
from elder_berry.avatar.proximity_attention_provider import (
    ProximityAttentionProvider,
    ProximityThresholds,
)

A, P, F, U = (
    AttentionState.AWAY,
    AttentionState.PRESENT,
    AttentionState.FOCUSED,
    AttentionState.UNKNOWN,
)
BASE = 128  # Defaults: away < +10, present >= +12, focused ein +30 / aus < +15


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeSensor:
    def __init__(self, value: int = BASE) -> None:
        self.value = value
        self.reads = 0
        self.fail = False

    def read_proximity(self) -> int:
        self.reads += 1
        if self.fail:
            raise OSError(121, "Remote I/O error")
        return self.value


@pytest.fixture
def env():
    clock = FakeClock()
    sensor = FakeSensor()
    provider = ProximityAttentionProvider(sensor, ProximityThresholds(), clock=clock)

    def step(value: int | None = None, dt: float = 0.05) -> AttentionState:
        clock.now += dt
        if value is not None:
            sensor.value = value
        return provider.current()

    return provider, sensor, clock, step


def test_defaults_are_the_documented_placeholders():
    t = ProximityThresholds()
    assert (t.baseline, t.focused_on, t.focused_off) == (128, 30, 15)
    assert (t.debounce_s, t.sample_interval_s) == (0.15, 0.05)
    assert (t.saturation_value, t.fault_after_s, t.fault_clear_s) == (255, 60.0, 10.0)


def test_basic_transitions(env):
    _, _, _, step = env
    assert step(BASE) == A
    assert step(BASE + 12) == P
    for _ in range(3):
        state = step(BASE + 30)
    assert state == P  # noch entprellt
    assert step(BASE + 30) == F  # >= 150 ms ueber focused_on
    assert step(BASE + 20) == F  # ueber focused_off: bleibt
    assert step(BASE + 14) == P  # unter focused_off
    assert step(BASE + 5) == A


def test_focused_can_drop_directly_to_away(env):
    _, _, _, step = env
    for _ in range(5):
        step(BASE + 40)
    assert step() == F
    assert step(BASE) == A


def test_hysteresis_between_away_and_present(env):
    _, _, _, step = env
    assert step(BASE) == A
    assert step(BASE + 11) == A  # Zwischenbereich: bleibt AWAY
    assert step(BASE + 12) == P
    assert step(BASE + 10) == P  # Zwischenbereich: bleibt PRESENT
    assert step(BASE + 9) == A


def test_no_flapping_between_focused_off_and_on(env):
    _, _, _, step = env
    for _ in range(5):
        step(BASE + 31)
    assert step() == F
    states = [step(BASE + value) for value in (16, 29, 15, 28, 17, 29, 15)]
    assert states == [F] * 7  # zwischen +15 und +30: kein Flattern


def test_short_spike_does_not_focus(env):
    _, _, _, step = env
    step(BASE)
    assert step(BASE + 60) == P  # Spitze, erst 0 ms
    assert step(BASE + 60) == P  # 50 ms
    assert step(BASE) == A  # weg vor 150 ms
    assert step(BASE + 60) == P  # neue Spitze beginnt von vorn
    assert step(BASE + 60) == P


def test_reentry_into_focused_is_debounced_again(env):
    _, _, _, step = env
    for _ in range(5):
        step(BASE + 40)
    assert step() == F
    assert step(BASE + 12) == P  # raus
    assert step(BASE + 40) == P  # wieder drueber: NICHT sofort FOCUSED
    assert step(BASE + 40) == P
    assert step(BASE + 40) == P
    assert step(BASE + 40) == F


def test_sampling_rate_is_limited(env):
    provider, sensor, clock, _ = env
    for _ in range(100):  # 100 Aufrufe innerhalb von 99 ms
        provider.current()
        clock.now += 0.001
    assert sensor.reads == 2  # t=0 und t>=50 ms


def test_cached_state_returned_between_samples(env):
    provider, sensor, clock, step = env
    step(BASE + 12)
    sensor.value = BASE  # aendert sich, aber noch kein neues Sample
    clock.now += 0.01
    assert provider.current() == P


def test_long_focused_is_fault_then_recovers(env, caplog):
    caplog.set_level(logging.INFO)
    provider, _, clock, step = env
    for _ in range(4):
        step(BASE + 40)
    assert step() == F
    state = F
    while state == F:
        state = step(dt=1.0)
    assert state == U
    assert provider.is_faulted
    assert clock.now > 60
    assert caplog.text.count("Sensorfehler angenommen") == 1
    # weiter hoch: bleibt UNKNOWN, keine zweite WARNING
    for _ in range(30):
        assert step(dt=1.0) == U
    assert caplog.text.count("Sensorfehler angenommen") == 1
    # unter present_above, aber noch keine 10 s
    for _ in range(9):
        assert step(BASE, dt=1.0) == U
    # Ausreisser setzt die 10 s zurueck
    assert step(BASE + 50, dt=1.0) == U
    for _ in range(10):  # 10 Samples im Abstand 1 s = erst 9 s
        assert step(BASE, dt=1.0) == U
    assert step(BASE, dt=1.0) == A  # 11. Sample: 10 s ununterbrochen
    state = A
    assert not provider.is_faulted
    assert "Fehlerzustand aufgehoben" in caplog.text


def test_saturation_counts_as_fault_after_duration():
    """Saettigung ohne FOCUSED (Grundwert nahe 255): Fehler erst nach 60 s."""
    clock = FakeClock()
    sensor = FakeSensor(255)
    thresholds = ProximityThresholds(
        baseline=250, away_below=1, present_above=2, focused_off=3, focused_on=10
    )
    provider = ProximityAttentionProvider(sensor, thresholds, clock=clock)
    clock.now = 1.0
    assert provider.current() == P  # relativ +5: PRESENT, nicht FOCUSED
    clock.now = 31.0
    assert provider.current() == P  # 30 s gesaettigt: noch kein Fehler
    clock.now = 62.0
    assert provider.current() == U  # > 60 s gesaettigt
    assert provider.is_faulted


def test_single_saturated_sample_is_not_a_fault(env):
    provider, _, _, step = env
    assert step(255) == P
    assert step(BASE) == A
    assert not provider.is_faulted


def test_read_errors_give_unknown_and_throttled_warning(env, caplog):
    caplog.set_level(logging.WARNING)
    provider, sensor, clock, step = env
    sensor.fail = True
    states = [step(dt=1.0) for _ in range(150)]  # 150 s Fehler
    assert set(states) == {U}
    assert provider.error_count == 150
    assert caplog.text.count("Lesefehler") == 3  # t=1, 61, 121
    sensor.fail = False
    assert step(BASE + 12, dt=1.0) == P


@pytest.mark.parametrize(
    "kwargs",
    [
        {"away_below": 20, "present_above": 12},
        {"focused_off": 30, "focused_on": 30},
        {"baseline": 300},
        {"debounce_s": -1},
    ],
)
def test_invalid_thresholds(kwargs):
    with pytest.raises(ValueError):
        ProximityThresholds(**kwargs)


def test_exposes_last_value_and_counts(env):
    provider, _, _, step = env
    step(BASE + 3)
    step(BASE + 4)
    assert provider.last_value == BASE + 4
    assert provider.sample_count == 2
    assert provider.thresholds.baseline == BASE
