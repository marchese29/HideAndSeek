"""Distance convention utilities — metric/imperial conversion and defaults.

Convention values are stored and transmitted in the map's convention units
(meters for metric, miles for imperial). Internal geo math always uses meters.
Conversion happens at the boundary in logic.py.
"""

from __future__ import annotations

from hideandseek.models.types import DistanceConvention, MapSize

_MILES_PER_METER = 1609.344


def to_meters(value: float, convention: DistanceConvention) -> float:
    """Convert a convention-unit value to meters."""
    if convention == DistanceConvention.imperial:
        return value * _MILES_PER_METER
    return value


def from_meters(meters: float, convention: DistanceConvention) -> float:
    """Convert meters to convention units."""
    if convention == DistanceConvention.imperial:
        return meters / _MILES_PER_METER
    return meters


def format_distance_label(value: float, convention: DistanceConvention) -> str:
    """Format a distance value for human-readable push notification labels.

    Metric: "500 m", "1 km", "5 km" (switches at >= 1000).
    Imperial: "0.25 mi", "1 mi", "10 mi".
    """
    if convention == DistanceConvention.imperial:
        return f'{value:g} mi'
    if value >= 1000:
        return f'{value / 1000:g} km'
    return f'{value:g} m'


# ── Default inventory constants ──────────────────────────────────────────────
#
# Keyed by (convention, size). The `special` size has no code-level defaults —
# maps with size=special must provide a default_inventory override.

_RADAR_METRIC = [500, 1_000, 2_000, 5_000, 10_000, 15_000, 40_000, 80_000, 160_000]
_RADAR_IMPERIAL = [0.25, 0.5, 1, 2, 5, 10, 25, 50, 100]

_THERMO_METRIC = {
    MapSize.small: [1_000, 5_000, 10_000],
    MapSize.medium: [1_000, 5_000, 10_000, 15_000],
    MapSize.large: [1_000, 5_000, 10_000, 15_000, 75_000],
}

_THERMO_IMPERIAL = {
    MapSize.small: [0.5, 1, 5],
    MapSize.medium: [0.5, 1, 5, 10],
    MapSize.large: [0.5, 1, 5, 10, 25],
}


def get_default_inventory(convention: DistanceConvention, size: MapSize) -> dict:
    """Return the default inventory template for a convention and map size.

    Raises ValueError for special-size maps (they must provide an override).
    """
    if size == MapSize.special:
        raise ValueError('special-size maps must provide a default_inventory override.')

    if convention == DistanceConvention.imperial:
        radars = _RADAR_IMPERIAL
        thermos = _THERMO_IMPERIAL[size]
    else:
        radars = _RADAR_METRIC
        thermos = _THERMO_METRIC[size]

    return {
        'radars': [{'distance': d} for d in radars],
        'thermometers': [{'distance': d} for d in thermos],
    }
