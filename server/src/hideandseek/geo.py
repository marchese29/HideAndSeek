"""Geographic math — pure functions, no game logic."""

from __future__ import annotations

import math

_EARTH_RADIUS_M = 6_371_000


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters between two WGS-84 points."""
    lat1, lon1, lat2, lon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def geojson_distance(point_a: dict, point_b: dict) -> float:
    """Great-circle distance in meters between two GeoJSON Point dicts."""
    lon_a, lat_a = point_a['coordinates'][0], point_a['coordinates'][1]
    lon_b, lat_b = point_b['coordinates'][0], point_b['coordinates'][1]
    return haversine(lat_a, lon_a, lat_b, lon_b)
