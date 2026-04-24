"""EmotionTracker – Emotionales Kurzzeitgedächtnis für persistente Stimmung."""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from elder_berry.character.base import Emotion

logger = logging.getLogger(__name__)

# Tendenz-Labels basierend auf Valenz-Verlauf
_EMOTION_VALENCE: dict[Emotion, float] = {
    Emotion.CHEERFUL: 1.0,
    Emotion.MOTIVATED: 0.8,
    Emotion.SHY: 0.2,
    Emotion.NEUTRAL: 0.0,
    Emotion.THOUGHTFUL: 0.0,
    Emotion.WHISPER: -0.1,
    Emotion.SARCASTIC: -0.3,
    Emotion.SAD: -0.6,
    Emotion.DEPRESSED: -0.8,
    Emotion.ANGRY: -0.7,
}


@dataclass
class EmotionEntry:
    """Ein einzelner Emotions-Eintrag im Tracker."""

    emotion: Emotion
    timestamp: datetime


class EmotionTracker:
    """
    Ringbuffer für die letzten Emotionen mit Decay und Trend-Erkennung.

    Einträge älter als ``decay_minutes`` werden bei Abfragen ignoriert.
    """

    def __init__(
        self,
        max_entries: int = 5,
        decay_minutes: int = 30,
    ) -> None:
        self._max_entries = max_entries
        self._decay = timedelta(minutes=decay_minutes)
        self._entries: deque[EmotionEntry] = deque(maxlen=max_entries)

    def record(self, emotion: Emotion, timestamp: datetime | None = None) -> None:
        """Zeichnet eine neue Emotion auf."""
        ts = timestamp or datetime.now()
        self._entries.append(EmotionEntry(emotion=emotion, timestamp=ts))
        logger.debug("Emotion recorded: %s @ %s", emotion.value, ts)

    def _active_entries(self, now: datetime | None = None) -> list[EmotionEntry]:
        """Gibt nur nicht-verfallene Einträge zurück."""
        now = now or datetime.now()
        cutoff = now - self._decay
        return [e for e in self._entries if e.timestamp >= cutoff]

    def dominant_emotion(self, now: datetime | None = None) -> Emotion:
        """Häufigste Emotion der aktiven Einträge. NEUTRAL als Fallback."""
        active = self._active_entries(now)
        if not active:
            return Emotion.NEUTRAL
        counts: dict[Emotion, int] = {}
        for entry in active:
            counts[entry.emotion] = counts.get(entry.emotion, 0) + 1
        return max(counts, key=counts.get)  # type: ignore[arg-type]

    def get_trend(self, now: datetime | None = None) -> str | None:
        """
        Ermittelt die Tendenz basierend auf dem Valenz-Verlauf.

        Returns:
            'aufhellend', 'abkühlend', 'stabil', 'wechselhaft' oder None
            wenn weniger als 2 Einträge vorhanden.
        """
        active = self._active_entries(now)
        if len(active) < 2:
            return None

        valences = [_EMOTION_VALENCE.get(e.emotion, 0.0) for e in active]
        diffs = [valences[i + 1] - valences[i] for i in range(len(valences) - 1)]

        avg_diff = sum(diffs) / len(diffs)
        avg_abs_diff = sum(abs(d) for d in diffs) / len(diffs)

        # Prüfe ob alle Diffs das gleiche Vorzeichen haben
        all_positive = all(d > 0.05 for d in diffs)
        all_negative = all(d < -0.05 for d in diffs)

        if all_positive or avg_diff > 0.3:
            return "aufhellend"
        if all_negative or avg_diff < -0.3:
            return "abkühlend"
        # Große Schwankungen in wechselnde Richtungen
        if avg_abs_diff > 0.3 and abs(avg_diff) <= 0.2:
            return "wechselhaft"
        if abs(avg_diff) <= 0.1 and avg_abs_diff <= 0.3:
            return "stabil"
        return "wechselhaft"

    def get_mood_summary(self, now: datetime | None = None) -> str | None:
        """
        Generiert eine strukturierte Zusammenfassung für den System-Prompt.

        Returns:
            Formatierter String oder None wenn keine aktiven Einträge.
        """
        active = self._active_entries(now)
        if not active:
            return None

        # Emotions-Verlauf
        emotion_chain = " → ".join(e.emotion.value for e in active)
        dominant = self.dominant_emotion(now)
        trend = self.get_trend(now)

        parts = [
            f"Emotionaler Kontext: {emotion_chain}",
            f"Dominante Stimmung: {dominant.value}",
        ]
        if trend:
            parts.append(f"Tendenz: {trend}")

        return " | ".join(parts)

    @property
    def entry_count(self) -> int:
        """Anzahl aller Einträge (inkl. verfallener)."""
        return len(self._entries)

    def clear(self) -> None:
        """Löscht alle Einträge."""
        self._entries.clear()
