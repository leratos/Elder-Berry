"""LipSyncDriver – wählt beim Sprechen pro Frame den Mund-Layer (Phase 83.4).

Geltungsbereich: **nur lokaler Playback-Modus** (§0.2 / B1). Im
``matrix_only``-Default sendet der Bot kein Speaking-Signal, daher läuft dort
weder das Amplitude- noch das Random-Lip-Sync.

Zwei Implementierungen:

- :class:`RandomLipSyncDriver` – parametrisiertes Bestandsverhalten (gewichtete
  Zufallsauswahl alle ``interval ± jitter`` Sekunden). Dient als Fallback-
  Vertrag (§4.4) und als künftige Heimat des heute noch im Renderer liegenden
  Random-Lip-Sync (Umzug erst 83.6).
- :class:`AmplitudeLipSyncDriver` – O(1)-Lookup in einen
  :class:`~elder_berry.core.audio_analyzer.AmplitudeTrack` nach
  ``now - start_time``; RMS-Bucket → Mund-Key (§4.2, bewusst nicht-uniform).
  Stille → geschlossener Mund; Komponenten-Existenz-Guard (§0.6).

Die Auswahl (Amplitude vs. Random) trifft der :class:`AvatarController`:
liegt ein nutzbarer AmplitudeTrack vor → ``AmplitudeLipSyncDriver``, sonst kein
Driver (→ der Renderer behält bis 83.6 seinen Inline-Random-Lip-Sync, §4.4).
"""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod
from collections.abc import Collection, Sequence

from elder_berry.core.audio_analyzer import AmplitudeTrack

logger = logging.getLogger(__name__)

# §4.2 Amplitude→Mouth-Frame-Tabelle (bewusst nicht-uniform): (untere
# RMS-Grenze inklusive, Mund-Key), absteigend geprüft. Der erste Eintrag, dessen
# Grenze ``<= RMS`` ist, gewinnt. Sprache hat einen RMS-Median um 0.1–0.3, daher
# liegt die Auflösung bewusst im unteren Bereich.
DEFAULT_AMPLITUDE_BUCKETS: tuple[tuple[float, str], ...] = (
    (0.75, "mouth_wide"),
    (0.45, "mouth_open"),
    (0.20, "mouth_halfopen"),
    (0.05, "mouth_tiny"),
    (0.00, "mouth_neutral_close"),
)

# Mund bei Stille / als Komponenten-Guard-Fallback (§0.6).
SILENCE_MOUTH = "mouth_neutral_close"

# Default-Wechselintervall + Jitter des Random-Drivers (s) – Bestandswerte.
DEFAULT_LIP_SYNC_INTERVAL = 0.18
DEFAULT_LIP_SYNC_JITTER = 0.03


class LipSyncDriver(ABC):
    """Liefert beim Sprechen den aktuellen Mund-Komponenten-Key.

    Geltungsbereich: nur lokaler Playback-Modus (§0.2 / B1).
    """

    @abstractmethod
    def start(self, now: float) -> None:
        """Markiert den Sprechbeginn (Zeit-Nullpunkt / Zustands-Reset).

        Args:
            now: ``time.monotonic``-Zeitpunkt des Sprechbeginns.
        """

    @abstractmethod
    def mouth_at(self, now: float) -> str:
        """Gibt den Mund-Key für den Frame zum monotonen Zeitpunkt ``now``."""


class RandomLipSyncDriver(LipSyncDriver):
    """Gewichtete Zufallsauswahl – parametrisiertes Bestandsverhalten (§4.4).

    Repliziert ``LayeredSpriteRenderer._get_lip_sync_mouth`` (Wechsel alle
    ``interval ± jitter`` Sekunden, gewichtete Auswahl). Dient als Fallback-
    Vertrag und als künftige Heimat des heute noch im Renderer lebenden
    Random-Lip-Sync (Umzug erst 83.6). Eine injizierbare ``rng`` macht Tests
    deterministisch.
    """

    def __init__(
        self,
        keys: Sequence[str],
        weights: Sequence[float] | None = None,
        interval: float = DEFAULT_LIP_SYNC_INTERVAL,
        jitter: float = DEFAULT_LIP_SYNC_JITTER,
        rng: random.Random | None = None,
    ) -> None:
        if not keys:
            raise ValueError("RandomLipSyncDriver braucht mindestens einen Mund-Key")
        self._keys = list(keys)
        self._weights = list(weights) if weights else None
        self._interval = interval
        self._jitter = jitter
        self._rng = rng if rng is not None else random.Random()
        self._mouth = self._keys[0]
        self._last_switch = 0.0
        self._next_interval = interval

    def start(self, now: float) -> None:
        """Setzt auf den ersten Mund-Key zurück (wie der show_speaking-Edge)."""
        self._mouth = self._keys[0]
        self._last_switch = now
        self._next_interval = self._interval

    def mouth_at(self, now: float) -> str:
        """Wechselt den Mund nach Ablauf des (gejitterten) Intervalls."""
        if now - self._last_switch >= self._next_interval:
            self._mouth = self._rng.choices(
                self._keys, weights=self._weights, k=1
            )[0]
            self._last_switch = now
            self._next_interval = self._interval + self._rng.uniform(
                -self._jitter, self._jitter
            )
        return self._mouth


class AmplitudeLipSyncDriver(LipSyncDriver):
    """O(1)-Mund-Lookup aus einem AmplitudeTrack (§4.2).

    Index ``= (now - start) / Sample-Dauer``; der RMS-Wert des Buckets wird über
    die :data:`DEFAULT_AMPLITUDE_BUCKETS`-Tabelle auf einen Mund-Key abgebildet.
    Stille (RMS unter der untersten Nicht-Null-Grenze) → geschlossener Mund.

    Ein Komponenten-Existenz-Guard (§0.6) ersetzt einen nicht vorhandenen
    Mund-Key durch den Fallback, damit kein leerer Blit entsteht (analog
    ``_start_idle_action``).
    """

    def __init__(
        self,
        track: AmplitudeTrack,
        *,
        available_components: Collection[str] | None = None,
        buckets: tuple[tuple[float, str], ...] = DEFAULT_AMPLITUDE_BUCKETS,
        fallback_mouth: str = SILENCE_MOUTH,
    ) -> None:
        """
        Args:
            track: Amplitude-Profil (RMS pro Bucket, 0..1).
            available_components: Vorhandene Komponenten-Keys für den
                Existenz-Guard. ``None`` = kein Guard (alle Keys gelten als
                verfügbar).
            buckets: RMS→Mund-Tabelle (absteigende untere Grenzen).
            fallback_mouth: Mund bei Stille / nicht verfügbarem Key.
        """
        self._track = track
        self._available = available_components
        self._buckets = buckets
        self._fallback = fallback_mouth
        self._start_time = 0.0
        n = len(track.samples)
        self._ms_per_sample = (track.duration_ms / n) if n else 0.0

    def start(self, now: float) -> None:
        """Setzt den Zeit-Nullpunkt für den Sample-Lookup."""
        self._start_time = now

    def mouth_at(self, now: float) -> str:
        """Liest den RMS-Bucket bei ``now`` und mappt ihn auf den Mund-Key."""
        samples = self._track.samples
        if not samples or self._ms_per_sample <= 0:
            return self._guard(self._fallback)
        elapsed_ms = max(0.0, (now - self._start_time) * 1000.0)
        idx = int(elapsed_ms / self._ms_per_sample)
        if idx >= len(samples):
            idx = len(samples) - 1
        return self._guard(self._mouth_for_rms(samples[idx]))

    def _mouth_for_rms(self, rms: float) -> str:
        """Bildet einen RMS-Wert über die Bucket-Tabelle auf einen Mund-Key ab."""
        for lower, key in self._buckets:
            if rms >= lower:
                return key
        return self._fallback

    def _guard(self, key: str) -> str:
        """Komponenten-Existenz-Guard (§0.6): nicht vorhandener Key → Fallback."""
        if self._available is None or key in self._available:
            return key
        if self._fallback in self._available:
            logger.debug("Mund-Key '%s' fehlt → Fallback '%s'", key, self._fallback)
            return self._fallback
        return key
