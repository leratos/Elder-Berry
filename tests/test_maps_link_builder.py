"""Tests fuer MapsLinkBuilder -- Google-Maps-Deep-Link-Format.

Phase 92 (E1). Pruefen URL-Format, Encoding und Edge-Cases.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from elder_berry.tools.maps_link_builder import MapsLinkBuilder, Stop


@pytest.fixture
def builder() -> MapsLinkBuilder:
    return MapsLinkBuilder()


def _params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


class TestBuildMultiStopLink:
    def test_basic_link(self, builder: MapsLinkBuilder) -> None:
        url = builder.build_multi_stop_link(
            origin=Stop("Musterstr. 5, Berlin"),
            waypoints=[Stop("Hauptstr. 12, Leipzig")],
            destination=Stop("Hauptbahnhof Leipzig"),
        )
        assert url.startswith("https://www.google.com/maps/dir/?api=1")
        params = _params(url)
        assert params["origin"] == ["Musterstr. 5, Berlin"]
        assert params["destination"] == ["Hauptbahnhof Leipzig"]
        assert params["waypoints"] == ["Hauptstr. 12, Leipzig"]
        assert params["travelmode"] == ["driving"]

    def test_umlauts_are_url_encoded(self, builder: MapsLinkBuilder) -> None:
        url = builder.build_multi_stop_link(
            origin=Stop("Mühlenstraße 4"),
            waypoints=[],
            destination=Stop("Görlitzer Park"),
        )
        # Erwartung: M%C3%BChlenstra%C3%9Fe und G%C3%B6rlitzer
        assert "M%C3%BChlenstra%C3%9Fe" in url
        assert "G%C3%B6rlitzer" in url

    def test_pipe_separator_unencoded(self, builder: MapsLinkBuilder) -> None:
        """Pipes zwischen Waypoints bleiben literal -- sonst rendert
        Google die Route nicht."""
        url = builder.build_multi_stop_link(
            origin=Stop("A-Str. 1"),
            waypoints=[Stop("B-Str. 2"), Stop("C-Str. 3")],
            destination=Stop("Z-Str. 9"),
        )
        # %7C waere encoded; das wollen wir NICHT.
        assert "%7C" not in url
        # Aber die Pipes muessen drin sein
        assert "waypoints=" in url
        wp_segment = next(p for p in url.split("&") if p.startswith("waypoints="))
        assert wp_segment.count("|") == 1  # 2 Waypoints -> 1 Pipe

    def test_no_waypoints_omits_param(self, builder: MapsLinkBuilder) -> None:
        url = builder.build_multi_stop_link(
            origin=Stop("A"),
            waypoints=[],
            destination=Stop("B"),
        )
        assert "waypoints=" not in url

    def test_travelmode_driving_default(self, builder: MapsLinkBuilder) -> None:
        url = builder.build_multi_stop_link(
            origin=Stop("A"),
            waypoints=[],
            destination=Stop("B"),
        )
        assert "travelmode=driving" in url

    @pytest.mark.parametrize(
        "mode",
        ["driving", "walking", "bicycling", "transit"],
    )
    def test_travelmode_other_valid(
        self,
        builder: MapsLinkBuilder,
        mode: str,
    ) -> None:
        url = builder.build_multi_stop_link(
            origin=Stop("A"),
            waypoints=[],
            destination=Stop("B"),
            travel_mode=mode,
        )
        assert f"travelmode={mode}" in url

    def test_travelmode_invalid_raises(self, builder: MapsLinkBuilder) -> None:
        with pytest.raises(ValueError, match="travel_mode"):
            builder.build_multi_stop_link(
                origin=Stop("A"),
                waypoints=[],
                destination=Stop("B"),
                travel_mode="flying",
            )

    def test_special_chars_encoded(self, builder: MapsLinkBuilder) -> None:
        url = builder.build_multi_stop_link(
            origin=Stop("Foo & Bar, Berlin"),
            waypoints=[],
            destination=Stop("Baz / Qux, Hamburg"),
        )
        # & und / muessen in den Parameter-Werten encoded sein
        params = _params(url)
        assert params["origin"] == ["Foo & Bar, Berlin"]
        assert params["destination"] == ["Baz / Qux, Hamburg"]

    def test_lat_lng_input(self, builder: MapsLinkBuilder) -> None:
        url = builder.build_multi_stop_link(
            origin=Stop("52.5,13.4"),
            waypoints=[],
            destination=Stop("51.3,12.4"),
        )
        params = _params(url)
        assert params["origin"] == ["52.5,13.4"]
        assert params["destination"] == ["51.3,12.4"]

    def test_empty_origin_raises(self, builder: MapsLinkBuilder) -> None:
        with pytest.raises(ValueError, match="origin"):
            builder.build_multi_stop_link(
                origin=Stop(""),
                waypoints=[],
                destination=Stop("B"),
            )

    def test_empty_destination_raises(self, builder: MapsLinkBuilder) -> None:
        with pytest.raises(ValueError, match="destination"):
            builder.build_multi_stop_link(
                origin=Stop("A"),
                waypoints=[],
                destination=Stop(""),
            )

    def test_whitespace_origin_raises(self, builder: MapsLinkBuilder) -> None:
        with pytest.raises(ValueError, match="origin"):
            builder.build_multi_stop_link(
                origin=Stop("   "),
                waypoints=[],
                destination=Stop("B"),
            )

    def test_empty_waypoints_are_filtered(
        self,
        builder: MapsLinkBuilder,
    ) -> None:
        """Waypoint mit leerer Adresse wird stillschweigend uebersprungen.

        Begruendung: der Sonnet-Parser kann gelegentlich einen leeren
        ``value`` liefern, wenn der User unklar war. Lieber den Link
        bauen als crashen -- der User sieht die Route und merkt es."""
        url = builder.build_multi_stop_link(
            origin=Stop("A"),
            waypoints=[Stop(""), Stop("B"), Stop("   ")],
            destination=Stop("Z"),
        )
        params = _params(url)
        assert params["waypoints"] == ["B"]

    def test_all_waypoints_empty_omits_param(
        self,
        builder: MapsLinkBuilder,
    ) -> None:
        url = builder.build_multi_stop_link(
            origin=Stop("A"),
            waypoints=[Stop(""), Stop("   ")],
            destination=Stop("Z"),
        )
        assert "waypoints=" not in url


class TestStop:
    def test_default_label(self) -> None:
        s = Stop("A-Str. 1")
        assert s.label == ""

    def test_frozen(self) -> None:
        s = Stop("A")
        with pytest.raises(AttributeError):
            s.address = "B"  # type: ignore[misc]
