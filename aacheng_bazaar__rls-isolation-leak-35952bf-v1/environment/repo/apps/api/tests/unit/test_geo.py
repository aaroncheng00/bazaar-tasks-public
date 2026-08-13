"""Unit tests for the geo proximity primitive (spike decision: bounding-box).

Reference values: SF center (37.7749, -122.4194); one degree of latitude is
~111 km; at SF's latitude one degree of longitude is ~87.7 km.
"""

import math
from typing import get_type_hints

import pytest

from bazaar_api.modules.listings.geo import (
    KM_PER_MILE,
    RadiusUnit,
    bounding_box,
    haversine_km,
    to_km,
)

SF_LAT, SF_LNG = 37.7749, -122.4194
OAK_LAT, OAK_LNG = 37.8044, -122.2712


def test_to_km_identity_for_km() -> None:
    assert to_km(25.0, RadiusUnit.KM) == 25.0


def test_to_km_converts_miles() -> None:
    assert to_km(1.0, RadiusUnit.MI) == pytest.approx(KM_PER_MILE)
    # 31 mi ≈ 49.9 km — just under the spec's 50 km cap (cap is post-conversion)
    assert to_km(31.0, RadiusUnit.MI) == pytest.approx(49.88954)
    assert to_km(31.0, RadiusUnit.MI) < 50.0 < to_km(32.0, RadiusUnit.MI)


def test_invalid_unit_is_a_type_error() -> None:
    # RadiusUnit is a StrEnum: invalid units are rejected by mypy at call
    # sites, and by FastAPI's Query enum parsing at the request boundary.
    assert get_type_hints(to_km)["unit"] is RadiusUnit


def test_bounding_box_sf_5km() -> None:
    box = bounding_box(SF_LAT, SF_LNG, 5.0)
    assert box.north - SF_LAT == pytest.approx(5.0 / 111.0)
    assert SF_LAT - box.south == pytest.approx(5.0 / 111.0)
    # longitude degree at SF latitude ≈ 87.7 km → 5 km ≈ 0.057°
    assert box.east - SF_LNG == pytest.approx(5.0 / (111.0 * math.cos(math.radians(SF_LAT))))
    assert box.west - SF_LNG == pytest.approx(-5.0 / (111.0 * math.cos(math.radians(SF_LAT))))


def test_bounding_box_contains_center_and_grows_with_radius() -> None:
    small = bounding_box(SF_LAT, SF_LNG, 5.0)
    large = bounding_box(SF_LAT, SF_LNG, 25.0)
    assert small.south < SF_LAT < small.north
    assert small.west < SF_LNG < small.east
    assert large.south < small.south
    assert large.north > small.north
    assert large.west < small.west
    assert large.east > small.east


def test_bounding_box_clamps_at_pole() -> None:
    box = bounding_box(89.9, 0.0, 50.0)
    assert box.north == 90.0
    # near the pole the longitude span saturates rather than blowing up
    assert box.west == -180.0
    assert box.east == 180.0


def test_bounding_box_clamps_at_antimeridian() -> None:
    # Documented MVP limitation: clamp, not wrap (US-only; 50 km cap)
    box = bounding_box(0.0, 179.95, 50.0)
    assert box.east == 180.0
    assert box.west < 179.95


def test_haversine_same_point_is_zero() -> None:
    assert haversine_km(SF_LAT, SF_LNG, SF_LAT, SF_LNG) == 0.0


def test_haversine_sf_to_oakland() -> None:
    assert 12.0 < haversine_km(SF_LAT, SF_LNG, OAK_LAT, OAK_LNG) < 15.0


def test_haversine_one_degree_latitude_at_equator() -> None:
    assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.19, rel=0.01)


def test_box_lat_edges_are_radius_away() -> None:
    box = bounding_box(SF_LAT, SF_LNG, 5.0)
    assert haversine_km(SF_LAT, SF_LNG, box.north, SF_LNG) == pytest.approx(5.0, rel=0.02)
    assert haversine_km(SF_LAT, SF_LNG, box.south, SF_LNG) == pytest.approx(5.0, rel=0.02)
