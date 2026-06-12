"""Geo-URI-Parsing fuer Matrix-Standort-Nachrichten (Phase 97, E5).

Element/Matrix sendet die Ortssendefunktion als ``m.location``-Event mit
einer Geo-URI nach RFC 5870 (``geo:lat,lng[,alt][;u=unsicherheit]``) im
``geo_uri``-Feld; neuere Clients legen zusaetzlich MSC3488
(``org.matrix.msc3488.location`` mit ``uri``) bei.

Bewusst nio-frei: matrix-nio kennt keine eigene Location-Eventklasse
(``m.location`` landet als ``RoomMessageUnknown``), und ohne nio-Import
laeuft dieser Parser auch in Umgebungen ohne Matrix-Install in den Tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_GEO_SCHEME = "geo:"

# MSC3488: extensible-location-Block (Element legt das zusaetzlich zum
# Legacy-geo_uri bei). Unstable-Prefix zuerst (heute im Feld), "m.location"
# als stabiler Key fuer den Tag der MSC-Stabilisierung (Codex PR #305).
_LOCATION_BLOCK_KEYS = ("org.matrix.msc3488.location", "m.location")


@dataclass(frozen=True)
class GeoLocation:
    """Geteilter Standort (WGS84) aus einer Matrix-Location-Nachricht."""

    lat: float
    lng: float


def parse_geo_uri(uri: str) -> GeoLocation | None:
    """Parst eine Geo-URI (RFC 5870) zu ``GeoLocation``.

    Akzeptiert ``geo:lat,lng``, optional mit Hoehe (``,alt``) und
    Parametern (``;u=35``); beides wird ignoriert. Liefert ``None`` bei
    fremdem Schema, nicht-numerischen Koordinaten oder Werten ausserhalb
    von +-90/+-180 -- der Aufrufer behandelt das wie "kein Standort".
    """
    if not uri or not uri.strip().lower().startswith(_GEO_SCHEME):
        return None
    payload = uri.strip()[len(_GEO_SCHEME) :]
    # Parameter (";u=35;crs=wgs84") abtrennen, nur die Koordinaten zaehlen.
    coords_part = payload.split(";", 1)[0]
    parts = coords_part.split(",")
    if len(parts) < 2:
        return None
    try:
        lat = float(parts[0])
        lng = float(parts[1])
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return None
    return GeoLocation(lat=lat, lng=lng)


def location_from_content(content: dict[str, Any]) -> GeoLocation | None:
    """Zieht den Standort aus dem Content eines ``m.location``-Events.

    Reihenfolge (Codex PR #305): erst der extensible MSC3488-Block (er ist
    laut MSC die kanonische Repraesentation; ``geo_uri`` ist das
    Abwaertskompat-Feld), dann Legacy-``geo_uri`` als Fallback fuer
    Clients, die nur das alte Format senden.
    """
    for key in _LOCATION_BLOCK_KEYS:
        block = content.get(key)
        if isinstance(block, dict):
            uri = block.get("uri")
            if isinstance(uri, str):
                location = parse_geo_uri(uri)
                if location is not None:
                    return location

    geo_uri = content.get("geo_uri")
    if isinstance(geo_uri, str):
        return parse_geo_uri(geo_uri)
    return None
