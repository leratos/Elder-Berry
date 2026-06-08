"""AttentionProvider – Stub-Schnittstelle für Sensor-Presence (Phase 83.6 / §3.7).

Friert das Interface ein; die echte APDS-9960-Implementierung kommt in einer
eigenen Hardware-Phase (§11). Das Default-Wiring nutzt
:class:`NoopAttentionProvider` → immer :data:`AttentionState.UNKNOWN`. Die
:class:`~elder_berry.avatar.idle_policy.IdleBehaviorPolicy` behandelt ``UNKNOWN``
(und ``AWAY``) als „Idle erlaubt", sodass sich am sichtbaren Verhalten gegenüber
dem sensorlosen Bestand **nichts** ändert. Nur ein positives Engagement-Signal
(``PRESENT``/``FOCUSED``) unterdrückt das ambient-Idle – und das ist mit dem Stub
unerreichbar.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum


class AttentionState(Enum):
    """Aufmerksamkeits-Zustand aus Sicht eines (künftigen) Presence-Sensors.

    Attributes:
        UNKNOWN: Keine Information (Default des Stubs / kein Sensor).
        AWAY: Kein Nutzer in Reichweite – ambient-Idle erlaubt.
        PRESENT: Nutzer anwesend – aktives Engagement, Idle unterdrückt.
        FOCUSED: Nutzer zugewandt/fokussiert – Idle unterdrückt.
    """

    UNKNOWN = "unknown"
    AWAY = "away"
    PRESENT = "present"
    FOCUSED = "focused"


class AttentionProvider(ABC):
    """Liefert den aktuellen :class:`AttentionState` (Frame-genauer Lese-Zugriff)."""

    @abstractmethod
    def current(self) -> AttentionState:
        """Gibt den aktuellen Aufmerksamkeits-Zustand zurück."""


class NoopAttentionProvider(AttentionProvider):
    """Default-Provider ohne Sensor: liefert immer :data:`AttentionState.UNKNOWN`.

    Damit verhält sich die :class:`~elder_berry.avatar.idle_policy.IdleBehaviorPolicy`
    exakt wie der sensorlose Bestand (Idle erlaubt, solange nicht gesprochen wird).
    """

    def current(self) -> AttentionState:
        return AttentionState.UNKNOWN
