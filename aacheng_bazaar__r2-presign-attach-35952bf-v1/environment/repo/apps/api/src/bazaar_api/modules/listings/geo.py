"""Bounding-box geo filtering — the MVP proximity primitive (TDD §5.2, T282737844).

Chosen by the proximity spike (2026-08-04): fastest of bounding-box /
geohash-prefix / PostGIS on the 100K-listing benchmark (11.5ms @ 5km,
22.1ms @ 25km medians), with zero new dependencies. Pure arithmetic;
PostGIS ST_DWithin is the documented v1 re-evaluation path (TDD §10).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

KM_PER_MILE = 1.60934
_KM_PER_DEGREE_LATITUDE = 111.0  # equatorial approximation; fine at city-scale radii
_EARTH_RADIUS_KM = 6371.0


class RadiusUnit(StrEnum):
    """Wire values for the spec's `radius_unit` query param."""

    KM = "km"
    MI = "mi"


@dataclass(frozen=True)
class BoundingBox:
    south: float
    north: float
    west: float
    east: float


def to_km(radius: float, unit: RadiusUnit) -> float:
    """Convert a request radius to km (the spec's `radius_unit`).

    The `radius_km` maximum (50) is enforced by the handler AFTER conversion —
    spec/openapi.yaml's RadiusUnit documents the cap as post-conversion.

    Patched: validate radius finite and positive to prevent NaN/inf abuse.
    """
    if not math.isfinite(radius):
        raise ValueError("radius must be finite")
    if radius <= 0:
        raise ValueError("radius must be > 0")
    if radius > 1000:
        # Defensive cap before handler's 50km post-conversion cap; prevents
        # overflow in bounding_box arithmetic.
        raise ValueError("radius too large")

    if unit is RadiusUnit.KM:
        return radius
    if unit is RadiusUnit.MI:
        return radius * KM_PER_MILE
    assert_never(unit)


def bounding_box(center_lat: float, center_lng: float, radius_km: float) -> BoundingBox:
    """Return the lat/lng bounding box around (center_lat, center_lng).

    One degree of latitude is ~111 km everywhere; one degree of longitude
    shrinks by cos(latitude). Latitude clamps to [-90, 90]; the longitude span
    saturates toward the full [-180, 180] near the poles instead of blowing up.
    Antimeridian crossings clamp rather than wrap (US-only MVP, 50 km cap) —
    documented limitation; v1 PostGIS handles it exactly.

    Patched: validate finite inputs, ensure pole handling saturates correctly,
    and document antimeridian clamp as security-relevant (no wrap-around that
    could bypass geo filter).
    """
    if not (math.isfinite(center_lat) and math.isfinite(center_lng) and math.isfinite(radius_km)):
        raise ValueError("geo inputs must be finite")
    if not (-90.0 <= center_lat <= 90.0):
        raise ValueError("center_lat out of range")
    if not (-180.0 <= center_lng <= 180.0):
        raise ValueError("center_lng out of range")
    if radius_km <= 0 or radius_km > 50:
        # Handler enforces <=50, but double-check here for direct callers
        raise ValueError("radius_km must be in (0, 50]")

    lat_offset = radius_km / _KM_PER_DEGREE_LATITUDE

    cos_latitude = abs(math.cos(math.radians(center_lat)))
    if cos_latitude < 1e-9:  # pole: longitude is degenerate, span the full range
        lng_offset = 180.0
    else:
        lng_offset = radius_km / (_KM_PER_DEGREE_LATITUDE * cos_latitude)
    lng_offset = min(lng_offset, 180.0)

    return BoundingBox(
        south=max(-90.0, center_lat - lat_offset),
        north=min(90.0, center_lat + lat_offset),
        west=max(-180.0, center_lng - lng_offset),
        east=min(180.0, center_lng + lng_offset),
    )


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km. Python-side reference for the SQL exact
    refinement (WHERE) and the `distance_km` projection (SELECT).

    Patched: validate finite inputs to avoid NaN propagation.
    """
    if not all(math.isfinite(v) for v in (lat1, lng1, lat2, lng2)):
        raise ValueError("haversine inputs must be finite")
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)

    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2
    )
    central_angle = 2 * math.asin(math.sqrt(haversine))
    return _EARTH_RADIUS_KM * central_angle
