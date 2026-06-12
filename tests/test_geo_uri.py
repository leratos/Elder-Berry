"""Tests fuer geo_uri -- Geo-URI-Parsing fuer Matrix-Standorte (Phase 97, E5).

Schwerpunkt: RFC-5870-Varianten (mit Hoehe, mit ``;u=``-Parameter),
Range-Validierung, fremde Schemata sowie die Content-Extraktion mit
Legacy-``geo_uri`` und MSC3488-Fallback.
"""

from __future__ import annotations

import pytest

from elder_berry.comms.geo_uri import (
    GeoLocation,
    location_from_content,
    parse_geo_uri,
)


class TestParseGeoUri:
    def test_simple(self) -> None:
        assert parse_geo_uri("geo:51.3397,12.3731") == GeoLocation(
            lat=51.3397, lng=12.3731
        )

    def test_with_altitude(self) -> None:
        loc = parse_geo_uri("geo:51.34,12.37,113")
        assert loc == GeoLocation(lat=51.34, lng=12.37)

    def test_with_uncertainty_param(self) -> None:
        loc = parse_geo_uri("geo:51.34,12.37;u=35")
        assert loc == GeoLocation(lat=51.34, lng=12.37)

    def test_with_altitude_and_params(self) -> None:
        loc = parse_geo_uri("geo:-33.86,151.21,8;u=10;crs=wgs84")
        assert loc == GeoLocation(lat=-33.86, lng=151.21)

    def test_negative_coordinates(self) -> None:
        loc = parse_geo_uri("geo:-51.5,-0.12")
        assert loc == GeoLocation(lat=-51.5, lng=-0.12)

    def test_scheme_case_insensitive_with_whitespace(self) -> None:
        loc = parse_geo_uri("  GEO:51.34,12.37  ")
        assert loc == GeoLocation(lat=51.34, lng=12.37)

    @pytest.mark.parametrize(
        "uri",
        [
            "",
            "https://maps.google.com/?q=51.34,12.37",
            "geo:",
            "geo:51.34",
            "geo:abc,12.37",
            "geo:51.34,xyz",
            "geo:91.0,12.37",  # lat > 90
            "geo:-90.1,12.37",  # lat < -90
            "geo:51.34,180.1",  # lng > 180
            "geo:51.34,-181",  # lng < -180
        ],
    )
    def test_invalid_returns_none(self, uri: str) -> None:
        assert parse_geo_uri(uri) is None

    def test_boundary_values_accepted(self) -> None:
        assert parse_geo_uri("geo:90,-180") == GeoLocation(lat=90.0, lng=-180.0)
        assert parse_geo_uri("geo:-90,180") == GeoLocation(lat=-90.0, lng=180.0)


class TestLocationFromContent:
    def test_legacy_geo_uri(self) -> None:
        content = {
            "msgtype": "m.location",
            "body": "Location",
            "geo_uri": "geo:51.34,12.37;u=35",
        }
        assert location_from_content(content) == GeoLocation(lat=51.34, lng=12.37)

    def test_msc3488_fallback(self) -> None:
        content = {
            "msgtype": "m.location",
            "body": "Location",
            "org.matrix.msc3488.location": {
                "uri": "geo:51.34,12.37",
                "description": "Mein Standort",
            },
        }
        assert location_from_content(content) == GeoLocation(lat=51.34, lng=12.37)

    def test_legacy_wins_over_msc3488(self) -> None:
        content = {
            "geo_uri": "geo:1,2",
            "org.matrix.msc3488.location": {"uri": "geo:3,4"},
        }
        assert location_from_content(content) == GeoLocation(lat=1.0, lng=2.0)

    def test_broken_legacy_falls_back_to_msc3488(self) -> None:
        content = {
            "geo_uri": "kaputt",
            "org.matrix.msc3488.location": {"uri": "geo:3,4"},
        }
        assert location_from_content(content) == GeoLocation(lat=3.0, lng=4.0)

    @pytest.mark.parametrize(
        "content",
        [
            {},
            {"msgtype": "m.location", "body": "Location"},
            {"geo_uri": 42},
            {"org.matrix.msc3488.location": "geo:1,2"},  # kein dict
            {"org.matrix.msc3488.location": {"uri": 7}},
        ],
    )
    def test_unusable_content_returns_none(self, content: dict) -> None:
        assert location_from_content(content) is None
