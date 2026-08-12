"""Security & edge cases for geo primitive — K3 patch additions."""

import math

import pytest

from bazaar_api.modules.listings.geo import RadiusUnit, bounding_box, haversine_km, to_km


def test_to_km_rejects_nan_inf() -> None:
    with pytest.raises(ValueError):
        to_km(float("nan"), RadiusUnit.KM)
    with pytest.raises(ValueError):
        to_km(float("inf"), RadiusUnit.KM)
    with pytest.raises(ValueError):
        to_km(-5.0, RadiusUnit.KM)


def test_to_km_rejects_too_large() -> None:
    with pytest.raises(ValueError):
        to_km(2000.0, RadiusUnit.KM)


def test_bounding_box_rejects_nan() -> None:
    with pytest.raises(ValueError):
        bounding_box(float("nan"), 0.0, 5.0)
    with pytest.raises(ValueError):
        bounding_box(0.0, float("inf"), 5.0)
    with pytest.raises(ValueError):
        bounding_box(0.0, 0.0, float("nan"))


def test_bounding_box_rejects_out_of_range_lat_lng() -> None:
    with pytest.raises(ValueError):
        bounding_box(100.0, 0.0, 5.0)
    with pytest.raises(ValueError):
        bounding_box(0.0, 200.0, 5.0)


def test_bounding_box_rejects_radius_over_50() -> None:
    with pytest.raises(ValueError):
        bounding_box(0.0, 0.0, 51.0)
    with pytest.raises(ValueError):
        bounding_box(0.0, 0.0, 0.0)


def test_bounding_box_pole_saturation() -> None:
    box = bounding_box(89.9, 0.0, 50.0)
    assert box.north == 90.0
    assert box.west == -180.0
    assert box.east == 180.0
    # south should be within bounds
    assert -90.0 <= box.south <= 90.0


def test_bounding_box_antimeridian_clamp_not_wrap() -> None:
    """US-only MVP limitation: clamp not wrap — ensure no bypass."""
    box = bounding_box(0.0, 179.95, 50.0)
    assert box.east == 180.0
    # west must be less than center, not wrapped to negative high
    assert box.west < 179.95
    assert box.west >= -180.0


def test_radius_unit_post_conversion_cap() -> None:
    # Spec says cap applies post-conversion
    km_31_mi = to_km(31.0, RadiusUnit.MI)
    assert km_31_mi < 50.0
    km_32_mi = to_km(32.0, RadiusUnit.MI)
    assert km_32_mi > 50.0
    # Handler should enforce <=50 after conversion, but to_km still allows 32mi
    # (49.9 vs 51.5). The handler's responsibility is documented.
    # Here we ensure conversion is correct and handler would reject 32mi.
    # Simulate handler check:
    assert km_31_mi <= 50.0
    assert km_32_mi > 50.0


def test_haversine_rejects_non_finite() -> None:
    with pytest.raises(ValueError):
        haversine_km(float("nan"), 0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        haversine_km(0.0, 0.0, float("inf"), 0.0)


def test_haversine_finite_and_zero() -> None:
    assert haversine_km(0.0, 0.0, 0.0, 0.0) == 0.0
    d = haversine_km(37.7749, -122.4194, 37.8044, -122.2712)
    assert 12.0 < d < 15.0
    assert math.isfinite(d)
