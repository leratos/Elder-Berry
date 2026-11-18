"""ProximityDiagnosticMode -- Live-Ansicht des Naeherungssensors fuer M5.

Phase 111, E3 (``--frame-view naeherung``). Reiner Messmodus, kein
Partyinhalt. Zeigt PDATA, Grundwert, Schwellen (absolut), Zustand
AWAY/PRESENT/FOCUSED/UNKNOWN, ``is_faulted`` und einen Balken mit den
Schwellen als Marken. Einmal pro Sekunde eine Logzeile mit Min/Mittel/Max
der in dieser Sekunde gelesenen PDATA-Werte -- daraus liest Lera bei M5 den
Grundwert und die Werte bei 30/40/50 cm ab.

Gerendert wird nur, wenn sich Anzeigewert, Zustand oder Fehlerstatus
aendern (Muster E2). Die Flaeche ist dynamisch und wird bei jedem Render
gedreht (``show_dynamic``) -- das passiert nur bei Aenderung.
"""

from __future__ import annotations

import logging

import pygame

from elder_berry.avatar.attention import AttentionState
from elder_berry.avatar.proximity_attention_provider import ProximityAttentionProvider
from elder_berry.room_display.content_mode import ContentMode
from elder_berry.room_display.oriented_display import OrientedDisplay

logger = logging.getLogger(__name__)

_STATE_COLORS = {
    AttentionState.AWAY: (90, 90, 90),
    AttentionState.PRESENT: (60, 140, 220),
    AttentionState.FOCUSED: (60, 200, 90),
    AttentionState.UNKNOWN: (220, 60, 60),
}
_WHITE = (255, 255, 255)
_GREY = (140, 140, 140)


class ProximityDiagnosticMode(ContentMode):
    """M5-Werkzeug: Live-Werte des ProximityAttentionProvider.

    Args:
        provider: Provider mit echtem Sensor; ``None`` = Sensor nicht
            verfuegbar (dann nur ein Hinweisbild).
        log_interval_s: Abstand der Min/Mittel/Max-Logzeilen.
    """

    def __init__(
        self,
        provider: ProximityAttentionProvider | None,
        *,
        log_interval_s: float = 1.0,
    ) -> None:
        self._provider = provider
        self._log_interval = log_interval_s
        self._shown: tuple[int | None, AttentionState, bool] | None = None
        self._state = AttentionState.UNKNOWN
        self._window: list[int] = []
        self._window_start: float | None = None
        self._last_sample = 0
        self._font: pygame.font.Font | None = None
        self._small: pygame.font.Font | None = None
        self.render_count = 0

    def on_enter(self, display: OrientedDisplay) -> None:
        if not pygame.font.get_init():
            pygame.font.init()
        self._font = pygame.font.Font(None, 96)
        self._small = pygame.font.Font(None, 40)
        if self._provider is None:
            logger.warning("Naeherungsansicht: kein Sensor -- nur Hinweis.")
        else:
            t = self._provider.thresholds
            logger.info(
                "Naeherungsansicht: Grundwert %d, AWAY < %d, PRESENT >= %d, FOCUSED "
                "ein >= %d / aus < %d (absolut), Entprellung %.0f ms",
                t.baseline,
                t.baseline + t.away_below,
                t.baseline + t.present_above,
                t.baseline + t.focused_on,
                t.baseline + t.focused_off,
                t.debounce_s * 1000,
            )

    def update(self, now: float) -> bool:
        if self._provider is None:
            current: tuple[int | None, AttentionState, bool] = (
                None,
                AttentionState.UNKNOWN,
                False,
            )
        else:
            self._state = self._provider.current()
            self._collect(now)
            current = (
                self._provider.last_value,
                self._state,
                self._provider.is_faulted,
            )
        if current != self._shown:
            self._shown = current
            return True
        return False

    def _collect(self, now: float) -> None:
        assert self._provider is not None
        if self._provider.sample_count != self._last_sample:
            self._last_sample = self._provider.sample_count
            if self._provider.last_value is not None:
                self._window.append(self._provider.last_value)
        if self._window_start is None:
            self._window_start = now
        if now - self._window_start >= self._log_interval:
            if self._window:
                logger.info(
                    "PDATA %.0fs: min %d, mittel %.1f, max %d (n=%d) | Zustand %s%s",
                    now - self._window_start,
                    min(self._window),
                    sum(self._window) / len(self._window),
                    max(self._window),
                    len(self._window),
                    self._state.value,
                    " | FEHLER" if self._provider.is_faulted else "",
                )
            elif self._provider.error_count:
                logger.info(
                    "PDATA: keine Werte (Lesefehler: %d)", self._provider.error_count
                )
            self._window = []
            self._window_start = now

    def render(self, display: OrientedDisplay) -> None:
        self.render_count += 1
        canvas = display.new_canvas()
        assert self._font is not None and self._small is not None
        if self._provider is None:
            lines = [
                "Naeherungssensor nicht verfuegbar",
                "I2C aktiv? Benutzer in Gruppe i2c? Verkabelung? (Log)",
            ]
            for i, line in enumerate(lines):
                canvas.blit(self._small.render(line, True, _WHITE), (60, 300 + i * 50))
            display.show_dynamic(canvas)
            return

        value, state, faulted = self._shown or (None, AttentionState.UNKNOWN, False)
        t = self._provider.thresholds
        color = _STATE_COLORS[AttentionState.UNKNOWN if faulted else state]
        canvas.blit(
            self._font.render(f"PDATA {'-' if value is None else value}", True, _WHITE),
            (60, 60),
        )
        label = "SENSORFEHLER" if faulted else state.value.upper()
        canvas.blit(self._font.render(label, True, color), (700, 60))
        info = [
            f"Grundwert {t.baseline} | AWAY < {t.baseline + t.away_below} | "
            f"PRESENT >= {t.baseline + t.present_above}",
            f"FOCUSED ein >= {t.baseline + t.focused_on} | aus < "
            f"{t.baseline + t.focused_off} | Entprellung {t.debounce_s * 1000:.0f} ms",
            f"Lesefehler: {self._provider.error_count}",
        ]
        for i, line in enumerate(info):
            canvas.blit(self._small.render(line, True, _GREY), (60, 200 + i * 48))
        self._draw_bar(canvas, value, color)
        display.show_dynamic(canvas)

    def _draw_bar(
        self, canvas: pygame.Surface, value: int | None, color: tuple[int, int, int]
    ) -> None:
        assert self._provider is not None
        t = self._provider.thresholds
        left, top, width, height = 60, 420, 1160, 120
        pygame.draw.rect(canvas, _GREY, pygame.Rect(left, top, width, height), 3)
        if value is not None:
            filled = int(width * min(255, max(0, value)) / 255)
            pygame.draw.rect(canvas, color, pygame.Rect(left, top, filled, height))
        for offset, mark_color in (
            (0, _WHITE),
            (t.present_above, _STATE_COLORS[AttentionState.PRESENT]),
            (t.focused_on, _STATE_COLORS[AttentionState.FOCUSED]),
        ):
            x = left + int(width * min(255, max(0, t.baseline + offset)) / 255)
            pygame.draw.line(
                canvas, mark_color, (x, top - 20), (x, top + height + 20), 4
            )
