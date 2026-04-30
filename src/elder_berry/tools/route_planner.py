"""RoutePlanner – Google Maps Directions API für Fahrtdauer + Link-Generierung.

Berechnet Fahrtdauer zwischen zwei Adressen, leitet Abfahrtszeit rückwärts
ab und generiert klickbare Google-Maps-Links.

Verwendung:
    planner = RoutePlanner(api_key="AIza...")
    result = planner.get_route("Musterstr. 5, Berlin", "Hauptstr. 12, Berlin")
    departure = planner.calculate_departure(arrival, result.duration_seconds)
    link = planner.generate_maps_link("Musterstr. 5", "Hauptstr. 12")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
_MAPS_LINK_BASE = "https://www.google.com/maps/dir/"


class RouteError(Exception):
    """Fehler bei der Routenberechnung (API-Status != OK)."""


@dataclass(frozen=True)
class RouteResult:
    """Ergebnis einer Routenabfrage."""

    duration_seconds: int
    """Fahrtdauer in Sekunden."""
    duration_text: str
    """Fahrtdauer als lesbarer Text (z.B. '1 Stunde 20 Minuten')."""
    distance_text: str
    """Entfernung als lesbarer Text (z.B. '85,3 km')."""
    summary: str
    """Routenname (z.B. 'A10')."""
    start_address: str
    """Von Google aufgelöste Startadresse."""
    end_address: str
    """Von Google aufgelöste Zieladresse."""


class RoutePlanner:
    """Google Maps Directions API – Fahrtdauer + Link-Generierung.

    Synchrone Implementierung (httpx.Client), passend zum
    CommandHandler-Pattern.
    """

    def __init__(
        self,
        api_key: str,
        default_buffer_minutes: int = 15,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._buffer = default_buffer_minutes
        self._client = httpx.Client(timeout=timeout)

    @property
    def buffer_minutes(self) -> int:
        """Puffer-Minuten für Abfahrtszeitberechnung."""
        return self._buffer

    def get_route(
        self,
        origin: str,
        destination: str,
        departure_time: datetime | None = None,
    ) -> RouteResult:
        """Fragt die Directions API ab.

        Args:
            origin: Startadresse (Freitext oder Koordinaten).
            destination: Zieladresse.
            departure_time: Abfahrtszeit für Verkehrsprognose.
                Nur verwendet wenn in der Zukunft.

        Returns:
            RouteResult mit Fahrtdauer, Entfernung, Routenname.

        Raises:
            RouteError: API-Status != OK oder keine Route gefunden.
            httpx.RequestError: Netzwerkfehler.
        """
        params: dict[str, str] = {
            "origin": origin,
            "destination": destination,
            "key": self._api_key,
            "language": "de",
            "units": "metric",
        }
        if departure_time and departure_time > datetime.now():
            params["departure_time"] = str(int(departure_time.timestamp()))
            params["traffic_model"] = "best_guess"

        resp = self._client.get(_DIRECTIONS_URL, params=params)
        resp.raise_for_status()
        return self._parse_response(resp.json())

    def calculate_departure(
        self,
        arrival_time: datetime,
        duration_seconds: int,
    ) -> datetime:
        """Abfahrtszeit = Ankunft - Fahrtdauer - Puffer."""
        return (
            arrival_time
            - timedelta(seconds=duration_seconds)
            - timedelta(minutes=self._buffer)
        )

    def generate_maps_link(self, origin: str, destination: str) -> str:
        """Google Maps Deep-Link (öffnet App auf Android/Desktop)."""
        params = urlencode(
            {
                "api": "1",
                "origin": origin,
                "destination": destination,
                "travelmode": "driving",
            }
        )
        return f"{_MAPS_LINK_BASE}?{params}"

    def _parse_response(self, data: dict) -> RouteResult:
        """Parst die Directions API Response."""
        status = data.get("status", "UNKNOWN")
        if status != "OK":
            raise RouteError(f"Directions API: {status}")

        routes = data.get("routes", [])
        if not routes:
            raise RouteError("Directions API: Keine Route gefunden")

        leg = routes[0]["legs"][0]
        # duration_in_traffic wenn verfügbar (genauer), sonst duration
        duration = leg.get("duration_in_traffic", leg["duration"])

        return RouteResult(
            duration_seconds=duration["value"],
            duration_text=duration["text"],
            distance_text=leg["distance"]["text"],
            summary=routes[0].get("summary", ""),
            start_address=leg.get("start_address", ""),
            end_address=leg.get("end_address", ""),
        )

    def close(self) -> None:
        """HTTP-Client sauber schließen."""
        self._client.close()
