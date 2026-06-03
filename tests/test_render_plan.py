"""Tests für RenderPlan – DTO + Layer-Priorität (Phase 83.2)."""

from __future__ import annotations

import dataclasses

import pytest

from elder_berry.avatar.avatar_config_loader import EmotionLayers
from elder_berry.avatar.render_plan import (
    OPAQUE_ALPHA,
    RenderPlan,
    TransitionState,
    lerp_alpha,
)


def _base(
    *,
    body: str = "relaxed",
    eye_left: str = "eye_left_open",
    eye_right: str = "eye_right_open",
    mouth: str = "mouth_neutral_close",
    effect: str | None = None,
) -> EmotionLayers:
    """Eine minimale Emotion-Layer-Quelle (erfüllt das LayerSource-Protocol)."""
    return EmotionLayers(
        body=body,
        eye_left=eye_left,
        eye_right=eye_right,
        mouth=mouth,
        can_blink=True,
        effect=effect,
    )


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestRenderPlanDefaults:
    def test_compose_without_overrides_uses_emotion_defaults(self):
        plan = RenderPlan.compose(_base())
        assert plan.body == "relaxed"
        assert plan.eye_left == "eye_left_open"
        assert plan.eye_right == "eye_right_open"
        assert plan.mouth == "mouth_neutral_close"

    def test_default_alpha_is_opaque(self):
        assert RenderPlan.compose(_base()).alpha == 255

    def test_default_y_offset_is_zero(self):
        assert RenderPlan.compose(_base()).y_offset == 0

    def test_effect_none_preserved(self):
        assert RenderPlan.compose(_base()).effect is None

    def test_effect_value_preserved(self):
        plan = RenderPlan.compose(_base(effect="aura"))
        assert plan.effect == "aura"

    def test_alpha_and_y_offset_passthrough(self):
        plan = RenderPlan.compose(_base(), alpha=128, y_offset=-3)
        assert plan.alpha == 128
        assert plan.y_offset == -3

    def test_plan_is_frozen(self):
        plan = RenderPlan.compose(_base())
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.body = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Augen-Priorität: blink > idle > Emotion
# ---------------------------------------------------------------------------


class TestEyePriority:
    def test_idle_eyes_override_default(self):
        plan = RenderPlan.compose(_base(), idle_eyes=("eye_left_side_open", "eye_right_side_open"))
        assert plan.eye_left == "eye_left_side_open"
        assert plan.eye_right == "eye_right_side_open"

    def test_blink_overrides_default(self):
        plan = RenderPlan.compose(_base(), blink_eyes=("eye_left_close", "eye_right_close"))
        assert plan.eye_left == "eye_left_close"
        assert plan.eye_right == "eye_right_close"

    def test_blink_beats_idle(self):
        plan = RenderPlan.compose(
            _base(),
            idle_eyes=("eye_left_side_open", "eye_right_side_open"),
            blink_eyes=("eye_left_close", "eye_right_close"),
        )
        assert plan.eye_left == "eye_left_close"
        assert plan.eye_right == "eye_right_close"

    def test_eyes_unaffected_by_mouth_overrides(self):
        plan = RenderPlan.compose(_base(), speaking_mouth="mouth_open")
        assert plan.eye_left == "eye_left_open"
        assert plan.eye_right == "eye_right_open"


# ---------------------------------------------------------------------------
# Mund-Priorität: speaking > idle > Emotion
# ---------------------------------------------------------------------------


class TestMouthPriority:
    def test_idle_mouth_overrides_default(self):
        plan = RenderPlan.compose(_base(), idle_mouth="mouth_halfopen")
        assert plan.mouth == "mouth_halfopen"

    def test_speaking_mouth_overrides_default(self):
        plan = RenderPlan.compose(_base(), speaking_mouth="mouth_wide")
        assert plan.mouth == "mouth_wide"

    def test_speaking_beats_idle(self):
        plan = RenderPlan.compose(
            _base(),
            idle_mouth="mouth_halfopen",
            speaking_mouth="mouth_wide",
        )
        assert plan.mouth == "mouth_wide"

    def test_mouth_unaffected_by_eye_overrides(self):
        plan = RenderPlan.compose(_base(), blink_eyes=("eye_left_close", "eye_right_close"))
        assert plan.mouth == "mouth_neutral_close"


# ---------------------------------------------------------------------------
# lerp_alpha (Crossfade-Fortschritt → Alpha, Phase 83.3)
# ---------------------------------------------------------------------------


class TestLerpAlpha:
    def test_zero_progress_fully_transparent(self):
        assert lerp_alpha(0.0) == 0

    def test_full_progress_opaque(self):
        assert lerp_alpha(1.0) == OPAQUE_ALPHA == 255

    def test_half_progress(self):
        assert lerp_alpha(0.5) == 128  # round(255 * 0.5) = 128

    def test_clamped_below_zero(self):
        assert lerp_alpha(-1.0) == 0

    def test_clamped_above_one(self):
        assert lerp_alpha(2.0) == 255

    def test_monotonic_over_8_frames(self):
        seq = [lerp_alpha(f / 8) for f in range(9)]
        assert seq == sorted(seq)
        assert seq[0] == 0
        assert seq[-1] == 255
        assert all(0 <= a <= 255 for a in seq)


# ---------------------------------------------------------------------------
# RenderPlan.with_alpha + LayerSource-Konformität (Phase 83.3)
# ---------------------------------------------------------------------------


class TestWithAlpha:
    def test_with_alpha_changes_only_alpha(self):
        plan = RenderPlan.compose(_base(effect="aura"), y_offset=4)
        faded = plan.with_alpha(100)
        assert faded.alpha == 100
        assert faded.body == plan.body
        assert faded.eye_left == plan.eye_left
        assert faded.eye_right == plan.eye_right
        assert faded.mouth == plan.mouth
        assert faded.effect == plan.effect
        assert faded.y_offset == plan.y_offset

    def test_with_alpha_returns_new_instance(self):
        plan = RenderPlan.compose(_base())
        faded = plan.with_alpha(50)
        assert faded is not plan
        assert plan.alpha == 255  # Original unverändert

    def test_render_plan_is_layer_source(self):
        """Ein RenderPlan erfüllt LayerSource → compose() akzeptiert ihn als Basis."""
        base_plan = RenderPlan.compose(_base(body="angry", effect="aura"))
        # compose mit einem RenderPlan als Basis (der Renderer legt im Crossfade
        # seine Overrides genau so auf die SM-Basis-Pläne).
        composed = RenderPlan.compose(
            base_plan,
            blink_eyes=("eye_left_close", "eye_right_close"),
            alpha=128,
        )
        assert composed.body == "angry"
        assert composed.effect == "aura"
        assert composed.eye_left == "eye_left_close"
        assert composed.alpha == 128


# ---------------------------------------------------------------------------
# TransitionState (Phase 83.3)
# ---------------------------------------------------------------------------


class TestTransitionState:
    def test_holds_previous_and_current_plans(self):
        prev = RenderPlan.compose(_base(body="relaxed"))
        curr = RenderPlan.compose(_base(body="angry")).with_alpha(64)
        ts = TransitionState(
            in_transition=True, progress=0.25, previous=prev, current=curr
        )
        assert ts.in_transition is True
        assert ts.progress == 0.25
        assert ts.previous.body == "relaxed"
        assert ts.current.body == "angry"
        assert ts.current.alpha == 64

    def test_is_frozen(self):
        plan = RenderPlan.compose(_base())
        ts = TransitionState(
            in_transition=False, progress=1.0, previous=plan, current=plan
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            ts.in_transition = True  # type: ignore[misc]
