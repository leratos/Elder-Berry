"""Tests für RenderPlan – DTO + Layer-Priorität (Phase 83.2)."""

from __future__ import annotations

import dataclasses

import pytest

from elder_berry.avatar.avatar_config_loader import EmotionLayers
from elder_berry.avatar.render_plan import RenderPlan


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
