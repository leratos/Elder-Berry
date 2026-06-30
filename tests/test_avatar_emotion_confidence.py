"""Phase 108: Confidence-Transport über die RPi5-REST-Grenze.

Belegt, dass die vom Bot-seitigen ``EmotionResolver`` mitgesendete Confidence
(``AvatarRequest.decision.confidence``) am ``/avatar/emotion``-Endpoint an
``AvatarDisplay.set_emotion`` durchgereicht wird – und nicht mehr (wie vor
Phase 108) nur geloggt. Ohne ``decision`` bleibt es beim Default 1.0.
"""

from __future__ import annotations

import pytest

try:
    from fastapi.testclient import TestClient

    from elder_berry.robot.server import RobotServer
    from elder_berry.robot.simulator import (
        SimulatedAvatar,
        SimulatedMotors,
        SimulatedSensors,
    )

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


def _server_with_avatar() -> tuple[RobotServer, SimulatedAvatar]:
    avatar = SimulatedAvatar()
    server = RobotServer(
        motors=SimulatedMotors(),
        avatar=avatar,
        sensors=SimulatedSensors(),
        turntable=None,
        hostname="test",
    )
    return server, avatar


class TestEmotionConfidenceTransport:
    def test_decision_confidence_reaches_avatar(self):
        server, avatar = _server_with_avatar()
        client = TestClient(server.app)
        r = client.post(
            "/avatar/emotion",
            json={
                "emotion": "angry",
                "decision": {
                    "emotion": "angry",
                    "confidence": 0.2,
                    "source": "tracker_trend",
                },
            },
        )
        assert r.status_code == 200
        state = avatar.get_state()
        assert state["emotion"] == "angry"
        assert state["confidence"] == pytest.approx(0.2)

    def test_high_confidence_transported(self):
        server, avatar = _server_with_avatar()
        client = TestClient(server.app)
        client.post(
            "/avatar/emotion",
            json={
                "emotion": "cheerful",
                "decision": {
                    "emotion": "cheerful",
                    "confidence": 0.85,
                    "source": "llm_tag",
                },
            },
        )
        assert avatar.get_state()["confidence"] == pytest.approx(0.85)

    def test_without_decision_defaults_to_one(self):
        """Legacy-/String-only-Pfad: keine decision → confidence 1.0."""
        server, avatar = _server_with_avatar()
        client = TestClient(server.app)
        r = client.post("/avatar/emotion", json={"emotion": "sad"})
        assert r.status_code == 200
        state = avatar.get_state()
        assert state["emotion"] == "sad"
        assert state["confidence"] == pytest.approx(1.0)

    def test_mismatched_decision_emotion_ignores_confidence(self):
        """decision.emotion != request.emotion → Confidence verworfen (→ 1.0)."""
        server, avatar = _server_with_avatar()
        client = TestClient(server.app)
        r = client.post(
            "/avatar/emotion",
            json={
                "emotion": "angry",
                "decision": {
                    "emotion": "cheerful",  # passt NICHT zum String
                    "confidence": 0.1,
                    "source": "llm_tag",
                },
            },
        )
        assert r.status_code == 200
        state = avatar.get_state()
        assert state["emotion"] == "angry"
        assert state["confidence"] == pytest.approx(1.0)  # nicht 0.1

    def test_out_of_range_confidence_rejected(self):
        """confidence > 1.0 → 422 (Schema-Bound, token-freier Server-Schutz)."""
        server, _ = _server_with_avatar()
        client = TestClient(server.app)
        r = client.post(
            "/avatar/emotion",
            json={
                "emotion": "angry",
                "decision": {
                    "emotion": "angry",
                    "confidence": 2.0,
                    "source": "x",
                },
            },
        )
        assert r.status_code == 422

    def test_negative_confidence_rejected(self):
        server, _ = _server_with_avatar()
        client = TestClient(server.app)
        r = client.post(
            "/avatar/emotion",
            json={
                "emotion": "angry",
                "decision": {
                    "emotion": "angry",
                    "confidence": -0.5,
                    "source": "x",
                },
            },
        )
        assert r.status_code == 422


class TestEmotionIntensityTransport:
    """Phase 110: die Anzeige-Tiefe (intensity) erreicht den AvatarDisplay."""

    def test_decision_intensity_reaches_avatar(self):
        server, avatar = _server_with_avatar()
        client = TestClient(server.app)
        r = client.post(
            "/avatar/emotion",
            json={
                "emotion": "angry",
                "decision": {
                    "emotion": "angry",
                    "confidence": 0.7,
                    "source": "llm_tag",
                    "intensity": 0.4,
                },
            },
        )
        assert r.status_code == 200
        assert avatar.get_state()["intensity"] == pytest.approx(0.4)

    def test_default_intensity_is_one(self):
        # decision ohne intensity-Feld (alter Client) → Default 1.0.
        server, avatar = _server_with_avatar()
        client = TestClient(server.app)
        client.post(
            "/avatar/emotion",
            json={
                "emotion": "cheerful",
                "decision": {
                    "emotion": "cheerful",
                    "confidence": 0.7,
                    "source": "llm_tag",
                },
            },
        )
        assert avatar.get_state()["intensity"] == pytest.approx(1.0)

    def test_mismatched_decision_ignores_intensity(self):
        server, avatar = _server_with_avatar()
        client = TestClient(server.app)
        client.post(
            "/avatar/emotion",
            json={
                "emotion": "angry",
                "decision": {
                    "emotion": "cheerful",  # passt nicht zum String
                    "confidence": 0.7,
                    "source": "llm_tag",
                    "intensity": 0.2,
                },
            },
        )
        assert avatar.get_state()["intensity"] == pytest.approx(1.0)  # nicht 0.2

    def test_out_of_range_intensity_rejected(self):
        server, _ = _server_with_avatar()
        client = TestClient(server.app)
        r = client.post(
            "/avatar/emotion",
            json={
                "emotion": "angry",
                "decision": {
                    "emotion": "angry",
                    "confidence": 0.7,
                    "source": "x",
                    "intensity": 2.0,
                },
            },
        )
        assert r.status_code == 422
