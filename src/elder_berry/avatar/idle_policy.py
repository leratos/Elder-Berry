"""IdleBehaviorPolicy – Idle- und Blink-Verhalten des Avatars (Phase 83.6).

Bis 83.5 lebten Idle und Blink im Renderer (``LayeredSpriteRenderer._update_idle``
/ ``_update_blink`` etc., per ``random``). Diese Subphase zieht **die Logik** hier
heraus – das **sichtbare Verhalten bleibt identisch** (globaler 2–6 s-Blink,
zufällige Idle-Aktion ~5–15 s, flache 2 s-Dauer). Nur der Ort wechselt; der
Renderer wendet die hier aufgelösten Overrides nur noch an.

Kernpunkte:

- **Blink** ist mood-**unabhängig** global 2–6 s (B2/§0.4); ``can_blink: false``
  blinzelt nie (Asset-Lock). Der Blink-Timer läuft – wie im Bestand – nur für
  blinzelnde Moods weiter (für nicht-blinzelnde eingefroren). Blink ist
  **unabhängig** vom Sprechen (wie heute).
- **Idle** triggert nur, wenn ``not is_speaking`` (Gate beim Aufrufer über
  :meth:`frame_overrides`) **und** keine aktive Aufmerksamkeit gemeldet ist:
  ``UNKNOWN``/``AWAY`` erlauben Idle (Default-Stub → unverändertes Verhalten),
  ``PRESENT``/``FOCUSED`` unterdrücken es (§3.6/§3.7).
- **Briefing-Modus** (formell, über :class:`BriefingModeProvider`): Idle-Frequenz
  −50 % und nur ``soft_close`` als Aktion (§3.6). Default-Provider = casual.
- Eine injizierbare ``random.Random`` macht Tests deterministisch (gleiches Muster
  wie :class:`~elder_berry.avatar.lip_sync.RandomLipSyncDriver`).

Die Policy ist **nicht** thread-safe; die Serialisierung übernimmt der
:class:`~elder_berry.avatar.controller.AvatarController` über seinen Lock
(§0.6/§6.5) – ``current_idle_blink`` ruft :meth:`frame_overrides` unter Lock.
"""

from __future__ import annotations

import random
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from elder_berry.avatar.attention import AttentionProvider, AttentionState
from elder_berry.avatar.briefing_mode import (
    BriefingModeProvider,
    CasualBriefingModeProvider,
)
from elder_berry.character.base import Emotion

# Blink-Timing (mood-unabhängig, B2/§0.4) – ehem. layered_renderer-Konstanten.
BLINK_MIN_INTERVAL = 2.0  # Sekunden
BLINK_MAX_INTERVAL = 6.0
BLINK_DURATION = 0.15  # Sekunden

# Idle-Timing – ehem. layered_renderer-Konstanten.
IDLE_MIN_INTERVAL = 5.0  # Sekunden zwischen Idle-Aktionen
IDLE_MAX_INTERVAL = 15.0
IDLE_ACTION_DURATION = 2.0  # Sekunden, die eine Idle-Aktion dauert (flat, wie Bestand)

# Geschlossene Augen während eines Blinks (Bestand: feste Keys, kein Guard).
BLINK_EYES: tuple[str, str] = ("eye_left_close", "eye_right_close")

# Formeller Briefing-Modus (§3.6): nur diese Idle-Aktion ist erlaubt, und die
# Idle-Frequenz wird halbiert (Intervall × Faktor).
FORMAL_IDLE_ACTION = "soft_close"
FORMAL_IDLE_FACTOR = 2.0  # −50 % Frequenz = doppeltes Intervall

# Aufmerksamkeits-Zustände, die ambient-Idle unterdrücken (aktives Engagement).
_ATTENTION_SUPPRESSES_IDLE: frozenset[AttentionState] = frozenset(
    {AttentionState.PRESENT, AttentionState.FOCUSED}
)


@dataclass(frozen=True)
class IdleAction:
    """Eine Idle-Aktion als Layer-Override (ohne Dauer – die ist global flat).

    Attributes:
        name: Aktionsname (z. B. ``glance_left``/``soft_close``); steuert u. a.
            den Formell-Filter.
        eye_left: Augen-Key links während der Aktion (``None`` = Emotion-Default).
        eye_right: Augen-Key rechts (``None`` = Emotion-Default).
        mouth: Mund-Key während der Aktion (``None`` = Emotion-Default).
    """

    name: str
    eye_left: str | None
    eye_right: str | None
    mouth: str | None


@dataclass(frozen=True)
class IdleBlinkOverrides:
    """Die pro Frame aufgelösten Idle-/Blink-Overrides für den Renderer.

    Attributes:
        blink_eyes: Geschlossene Augen-Keys während eines Blinks (sonst ``None``).
        idle_eyes: Augen-Keys einer aktiven Idle-Aktion (sonst ``None``).
        idle_mouth: Mund-Key einer aktiven Idle-Aktion (sonst ``None``).
    """

    blink_eyes: tuple[str, str] | None = None
    idle_eyes: tuple[str, str] | None = None
    idle_mouth: str | None = None


class IdleBehaviorPolicy:
    """Hält Idle- und Blink-Zustand und löst pro Frame die Overrides auf.

    Args:
        idle_actions: Verfügbare Idle-Aktionen (aus der geladenen Avatar-Config;
            der :class:`AvatarController` reicht ``renderer.idle_actions`` durch).
        can_blink: Emotion → ``can_blink``-Flag (aus ``renderer.emotion_map``).
            Unbekannte Emotion ⇒ ``False`` (kein Blink, wie der Renderer-Fallback).
        attention_provider: Liefert den :class:`AttentionState` (Default-Wiring:
            :class:`NoopAttentionProvider` → ``UNKNOWN`` → Idle erlaubt).
        briefing_provider: Formell-vs-casual (Default :class:`CasualBriefingModeProvider`).
        available_components: Vorhandene Komponenten-Keys; eine Idle-Aktion mit
            fehlendem Augen-/Mund-Key wird übersprungen (Bestands-Guard aus
            ``_start_idle_action``). ``None`` = kein Guard.
        rng: Injizierbare Zufallsquelle (Tests). ``None`` → frische ``Random``.
        blink_min/blink_max/blink_duration: Blink-Timing (s).
        idle_min/idle_max/idle_duration: Idle-Timing (s).
        formal_idle_factor: Faktor auf das Idle-Intervall im formellen Modus.
    """

    def __init__(
        self,
        *,
        idle_actions: Sequence[IdleAction],
        can_blink: Mapping[Emotion, bool],
        attention_provider: AttentionProvider,
        briefing_provider: BriefingModeProvider | None = None,
        available_components: Collection[str] | None = None,
        rng: random.Random | None = None,
        blink_min: float = BLINK_MIN_INTERVAL,
        blink_max: float = BLINK_MAX_INTERVAL,
        blink_duration: float = BLINK_DURATION,
        idle_min: float = IDLE_MIN_INTERVAL,
        idle_max: float = IDLE_MAX_INTERVAL,
        idle_duration: float = IDLE_ACTION_DURATION,
        formal_idle_factor: float = FORMAL_IDLE_FACTOR,
    ) -> None:
        self._idle_actions = list(idle_actions)
        self._can_blink = dict(can_blink)
        self._attention = attention_provider
        self._briefing = briefing_provider or CasualBriefingModeProvider()
        self._available = available_components
        self._rng = rng if rng is not None else random.Random()

        self._blink_min = blink_min
        self._blink_max = blink_max
        self._blink_duration = blink_duration
        self._idle_min = idle_min
        self._idle_max = idle_max
        self._idle_duration = idle_duration
        self._formal_idle_factor = formal_idle_factor

        # Blink-State (lazy: _next_blink_time None bis zur ersten Planung).
        self._blink_active = False
        self._blink_end_time = 0.0
        self._next_blink_time: float | None = None

        # Idle-State (lazy: _next_idle_time None bis zur ersten Planung).
        self._active_action: IdleAction | None = None
        self._idle_end_time = 0.0
        self._next_idle_time: float | None = None

    # -- Integrations-Einstieg (vom Controller pro Frame gerufen) --------------

    def frame_overrides(
        self, now: float, mood: Emotion, is_speaking: bool
    ) -> IdleBlinkOverrides:
        """Löst Blink + Idle für genau ein Frame auf (Renderer-Overrides).

        - **Blink** läuft unabhängig vom Sprechen (wie Bestand): :meth:`update_blink`.
        - **Idle** nur, wenn ``not is_speaking`` (ambient-Verhalten ruht beim
          Sprechen, exakt wie der Bestand ``_update_idle`` nur bei ``not speaking``
          ansprach). Während des Sprechens werden Idle-Overrides **nicht** gezeigt
          (saubere Unterdrückung statt eingefrorener Idle-Augen).

        Args:
            now: ``time.monotonic``-Zeitpunkt des Frames.
            mood: Aktuelle (Ziel-)Emotion – entscheidet ``can_blink``.
            is_speaking: Ob der Avatar gerade spricht (Idle-Gate).

        Returns:
            Die aufgelösten :class:`IdleBlinkOverrides` (Blink schlägt im Renderer
            via ``RenderPlan.compose`` weiterhin Idle).
        """
        blink_eyes = self.update_blink(now, mood)
        if is_speaking:
            return IdleBlinkOverrides(blink_eyes=blink_eyes)

        action = self.next_action(now, mood)
        idle_eyes: tuple[str, str] | None = None
        idle_mouth: str | None = None
        if action is not None:
            if action.eye_left:
                idle_eyes = (action.eye_left, action.eye_right or "")
            if action.mouth:
                idle_mouth = action.mouth
        return IdleBlinkOverrides(
            blink_eyes=blink_eyes, idle_eyes=idle_eyes, idle_mouth=idle_mouth
        )

    # -- Blink (§3.6, mood-unabhängig) -----------------------------------------

    def blink_interval(self, mood: Emotion) -> float:
        """Globales, **mood-unabhängiges** Blink-Intervall in Sekunden (B2/§0.4).

        ``mood`` ist Teil der §3.6-Signatur, beeinflusst das Intervall aber
        bewusst **nicht** – Per-Emotion-Blink ist gestrichen.
        """
        return self._rng.uniform(self._blink_min, self._blink_max)

    def update_blink(self, now: float, mood: Emotion) -> tuple[str, str] | None:
        """Tickt den Blink-Zustand und liefert geschlossene Augen oder ``None``.

        Nicht-blinzelnde Moods (``can_blink: false``) blinzeln **nie**; ihr Timer
        läuft – wie im Bestand – nicht weiter (eingefroren). Unabhängig vom
        Sprechen (wie Bestand). Eine in der Config fehlende Emotion fällt – wie der
        Layer-Fallback in Renderer/StateMachine – auf NEUTRAL zurück.
        """
        if not self._can_blink_for(mood):
            return None
        if self._next_blink_time is None:
            self._schedule_next_blink(now, mood)
            return None
        if self._blink_active:
            if now >= self._blink_end_time:
                self._blink_active = False
                self._schedule_next_blink(now, mood)
        elif now >= self._next_blink_time:
            self._blink_active = True
            self._blink_end_time = now + self._blink_duration
        return BLINK_EYES if self._blink_active else None

    def _can_blink_for(self, mood: Emotion) -> bool:
        """``can_blink`` der Emotion, mit NEUTRAL-Fallback für unbekannte Moods.

        Eine in der (Custom-)Config fehlende Emotion wird im Renderer/in der
        StateMachine als **NEUTRAL** gerendert (Layer-Fallback). Damit das gezeigte
        Neutral-Gesicht nicht stumm einfriert, folgt der Blink demselben Fallback:
        unbekannte Emotion ⇒ ``can_blink`` von NEUTRAL (sonst ``False``).
        """
        if mood in self._can_blink:
            return self._can_blink[mood]
        return self._can_blink.get(Emotion.NEUTRAL, False)

    def _schedule_next_blink(self, now: float, mood: Emotion) -> None:
        self._next_blink_time = now + self.blink_interval(mood)

    # -- Idle (§3.6) -----------------------------------------------------------

    def next_action(self, now: float, mood: Emotion) -> IdleAction | None:
        """Tickt den Idle-Zustand und liefert die aktive Idle-Aktion oder ``None``.

        Beachtet das Aufmerksamkeits-Gate (``PRESENT``/``FOCUSED`` unterdrücken den
        **Start**) und den formellen Briefing-Modus (Frequenz/Aktionsfilter). Der
        Sprech-Gate liegt beim Aufrufer (:meth:`frame_overrides`). ``mood`` ist Teil
        der §3.6-Signatur; Idle-Aktionen sind bewusst emotionsunabhängig.
        """
        if self._next_idle_time is None:
            self._schedule_next_idle(now)
            return None
        if self._active_action is not None:
            if now >= self._idle_end_time:
                self._active_action = None
                self._schedule_next_idle(now)
                return None
            return self._active_action
        if now >= self._next_idle_time and self._idle_allowed():
            self._start_idle_action(now)
        return self._active_action

    def _idle_allowed(self) -> bool:
        """``True``, solange keine aktive Aufmerksamkeit gemeldet ist (§3.7).

        ``UNKNOWN``/``AWAY`` erlauben Idle (Default-Stub → unverändertes Verhalten);
        nur ``PRESENT``/``FOCUSED`` unterdrücken es.
        """
        return self._attention.current() not in _ATTENTION_SUPPRESSES_IDLE

    def _start_idle_action(self, now: float) -> None:
        """Wählt eine Idle-Aktion (random) und aktiviert sie, mit Komponenten-Guard.

        Im formellen Modus ist nur ``soft_close`` wählbar (§3.6). Fehlt eine
        benötigte Komponente (Augen/Mund), wird die Aktion verworfen und neu
        geplant (Bestands-Guard aus ``_start_idle_action``).
        """
        pool = self._action_pool()
        if not pool:
            self._schedule_next_idle(now)
            return
        action = self._rng.choice(pool)
        if not self._components_available(action):
            self._schedule_next_idle(now)
            return
        self._active_action = action
        self._idle_end_time = now + self._idle_duration

    def _action_pool(self) -> list[IdleAction]:
        """Wählbare Idle-Aktionen – im formellen Modus nur ``soft_close`` (§3.6)."""
        if self._briefing.is_formal():
            return [a for a in self._idle_actions if a.name == FORMAL_IDLE_ACTION]
        return self._idle_actions

    def _components_available(self, action: IdleAction) -> bool:
        """Prüft, ob die benötigten Komponenten der Aktion vorhanden sind (§0.6).

        Spiegelt den Bestands-Guard: prüft ``eye_left`` und ``mouth`` (nicht
        ``eye_right``). ``available_components is None`` → kein Guard.
        """
        if self._available is None:
            return True
        if action.eye_left and action.eye_left not in self._available:
            return False
        if action.mouth and action.mouth not in self._available:
            return False
        return True

    def _schedule_next_idle(self, now: float) -> None:
        """Plant die nächste Idle-Aktion; halbiert die Frequenz im formellen Modus."""
        delay = self._rng.uniform(self._idle_min, self._idle_max)
        if self._briefing.is_formal():
            delay *= self._formal_idle_factor
        self._next_idle_time = now + delay
