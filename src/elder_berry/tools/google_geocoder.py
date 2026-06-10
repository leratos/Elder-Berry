"""GoogleGeocoder -- Freitext-Ort -> Koordinaten via Google Geocoding API.

Phase 97 (E0). Liefert den Distanz-Bezugspunkt fuer die Umkreissuche
(`NearbyPlaceSearch`): der Nutzer nennt seinen Standort als Freitext
("Karl-Liebknecht-Str. 12, Leipzig"), der Geocoder macht daraus ein
``LatLng``, gegen das spaeter die Haversine-Distanz gerechnet wird.

Bewusst eigene Klasse, NICHT in ``GoogleMapsRoutePlanner`` gequetscht:
der Routenplaner nutzt die Directions-API (loest Adressen implizit auf),
die Umkreissuche braucht aber explizite Koordinaten als Sortier-Anker.
Die vorhandene ``WeatherClient.geocode`` ist KEINE Alternative -- sie
geht ueber Open-Meteo und ist nur stadt-granular; §0.1 verlangt
Strassen-Granularitaet.

Fehler-Semantik (Konzept §3 / R2-C3, "Config-Probleme nicht verstecken"):
- ``ZERO_RESULTS`` -> ``None`` (echtes "Ort nicht gefunden").
- ``REQUEST_DENIED`` / ``OVER_QUERY_LIMIT`` / HTTP 403 / 429 ->
  ``GeocoderConfigError`` (Auth/Quota -- NICHT als ``None`` tarnen, sonst
  meldet der Handler faelschlich "Ort nicht gefunden" statt "Dienst kaputt").
- jeder andere nicht-``OK``-Status -> ``GeocoderConfigError`` (z.B.
  ``INVALID_REQUEST``/``UNKNOWN_ERROR``), damit nichts still verschluckt wird.

Synchron via ``httpx.Client`` -- gleiches Muster wie
``GoogleMapsRoutePlanner`` (passt zum CommandHandler-Pattern).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Status-Werte der Geocoding-API, die auf ein Auth-/Quota-/Config-Problem
# hindeuten -> sichtbar machen, nicht als "nicht gefunden" tarnen.
_CONFIG_ERROR_STATUSES = frozenset({"REQUEST_DENIED", "OVER_QUERY_LIMIT"})
# HTTP-Codes mit derselben Bedeutung (Key gesperrt / Rate-Limit).
_CONFIG_ERROR_HTTP = frozenset({403, 429})


@dataclass(frozen=True)
class LatLng:
    """Geografischer Punkt (WGS84), Distanz-Bezugspunkt der Umkreissuche."""

    lat: float
    lng: float


class GeocoderConfigError(Exception):
    """Auth-/Quota-/Config-Fehler der Geocoding-API.

    Bewusst getrennt vom ``None``-Pfad (= ZERO_RESULTS): der Handler
    soll "Geocoding ist falsch konfiguriert / Quota erschoepft" anders
    beantworten als "diesen Ort gibt es nicht".
    """


class GoogleGeocoder:
    """Loest Freitext-Standorte in Koordinaten auf (Google Geocoding API)."""

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key darf nicht leer sein")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def geocode(self, location_text: str) -> LatLng | None:
        """Freitext-Ort -> ``LatLng`` oder ``None`` (ZERO_RESULTS).

        Args:
            location_text: Standort als Freitext (Strasse + Stadt o.ae.).

        Returns:
            ``LatLng`` beim ersten Treffer, ``None`` wenn die API
            ``ZERO_RESULTS`` liefert (Ort existiert nicht).

        Raises:
            ValueError: ``location_text`` ist leer.
            GeocoderConfigError: Auth/Quota/Config (REQUEST_DENIED,
                OVER_QUERY_LIMIT, HTTP 403/429) oder anderer nicht-``OK``-
                Status -- damit Config-Probleme sichtbar bleiben.
        """
        if not location_text.strip():
            raise ValueError("location_text darf nicht leer sein")

        params = {
            "address": location_text,
            "key": self._api_key,
            "language": "de",
        }
        resp = self._client.get(GEOCODE_URL, params=params)

        if resp.status_code in _CONFIG_ERROR_HTTP:
            logger.error(
                "Geocoding API HTTP %s (Key gesperrt oder Rate-Limit)",
                resp.status_code,
            )
            raise GeocoderConfigError(
                f"Geocoding API: HTTP {resp.status_code}",
            )
        resp.raise_for_status()

        data = resp.json()
        status = data.get("status", "UNKNOWN")

        if status == "OK":
            return self._first_latlng(data)
        if status == "ZERO_RESULTS":
            return None

        # Alles andere (REQUEST_DENIED, OVER_QUERY_LIMIT, INVALID_REQUEST,
        # UNKNOWN_ERROR, ...) ist KEIN "nicht gefunden" -> sichtbar machen.
        if status in _CONFIG_ERROR_STATUSES:
            logger.error("Geocoding API Status %s (Auth/Quota)", status)
        else:
            logger.error("Geocoding API unerwarteter Status %s", status)
        raise GeocoderConfigError(f"Geocoding API: {status}")

    def close(self) -> None:
        """HTTP-Client schliessen, falls wir ihn besitzen."""
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    @staticmethod
    def _first_latlng(data: dict[str, Any]) -> LatLng | None:
        """Zieht ``results[0].geometry.location`` als ``LatLng``.

        Defensiv: ein ``OK``-Status ohne brauchbare ``location`` (sollte
        nicht vorkommen) -> ``None`` statt KeyError/Crash.
        """
        results = data.get("results") or []
        if not results:
            logger.warning("Geocoding API: status OK aber leere results")
            return None
        location = (results[0].get("geometry") or {}).get("location") or {}
        lat = location.get("lat")
        lng = location.get("lng")
        if lat is None or lng is None:
            logger.warning("Geocoding API: results[0] ohne lat/lng")
            return None
        return LatLng(lat=float(lat), lng=float(lng))
