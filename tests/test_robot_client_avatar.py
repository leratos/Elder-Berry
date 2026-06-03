"""Tests für RobotClient-Avatar-Aufrufe (Phase 83.4): Amplitude-Payload.

Prüft, dass ``set_speaking``/``set_avatar`` das Amplitude-Profil additiv als
``amplitude``/``amplitude_duration_ms`` mitsenden – und ohne Track nicht.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from elder_berry.core.audio_analyzer import AmplitudeTrack
from elder_berry.robot.client import RobotClient


def _client_with_capture() -> tuple[RobotClient, list[dict]]:
    """RobotClient mit gemocktem httpx.Client, der gepostete JSON-Bodies sammelt."""
    client = RobotClient.__new__(RobotClient)
    client._base_url = "http://localhost:8000"
    client._timeout = 5.0

    posted: list[dict] = []

    def mock_post(path, json=None, **kwargs):
        posted.append({"path": path, "json": json})
        return httpx.Response(
            200,
            json={"success": True, "message": "ok"},
            request=httpx.Request("POST", "http://test" + path),
        )

    mock_httpx = MagicMock(spec=httpx.Client)
    mock_httpx.post = mock_post
    client._client = mock_httpx
    return client, posted


class TestSetSpeakingPayload:
    def test_without_track_sends_no_amplitude(self):
        client, posted = _client_with_capture()
        client.set_speaking(True)
        assert posted[0]["json"] == {"is_speaking": True}

    def test_with_track_sends_amplitude(self):
        client, posted = _client_with_capture()
        track = AmplitudeTrack(samples=[0.1, 0.7, 0.2], duration_ms=150)
        client.set_speaking(True, audio_meta=track)
        body = posted[0]["json"]
        assert body["is_speaking"] is True
        assert body["amplitude"] == [0.1, 0.7, 0.2]
        assert body["amplitude_duration_ms"] == 150

    def test_empty_track_sends_no_amplitude(self):
        client, posted = _client_with_capture()
        client.set_speaking(True, audio_meta=AmplitudeTrack(samples=[], duration_ms=0))
        assert "amplitude" not in posted[0]["json"]


class TestSetAvatarPayload:
    def test_set_avatar_with_track(self):
        client, posted = _client_with_capture()
        track = AmplitudeTrack(samples=[0.9], duration_ms=50)
        client.set_avatar(emotion="cheerful", is_speaking=True, audio_meta=track)
        body = posted[0]["json"]
        assert body["emotion"] == "cheerful"
        assert body["is_speaking"] is True
        assert body["amplitude"] == [0.9]
        assert body["amplitude_duration_ms"] == 50

    def test_set_avatar_without_track(self):
        client, posted = _client_with_capture()
        client.set_avatar(emotion="neutral")
        assert posted[0]["json"] == {"emotion": "neutral"}
