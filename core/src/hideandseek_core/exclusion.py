"""Exclusion and boundary geometry for question zones.

**Exclusion functions** (``exclude_*``) compute filled polygons representing regions of
the game map where the hider cannot be.  The client subtracts these zones from the
visible map to narrow down the hider's location.

**Boundary functions** (``boundary_*``) compute the *dividing line* between the two
possible answer outcomes — the answer-agnostic geometry shown during question preview.
They return a line/ring, not a filled zone.

All functions accept and return WGS84 (EPSG:4326) geometries.  Metric operations
(buffering, Voronoi) are performed in a local azimuthal equidistant projection centered
on the geometry's centroid, then projected back to WGS84.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pyproj import Transformer
from shapely import MultiPoint, Point, voronoi_polygons
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from hideandseek_models.question import Question


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


def _voronoi_seeker_cell(
    game_map: BaseGeometry,
    seeker_poi: BaseGeometry,
    other_pois: Sequence[BaseGeometry],
) -> tuple[BaseGeometry, BaseGeometry, _VoronoiProjection]:
    """Shared Voronoi helper — returns (local_seeker_cell, local_map, projection).

    Projects to a local AEQD plane, computes Voronoi cells, and identifies the cell
    containing the seeker's POI centroid.
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

    return seeker_cell, local_map, _VoronoiProjection(to_local, to_wgs)


@dataclass
class _VoronoiProjection:
    to_local: Any  # Transformer.transform callable
    to_wgs: Any


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
    seeker_cell, local_map, vp = _voronoi_seeker_cell(game_map, seeker_poi, other_pois)

    result = local_map.difference(seeker_cell) if same else local_map.intersection(seeker_cell)
    return transform(vp.to_wgs, result)


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


def exclude_tentacles(
    game_map: BaseGeometry,
    seeker_location: Point,
    distance_m: float,
    answered_poi: Point,
    other_pois: Sequence[Point],
) -> BaseGeometry:
    """Exclusion zone for a tentacles hit.

    Computes Voronoi cells for all in-circle POIs, intersects the answered POI's
    cell with the distance circle to get the "safe zone" where the hider is.
    Excludes everything else in the game boundary.

    On a miss, the caller should use exclude_radar(hit=False) instead.
    """
    circle = _buffer(seeker_location, distance_m)

    if not other_pois:
        # Single POI: safe zone is the entire circle (equivalent to radar hit)
        return game_map.difference(circle)

    all_pois = [answered_poi, *list(other_pois)]
    centroid = game_map.centroid
    proj = f'+proj=aeqd +lat_0={centroid.y} +lon_0={centroid.x} +datum=WGS84 +units=m'
    to_local = Transformer.from_crs('EPSG:4326', proj, always_xy=True).transform
    to_wgs = Transformer.from_crs(proj, 'EPSG:4326', always_xy=True).transform

    local_map = transform(to_local, game_map)
    local_circle = transform(to_local, circle)
    local_answered = transform(to_local, answered_poi)
    local_all = [transform(to_local, p) for p in all_pois]

    points = [p.centroid for p in local_all]
    regions = voronoi_polygons(MultiPoint(points), extend_to=local_map.envelope)

    answered_cell = None
    for cell in regions.geoms:
        if cell.contains(local_answered.centroid):
            answered_cell = cell
            break

    if answered_cell is None:
        raise RuntimeError('No Voronoi cell containing answered POI was found')

    safe_zone = answered_cell.intersection(local_circle)
    exclusion = local_map.difference(safe_zone)
    return transform(to_wgs, exclusion)


# ── Hiding zone ───────────────────────────────────────────────────────────


def compute_hiding_zone(
    station: Point,
    radius_m: float,
    boundary: BaseGeometry,
) -> BaseGeometry:
    """Compute the hiding zone around a station, clipped to the game map boundary."""
    return _buffer(station, radius_m).intersection(boundary)


# ── Endgame exclusions ─────────────────────────────────────────────────────


@dataclass
class EndgameExclusionEntry:
    """One question's exclusion intersected with the hiding zone circle."""

    question_id: uuid.UUID
    sequence: int
    exclusion: BaseGeometry | None
    total_exclusion: BaseGeometry | None


@dataclass
class EndgameExclusionResult:
    """Endgame exclusion view: hiding zone circle + per-question intersected exclusions."""

    hiding_zone: BaseGeometry
    entries: list[EndgameExclusionEntry]


def compute_endgame_exclusions(
    game_map: BaseGeometry,
    station: Point,
    radius_m: float,
    questions: Sequence[Question],
) -> EndgameExclusionResult:
    """Compute endgame exclusions by intersecting each question's exclusion with the hiding zone.

    Builds a hiding zone circle around the station, clips it to the game map boundary,
    intersects each question's stored exclusion with it, and builds a fresh cumulative
    total_exclusion from the intersected results only (long-game exclusions do not carry over).
    """
    hiding_zone = compute_hiding_zone(station, radius_m, game_map)
    cumulative: BaseGeometry | None = None
    entries: list[EndgameExclusionEntry] = []

    for q in questions:
        if q.exclusion is None:
            entries.append(
                EndgameExclusionEntry(
                    question_id=q.id,
                    sequence=q.sequence,
                    exclusion=None,
                    total_exclusion=cumulative,
                )
            )
            continue

        intersected = hiding_zone.intersection(q.exclusion)
        if intersected.is_empty:
            intersected = None

        if intersected is not None:
            if cumulative is None:
                cumulative = intersected
            else:
                cumulative = unary_union([cumulative, intersected])

        entries.append(
            EndgameExclusionEntry(
                question_id=q.id,
                sequence=q.sequence,
                exclusion=intersected,
                total_exclusion=cumulative,
            )
        )

    return EndgameExclusionResult(hiding_zone=hiding_zone, entries=entries)


# ── Preview boundaries ───────────────────────────────────────────────────
#
# Answer-agnostic dividing lines — the geometry that separates the two
# possible answer outcomes for a question configuration.


def boundary_radar(game_map: BaseGeometry, location: Point, radius_m: float) -> BaseGeometry:
    """Dividing circle for a radar question preview.

    Returns the circle ring at the given radius, clipped to the game map boundary.
    """
    circle = _buffer(location, radius_m)
    return game_map.intersection(circle.boundary)


def boundary_thermometer(
    game_map: BaseGeometry, seeker_start: Point, seeker_end: Point
) -> BaseGeometry:
    """Perpendicular bisector for a thermometer question preview.

    The bisector divides the plane into the half closer to the start position
    and the half closer to the end position.
    """
    return boundary_matching(game_map, seeker_end, [seeker_start])


def boundary_matching(
    game_map: BaseGeometry,
    seeker_poi: BaseGeometry,
    other_pois: Sequence[BaseGeometry],
) -> BaseGeometry:
    """Voronoi cell edge for a matching question preview.

    Returns the boundary of the seeker's Voronoi cell, clipped to the game map.
    """
    seeker_cell, local_map, vp = _voronoi_seeker_cell(game_map, seeker_poi, other_pois)
    clipped_cell = local_map.intersection(seeker_cell)
    return transform(vp.to_wgs, clipped_cell.boundary)


def boundary_measuring(
    game_map: BaseGeometry,
    distance_m: float,
    pois: Sequence[BaseGeometry],
) -> BaseGeometry:
    """Buffer ring(s) for a measuring question preview.

    Returns the boundary of the unioned buffer circles around each POI at the
    seeker's measured distance, clipped to the game map.
    """
    combined = unary_union([_buffer(poi, distance_m) for poi in pois])
    return game_map.intersection(combined.boundary)


def boundary_tentacles(
    game_map: BaseGeometry,
    seeker_location: Point,
    distance_m: float,
    pois: Sequence[Point],
) -> BaseGeometry:
    """Preview boundary for a tentacles question.

    Returns the distance circle ring plus Voronoi cell edges within the circle,
    clipped to the game map. For a single POI, returns just the circle ring.
    """
    if len(pois) <= 1:
        return boundary_radar(game_map, seeker_location, distance_m)

    circle = _buffer(seeker_location, distance_m)

    centroid = game_map.centroid
    proj = f'+proj=aeqd +lat_0={centroid.y} +lon_0={centroid.x} +datum=WGS84 +units=m'
    to_local = Transformer.from_crs('EPSG:4326', proj, always_xy=True).transform
    to_wgs = Transformer.from_crs(proj, 'EPSG:4326', always_xy=True).transform

    local_map = transform(to_local, game_map)
    local_circle = transform(to_local, circle)
    local_pois = [transform(to_local, p) for p in pois]

    points = [p.centroid for p in local_pois]
    regions = voronoi_polygons(MultiPoint(points), extend_to=local_map.envelope)

    # Voronoi cell edges clipped to circle
    voronoi_edges = unary_union([cell.boundary for cell in regions.geoms]).intersection(
        local_circle
    )

    # Circle ring clipped to game map
    circle_ring = local_circle.boundary

    combined = unary_union([voronoi_edges, circle_ring])
    return transform(to_wgs, local_map.intersection(combined))
