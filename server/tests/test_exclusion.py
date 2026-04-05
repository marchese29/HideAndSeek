"""Unit tests for exclusion geometry functions — no DB needed."""

from __future__ import annotations

from shapely import Point, Polygon

from hideandseek.exclusion import (
    boundary_matching,
    boundary_measuring,
    boundary_radar,
    boundary_thermometer,
    exclude_matching,
    exclude_measuring,
    exclude_radar,
    exclude_thermometer,
)

# A simple ~10 km square around (0, 0) — large enough to contain all test buffers.
GAME_MAP = Polygon([(-0.1, -0.1), (0.1, -0.1), (0.1, 0.1), (-0.1, 0.1), (-0.1, -0.1)])


# ── exclude_radar ────────────────────────────────────────────────────────────


def test_radar_miss_excludes_circle():
    """On miss, the circle around the seeker is excluded (hider can't be there)."""
    result = exclude_radar(GAME_MAP, Point(0, 0), 1000, hit=False)
    assert not result.is_empty
    # The excluded zone is inside the circle, so the center should be excluded
    assert result.contains(Point(0, 0))
    # A point far from the seeker should not be excluded
    assert not result.contains(Point(0.05, 0.05))


def test_radar_hit_excludes_outside():
    """On hit, everything outside the circle is excluded (hider must be inside)."""
    result = exclude_radar(GAME_MAP, Point(0, 0), 1000, hit=True)
    assert not result.is_empty
    # Center should NOT be excluded (hider is in the circle)
    assert not result.contains(Point(0, 0))
    # A far point should be excluded
    assert result.contains(Point(0.05, 0.05))


# ── exclude_thermometer ─────────────────────────────────────────────────────


def test_thermometer_closer():
    """Seeker got closer → exclude the half near the start (hider is near end)."""
    start = Point(-0.02, 0)
    end = Point(0.02, 0)
    result = exclude_thermometer(GAME_MAP, start, end, seeker_closer=True)
    assert not result.is_empty
    # A point near start should be excluded
    assert result.contains(Point(-0.05, 0))
    # A point near end should NOT be excluded
    assert not result.contains(Point(0.05, 0))


def test_thermometer_farther():
    """Seeker got farther → exclude the half near the end (hider is near start)."""
    start = Point(-0.02, 0)
    end = Point(0.02, 0)
    result = exclude_thermometer(GAME_MAP, start, end, seeker_closer=False)
    assert not result.is_empty
    # A point near end should be excluded
    assert result.contains(Point(0.05, 0))
    # A point near start should NOT be excluded
    assert not result.contains(Point(-0.05, 0))


# ── exclude_matching ─────────────────────────────────────────────────────────


def test_matching_same():
    """Same POI → exclude everything outside the seeker's Voronoi cell."""
    seeker_poi = Point(-0.03, 0)
    other_pois = [Point(0.03, 0)]
    result = exclude_matching(GAME_MAP, seeker_poi, other_pois, same=True)
    assert not result.is_empty
    # A point near the other POI should be excluded
    assert result.contains(Point(0.05, 0))
    # A point near the seeker's POI should NOT be excluded
    assert not result.contains(Point(-0.05, 0))


def test_matching_different():
    """Different POI → exclude the seeker's Voronoi cell."""
    seeker_poi = Point(-0.03, 0)
    other_pois = [Point(0.03, 0)]
    result = exclude_matching(GAME_MAP, seeker_poi, other_pois, same=False)
    assert not result.is_empty
    # A point near the seeker's POI should be excluded
    assert result.contains(Point(-0.05, 0))
    # A point near the other POI should NOT be excluded
    assert not result.contains(Point(0.05, 0))


# ── exclude_measuring ────────────────────────────────────────────────────────


def test_measuring_hider_closer():
    """Hider closer → exclude outside buffer (hider must be inside)."""
    pois = [Point(0, 0)]
    result = exclude_measuring(GAME_MAP, 5000, pois, hider_closer=True)
    assert not result.is_empty
    # A far point should be excluded (hider must be closer than seeker)
    assert result.contains(Point(0.09, 0.09))
    # A point near the POI should NOT be excluded
    assert not result.contains(Point(0, 0))


def test_measuring_hider_farther():
    """Hider farther → exclude inside buffer (hider must be outside)."""
    pois = [Point(0, 0)]
    result = exclude_measuring(GAME_MAP, 5000, pois, hider_closer=False)
    assert not result.is_empty
    # A point near the POI should be excluded (hider is farther)
    assert result.contains(Point(0, 0))
    # A far point should NOT be excluded
    assert not result.contains(Point(0.09, 0.09))


# ── boundary_radar ──────────────────────────────────────────────────────────


def test_boundary_radar_is_line():
    """Radar boundary is a line (ring), not a filled polygon."""
    result = boundary_radar(GAME_MAP, Point(0, 0), 1000)
    assert not result.is_empty
    # Boundary should be 1-dimensional (line), not 2-dimensional (polygon)
    assert result.geom_type in ('LinearRing', 'LineString', 'MultiLineString')


def test_boundary_radar_within_game_map():
    """Radar boundary is clipped to the game map."""
    result = boundary_radar(GAME_MAP, Point(0, 0), 1000)
    assert GAME_MAP.contains(result) or GAME_MAP.covers(result)


# ── boundary_thermometer ────────────────────────────────────────────────────


def test_boundary_thermometer_is_line():
    """Thermometer boundary (perpendicular bisector) is a line."""
    start = Point(-0.02, 0)
    end = Point(0.02, 0)
    result = boundary_thermometer(GAME_MAP, start, end)
    assert not result.is_empty
    assert result.geom_type in ('LinearRing', 'LineString', 'MultiLineString')


def test_boundary_thermometer_bisects():
    """The bisector separates start-half from end-half."""
    start = Point(-0.02, 0)
    end = Point(0.02, 0)
    result = boundary_thermometer(GAME_MAP, start, end)
    # The midpoint of start and end should be very close to the boundary
    midpoint = Point(0, 0)
    assert result.distance(midpoint) < 1e-6


# ── boundary_matching ───────────────────────────────────────────────────────


def test_boundary_matching_is_line():
    """Matching boundary (Voronoi cell edge) is a line."""
    seeker_poi = Point(-0.03, 0)
    other_pois = [Point(0.03, 0)]
    result = boundary_matching(GAME_MAP, seeker_poi, other_pois)
    assert not result.is_empty
    assert result.geom_type in ('LinearRing', 'LineString', 'MultiLineString')


# ── boundary_measuring ──────────────────────────────────────────────────────


def test_boundary_measuring_is_line():
    """Measuring boundary (buffer ring) is a line."""
    pois = [Point(0, 0)]
    result = boundary_measuring(GAME_MAP, 5000, pois)
    assert not result.is_empty
    assert result.geom_type in ('LinearRing', 'LineString', 'MultiLineString')
