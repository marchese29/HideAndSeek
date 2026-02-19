"""Geographic math — pure functions, no game logic."""

from __future__ import annotations

import math

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

_EARTH_RADIUS_M = 6_371_000


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in meters between two (lat, lon) tuples."""
    lat1, lon1 = a
    lat2, lon2 = b
    lat1, lon1, lat2, lon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a_val = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a_val))


def distance(point_a: Point, point_b: Point) -> float:
    """Great-circle distance in meters between two shapely Points.

    Shapely Points store (x=lng, y=lat).
    """
    return haversine((point_a.y, point_a.x), (point_b.y, point_b.x))


def distance_to_feature(player: Point, geometry: BaseGeometry) -> float:
    """Distance in meters from a player point to the nearest point on a geometry.

    Works for Point, LineString, and Polygon geometries. Uses shapely's
    nearest_points for the geometric projection, then haversine for meters.
    """
    nearest_pt, _ = nearest_points(geometry, player)
    return haversine((nearest_pt.y, nearest_pt.x), (player.y, player.x))
