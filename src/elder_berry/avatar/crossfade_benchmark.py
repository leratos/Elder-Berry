"""Deterministischer Crossfade-FPS-Stopwatch (Phase 83.3, §6.1 / §0.6).

Misst die **CPU-Kompositionskosten** genau eines Crossfade-Frames – fill + zwei
Offscreen-Kompositionen (alt opak + neu verblasst) + 180°-Vollbild-Flip – gegen
das 30-FPS-Budget (33.33 ms). ``display.flip()`` und ``clock.tick()`` sind
bewusst **ausgeschlossen**: der erste throttelt (vsync), der zweite verfälscht
die reine Kompositionszeit.

Läuft headless über Software-Surfaces (kein Display nötig) und exerziert den
**echten** Renderer-Pfad (:meth:`LayeredSpriteRenderer._composite_crossfade_to_screen`).
Damit taugt dasselbe Modul für den CI-Stopwatch-Test **und** für Leras
verbindliche RPi5-Messung (``scripts/start_rpi5.py --benchmark-crossfade``).

WICHTIG (§0.6): MIT ``rotation=180`` messen – der Vollbild-Flip ist in §5/§6.1
nicht eingerechnet. Die in CI gemessene Zahl ist die *CPU*-Kompositionszeit des
Devhosts, **nicht** die GPU-genaue RPi5-Zahl; die bindende ≥30-FPS-Bestätigung
liefert der Pi-Lauf.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

try:
    import pygame
except ImportError:  # pragma: no cover - pygame ist auf dem RPi5/Devhost da
    # unused-ignore: ohne installiertes pygame (CI-typecheck) ist die
    # [assignment]-Unterdrueckung ueberfluessig, mit pygame noetig.
    pygame = None  # type: ignore[assignment, unused-ignore]

from elder_berry.avatar.layered_renderer import (
    CrossfadeScope,
    LayeredSpriteRenderer,
)
from elder_berry.avatar.render_plan import RenderPlan, lerp_alpha

logger = logging.getLogger(__name__)

# 30-FPS-Budget pro Frame in Millisekunden (§6.1).
FRAME_BUDGET_MS = 1000.0 / 30.0

# Fallback-Auflösung für den Crossfade-Übergang (§5/§6.1), falls die native
# Auflösung unter 30 FPS fällt.
FALLBACK_SIZE = (540, 960)

# Komponenten-Keys eines synthetischen Avatars (Body + 2 Augen + Mund pro Plan;
# alt/neu unterscheiden sich in Body und Mund → 4 Layer je Ebene wie im realen
# Pfad, §6.1: "8 Blits/Frame während Übergang").
_COMPONENT_KEYS = (
    "bench_body_old",
    "bench_body_new",
    "bench_eye_left",
    "bench_eye_right",
    "bench_mouth_old",
    "bench_mouth_new",
)


@dataclass(frozen=True)
class CrossfadeBenchmarkResult:
    """Ergebnis einer Crossfade-FPS-Messung.

    Attributes:
        frames: Anzahl gemessener Crossfade-Frames.
        width: Render-Breite in Pixeln.
        height: Render-Höhe in Pixeln.
        rotation: Display-Rotation (0/180); 180 schließt den Vollbild-Flip ein.
        scope: Crossfade-Reichweite (FULL/MOUTH_ONLY).
        mean_ms: Mittlere Kompositionszeit pro Frame in ms.
        max_ms: Schlechtester Frame (Worst-Case) in ms.
        budget_ms: 30-FPS-Budget pro Frame (33.33 ms).
        effective_fps: ``1000 / mean_ms`` – rein aus der Kompositionszeit.
        holds_30fps: ``True``, wenn **jeder** Frame im Budget blieb
            (``max_ms <= budget_ms``).
    """

    frames: int
    width: int
    height: int
    rotation: int
    scope: CrossfadeScope
    mean_ms: float
    max_ms: float
    budget_ms: float
    effective_fps: float
    holds_30fps: bool


def _require_pygame() -> None:
    if pygame is None:
        raise RuntimeError(
            "pygame nicht installiert – Crossfade-Benchmark nicht möglich."
        )


def _synthetic_components(
    size: tuple[int, int],
) -> dict[str, "pygame.Surface"]:
    """Erzeugt halb-deckende SRCALPHA-Komponenten (echte Pixel zum Blenden)."""
    components: dict[str, pygame.Surface] = {}
    for index, key in enumerate(_COMPONENT_KEYS):
        surface = pygame.Surface(size, pygame.SRCALPHA)
        # Unterschiedliche Farben/Deckkraft je Layer → realistische Blends.
        surface.fill((40 + index * 30, 80, 200 - index * 20, 200))
        components[key] = surface
    return components


def _build_renderer(
    width: int,
    height: int,
    rotation: int,
    scope: CrossfadeScope,
    component_size: tuple[int, int],
) -> LayeredSpriteRenderer:
    """Baut einen Renderer mit Software-Screen + synthetischen Komponenten.

    Greift bewusst auf Renderer-Interna zu (``_screen``/``_components`` etc.):
    Dies ist ein Diagnose-Harness im selben Package, kein Produktionspfad. So
    läuft der **echte** Kompositionspfad ohne Display/Asset-Abhängigkeit.
    """
    renderer = LayeredSpriteRenderer(crossfade_scope=scope)
    renderer._width = width
    renderer._height = height
    renderer._rotation = rotation
    renderer._clock = None  # kein Tick-Throttle in der Messung
    renderer._screen = pygame.Surface((width, height))
    renderer._components = _synthetic_components(component_size)
    return renderer


def measure_crossfade_fps(
    width: int = 720,
    height: int = 1280,
    rotation: int = 180,
    frames: int = 8,
    scope: CrossfadeScope = CrossfadeScope.FULL,
    component_size: tuple[int, int] | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> CrossfadeBenchmarkResult:
    """Misst die Kompositionszeit eines ``frames``-langen Crossfades.

    Args:
        width: Render-Breite (RPi5-Default 720).
        height: Render-Höhe (RPi5-Default 1280).
        rotation: Display-Rotation (0/180). **180 für die §0.6-Messung.**
        frames: Anzahl Crossfade-Frames (Default 8 = ``DEFAULT_CROSSFADE_FRAMES``).
        scope: FULL (alle Layer) oder MOUTH_ONLY (Fallback).
        component_size: Größe der synthetischen Layer-Surfaces. ``None`` →
            Vollbild ``(width, height)`` als **konservativer** Worst-Case
            (reale, kleinere Sprites sind schneller).
        clock: Zeitquelle (injizierbar für Tests). Default ``time.perf_counter``.

    Returns:
        Ein :class:`CrossfadeBenchmarkResult`.

    Raises:
        RuntimeError: wenn pygame fehlt.
        ValueError: wenn ``frames < 1``.
    """
    _require_pygame()
    if frames < 1:
        raise ValueError(f"frames muss >= 1 sein (war: {frames})")

    if not pygame.get_init():
        pygame.init()

    size = component_size or (width, height)
    renderer = _build_renderer(width, height, rotation, scope, size)

    old_plan = RenderPlan(
        body="bench_body_old",
        eye_left="bench_eye_left",
        eye_right="bench_eye_right",
        mouth="bench_mouth_old",
        alpha=255,
    )

    def _new_plan(alpha: int) -> RenderPlan:
        return RenderPlan(
            body="bench_body_new",
            eye_left="bench_eye_left",
            eye_right="bench_eye_right",
            mouth="bench_mouth_new",
            alpha=alpha,
        )

    # Aufwärmen (Surface-Allokationen, SDL-Caches) – nicht gemessen.
    renderer._composite_crossfade_to_screen(old_plan, _new_plan(lerp_alpha(0.5)))

    samples: list[float] = []
    for frame in range(1, frames + 1):
        alpha = lerp_alpha(frame / frames)
        new_plan = _new_plan(alpha)
        start = clock()
        renderer._composite_crossfade_to_screen(old_plan, new_plan)
        samples.append((clock() - start) * 1000.0)

    mean_ms = sum(samples) / len(samples)
    max_ms = max(samples)
    return CrossfadeBenchmarkResult(
        frames=frames,
        width=width,
        height=height,
        rotation=rotation,
        scope=scope,
        mean_ms=mean_ms,
        max_ms=max_ms,
        budget_ms=FRAME_BUDGET_MS,
        effective_fps=(1000.0 / mean_ms) if mean_ms > 0 else float("inf"),
        holds_30fps=max_ms <= FRAME_BUDGET_MS,
    )


def sweep_crossfade_fps(
    width: int = 720,
    height: int = 1280,
    rotation: int = 180,
    frames: int = 8,
    clock: Callable[[], float] = time.perf_counter,
) -> list[CrossfadeBenchmarkResult]:
    """Misst alle relevanten Crossfade-Varianten in einem Lauf (§5/§6.1).

    Deckt das Entscheidungsfeld ab: ``FULL`` und ``MOUTH_ONLY``, jeweils bei
    nativer Auflösung und beim Fallback :data:`FALLBACK_SIZE` (540x960). So lässt
    sich auf dem RPi5 in **einem** Durchlauf ablesen, welche Kombination 30 FPS
    hält. Duplikate (falls nativ == Fallback) werden übersprungen.

    Returns:
        Eine Liste von :class:`CrossfadeBenchmarkResult` (Reihenfolge: FULL nativ,
        MOUTH_ONLY nativ, FULL Fallback, MOUTH_ONLY Fallback).
    """
    configs: list[tuple[CrossfadeScope, int, int]] = [
        (CrossfadeScope.FULL, width, height),
        (CrossfadeScope.MOUTH_ONLY, width, height),
        (CrossfadeScope.FULL, *FALLBACK_SIZE),
        (CrossfadeScope.MOUTH_ONLY, *FALLBACK_SIZE),
    ]
    seen: set[tuple[CrossfadeScope, int, int]] = set()
    results: list[CrossfadeBenchmarkResult] = []
    for scope, w, h in configs:
        if (scope, w, h) in seen:
            continue
        seen.add((scope, w, h))
        results.append(
            measure_crossfade_fps(
                width=w,
                height=h,
                rotation=rotation,
                frames=frames,
                scope=scope,
                clock=clock,
            )
        )
    return results


def result_for(
    results: list[CrossfadeBenchmarkResult],
    scope: CrossfadeScope,
    width: int,
    height: int,
) -> CrossfadeBenchmarkResult | None:
    """Findet im Sweep das Ergebnis einer konkreten (scope, width, height)-Konfig.

    Dient dem **Gate**-Exit-Code: ob die tatsächlich laufende Produktions-Konfig
    (gewählter Scope @ nativer Auflösung) 30 FPS hält – **nicht** ob irgendeine
    Sweep-Variante (z. B. der 540x960-Fallback) hält. Sonst meldete das Gate
    grün, obwohl der echte Lauf unter 30 bleibt und der Fallback nicht
    automatisch greift.

    Returns:
        Das passende :class:`CrossfadeBenchmarkResult` oder ``None``, wenn die
        Kombination nicht im Sweep enthalten ist.
    """
    for result in results:
        if result.scope is scope and result.width == width and result.height == height:
            return result
    return None


def format_result(result: CrossfadeBenchmarkResult) -> str:
    """Formatiert ein Messergebnis als einzeilige, menschenlesbare Zusammenfassung."""
    verdict = "HOLDS ≥30 FPS" if result.holds_30fps else "UNTER 30 FPS"
    return (
        f"Crossfade {result.width}x{result.height} rotation={result.rotation} "
        f"scope={result.scope.value} frames={result.frames}: "
        f"mean={result.mean_ms:.2f}ms max={result.max_ms:.2f}ms "
        f"(budget={result.budget_ms:.2f}ms) "
        f"≈{result.effective_fps:.1f} FPS → {verdict}"
    )


def main() -> None:  # pragma: no cover - CLI-Komfort
    """CLI: ``python -m elder_berry.avatar.crossfade_benchmark``."""
    import argparse

    parser = argparse.ArgumentParser(description="Crossfade-FPS-Stopwatch (83.3)")
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--rotation", type=int, choices=[0, 180], default=180)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument(
        "--scope",
        choices=[s.value for s in CrossfadeScope],
        default=CrossfadeScope.FULL.value,
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = measure_crossfade_fps(
        width=args.width,
        height=args.height,
        rotation=args.rotation,
        frames=args.frames,
        scope=CrossfadeScope(args.scope),
    )
    logger.info("%s", format_result(result))


if __name__ == "__main__":  # pragma: no cover
    main()
