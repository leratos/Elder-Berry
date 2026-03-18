"""Tests für AudioRouter – Thread-safe Audio-Routing-Flag."""

import threading

import pytest

from elder_berry.core.audio_router import AudioOutputMode, AudioRouter


class TestAudioOutputMode:
    """AudioOutputMode Enum."""

    def test_matrix_only_value(self):
        assert AudioOutputMode.MATRIX_ONLY.value == "matrix_only"

    def test_matrix_and_local_value(self):
        assert AudioOutputMode.MATRIX_AND_LOCAL.value == "matrix_and_local"

    def test_from_string(self):
        assert AudioOutputMode("matrix_only") == AudioOutputMode.MATRIX_ONLY
        assert AudioOutputMode("matrix_and_local") == AudioOutputMode.MATRIX_AND_LOCAL

    def test_invalid_value(self):
        with pytest.raises(ValueError):
            AudioOutputMode("invalid")


class TestAudioRouterDefaults:
    """Default-Werte."""

    def test_default_mode_matrix_only(self):
        router = AudioRouter()
        assert router.mode == AudioOutputMode.MATRIX_ONLY

    def test_default_local_not_available(self):
        router = AudioRouter()
        assert router.local_available is False

    def test_default_should_not_play_local(self):
        router = AudioRouter()
        assert router.should_play_local() is False

    def test_should_always_send_matrix(self):
        router = AudioRouter()
        assert router.should_send_matrix() is True

    def test_local_available_true(self):
        router = AudioRouter(local_available=True)
        assert router.local_available is True


class TestAudioRouterSetMode:
    """set_mode() Verhalten."""

    def test_set_matrix_and_local(self):
        router = AudioRouter(local_available=True)
        result = router.set_mode(AudioOutputMode.MATRIX_AND_LOCAL)
        assert result == AudioOutputMode.MATRIX_AND_LOCAL
        assert router.mode == AudioOutputMode.MATRIX_AND_LOCAL

    def test_set_matrix_only(self):
        router = AudioRouter(
            default_mode=AudioOutputMode.MATRIX_AND_LOCAL,
            local_available=True,
        )
        result = router.set_mode(AudioOutputMode.MATRIX_ONLY)
        assert result == AudioOutputMode.MATRIX_ONLY

    def test_set_local_without_capability_ignored(self):
        router = AudioRouter(local_available=False)
        result = router.set_mode(AudioOutputMode.MATRIX_AND_LOCAL)
        assert result == AudioOutputMode.MATRIX_ONLY
        assert router.mode == AudioOutputMode.MATRIX_ONLY

    def test_init_local_without_capability_forced_matrix_only(self):
        router = AudioRouter(
            default_mode=AudioOutputMode.MATRIX_AND_LOCAL,
            local_available=False,
        )
        assert router.mode == AudioOutputMode.MATRIX_ONLY


class TestAudioRouterToggle:
    """toggle() Verhalten."""

    def test_toggle_to_local(self):
        router = AudioRouter(local_available=True)
        result = router.toggle()
        assert result == AudioOutputMode.MATRIX_AND_LOCAL

    def test_toggle_back_to_matrix(self):
        router = AudioRouter(
            default_mode=AudioOutputMode.MATRIX_AND_LOCAL,
            local_available=True,
        )
        result = router.toggle()
        assert result == AudioOutputMode.MATRIX_ONLY

    def test_toggle_without_local_stays(self):
        router = AudioRouter(local_available=False)
        result = router.toggle()
        assert result == AudioOutputMode.MATRIX_ONLY

    def test_double_toggle_back_to_original(self):
        router = AudioRouter(local_available=True)
        router.toggle()
        router.toggle()
        assert router.mode == AudioOutputMode.MATRIX_ONLY


class TestAudioRouterShouldPlayLocal:
    """should_play_local() korrekt je nach Modus."""

    def test_false_when_matrix_only(self):
        router = AudioRouter(local_available=True)
        assert router.should_play_local() is False

    def test_true_when_matrix_and_local(self):
        router = AudioRouter(
            default_mode=AudioOutputMode.MATRIX_AND_LOCAL,
            local_available=True,
        )
        assert router.should_play_local() is True

    def test_false_when_no_local_capability(self):
        router = AudioRouter(local_available=False)
        assert router.should_play_local() is False


class TestAudioRouterThreadSafety:
    """Thread-Safety: parallele Zugriffe."""

    def test_concurrent_toggles(self):
        router = AudioRouter(local_available=True)
        results = []

        def toggle_many():
            for _ in range(100):
                results.append(router.toggle())

        threads = [threading.Thread(target=toggle_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Nach 400 Toggles (gerade Zahl) muss Mode == MATRIX_ONLY sein
        assert router.mode == AudioOutputMode.MATRIX_ONLY
        assert len(results) == 400
        # Alle Ergebnisse müssen gültige Modi sein
        assert all(isinstance(r, AudioOutputMode) for r in results)

    def test_concurrent_reads(self):
        router = AudioRouter(local_available=True)
        results = []

        def read_many():
            for _ in range(100):
                results.append(router.mode)
                results.append(router.should_play_local())

        threads = [threading.Thread(target=read_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 800
