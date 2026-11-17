"""OpenRouterImageGenerator -- Bildgenerierung ueber die OpenRouter Image API.

Phase 111, E1. Schema laut OpenRouter-Doku (Quellen und Abrufdatum in
#1473, F10): ``POST https://openrouter.ai/api/v1/images``, Antwort
``{"created", "data": [{"b64_json", "media_type"?}], "usage"?: {"cost"?}}``,
Fehlerbody ``{"error": {"code", "message", "metadata"?}}``.

Request-Felder (Ae3, #1474): ``model``, ``prompt``, ``input_references``
(Data-URL), ``aspect_ratio``, ``quality``, ``n=1``, ``output_format``. Bewusst
NICHT: ``size``, ``resolution``, ``seed`` (fuer gpt-image-2.6-flare nicht in
``supported_parameters``) und ``user`` (nie Gaestedaten). ``provider`` nur,
wenn konfiguriert (Ae4).

Statuszuordnung (Ae1): siehe :func:`_classify`.

Log-Disziplin (Ae2): Request- und Response-Bodies werden nie geloggt, auch
nicht im Fehlerfall. Geloggt werden Dauer, HTTP-Status, Kategorie,
``error.code``, Kosten und bei ERROR/REFUSED die ``error.metadata`` ohne
``flagged_input``. Exceptions von httpx werden nur mit ihrem Typnamen
geloggt.

Timeout: ``timeout_s`` gilt als httpx-Read-Timeout (Abstand zwischen zwei
empfangenen Bytes) und begrenzt Write/Pool. Die Image API sendet ohne
Streaming erst, wenn das Bild fertig ist; damit liegt die Gesamtdauer bei
etwa Verbindungsaufbau + ``timeout_s``. Eine harte Wanduhr-Grenze ist das
NICHT -- die setzt der aufrufende Worker (E5) selbst durch.
"""

from __future__ import annotations

import base64
import binascii
import logging
import time
from collections.abc import Mapping
from typing import Any

import httpx

from elder_berry.core.http_defaults import with_user_agent
from elder_berry.llm.image_generator import (
    ImageGenerator,
    ImageRequest,
    ImageResult,
    ImageStatus,
)

logger = logging.getLogger(__name__)

OPENROUTER_IMAGES_URL = "https://openrouter.ai/api/v1/images"
DEFAULT_TIMEOUT_S = 90.0
#: Verbindungsaufbau darf nicht den ganzen Timeout fressen: offline soll der
#: Rahmen schnell in den Rueckfall gehen (§4.4 "Offline").
DEFAULT_CONNECT_TIMEOUT_S = 10.0

_MAX_DETAIL_CHARS = 200
_MAX_META_VALUE_CHARS = 120
#: Diese Teilstrings duerfen in keinem Log-Record und keinem ``detail`` stehen.
_FORBIDDEN_MARKERS = ("data:image", "base64,", "sk-or")


def _sanitize(text: str, limit: int) -> str:
    """Kuerzt und entfernt Inhalte, die nach Bild-/Base64-Daten oder einem
    OpenRouter-Schluessel aussehen."""
    lowered = text.lower()
    if any(marker in lowered for marker in _FORBIDDEN_MARKERS):
        return "<entfernt: enthielt Bild- oder Schluesseldaten>"
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _safe_metadata(metadata: object) -> dict[str, str]:
    """``error.metadata`` ohne ``flagged_input``, Werte gekuerzt (Ae1)."""
    if not isinstance(metadata, Mapping):
        return {}
    safe: dict[str, str] = {}
    for key, value in metadata.items():
        if key == "flagged_input":
            continue
        safe[str(key)] = _sanitize(str(value), _MAX_META_VALUE_CHARS)
    return safe


def _error_fields(body: object) -> tuple[str | None, str | None, object]:
    """Liest ``error.code``, ``error.message`` und ``error.metadata``."""
    if not isinstance(body, Mapping):
        return None, None, None
    error = body.get("error")
    if not isinstance(error, Mapping):
        return None, None, None
    code = error.get("code")
    message = error.get("message")
    return (
        None if code is None else str(code),
        message if isinstance(message, str) else None,
        error.get("metadata"),
    )


def _has_reasons(metadata: object) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    reasons = metadata.get("reasons")
    return isinstance(reasons, list) and len(reasons) > 0


def _extract_cost(body: Mapping[str, Any]) -> float | None:
    usage = body.get("usage")
    if not isinstance(usage, Mapping):
        return None
    cost = usage.get("cost")
    if isinstance(cost, bool) or not isinstance(cost, int | float):
        return None
    return float(cost)


class OpenRouterImageGenerator(ImageGenerator):
    """:class:`ImageGenerator` gegen ``POST /api/v1/images``.

    Args:
        api_key: OpenRouter-Schluessel (per DI, wird nie geloggt).
        model: Modell-ID, z.B. ``openai/gpt-image-2.6-flare``.
        quality: ``auto|low|medium|high|xhigh|max``.
        aspect_ratio: Default ``16:9`` (Querformat, §4.5).
        output_format: Default ``png`` (explizit, Ae3).
        provider_options: Optionales ``provider``-Objekt, z.B.
            ``{"data_collection": "deny", "zdr": True}`` (Ae4). Leer oder
            ``None`` -> Feld wird nicht gesendet.
        timeout_s: Read-Timeout in Sekunden (Default 90, #1451).
        client: httpx-Client per DI (Tests: ``httpx.MockTransport``). Ohne
            Angabe wird ein eigener Client erzeugt und von :meth:`close`
            geschlossen.
        url: Endpoint, Default :data:`OPENROUTER_IMAGES_URL`.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        quality: str = "low",
        aspect_ratio: str = "16:9",
        output_format: str = "png",
        provider_options: Mapping[str, object] | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
        url: str = OPENROUTER_IMAGES_URL,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("api_key darf nicht leer sein.")
        if not model.strip():
            raise ValueError("model darf nicht leer sein.")
        if timeout_s <= 0:
            raise ValueError("timeout_s muss > 0 sein.")
        self._api_key = api_key.strip()
        self._model = model
        self._quality = quality
        self._aspect_ratio = aspect_ratio
        self._output_format = output_format
        self._provider_options = dict(provider_options or {})
        self._timeout = httpx.Timeout(
            timeout_s, connect=min(DEFAULT_CONNECT_TIMEOUT_S, timeout_s)
        )
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client()
        self._url = url

    def __repr__(self) -> str:  # Schluessel nie im repr
        return (
            f"OpenRouterImageGenerator(model={self._model!r}, "
            f"quality={self._quality!r}, provider={self._provider_options!r})"
        )

    def close(self) -> None:
        """Schliesst den httpx-Client, sofern er hier erzeugt wurde."""
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------
    # Request
    # ------------------------------------------------------------------

    def build_payload(self, request: ImageRequest) -> dict[str, Any]:
        """Baut den JSON-Body (oeffentlich fuer Tests; enthaelt Bilddaten!)."""
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": request.prompt,
            "aspect_ratio": self._aspect_ratio,
            "quality": self._quality,
            "n": 1,
            "output_format": self._output_format,
        }
        if request.input_images:
            payload["input_references"] = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": (
                            f"data:{request.input_media_type};base64,"
                            + base64.b64encode(image).decode("ascii")
                        )
                    },
                }
                for image in request.input_images
            ]
        if self._provider_options:
            payload["provider"] = dict(self._provider_options)
        return payload

    def generate(self, request: ImageRequest) -> ImageResult:
        payload = self.build_payload(request)
        headers = with_user_agent(
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
        )
        start = time.monotonic()
        try:
            response = self._client.post(
                self._url, json=payload, headers=headers, timeout=self._timeout
            )
        except httpx.TimeoutException as exc:
            result = ImageResult(
                status=ImageStatus.TIMEOUT,
                duration_s=time.monotonic() - start,
                detail=type(exc).__name__,
            )
        except httpx.HTTPError as exc:
            # Verbindungs-/DNS-/Protokollfehler: sofort ERROR, kein Retry.
            result = ImageResult(
                status=ImageStatus.ERROR,
                duration_s=time.monotonic() - start,
                detail=type(exc).__name__,
            )
        else:
            result = self._classify(response, time.monotonic() - start)
        finally:
            del payload  # Data-URL der Gaestefotos nicht laenger halten
        self._log_result(result)
        return result

    # ------------------------------------------------------------------
    # Response
    # ------------------------------------------------------------------

    def _classify(self, response: httpx.Response, duration_s: float) -> ImageResult:
        """Ordnet eine Antwort einer Kategorie zu (Ae1, #1474).

        * 200 + ``data[0].b64_json`` -> OK
        * 200 ohne Bild oder mit ``error`` im Body -> ERROR
        * 402 -> CREDIT_EXHAUSTED
        * 403 + ``error.metadata.reasons`` -> REFUSED
        * alles andere (400, 401, 403 ohne reasons, 404, 413, 429, 5xx,
          524, 529) -> ERROR
        """
        status_code = response.status_code
        try:
            body: object = response.json()
        except ValueError:
            body = None
        code, message, metadata = _error_fields(body)
        detail = None if message is None else _sanitize(message, _MAX_DETAIL_CHARS)
        if detail is not None and self._api_key in detail:
            detail = "<entfernt: enthielt Schluessel>"

        def make(status: ImageStatus, **kwargs: Any) -> ImageResult:
            return ImageResult(
                status=status,
                duration_s=duration_s,
                http_status=status_code,
                error_code=code,
                detail=kwargs.pop("detail", detail),
                **kwargs,
            )

        if status_code == 402:
            return make(ImageStatus.CREDIT_EXHAUSTED)
        if status_code == 403 and _has_reasons(metadata):
            self._log_metadata(status_code, code, metadata)
            return make(ImageStatus.REFUSED)
        if status_code != 200:
            self._log_metadata(status_code, code, metadata)
            return make(ImageStatus.ERROR)

        if not isinstance(body, Mapping):
            return make(ImageStatus.ERROR, detail="200 ohne JSON-Objekt")
        if "error" in body:
            self._log_metadata(status_code, code, metadata)
            return make(ImageStatus.ERROR, detail=detail or "200 mit error-Feld")
        cost = _extract_cost(body)
        data = body.get("data")
        first = data[0] if isinstance(data, list) and data else None
        b64 = first.get("b64_json") if isinstance(first, Mapping) else None
        if not isinstance(b64, str) or not b64:
            return make(ImageStatus.ERROR, cost_usd=cost, detail="200 ohne Bild")
        try:
            image = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            return make(ImageStatus.ERROR, cost_usd=cost, detail="b64_json ungueltig")
        media_type = first.get("media_type") if isinstance(first, Mapping) else None
        return make(
            ImageStatus.OK,
            image_bytes=image,
            media_type=media_type if isinstance(media_type, str) else None,
            cost_usd=cost,
            detail=None,
        )

    # ------------------------------------------------------------------
    # Logging (nie Bodies, nie Schluessel)
    # ------------------------------------------------------------------

    @staticmethod
    def _log_metadata(status_code: int, code: str | None, metadata: object) -> None:
        logger.info(
            "Image API Fehlerdetails: http=%d code=%s metadata=%s",
            status_code,
            code,
            _safe_metadata(metadata),
        )

    def _log_result(self, result: ImageResult) -> None:
        level = logging.INFO if result.status is ImageStatus.OK else logging.WARNING
        logger.log(
            level,
            "Image API: status=%s http=%s code=%s dauer=%.1fs kosten=%s modell=%s",
            result.status.value,
            result.http_status,
            result.error_code,
            result.duration_s,
            "-" if result.cost_usd is None else f"{result.cost_usd:.4f}",
            self._model,
        )
