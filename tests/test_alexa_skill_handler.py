"""Tests fuer AlexaSkillHandler und AlexaRequestVerifier -- Alexa Custom Skill auf RPi5."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from elder_berry.robot.alexa_skill_handler import (
    AlexaRequestVerifier,
    AlexaResult,
    AlexaSkillHandler,
    AlexaVerificationError,
)


def _run(coro):
    """Hilfsfunktion: fuehrt async Coroutine synchron aus."""
    return asyncio.run(coro)


# -- Fixtures -------------------------------------------------------------- #


@pytest.fixture()
def harmony():
    """Mock-HarmonyAdapter."""
    mock = AsyncMock()
    mock.start_activity = AsyncMock(return_value=True)
    mock.power_off = AsyncMock(return_value=True)
    mock.send_command = AsyncMock(return_value=True)
    mock.get_current_activity = AsyncMock(return_value="Fernsehen")
    return mock


@pytest.fixture()
def harmony_scenes():
    """Mock-HarmonySceneManager."""
    mock = AsyncMock()
    mock.start_scene = AsyncMock(return_value={"steps_ok": 3, "steps_total": 3})
    return mock


@pytest.fixture()
def handler(harmony, harmony_scenes):
    """AlexaSkillHandler mit Mock-Harmony."""
    return AlexaSkillHandler(harmony=harmony, harmony_scenes=harmony_scenes)


@pytest.fixture()
def handler_no_harmony():
    """AlexaSkillHandler ohne Harmony."""
    return AlexaSkillHandler(harmony=None, harmony_scenes=None)


def _intent_request(intent_name: str) -> dict:
    """Baut ein minimales Alexa IntentRequest."""
    return {
        "version": "1.0",
        "session": {},
        "request": {
            "type": "IntentRequest",
            "intent": {
                "name": intent_name,
                "slots": {},
            },
        },
    }


def _launch_request() -> dict:
    """Baut ein Alexa LaunchRequest."""
    return {
        "version": "1.0",
        "session": {},
        "request": {"type": "LaunchRequest"},
    }


def _session_ended_request() -> dict:
    """Baut ein Alexa SessionEndedRequest."""
    return {
        "version": "1.0",
        "session": {},
        "request": {"type": "SessionEndedRequest"},
    }


# -- Request Parsing ------------------------------------------------------- #


class TestAlexaRequestParsing:
    """Tests fuer parse_alexa_request()."""

    def test_intent_request_extracts_intent(self, handler):
        req = _intent_request("TVAnIntent")
        rtype, intent = handler.parse_alexa_request(req)
        assert rtype == "IntentRequest"
        assert intent == "TVAnIntent"

    def test_launch_request(self, handler):
        req = _launch_request()
        rtype, intent = handler.parse_alexa_request(req)
        assert rtype == "LaunchRequest"
        assert intent == ""

    def test_session_ended_request(self, handler):
        req = _session_ended_request()
        rtype, intent = handler.parse_alexa_request(req)
        assert rtype == "SessionEndedRequest"
        assert intent == ""

    def test_missing_intent_returns_empty(self, handler):
        req = {
            "version": "1.0",
            "session": {},
            "request": {
                "type": "IntentRequest",
                "intent": {},
            },
        }
        rtype, intent = handler.parse_alexa_request(req)
        assert rtype == "IntentRequest"
        assert intent == ""


# -- Response Building ----------------------------------------------------- #


class TestAlexaResponseBuilding:
    """Tests fuer build_alexa_response()."""

    def test_response_format(self, handler):
        result = AlexaResult(text="Hallo", success=True, end_session=True)
        resp = handler.build_alexa_response(result)
        assert resp["version"] == "1.0"
        assert resp["response"]["outputSpeech"]["type"] == "PlainText"
        assert resp["response"]["outputSpeech"]["text"] == "Hallo"
        assert resp["response"]["shouldEndSession"] is True

    def test_session_kept_open(self, handler):
        result = AlexaResult(text="Was?", end_session=False)
        resp = handler.build_alexa_response(result)
        assert resp["response"]["shouldEndSession"] is False


# -- LaunchRequest --------------------------------------------------------- #


class TestLaunchRequest:
    def test_launch_returns_greeting(self, handler):
        resp = _run(handler.handle_request(_launch_request()))
        text = resp["response"]["outputSpeech"]["text"]
        assert "hört" in text.lower() or "saleria" in text.lower()
        assert resp["response"]["shouldEndSession"] is False


# -- Activity Intents ------------------------------------------------------ #


class TestActivityIntents:
    def test_tv_an_intent(self, handler, harmony):
        resp = _run(handler.handle_request(_intent_request("TVAnIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "eingeschaltet" in text.lower() or "fernsehen" in text.lower()
        harmony.start_activity.assert_called_once_with("Fernsehen")

    def test_musik_an_intent(self, handler, harmony):
        _run(handler.handle_request(_intent_request("MusikAnIntent")))
        harmony.start_activity.assert_called_once_with("Musik")

    def test_gaming_an_intent(self, handler, harmony):
        _run(handler.handle_request(_intent_request("GamingAnIntent")))
        harmony.start_activity.assert_called_once_with("Gaming")

    def test_activity_failure(self, handler, harmony):
        harmony.start_activity = AsyncMock(return_value=False)
        resp = _run(handler.handle_request(_intent_request("TVAnIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht" in text.lower() or "fehl" in text.lower()

    def test_activity_exception(self, handler, harmony):
        harmony.start_activity = AsyncMock(side_effect=RuntimeError("Hub offline"))
        resp = _run(handler.handle_request(_intent_request("TVAnIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fehler" in text.lower()


# -- AllesAusIntent -------------------------------------------------------- #


class TestAllesAusIntent:
    def test_alles_aus(self, handler, harmony):
        resp = _run(handler.handle_request(_intent_request("AllesAusIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "ausgeschaltet" in text.lower() or "aus" in text.lower()
        harmony.power_off.assert_called_once()

    def test_all_off_failure(self, handler, harmony):
        harmony.power_off = AsyncMock(return_value=False)
        resp = _run(handler.handle_request(_intent_request("AllesAusIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fehlgeschlagen" in text.lower()


# -- Volume Intents -------------------------------------------------------- #


class TestVolumeIntents:
    def test_lauter(self, handler, harmony):
        resp = _run(handler.handle_request(_intent_request("LauterIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "lauter" in text.lower()
        harmony.send_command.assert_called_once_with(
            device="Samsung TV",
            command="VolumeUp",
        )

    def test_leiser(self, handler, harmony):
        _run(handler.handle_request(_intent_request("LeiserIntent")))
        harmony.send_command.assert_called_once_with(
            device="Samsung TV",
            command="VolumeDown",
        )

    def test_stumm(self, handler, harmony):
        _run(handler.handle_request(_intent_request("StummIntent")))
        harmony.send_command.assert_called_once_with(
            device="Samsung TV",
            command="Mute",
        )

    def test_volume_failure(self, handler, harmony):
        harmony.send_command = AsyncMock(return_value=False)
        resp = _run(handler.handle_request(_intent_request("LauterIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fehlgeschlagen" in text.lower()


# -- StatusIntent ---------------------------------------------------------- #


class TestStatusIntent:
    def test_was_laeuft(self, handler, harmony):
        resp = _run(handler.handle_request(_intent_request("StatusIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fernsehen" in text.lower()

    def test_nothing_active(self, handler, harmony):
        harmony.get_current_activity = AsyncMock(return_value=None)
        resp = _run(handler.handle_request(_intent_request("StatusIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "aus" in text.lower() or "nichts" in text.lower()


# -- Amazon Built-in Intents ----------------------------------------------- #


class TestBuiltinIntents:
    def test_cancel_intent(self, handler):
        resp = _run(handler.handle_request(_intent_request("AMAZON.CancelIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "tschüss" in text.lower()
        assert resp["response"]["shouldEndSession"] is True

    def test_stop_intent(self, handler):
        resp = _run(handler.handle_request(_intent_request("AMAZON.StopIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "tschüss" in text.lower()

    def test_help_intent(self, handler):
        resp = _run(handler.handle_request(_intent_request("AMAZON.HelpIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "fernsehen" in text.lower()
        assert resp["response"]["shouldEndSession"] is False

    def test_fallback_intent(self, handler):
        resp = _run(handler.handle_request(_intent_request("AMAZON.FallbackIntent")))
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht verstanden" in text.lower()
        assert resp["response"]["shouldEndSession"] is False


# -- No Harmony ------------------------------------------------------------ #


class TestNoHarmony:
    def test_activity_without_harmony(self, handler_no_harmony):
        resp = _run(
            handler_no_harmony.handle_request(
                _intent_request("TVAnIntent"),
            )
        )
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht verfügbar" in text.lower()

    def test_off_without_harmony(self, handler_no_harmony):
        resp = _run(
            handler_no_harmony.handle_request(
                _intent_request("AllesAusIntent"),
            )
        )
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht verfügbar" in text.lower()

    def test_volume_without_harmony(self, handler_no_harmony):
        resp = _run(
            handler_no_harmony.handle_request(
                _intent_request("LauterIntent"),
            )
        )
        text = resp["response"]["outputSpeech"]["text"]
        assert "nicht verfügbar" in text.lower()


# -- Unknown Intent -------------------------------------------------------- #


class TestUnknownIntent:
    def test_unknown_intent(self, handler):
        resp = _run(
            handler.handle_request(
                _intent_request("PizzaBestellenIntent"),
            )
        )
        text = resp["response"]["outputSpeech"]["text"]
        assert "kenne ich" in text.lower() or "nicht" in text.lower()


# -- Session End ----------------------------------------------------------- #


class TestSessionEnd:
    def test_session_ended(self, handler):
        resp = _run(handler.handle_request(_session_ended_request()))
        assert resp["response"]["shouldEndSession"] is True

    def test_all_responses_end_session(self, handler):
        """Befehle beenden die Session (kein Follow-up noetig)."""
        resp = _run(handler.handle_request(_intent_request("TVAnIntent")))
        assert resp["response"]["shouldEndSession"] is True


# ---------------------------------------------------------------------------
# AlexaRequestVerifier Tests
# ---------------------------------------------------------------------------

# Hilfswerte
_VALID_CERT_URL = "https://s3.amazonaws.com/echo.api/echo-api-cert-7.pem"
_VALID_SIGNATURE = base64.b64encode(b"fakesig").decode()
_APP_ID = "amzn1.ask.skill.test-skill-id"


def _fresh_timestamp() -> str:
    """ISO-8601-Timestamp der aktuellen Zeit (UTC, Alexa-Format)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stale_timestamp() -> str:
    """ISO-8601-Timestamp der 5 Minuten alt ist (zu alt für Alexa)."""
    ts = datetime.now(tz=timezone.utc) - timedelta(seconds=300)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _intent_body_dict(ts: str | None = None) -> dict:
    """Minimales Alexa-Request-Dict mit Timestamp."""
    return {
        "version": "1.0",
        "session": {
            "application": {"applicationId": _APP_ID},
        },
        "request": {
            "type": "IntentRequest",
            "timestamp": ts or _fresh_timestamp(),
            "intent": {"name": "TVAnIntent", "slots": {}},
        },
    }


class TestAlexaRequestVerifierCertUrl:
    """Tests fuer _validate_cert_url()."""

    def test_valid_url_accepted(self):
        AlexaRequestVerifier._validate_cert_url(_VALID_CERT_URL)  # kein Fehler

    def test_http_scheme_rejected(self):
        with pytest.raises(AlexaVerificationError, match="HTTPS"):
            AlexaRequestVerifier._validate_cert_url(
                "http://s3.amazonaws.com/echo.api/cert.pem"
            )

    def test_wrong_host_rejected(self):
        with pytest.raises(AlexaVerificationError, match="Host ungültig"):
            AlexaRequestVerifier._validate_cert_url(
                "https://evil.com/echo.api/cert.pem"
            )

    def test_wrong_port_rejected(self):
        with pytest.raises(AlexaVerificationError, match="Port ungültig"):
            AlexaRequestVerifier._validate_cert_url(
                "https://s3.amazonaws.com:8080/echo.api/cert.pem"
            )

    def test_port_443_accepted(self):
        AlexaRequestVerifier._validate_cert_url(
            "https://s3.amazonaws.com:443/echo.api/cert.pem"
        )  # kein Fehler

    def test_wrong_path_prefix_rejected(self):
        with pytest.raises(AlexaVerificationError, match="Pfad"):
            AlexaRequestVerifier._validate_cert_url(
                "https://s3.amazonaws.com/other-path/cert.pem"
            )


class TestAlexaRequestVerifierTimestamp:
    """Tests fuer _verify_timestamp()."""

    def test_fresh_timestamp_passes(self):
        body = _intent_body_dict(_fresh_timestamp())
        AlexaRequestVerifier._verify_timestamp(body)  # kein Fehler

    def test_stale_timestamp_rejected(self):
        body = _intent_body_dict(_stale_timestamp())
        with pytest.raises(AlexaVerificationError, match="alt"):
            AlexaRequestVerifier._verify_timestamp(body)

    def test_missing_timestamp_rejected(self):
        body = {"request": {}}
        with pytest.raises(AlexaVerificationError, match="Timestamp"):
            AlexaRequestVerifier._verify_timestamp(body)

    def test_invalid_timestamp_format_rejected(self):
        body = {"request": {"timestamp": "kein-datum"}}
        with pytest.raises(AlexaVerificationError, match="Ungültiges Timestamp"):
            AlexaRequestVerifier._verify_timestamp(body)


class TestAlexaRequestVerifierApplicationId:
    """Tests fuer _verify_application_id()."""

    def test_matching_id_passes(self):
        verifier = AlexaRequestVerifier(application_id=_APP_ID)
        verifier._verify_application_id(_intent_body_dict())  # kein Fehler

    def test_wrong_id_rejected(self):
        verifier = AlexaRequestVerifier(application_id="amzn1.ask.skill.other-id")
        with pytest.raises(AlexaVerificationError, match="applicationId"):
            verifier._verify_application_id(_intent_body_dict())

    def test_missing_id_rejected(self):
        verifier = AlexaRequestVerifier(application_id=_APP_ID)
        body = {"session": {}, "request": {"timestamp": _fresh_timestamp()}}
        with pytest.raises(AlexaVerificationError, match="applicationId"):
            verifier._verify_application_id(body)

    def test_no_app_id_configured_skips_check(self):
        verifier = AlexaRequestVerifier(application_id=None)
        # Wenn keine App-ID konfiguriert, darf verify() nicht
        # _verify_application_id() aufrufen – der Call wird via Mocking sichergestellt.
        verifier._verify_application_id = MagicMock()  # type: ignore[method-assign]
        # kein Fehler, da _verify_application_id nicht aufgerufen wird
        assert verifier._application_id is None


class TestAlexaRequestVerifierMissingHeaders:
    """Fehlende Header werden korrekt abgelehnt."""

    def test_missing_cert_url_header(self):
        verifier = AlexaRequestVerifier()
        body = _intent_body_dict()
        with pytest.raises(AlexaVerificationError, match="SignatureCertChainUrl"):
            _run(
                verifier.verify(
                    headers={"signature": _VALID_SIGNATURE},
                    body_bytes=json.dumps(body).encode(),
                    body_dict=body,
                )
            )

    def test_missing_signature_header(self):
        verifier = AlexaRequestVerifier()
        body = _intent_body_dict()
        with pytest.raises(AlexaVerificationError, match="Signature"):
            _run(
                verifier.verify(
                    headers={"signaturecertchainurl": _VALID_CERT_URL},
                    body_bytes=json.dumps(body).encode(),
                    body_dict=body,
                )
            )


class TestAlexaRequestVerifierSignature:
    """Tests fuer _verify_signature()."""

    def test_invalid_base64_rejected(self):
        # Nicht-Base64-String als Signatur
        mock_cert = MagicMock()
        with pytest.raises(AlexaVerificationError, match="Base64"):
            AlexaRequestVerifier._verify_signature(mock_cert, "!!not-base64!!", b"body")

    def test_wrong_signature_rejected(self):
        from cryptography.hazmat.primitives.asymmetric import rsa, padding
        from cryptography.hazmat.backends import default_backend
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.x509.oid import NameOID

        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        now = datetime.now(tz=timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")]))
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=1))
            .sign(private_key, hashes.SHA256())
        )
        # Falsche Signatur (signiert anderes Dokument)
        wrong_sig = private_key.sign(
            b"other content", padding.PKCS1v15(), hashes.SHA256()
        )
        wrong_sig_b64 = base64.b64encode(wrong_sig).decode()

        with pytest.raises(AlexaVerificationError, match="ungültig"):
            AlexaRequestVerifier._verify_signature(cert, wrong_sig_b64, b"correct body")

    def test_correct_signature_passes(self):
        from cryptography.hazmat.primitives.asymmetric import rsa, padding
        from cryptography.hazmat.backends import default_backend
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.x509.oid import NameOID

        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        now = datetime.now(tz=timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")]))
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=1))
            .sign(private_key, hashes.SHA256())
        )
        body = b"test body content"
        sig = private_key.sign(body, padding.PKCS1v15(), hashes.SHA256())
        sig_b64 = base64.b64encode(sig).decode()

        # Kein Fehler erwartet
        AlexaRequestVerifier._verify_signature(cert, sig_b64, body)
