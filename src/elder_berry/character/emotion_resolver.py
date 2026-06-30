"""EmotionResolver – aggregiert Emotions-Signale zu einer EmotionDecision.

Phase 83.1 (Reactive AvatarEngine). Scoring-Modell statt Enum-Mittelung:
jede Quelle wirft ``(Emotion, Gewicht)`` in einen Topf, das Maximum gewinnt die
*Identität*, die Summe ergibt die *Confidence*. Keine Valenz-Rückabbildung
(NEUTRAL und THOUGHTFUL teilen die Valenz 0.0, das wäre mehrdeutig).

Standalone und opt-in: dieser Resolver wird in 83.1 noch nicht in den
``Assistant`` verdrahtet (das ist 83.5). ``character.extract_emotion`` bleibt
der aktive Pfad und damit das Default-Verhalten unverändert.

Confidence-Skala (deterministisch, Gewichte 0.7/0.2/0.1):
    * Tag + leerer Tracker         → 0.7
    * Tag + Tracker-Übereinstimmung → bis 0.9
    * Tag + Widerspruch            → 0.7 (Tag gewinnt die Identität)
    * nur Tracker                  → bis 0.2
    * nichts                       → 0.0

Phase 109/110: ein Tag kann eine Intensität tragen (``[emotion:staerke]``).
Ab Phase 110 (Modell B) ist die **Confidence intensitäts-unabhängig** (ein Tag
trägt die volle ``tag_weight`` und schaltet immer um); die Intensität steuert
ausschließlich die **Anzeige-Tiefe** über das eigene Feld
``EmotionDecision.intensity`` (Blend Richtung neutral im Renderer). Die Skala
oben gilt damit wieder wie in Tier 1 – das Gate hält nur tag-lose Turns.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from elder_berry.character.base import CharacterEngine, Emotion
from elder_berry.character.emotion_tracker import EmotionTracker

logger = logging.getLogger(__name__)

# Default-Gewicht des LLM-Tags im Scoring. Auch vom Legacy-/Fallback-Pfad
# (``Assistant`` ohne Resolver) genutzt, um die Intensität → Confidence identisch
# zu skalieren (Phase 109), damit ``[emotion:intensity]`` überall gleich wirkt.
DEFAULT_TAG_WEIGHT = 0.7


@dataclass(frozen=True)
class EmotionDecision:
    """Ergebnis der Emotions-Aggregation für einen Turn."""

    emotion: Emotion
    confidence: float  # 0.0–1.0 (Identitäts-Sicherheit → Phase-108-Gate)
    source: str  # "llm_tag" | "tracker_trend" | "sensor" | "fallback"
    raw_signals: dict[str, float]  # Debug: alle beitragenden Eingangs-Scores
    intensity: float = 1.0  # Phase 110: Anzeige-Tiefe (Blend), 0.0–1.0


class EmotionResolver:
    """Aggregiert LLM-Tag, EmotionTracker-Trend (+ Sensor-Stub) zu einer Decision.

    Der LLM-Tag (Gewicht 0.7) entscheidet faktisch *welche* Emotion; der
    Tracker-Trend (0.2) hebt nur die Confidence bzw. springt ein, wenn kein Tag
    da ist. Das Sensor-Gewicht (0.1) ist für eine spätere Phase reserviert.

    Der Resolver übernimmt – nur bei vorhandenem Tag und **nach** dem Trend-Read
    – ``set_mood`` und ``tracker.record`` (B4): identische Aufzeichnungs-Semantik
    wie das heutige ``extract_emotion``.
    """

    def __init__(
        self,
        character: CharacterEngine,
        emotion_tracker: EmotionTracker,
        tag_weight: float = DEFAULT_TAG_WEIGHT,
        trend_weight: float = 0.2,
        sensor_weight: float = 0.1,
    ) -> None:
        self._character = character
        self._tracker = emotion_tracker
        self._tag_weight = tag_weight
        self._trend_weight = trend_weight
        self._sensor_weight = sensor_weight

    def resolve_from_llm(
        self,
        llm_response: str,
        sensor_state: object | None = None,
    ) -> EmotionDecision:
        """Leitet die Emotion aus LLM-Tag + Tracker-Trend ab.

        Args:
            llm_response: Rohe LLM-Antwort mit möglichem [emotion]-Tag.
            sensor_state: Reserviert (Sensor-Stub, Phase 83.x). Kein Beitrag.

        Returns:
            Eine :class:`EmotionDecision`. Bei vorhandenem Tag werden Mood und
            Tracker (nach dem Trend-Read) aktualisiert.
        """
        scores: dict[Emotion, float] = defaultdict(float)
        raw: dict[str, float] = {}

        # Tag + optionale Intensität (Phase 109; 0.0–1.0, ohne ``:x`` → 1.0).
        parsed = self._character.parse_emotion_tag_with_intensity(llm_response)
        tag: Emotion | None = None
        intensity = 1.0
        if parsed is not None:
            tag, intensity = parsed
        # Phase 110 (Modell B): der Tag trägt die VOLLE ``tag_weight``-Confidence,
        # **unabhängig** von der Intensität (Rücknahme der 109-Skalierung). Ein
        # Tag ist immer „sicher genug" zum Umschalten – das Confidence-Gate hält
        # nur noch tag-lose/Tracker-Turns. Die Intensität steuert ausschließlich
        # die Anzeige-Tiefe (Blend, eigenes ``EmotionDecision.intensity``-Feld).
        # Intensität 0 zählt als KEIN Signal (kein Score/Record → Fallback), damit
        # ``[emotion:0.0]`` nicht „leer" schaltet und den Tracker verschmutzt.
        tag_contributes = tag is not None and intensity > 0.0
        if tag_contributes:
            scores[tag] += self._tag_weight
            raw["llm_tag"] = self._tag_weight

        # Trend VOR record lesen, sonst verfälscht der eigene Eintrag die Ratio.
        dom, ratio = self._tracker.dominant_with_confidence()
        if ratio > 0.0:
            damp = 0.5 if self._tracker.get_trend() == "wechselhaft" else 1.0
            contribution = self._trend_weight * ratio * damp
            scores[dom] += contribution
            raw["tracker_trend"] = contribution

        # sensor_state: Stub → kein Beitrag (sensor_weight für Sensor-Phase reserviert).

        if not scores:
            return EmotionDecision(Emotion.NEUTRAL, 0.0, "fallback", raw, 1.0)

        emotion = max(scores, key=scores.get)  # type: ignore[arg-type]
        if tag == emotion:
            source = "llm_tag"
        elif dom == emotion:
            source = "tracker_trend"
        else:  # defensiv – bei vorhandenem Tag gewinnt der Tag immer (0.7 > 0.2)
            source = "fallback"

        if tag_contributes:  # B4 + Phase 110 (kein Null-Tag-Record)
            # Die explizite Intensität in den MoodState durchreichen (der
            # Parameter existierte schon, wurde bisher mit Default gefüttert).
            self._character.set_mood(emotion, intensity)
            self._tracker.record(emotion)  # record NACH Trend-Read

        # Phase 110: ``intensity`` (Anzeige-Tiefe) nur vom Tag; sonst 1.0 (eine
        # Trend-/Fallback-Emotion wird ohnehin vom Gate gehalten, nie angezeigt).
        decision_intensity = intensity if tag_contributes else 1.0
        return EmotionDecision(
            emotion, round(scores[emotion], 3), source, raw, decision_intensity
        )
