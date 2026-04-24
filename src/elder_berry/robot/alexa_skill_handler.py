"""AlexaSkillHandler -- Alexa Custom Skill Endpoint fuer RPi5.

Empfaengt Intents von Amazon Alexa, dispatcht an HarmonyAdapter
und gibt Alexa-Response zurueck.

Flow:
  Echo -> Amazon STT -> Rootserver (HTTPS) -> SSH-Tunnel -> RPi5:8000
  -> AlexaSkillHandler -> HarmonyAdapter -> Harmony Hub -> IR -> Geraet

Routing: Alexa sendet Intent-Namen (TVAnIntent, AllesAusIntent, etc.),
kein Freitext-Slot. Dadurch keine Carrier-Phrase noetig.

Sicherheit:
  AlexaRequestVerifier prüft jeden eingehenden Request:
  - SignatureCertChainUrl: muss HTTPS von s3.amazonaws.com sein, Pfad /echo.api/
  - Zertifikat: nicht abgelaufen, SAN enthält echo-api.amazon.com
  - Signatur: RSA-SHA256 des rohen Request-Body mit Amazon-Zertifikat
  - Timestamp: max. 150 Sekunden alt (verhindert Replay-Angriffe)
  - ApplicationId: optional, prüft gegen konfigurierten Skill-ID-Wert
"""
from __future__ import annotations

import base64
import logging
import time as _time
from dataclasses import dataclass
from datetime import datetime as _dt, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from cryptography.x509 import Certificate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Alexa Request Verification
# ---------------------------------------------------------------------------

# Zertifikat-Cache: URL -> (Certificate, expires_at_monotonic)
_CERT_CACHE: dict[str, tuple[Certificate, float]] = {}
_CERT_CACHE_TTL_S = 3600  # 1 Stunde

# Erlaubter Hostname fuer Zertifikat-URLs (Amazon S3)
_CERT_ALLOWED_HOST = "s3.amazonaws.com"
# Pflicht-Pfadpräfix fuer Alexa-Zertifikat-URLs
_CERT_PATH_PREFIX = "/echo.api/"
# Pflicht-SAN im Alexa-Zertifikat
_CERT_ALEXA_SAN = "echo-api.amazon.com"
# Maximales Alter eines Alexa-Request-Timestamps (Amazon-Vorgabe: 150 s)
_TIMESTAMP_TOLERANCE_S = 150


class AlexaVerificationError(Exception):
    """Wird geworfen wenn ein Alexa-Request die Verifikation nicht besteht."""


class AlexaRequestVerifier:
    """Verifiziert Alexa-Requests gemaess Amazon-Sicherheitsanforderungen.

    Prueft:
    1. ``SignatureCertChainUrl``-Header: HTTPS, Amazon-S3-Host, /echo.api/-Pfad
    2. Zertifikat: nicht abgelaufen, SAN enthaelt ``echo-api.amazon.com``
    3. Signatur: RSA-SHA256 des rohen Request-Bodys (Base64 aus ``Signature``-Header)
    4. Timestamp: max. 150 Sekunden alt (Replay-Schutz)
    5. ApplicationId: optional, Vergleich mit konfiguriertem Wert

    Parameters
    ----------
    application_id:
        Erwartete Alexa-Skill-ApplicationId (``amzn1.ask.skill.…``).
        Wenn ``None``, wird die ApplicationId nicht geprüft.
    """

    def __init__(self, application_id: str | None = None) -> None:
        self._application_id = application_id

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    async def verify(
        self,
        headers: dict[str, str],
        body_bytes: bytes,
        body_dict: dict,
    ) -> None:
        """Vollständige Verifikation eines Alexa-Requests.

        Parameters
        ----------
        headers:
            HTTP-Header des Requests (Keys lowercase).
        body_bytes:
            Roher Request-Body (für Signatur-Check).
        body_dict:
            Geparster Request-Body als dict (für Timestamp + ApplicationId).

        Raises
        ------
        AlexaVerificationError
            Wenn ein Prüfschritt fehlschlägt.
        """
        cert_url = headers.get("signaturecertchainurl", "")
        # Alexa sendet SHA256-Signatur als "Signature-256" (bevorzugt)
        # und SHA1-Signatur als "Signature" (legacy)
        signature_b64 = headers.get("signature-256", "") or headers.get("signature", "")

        if not cert_url:
            raise AlexaVerificationError("Header 'SignatureCertChainUrl' fehlt")
        if not signature_b64:
            raise AlexaVerificationError("Header 'Signature' fehlt")

        self._validate_cert_url(cert_url)
        cert = await self._get_cert(cert_url)
        self._validate_cert(cert)
        self._verify_signature(cert, signature_b64, body_bytes)
        self._verify_timestamp(body_dict)
        if self._application_id:
            self._verify_application_id(body_dict)

    # ------------------------------------------------------------------
    # Interne Prüfschritte
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_cert_url(url: str) -> None:
        """Prüft ob die Cert-URL dem Amazon-Schema entspricht."""
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            raise AlexaVerificationError(
                f"Cert-URL muss HTTPS sein, ist: {parsed.scheme!r}"
            )
        host = (parsed.hostname or "").lower()
        if host != _CERT_ALLOWED_HOST:
            raise AlexaVerificationError(
                f"Cert-URL Host ungültig: {host!r} (erwartet: {_CERT_ALLOWED_HOST!r})"
            )
        if parsed.port not in (None, 443):
            raise AlexaVerificationError(
                f"Cert-URL Port ungültig: {parsed.port} (nur 443 erlaubt)"
            )
        if not parsed.path.startswith(_CERT_PATH_PREFIX):
            raise AlexaVerificationError(
                f"Cert-URL Pfad muss mit {_CERT_PATH_PREFIX!r} beginnen, ist: {parsed.path!r}"
            )

    @staticmethod
    async def _get_cert(url: str) -> Certificate:
        """Lädt das Zertifikat von der URL (mit Cache, 1h TTL)."""
        cached = _CERT_CACHE.get(url)
        if cached is not None:
            cert, expires_at = cached
            if _time.monotonic() < expires_at:
                return cert

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=5.0)
                resp.raise_for_status()
                pem_data = resp.content
        except Exception as exc:
            raise AlexaVerificationError(
                f"Zertifikat-Download fehlgeschlagen: {exc}"
            ) from exc

        try:
            from cryptography import x509
            cert = x509.load_pem_x509_certificate(pem_data)
        except Exception as exc:
            raise AlexaVerificationError(
                f"Zertifikat konnte nicht geparst werden: {exc}"
            ) from exc

        _CERT_CACHE[url] = (cert, _time.monotonic() + _CERT_CACHE_TTL_S)
        return cert

    @staticmethod
    def _validate_cert(cert: Certificate) -> None:
        """Prüft Gültigkeit und SAN des Zertifikats."""
        from cryptography import x509 as cx509

        now = _dt.now(tz=timezone.utc)
        if now < cert.not_valid_before_utc:
            raise AlexaVerificationError("Zertifikat ist noch nicht gültig")
        if now > cert.not_valid_after_utc:
            raise AlexaVerificationError("Zertifikat ist abgelaufen")

        try:
            san_ext = cert.extensions.get_extension_for_class(
                cx509.SubjectAlternativeName
            )
            dns_names = san_ext.value.get_values_for_type(cx509.DNSName)
        except cx509.ExtensionNotFound:
            raise AlexaVerificationError("Zertifikat enthält keine SAN-Extension") from None

        if _CERT_ALEXA_SAN not in dns_names:
            raise AlexaVerificationError(
                f"Zertifikat SAN enthält nicht {_CERT_ALEXA_SAN!r}: {dns_names}"
            )

    @staticmethod
    def _verify_signature(
        cert: Certificate, signature_b64: str, body_bytes: bytes
    ) -> None:
        """Prüft die RSA-SHA256-Signatur des Request-Bodys."""
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes
        from cryptography.exceptions import InvalidSignature

        try:
            signature = base64.b64decode(signature_b64)
        except Exception as exc:
            raise AlexaVerificationError(
                f"Signatur ist kein gültiges Base64: {exc}"
            ) from exc

        public_key = cert.public_key()
        try:
            public_key.verify(
                signature, body_bytes, padding.PKCS1v15(), hashes.SHA256()
            )
        except InvalidSignature as exc:
            raise AlexaVerificationError("Signatur ist ungültig") from exc
        except Exception as exc:
            raise AlexaVerificationError(
                f"Signatur-Prüfung fehlgeschlagen: {exc}"
            ) from exc

    @staticmethod
    def _verify_timestamp(body: dict) -> None:
        """Prüft ob der Request-Timestamp max. 150 Sekunden alt ist."""
        ts_str = body.get("request", {}).get("timestamp", "")
        if not ts_str:
            raise AlexaVerificationError("Request enthält keinen Timestamp")

        try:
            ts = _dt.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AlexaVerificationError(
                f"Ungültiges Timestamp-Format: {ts_str!r}"
            ) from exc

        age_s = abs((_dt.now(tz=timezone.utc) - ts).total_seconds())
        if age_s > _TIMESTAMP_TOLERANCE_S:
            raise AlexaVerificationError(
                f"Request-Timestamp zu alt: {age_s:.0f}s "
                f"(Limit: {_TIMESTAMP_TOLERANCE_S}s)"
            )

    def _verify_application_id(self, body: dict) -> None:
        """Prüft die Skill-ApplicationId gegen den konfigurierten Wert."""
        app_id = (
            body.get("session", {})
            .get("application", {})
            .get("applicationId", "")
        )
        if app_id != self._application_id:
            raise AlexaVerificationError(
                f"Unbekannte applicationId: {app_id!r}"
            )


# -- Geraet fuer Lautstaerke (Samsung TV steuert Denon via ARC/CEC) ------- #

_VOLUME_DEVICE = "Samsung TV"

# -- Intent -> Activity Mapping -------------------------------------------- #

_INTENT_ACTIVITY_MAP: dict[str, str] = {
    "TVAnIntent": "Fernsehen",
    "MusikAnIntent": "Musik",
    "GamingAnIntent": "Gaming",
}


@dataclass
class AlexaResult:
    """Ergebnis einer Alexa-Command-Verarbeitung."""

    text: str
    success: bool = True
    end_session: bool = True


class AlexaSkillHandler:
    """Verarbeitet Alexa-Requests und dispatcht an HarmonyAdapter.

    Parameters
    ----------
    harmony : HarmonyAdapter | None
        Adapter fuer Harmony-Hub-Steuerung (optional).
    harmony_scenes : HarmonySceneManager | None
        Szenen-Manager (optional).
    """

    def __init__(
        self,
        harmony: Any = None,
        harmony_scenes: Any = None,
    ) -> None:
        self._harmony = harmony
        self._harmony_scenes = harmony_scenes

    # -- Alexa Request Parsing --------------------------------------------- #

    def parse_alexa_request(self, body: dict) -> tuple[str, str]:
        """Extrahiert Request-Typ und Intent-Name aus Alexa-JSON.

        Returns
        -------
        tuple[str, str]
            (request_type, intent_name)
            request_type: "LaunchRequest", "IntentRequest", "SessionEndedRequest"
            intent_name: z.B. "TVAnIntent" oder leerer String
        """
        request = body.get("request", {})
        request_type = request.get("type", "")

        if request_type != "IntentRequest":
            return request_type, ""

        intent = request.get("intent", {})
        intent_name = intent.get("name", "")

        return request_type, intent_name

    # -- Alexa Response Building ------------------------------------------- #

    def build_alexa_response(self, result: AlexaResult) -> dict:
        """Baut Alexa-kompatible JSON-Response."""
        return {
            "version": "1.0",
            "response": {
                "outputSpeech": {
                    "type": "PlainText",
                    "text": result.text,
                },
                "shouldEndSession": result.end_session,
            },
        }

    # -- Command Dispatch -------------------------------------------------- #

    async def handle_request(self, body: dict) -> dict:
        """Verarbeitet einen kompletten Alexa-Request.

        Returns
        -------
        dict
            Alexa-Response-JSON.
        """
        request_type, intent_name = self.parse_alexa_request(body)

        if request_type == "LaunchRequest":
            result = AlexaResult(
                text="Saleria hört. Was soll ich tun?",
                end_session=False,
            )
            return self.build_alexa_response(result)

        if request_type == "SessionEndedRequest":
            return self.build_alexa_response(AlexaResult(text=""))

        if request_type != "IntentRequest":
            result = AlexaResult(
                text="Das habe ich nicht verstanden.",
                success=False,
            )
            return self.build_alexa_response(result)

        # Amazon Built-in Intents
        if intent_name in ("AMAZON.CancelIntent", "AMAZON.StopIntent"):
            return self.build_alexa_response(AlexaResult(text="Tschüss."))

        if intent_name == "AMAZON.HelpIntent":
            result = AlexaResult(
                text="Du kannst sagen: Fernsehen an, Musik an, "
                     "alles aus, lauter, leiser, stumm, oder was läuft.",
                end_session=False,
            )
            return self.build_alexa_response(result)

        if intent_name == "AMAZON.FallbackIntent":
            result = AlexaResult(
                text="Das habe ich nicht verstanden. "
                     "Sag zum Beispiel: Fernsehen an.",
                success=False,
                end_session=False,
            )
            return self.build_alexa_response(result)

        logger.info("Alexa-Intent: '%s'", intent_name)
        result = await self._dispatch_intent(intent_name)
        return self.build_alexa_response(result)

    async def _dispatch_intent(self, intent_name: str) -> AlexaResult:
        """Dispatcht Intent an passenden Handler."""

        # Activity on (TV, Musik, Gaming)
        if intent_name in _INTENT_ACTIVITY_MAP:
            activity = _INTENT_ACTIVITY_MAP[intent_name]
            return await self._cmd_activity_on(activity)

        # All off
        if intent_name == "AllesAusIntent":
            return await self._cmd_all_off()

        # Volume
        if intent_name == "LauterIntent":
            return await self._cmd_volume("VolumeUp", "Lauter")

        if intent_name == "LeiserIntent":
            return await self._cmd_volume("VolumeDown", "Leiser")

        if intent_name == "StummIntent":
            return await self._cmd_volume("Mute", "Stummgeschaltet")

        # Status
        if intent_name == "StatusIntent":
            return await self._cmd_current()

        return AlexaResult(
            text="Diesen Befehl kenne ich noch nicht.",
            success=False,
        )

    # -- Harmony Commands -------------------------------------------------- #

    async def _cmd_activity_on(self, activity_name: str) -> AlexaResult:
        if not self._harmony:
            return AlexaResult(text="Harmony Hub nicht verfügbar.", success=False)

        try:
            success = await self._harmony.start_activity(activity_name)
            if success:
                return AlexaResult(text=f"{activity_name} wurde eingeschaltet.")
            return AlexaResult(
                text=f"{activity_name} konnte nicht gestartet werden.",
                success=False,
            )
        except Exception as e:
            logger.error("Alexa activity_on Fehler: %s", e)
            return AlexaResult(text="Fehler bei der Steuerung.", success=False)

    async def _cmd_all_off(self) -> AlexaResult:
        if not self._harmony:
            return AlexaResult(text="Harmony Hub nicht verfügbar.", success=False)

        try:
            success = await self._harmony.power_off()
            if success:
                return AlexaResult(text="Alles ausgeschaltet.")
            return AlexaResult(text="Ausschalten fehlgeschlagen.", success=False)
        except Exception as e:
            logger.error("Alexa all_off Fehler: %s", e)
            return AlexaResult(text="Fehler beim Ausschalten.", success=False)

    async def _cmd_volume(self, command: str, label: str) -> AlexaResult:
        if not self._harmony:
            return AlexaResult(text="Harmony Hub nicht verfügbar.", success=False)

        try:
            success = await self._harmony.send_command(
                device=_VOLUME_DEVICE, command=command,
            )
            if success:
                return AlexaResult(text=f"{label}.")
            return AlexaResult(text=f"{label} fehlgeschlagen.", success=False)
        except Exception as e:
            logger.error("Alexa volume Fehler: %s", e)
            return AlexaResult(text="Fehler bei der Lautstärke.", success=False)

    async def _cmd_current(self) -> AlexaResult:
        if not self._harmony:
            return AlexaResult(text="Harmony Hub nicht verfügbar.", success=False)

        try:
            activity = await self._harmony.get_current_activity()
            if activity:
                return AlexaResult(text=f"Gerade läuft: {activity}.")
            return AlexaResult(text="Nichts aktiv. Alles ist aus.")
        except Exception as e:
            logger.error("Alexa current Fehler: %s", e)
            return AlexaResult(text="Status konnte nicht abgefragt werden.", success=False)
