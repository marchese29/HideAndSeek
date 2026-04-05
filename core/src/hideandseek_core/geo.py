"""Geographic math — pure functions, no game logic."""

from __future__ import annotations

from pyproj import Geod
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

_geod = Geod(ellps='WGS84')


def distance(point_a: Point, point_b: Point) -> float:
    """Great-circle distance in meters between two shapely Points.

    Shapely Points store (x=lng, y=lat).
    """
    _, _, dist = _geod.inv(point_a.x, point_a.y, point_b.x, point_b.y)
    return dist


def distance_to_feature(player: Point, geometry: BaseGeometry) -> float:
    """Distance in meters from a player point to the nearest point on a geometry.

    Works for Point, LineString, and Polygon geometries. Uses shapely's
    nearest_points for the geometric projection, then geodesic distance for meters.
    """
    nearest_pt, _ = nearest_points(geometry, player)
    return distance(nearest_pt, player)
