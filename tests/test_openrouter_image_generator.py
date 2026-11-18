"""Tests fuer OpenRouterImageGenerator (Phase 111, E1; Ae1-Ae3, #1474)."""

from __future__ import annotations

import base64
import json
import logging
import time

import httpx
import pytest

from elder_berry.core.http_defaults import USER_AGENT
from elder_berry.llm.image_generator import ImageRequest, ImageStatus
from elder_berry.llm.openrouter_image_generator import (
    OPENROUTER_IMAGES_URL,
    OpenRouterImageGenerator,
)

API_KEY = "sk-or-v1-TESTKEY-0123456789abcdef"
MODEL = "openai/gpt-image-2.6-flare"
GUEST_JPEG = b"\xff\xd8\xff\xe0GUEST-PHOTO-BYTES\xff\xd9"
RESULT_PNG = b"\x89PNG\r\n\x1a\nRESULT-IMAGE-BYTES" * 20
RESULT_B64 = base64.b64encode(RESULT_PNG).decode("ascii")
GUEST_B64 = base64.b64encode(GUEST_JPEG).decode("ascii")


def _make(handler, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenRouterImageGenerator(API_KEY, model=MODEL, client=client, **kwargs)


def _request() -> ImageRequest:
    return ImageRequest(
        prompt="Transform everyone. Not photorealistic.", input_images=(GUEST_JPEG,)
    )


def _respond(status: int, body: object):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return handler


def _error_body(code: object, message: str = "msg", metadata: object = None) -> dict:
    error: dict = {"code": code, "message": message}
    if metadata is not None:
        error["metadata"] = metadata
    return {"error": error}


# ---------------------------------------------------------------------------
# Statuszuordnung (Ae1)
# ---------------------------------------------------------------------------


class TestClassification:
    def test_200_with_image_is_ok_with_cost(self):
        body = {
            "created": 1,
            "data": [{"b64_json": RESULT_B64, "media_type": "image/png"}],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 3,
                "cost": 0.0312,
            },
        }
        result = _make(_respond(200, body)).generate(_request())
        assert result.status is ImageStatus.OK
        assert result.ok
        assert result.image_bytes == RESULT_PNG
        assert result.media_type == "image/png"
        assert result.cost_usd == pytest.approx(0.0312)
        assert result.http_status == 200
        assert result.duration_s >= 0

    def test_200_without_cost_is_ok_without_cost(self):
        result = _make(
            _respond(200, {"created": 1, "data": [{"b64_json": RESULT_B64}]})
        ).generate(_request())
        assert result.status is ImageStatus.OK
        assert result.cost_usd is None
        assert result.media_type is None

    @pytest.mark.parametrize(
        "body",
        [
            {"created": 1, "data": []},
            {"created": 1},
            {"created": 1, "data": [{"b64_json": ""}]},
            {"created": 1, "data": [{"media_type": "image/png"}]},
            {"created": 1, "data": [{"b64_json": "!!kein-base64!!"}]},
            [],
        ],
    )
    def test_200_without_image_is_error(self, body):
        result = _make(_respond(200, body)).generate(_request())
        assert result.status is ImageStatus.ERROR
        assert result.image_bytes is None
        assert not result.ok

    def test_200_with_non_json_is_error(self):
        handler = lambda request: httpx.Response(200, text="<html>oops</html>")  # noqa: E731
        assert _make(handler).generate(_request()).status is ImageStatus.ERROR

    def test_200_with_error_field_is_error(self):
        body = {
            "data": [{"b64_json": RESULT_B64}],
            **_error_body("server_error", "Generation failed"),
        }
        result = _make(_respond(200, body)).generate(_request())
        assert result.status is ImageStatus.ERROR
        assert result.error_code == "server_error"
        assert result.image_bytes is None

    def test_400_is_error_not_refused(self):
        result = _make(
            _respond(400, _error_body(400, "Invalid request parameters"))
        ).generate(_request())
        assert result.status is ImageStatus.ERROR
        assert result.http_status == 400
        assert result.error_code == "400"
        assert result.detail == "Invalid request parameters"

    def test_402_is_credit_exhausted(self):
        result = _make(
            _respond(402, _error_body(402, "Insufficient credits"))
        ).generate(_request())
        assert result.status is ImageStatus.CREDIT_EXHAUSTED
        assert result.http_status == 402

    def test_generator_is_stateless_after_402(self):
        """Die Sperre bis zum Neustart gehoert in den PortraitMode (E5)."""
        calls = []

        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(402, json=_error_body(402))
            return httpx.Response(200, json={"data": [{"b64_json": RESULT_B64}]})

        generator = _make(handler)
        assert generator.generate(_request()).status is ImageStatus.CREDIT_EXHAUSTED
        assert generator.generate(_request()).status is ImageStatus.OK
        assert len(calls) == 2

    def test_403_with_reasons_is_refused(self):
        metadata = {
            "reasons": ["violence"],
            "flagged_input": "GEHEIMER-PROMPT-AUSSCHNITT",
            "provider_name": "OpenAI",
            "model_slug": MODEL,
        }
        result = _make(_respond(403, _error_body(403, "flagged", metadata))).generate(
            _request()
        )
        assert result.status is ImageStatus.REFUSED
        assert result.error_code == "403"

    @pytest.mark.parametrize(
        "metadata", [None, {}, {"reasons": []}, {"provider_name": "OpenAI"}]
    )
    def test_403_without_reasons_is_error(self, metadata):
        result = _make(_respond(403, _error_body(403, "Forbidden", metadata))).generate(
            _request()
        )
        assert result.status is ImageStatus.ERROR

    @pytest.mark.parametrize("status", [401, 404, 413, 429, 500, 502, 524, 529])
    def test_other_http_errors_are_error(self, status):
        result = _make(_respond(status, _error_body(status))).generate(_request())
        assert result.status is ImageStatus.ERROR
        assert result.http_status == status

    def test_error_without_json_body_is_error(self):
        handler = lambda request: httpx.Response(502, text="Bad Gateway")  # noqa: E731
        result = _make(handler).generate(_request())
        assert result.status is ImageStatus.ERROR
        assert result.error_code is None

    def test_timeout_is_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout("timed out", request=request)

        result = _make(handler).generate(_request())
        assert result.status is ImageStatus.TIMEOUT
        assert result.http_status is None

    def test_connect_error_is_error_without_waiting(self):
        calls = []

        def handler(request):
            calls.append(request)
            raise httpx.ConnectError(
                "[Errno -3] Temporary failure in name resolution", request=request
            )

        start = time.monotonic()
        result = _make(handler).generate(_request())
        assert result.status is ImageStatus.ERROR
        assert result.detail == "ConnectError"
        assert len(calls) == 1  # kein Retry
        assert time.monotonic() - start < 1.0

    def test_api_key_in_error_message_is_redacted(self):
        result = _make(_respond(401, _error_body(401, f"bad key {API_KEY}"))).generate(
            _request()
        )
        assert API_KEY not in (result.detail or "")


# ---------------------------------------------------------------------------
# Request (Ae3/Ae4)
# ---------------------------------------------------------------------------


class _Capture:
    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"data": [{"b64_json": RESULT_B64}]})

    @property
    def body(self) -> dict:
        return json.loads(self.requests[-1].content)


class TestRequest:
    def test_body_contains_exactly_the_ae3_fields(self):
        capture = _Capture()
        _make(capture, quality="low").generate(_request())
        body = capture.body
        assert set(body) == {
            "model",
            "prompt",
            "input_references",
            "aspect_ratio",
            "quality",
            "n",
            "output_format",
        }
        assert body["model"] == MODEL
        assert body["aspect_ratio"] == "16:9"
        assert body["quality"] == "low"
        assert body["n"] == 1
        assert body["output_format"] == "png"
        for forbidden in ("size", "resolution", "seed", "user", "provider", "stream"):
            assert forbidden not in body

    def test_input_reference_is_data_url(self):
        capture = _Capture()
        _make(capture).generate(_request())
        refs = capture.body["input_references"]
        assert refs == [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{GUEST_B64}"},
            }
        ]

    def test_provider_options_only_when_configured(self):
        capture = _Capture()
        _make(
            capture, provider_options={"data_collection": "deny", "zdr": True}
        ).generate(_request())
        assert capture.body["provider"] == {"data_collection": "deny", "zdr": True}

    def test_empty_provider_options_not_sent(self):
        capture = _Capture()
        _make(capture, provider_options={}).generate(_request())
        assert "provider" not in capture.body

    def test_headers_url_and_user_agent(self):
        capture = _Capture()
        _make(capture).generate(_request())
        request = capture.requests[-1]
        assert str(request.url) == OPENROUTER_IMAGES_URL
        assert request.method == "POST"
        assert request.headers["User-Agent"] == USER_AGENT
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"

    def test_timeout_default_90s(self):
        capture = _Capture()
        _make(capture).generate(_request())
        timeouts = capture.requests[-1].extensions["timeout"]
        assert timeouts["read"] == 90.0
        assert timeouts["connect"] == 10.0

    def test_constructor_rejects_empty_key_and_model(self):
        with pytest.raises(ValueError):
            OpenRouterImageGenerator("  ", model=MODEL)
        with pytest.raises(ValueError):
            OpenRouterImageGenerator(API_KEY, model=" ")
        with pytest.raises(ValueError):
            OpenRouterImageGenerator(API_KEY, model=MODEL, timeout_s=0)

    def test_repr_hides_key(self):
        generator = _make(_Capture())
        assert API_KEY not in repr(generator)

    def test_request_rejects_empty_prompt_and_image(self):
        with pytest.raises(ValueError):
            ImageRequest(prompt="  ")
        with pytest.raises(ValueError):
            ImageRequest(prompt="x", input_images=(b"",))

    def test_request_and_result_repr_hide_bytes(self):
        assert "GUEST-PHOTO" not in repr(_request())
        result = _make(_Capture()).generate(_request())
        assert "RESULT-IMAGE" not in repr(result)


# ---------------------------------------------------------------------------
# Log-Disziplin (Ae2)
# ---------------------------------------------------------------------------

_LOG_CASES = [
    (200, {"data": [{"b64_json": RESULT_B64}], "usage": {"cost": 0.02}}),
    (200, {"data": []}),
    (
        200,
        {
            "data": [{"b64_json": RESULT_B64}],
            **_error_body("e", f"echo data:image/jpeg;base64,{GUEST_B64}"),
        },
    ),
    (
        400,
        _error_body(
            400, f"bad input data:image/jpeg;base64,{GUEST_B64}", {"provider_code": "x"}
        ),
    ),
    (402, _error_body(402)),
    (
        403,
        _error_body(
            403, "flagged", {"reasons": ["r"], "flagged_input": "GEHEIMER-PROMPT"}
        ),
    ),
    (403, _error_body(403, "nope", {"raw": f"base64,{GUEST_B64}"})),
    (429, _error_body(429)),
    (
        502,
        _error_body(502, "Provider returned error", {"provider_code": "server_error"}),
    ),
]


def _assert_clean(caplog):
    text = "\n".join(
        record.getMessage() + " " + repr(record.args) for record in caplog.records
    )
    assert caplog.records, "es sollte geloggt werden"
    for forbidden in (
        API_KEY,
        "sk-or",
        "base64,",
        "data:image",
        GUEST_B64[:16],
        RESULT_B64[:16],
        "GEHEIMER-PROMPT",
    ):
        assert forbidden not in text, forbidden


@pytest.mark.parametrize(("status", "body"), _LOG_CASES)
def test_logs_never_contain_key_or_image_data(caplog, status, body):
    caplog.set_level(logging.DEBUG)
    result = _make(_respond(status, body)).generate(_request())
    _assert_clean(caplog)
    assert "data:image" not in (result.detail or "")
    assert "base64," not in (result.detail or "")


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout(f"timeout {API_KEY}"),
        httpx.ConnectError(f"connect data:image/jpeg;base64,{GUEST_B64}"),
    ],
)
def test_logs_clean_on_transport_errors(caplog, exc):
    caplog.set_level(logging.DEBUG)

    def handler(request):
        raise exc

    _make(handler).generate(_request())
    _assert_clean(caplog)


def test_refused_logs_metadata_without_flagged_input(caplog):
    caplog.set_level(logging.INFO)
    body = _error_body(
        403,
        "flagged",
        {
            "reasons": ["violence"],
            "flagged_input": "GEHEIMER-PROMPT",
            "provider_name": "OpenAI",
        },
    )
    _make(_respond(403, body)).generate(_request())
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "violence" in text
    assert "OpenAI" in text
    assert "flagged_input" not in text
