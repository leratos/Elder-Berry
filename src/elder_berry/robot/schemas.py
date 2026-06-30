"""Pydantic-Request-Modelle für den :mod:`elder_berry.robot.server`.

Phase 106 (Modul-Entflechtung): aus ``robot/server.py`` ausgelagert, damit die
Server-Datei unter die ~400-Zeilen-Richtlinie kommt. Die Modelle werden in
``server.py`` re-exportiert, sodass bestehende Importe
(``from elder_berry.robot.server import AvatarRequest`` etc.) und Test-Patches
unverändert weiterlaufen. Reiner Symbol-Umzug, keine Verhaltensänderung.

Plattformhinweis: reine Datenmodelle, plattformunabhängig.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Obergrenze für die Amplitude-Liste (§4.2: 50ms-Buckets). 6000 Buckets =
# 5 Minuten Audio – weit über jedem realen TTS-Clip, deckelt aber den Speicher
# bei tokenfreien Deployments (Pydantic weist Längere mit 422 ab, bevor
# _build_amplitude_track die Liste kopiert). Codex P2.
MAX_AMPLITUDE_SAMPLES = 6000


class AvatarDecision(BaseModel):
    """Phase 83.5: Aggregierte Emotions-Entscheidung des Bot-seitigen Resolvers.

    Phase 108: ``confidence`` steuert jetzt das StateMachine-Confidence-Gate am
    RPi5 (nicht mehr nur Logging). Da der RobotServer token-frei laufen kann,
    wird der Wert hart auf ``0.0–1.0`` begrenzt und ``inf``/``NaN`` abgewiesen
    (Pydantic → 422), damit ein fehlerhafter/bösartiger Client keinen
    Out-of-range-Wert als Steuergröße einschleust (z.B. ``2.0``/``NaN``, die den
    ``< threshold``-Check sonst unterliefen).
    """

    emotion: str
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    source: str
    # Phase 110: Anzeige-Tiefe (Blend Richtung neutral). Wie confidence hart auf
    # 0–1 gebunden + kein inf/NaN (token-freier Server-Schutz). Default 1.0 hält
    # ältere Clients ohne intensity-Feld rückwärtskompatibel (= voll/opak).
    intensity: float = Field(default=1.0, ge=0.0, le=1.0, allow_inf_nan=False)


class AvatarRequest(BaseModel):
    """Request: Emotion und/oder Sprechzustand setzen.

    Phase 83.4 (additiv, rückwärtskompatibel): ``amplitude`` trägt das
    Amplitude-Profil (RMS pro 50ms-Bucket, 0.0–1.0) des gesprochenen Audios,
    ``amplitude_duration_ms`` die Gesamtdauer. Beide nur im lokalen
    Playback-Modus gesetzt (§0.2/B1); fehlen sie, fällt der Avatar auf den
    RandomLipSyncDriver zurück (§4.4). ``amplitude`` ist längen-begrenzt
    (:data:`MAX_AMPLITUDE_SAMPLES`), damit ein bösartiger/fehlerhafter Request
    den (ggf. tokenfreien) RobotServer nicht über RAM lahmlegt.

    Phase 83.5 (additiv): ``decision`` trägt die Resolver-Entscheidung
    (Emotion + Confidence + Source) **nur fürs Logging** mit – keine
    Verhaltensänderung am RPi5 (§6.3).
    """

    emotion: str | None = None
    is_speaking: bool | None = None
    amplitude: list[float] | None = Field(default=None, max_length=MAX_AMPLITUDE_SAMPLES)
    amplitude_duration_ms: int | None = None
    decision: AvatarDecision | None = None


class DriveRequest(BaseModel):
    """Request: Fahrbefehl.

    ``direction`` ist auf eine feste Liste eingeschraenkt. Pydantic
    weist alles andere mit 422 ab, bevor es zum MotorController kommt
    -- das ist sowohl Defense-in-Depth (kein freier String aus dem
    Internet steuert die Hardware) als auch log-injection-Mitigation
    (CodeQL erkennt Literal-Constraints als Sanitizer).
    """

    direction: Literal["forward", "backward", "left", "right", "stop"]
    speed: float = 0.5
    duration: float | None = None


class StopRequest(BaseModel):
    """Request: Notfall-Stopp."""

    reason: str = "manual"


class TurntableRotateRequest(BaseModel):
    """Request: Drehteller rotieren."""

    target_degrees: float | None = None  # Absolute Position
    relative_degrees: float | None = None  # Relative Rotation


class HarmonyActivityRequest(BaseModel):
    """Request: Harmony-Aktivitaet starten."""

    activity: str  # z.B. "Fernsehen"


class HarmonyCommandRequest(BaseModel):
    """Request: Harmony-Geraetebefehl senden."""

    device: str  # z.B. "Receiver"
    command: str  # z.B. "VolumeUp"
    repeat: int = 1


class HarmonySceneStartRequest(BaseModel):
    """Request: Szene starten."""

    name: str  # z.B. "Gaming"
