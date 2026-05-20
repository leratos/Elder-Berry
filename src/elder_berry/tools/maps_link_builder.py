"""MapsLinkBuilder -- Google-Maps-Deep-Links fuer Multi-Stop-Routen.

Phase 92 (E1): Provider-unabhaengige Util. Bewusst von
``GoogleMapsRoutePlanner`` getrennt, damit der Link auch funktioniert,
wenn die Route aus einer anderen Quelle kommt (Cache, persistierte
Route, externe Anfrage).

Format:
    https://www.google.com/maps/dir/?api=1
      &origin=<encoded>
      &destination=<encoded>
      &waypoints=<encoded>|<encoded>|...
      &travelmode=driving

Detail: ``quote_plus`` fuer origin / destination / einzelne Waypoints.
Die Pipes (|) zwischen Waypoints duerfen NICHT URL-encoded werden --
Google erwartet sie literal, sonst funktioniert der Link nicht.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus


_BASE = "https://www.google.com/maps/dir/?api=1"
_VALID_TRAVEL_MODES = frozenset({"driving", "walking", "bicycling", "transit"})


@dataclass(frozen=True)
class Stop:
    """Ein Stop in der Route.

    Identisch zur ``Stop``-Dataclass im ``GoogleMapsRoutePlanner``, aber
    hier dupliziert, damit der LinkBuilder keinen Routing-Provider-Import
    braucht (provider-unabhaengig laut Konzept §MapsLinkBuilder).
    """

    address: str
    """Aufloesbare Adresse oder ``"lat,lng"``-Koordinaten-String."""

    label: str = ""
    """Anzeigename, derzeit nicht im Link verwendet -- Google nimmt nur
    den ``address``-String fuer das URL-Encoding."""


class MapsLinkBuilder:
    """Baut Google-Maps-Deep-Links fuer Android-Auto-Anzeige."""

    def build_multi_stop_link(
        self,
        origin: Stop,
        waypoints: list[Stop],
        destination: Stop,
        travel_mode: str = "driving",
    ) -> str:
        """Baut den Deep-Link aus Origin + Waypoints + Destination.

        Args:
            origin: Startpunkt. Pflicht, ``address`` darf nicht leer sein.
            waypoints: Zwischenstops in der gewuenschten Reihenfolge.
                Leere Liste -> kein ``waypoints``-Parameter im URL.
            destination: Ziel. Pflicht, ``address`` darf nicht leer sein.
            travel_mode: ``driving`` (Default), ``walking``, ``bicycling``,
                ``transit``. Bei unbekanntem Wert: ValueError.

        Returns:
            Vollstaendige Google-Maps-URL.

        Raises:
            ValueError: leerer Origin/Destination oder unbekannter
                ``travel_mode``.
        """
        if not origin.address.strip():
            raise ValueError("origin.address darf nicht leer sein")
        if not destination.address.strip():
            raise ValueError("destination.address darf nicht leer sein")
        if travel_mode not in _VALID_TRAVEL_MODES:
            raise ValueError(
                f"Unbekannter travel_mode '{travel_mode}'. "
                f"Erlaubt: {sorted(_VALID_TRAVEL_MODES)}",
            )
        # Reihenfolge: origin, destination, waypoints, travelmode --
        # Google ignoriert Reihenfolge, aber lesbar bleibt's so.
        params = [
            f"origin={quote_plus(origin.address)}",
            f"destination={quote_plus(destination.address)}",
        ]
        if waypoints:
            non_empty = [wp for wp in waypoints if wp.address.strip()]
            if non_empty:
                encoded = [quote_plus(wp.address) for wp in non_empty]
                # Pipes BLEIBEN literal -- nicht durch quote_plus jagen.
                params.append("waypoints=" + "|".join(encoded))
        params.append(f"travelmode={travel_mode}")
        return _BASE + "&" + "&".join(params)
