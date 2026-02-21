"""Exclusion geometry — computes regions of the game map where the hider cannot be.

Each question type produces an exclusion zone (a geometry within the game map polygon).
The client subtracts these zones from the visible map to narrow down the hider's location.

All functions accept and return WGS84 (EPSG:4326) geometries. Metric operations
(buffering, Voronoi) are performed in a local azimuthal equidistant projection centered
on the geometry's centroid, then projected back to WGS84.
"""

from __future__ import annotations

from collections.abc import Sequence

from pyproj import Transformer
from shapely import MultiPoint, Point, voronoi_polygons
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union


def _buffer(geom: BaseGeometry, radius_m: float) -> BaseGeometry:
    """Buffer a WGS84 geometry by a metric radius and return the result in WGS84.

    Projects to a local azimuthal equidistant (AEQD) plane centered on the geometry's
    centroid, applies the buffer there (180 points per circle for ~2-degree resolution),
    and projects back. A per-geometry projection is used for accuracy; if this becomes
    a bottleneck, a single projection centered on the game map could be shared.
    """
    projection = (
        f'+proj=aeqd +lat_0={geom.centroid.y} +lon_0={geom.centroid.x} +datum=WGS84 +units=m'
    )
    to_local = Transformer.from_crs('EPSG:4326', projection, always_xy=True).transform
    to_wgs = Transformer.from_crs(projection, 'EPSG:4326', always_xy=True).transform
    return transform(to_wgs, transform(to_local, geom).buffer(radius_m, quad_segs=45))


def exclude_radar(
    game_map: BaseGeometry, location: Point, radius_m: float, *, hit: bool
) -> BaseGeometry:
    """Exclusion zone for a radar question.

    - MISS (hit=False): the hider is NOT within radius_m of the seeker. Exclude the
      circle around the seeker (hider can't be there).
    - HIT (hit=True): the hider IS within radius_m. Exclude everything outside the
      circle (hider must be inside).
    """
    circle = _buffer(location, radius_m)

    if not hit:
        return game_map.intersection(circle)
    else:
        return game_map.difference(circle)


def exclude_measuring(
    game_map: BaseGeometry,
    distance_m: float,
    pois: Sequence[BaseGeometry],
    *,
    hider_closer: bool,
) -> BaseGeometry:
    """Exclusion zone for a measuring question.

    Buffers each POI by the seeker's measured distance and unions them into a
    "nearby" zone. The seeker is exactly ``distance_m`` from the POI(s).

    - hider_closer=True: the hider is closer to the POI than the seeker.
      The hider must be inside the buffer, so exclude everything outside it.
    - hider_closer=False: the hider is farther from the POI than the seeker.
      The hider must be outside the buffer, so exclude the buffer itself.
    """
    combined = unary_union([_buffer(poi, distance_m) for poi in pois])
    if hider_closer:
        return game_map.difference(combined)
    else:
        return game_map.intersection(combined)


def exclude_matching(
    game_map: BaseGeometry,
    seeker_poi: BaseGeometry,
    other_pois: Sequence[BaseGeometry],
    *,
    same: bool,
) -> BaseGeometry:
    """Exclusion zone for a matching question using Voronoi partitioning.

    Computes Voronoi cells for the seeker's POI and all other POIs of the same category.
    Each cell contains the region of space closer to that POI than any other.

    - SAME (same=True): the hider matched the seeker's POI. Exclude everything outside
      the seeker's Voronoi cell (hider must be in the same cell).
    - DIFFERENT (same=False): the hider matched a different POI. Exclude the seeker's
      Voronoi cell (hider must be in a different cell).
    """
    centroid = game_map.centroid
    proj = f'+proj=aeqd +lat_0={centroid.y} +lon_0={centroid.x} +datum=WGS84 +units=m'
    to_local = Transformer.from_crs('EPSG:4326', proj, always_xy=True).transform
    to_wgs = Transformer.from_crs(proj, 'EPSG:4326', always_xy=True).transform

    local_map = transform(to_local, game_map)
    local_seeker = transform(to_local, seeker_poi)
    local_others = [transform(to_local, p) for p in other_pois]

    all_points = [local_seeker.centroid] + [p.centroid for p in local_others]
    regions = voronoi_polygons(MultiPoint(all_points), extend_to=local_map.envelope)

    seeker_cell = None
    for cell in regions.geoms:
        if cell.contains(local_seeker.centroid):
            seeker_cell = cell
            break

    if seeker_cell is None:
        raise RuntimeError("No Voronoi cell containing seeker's POI was found")

    result = local_map.difference(seeker_cell) if same else local_map.intersection(seeker_cell)
    return transform(to_wgs, result)


def exclude_thermometer(
    game_map: BaseGeometry, seeker_start: Point, seeker_end: Point, *, seeker_closer: bool
) -> BaseGeometry:
    """Exclusion zone for a thermometer question.

    Reuses Voronoi partitioning with two points (start and end positions). The Voronoi
    diagram of two points produces a perpendicular bisector, splitting the plane into
    the half closer to each point.

    - seeker_closer=True: the seeker got closer to the hider by moving. The hider must
      be in the half-plane closer to the end position, so exclude the start half.
    - seeker_closer=False: the seeker got farther from the hider. The hider must be in
      the half-plane closer to the start position, so exclude the end half.
    """
    return exclude_matching(game_map, seeker_end, [seeker_start], same=seeker_closer)
