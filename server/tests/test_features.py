"""Tests for map feature spatial queries and distance utilities."""

from __future__ import annotations

from shapely.geometry import LineString, Point, Polygon
from sqlalchemy.orm import Session

from hideandseek_core.geo import distance_to_feature
from hideandseek_core.queries.features import (
    get_map_feature_categories,
    resolve_containing_feature,
    resolve_nearest_feature,
)
from hideandseek_models.types import FeatureCategory
from tests.conftest import (
    create_game_map,
    create_game_map_feature,
    create_map_feature,
)

# ── resolve_nearest_feature ──────────────────────────────────────────────────


def test_nearest_feature_returns_closest(session: Session) -> None:
    """With multiple features of the same category, the closest is returned."""
    gm = create_game_map(session)
    # Near feature at (0.5, 0.5), far feature at (2.0, 2.0)
    near = create_map_feature(session, name='Near Hospital', shape=Point(0.5, 0.5))
    far = create_map_feature(session, name='Far Hospital', shape=Point(2.0, 2.0))
    create_game_map_feature(session, gm.id, near.id)
    create_game_map_feature(session, gm.id, far.id)

    result = resolve_nearest_feature(
        category=FeatureCategory.hospital,
        location=Point(0.4, 0.4),
        game_map=gm,
    )
    assert result is not None
    assert result.id == near.id


def test_nearest_feature_no_features(session: Session) -> None:
    """Returns None when no features exist for the category on the map."""
    gm = create_game_map(session)
    result = resolve_nearest_feature(
        category=FeatureCategory.hospital,
        location=Point(0.5, 0.5),
        game_map=gm,
    )
    assert result is None


def test_nearest_feature_map_scoping(session: Session) -> None:
    """Feature linked to map A is not visible from map B."""
    gm_a = create_game_map(session)
    gm_b = create_game_map(session)
    feature = create_map_feature(session)
    create_game_map_feature(session, gm_a.id, feature.id)

    # Map A finds it
    assert (
        resolve_nearest_feature(
            category=FeatureCategory.hospital,
            location=Point(0.5, 0.5),
            game_map=gm_a,
        )
        is not None
    )
    # Map B does not
    assert (
        resolve_nearest_feature(
            category=FeatureCategory.hospital,
            location=Point(0.5, 0.5),
            game_map=gm_b,
        )
        is None
    )


def test_nearest_feature_class_filtering(session: Session) -> None:
    """Feature class filter selects the correct tier."""
    gm = create_game_map(session)
    class1 = create_map_feature(
        session,
        category=FeatureCategory.administrative_area,
        name='State A',
        feature_class=1,
        shape=Point(0.5, 0.5),
    )
    class2 = create_map_feature(
        session,
        category=FeatureCategory.administrative_area,
        name='County A',
        feature_class=2,
        shape=Point(0.5, 0.5),
    )
    create_game_map_feature(session, gm.id, class1.id)
    create_game_map_feature(session, gm.id, class2.id)

    result = resolve_nearest_feature(
        category=FeatureCategory.administrative_area,
        location=Point(0.5, 0.5),
        game_map=gm,
        feature_class=1,
    )
    assert result is not None
    assert result.id == class1.id
    assert result.feature_class == 1


# ── resolve_containing_feature ───────────────────────────────────────────────


def test_containing_feature_point_inside(session: Session) -> None:
    """Point inside a polygon returns the containing feature."""
    gm = create_game_map(session)
    poly = create_map_feature(
        session,
        category=FeatureCategory.administrative_area,
        name='Test State',
        shape=Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
    )
    create_game_map_feature(session, gm.id, poly.id)

    result = resolve_containing_feature(
        category=FeatureCategory.administrative_area,
        location=Point(0.5, 0.5),
        game_map=gm,
    )
    assert result is not None
    assert result.id == poly.id


def test_containing_feature_point_outside(session: Session) -> None:
    """Point outside a polygon returns None."""
    gm = create_game_map(session)
    poly = create_map_feature(
        session,
        category=FeatureCategory.administrative_area,
        name='Test State',
        shape=Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
    )
    create_game_map_feature(session, gm.id, poly.id)

    result = resolve_containing_feature(
        category=FeatureCategory.administrative_area,
        location=Point(5.0, 5.0),
        game_map=gm,
    )
    assert result is None


def test_containing_feature_class_filtering(session: Session) -> None:
    """Feature class filter works for containment queries."""
    gm = create_game_map(session)
    state = create_map_feature(
        session,
        category=FeatureCategory.administrative_area,
        name='State',
        feature_class=1,
        shape=Polygon([(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]),
    )
    county = create_map_feature(
        session,
        category=FeatureCategory.administrative_area,
        name='County',
        feature_class=2,
        shape=Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
    )
    create_game_map_feature(session, gm.id, state.id)
    create_game_map_feature(session, gm.id, county.id)

    # Point (0.5, 0.5) is inside both, but class=1 should return only state
    result = resolve_containing_feature(
        category=FeatureCategory.administrative_area,
        location=Point(0.5, 0.5),
        game_map=gm,
        feature_class=1,
    )
    assert result is not None
    assert result.id == state.id


# ── get_map_feature_categories ───────────────────────────────────────────────


def test_get_map_feature_categories(session: Session) -> None:
    """Returns correct (category, feature_class) pairs for a map."""
    gm = create_game_map(session)
    hosp = create_map_feature(session, category=FeatureCategory.hospital)
    area1 = create_map_feature(
        session,
        category=FeatureCategory.administrative_area,
        feature_class=1,
        shape=Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
    )
    area2 = create_map_feature(
        session,
        category=FeatureCategory.administrative_area,
        feature_class=2,
        shape=Polygon([(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]),
    )
    create_game_map_feature(session, gm.id, hosp.id)
    create_game_map_feature(session, gm.id, area1.id)
    create_game_map_feature(session, gm.id, area2.id)

    cats = get_map_feature_categories(game_map=gm)
    cats_set = set(cats)
    assert (FeatureCategory.hospital, None) in cats_set
    assert (FeatureCategory.administrative_area, 1) in cats_set
    assert (FeatureCategory.administrative_area, 2) in cats_set
    assert len(cats) == 3


def test_get_map_feature_categories_empty(session: Session) -> None:
    """Returns empty list when map has no features."""
    gm = create_game_map(session)
    assert get_map_feature_categories(game_map=gm) == []


# ── distance_to_feature ─────────────────────────────────────────────────────


def test_distance_to_feature_point() -> None:
    """Distance from player to a Point feature."""
    player = Point(-71.06, 42.36)  # (lng, lat)
    feature_pt = Point(-71.07, 42.36)
    dist = distance_to_feature(player, feature_pt)
    # ~0.01 degrees longitude at lat 42 ≈ ~826 m
    assert 700 < dist < 900


def test_distance_to_feature_linestring() -> None:
    """Distance from player to a LineString feature uses nearest point."""
    player = Point(0.0, 1.0)  # 1 degree north of the line
    line = LineString([(0.0, 0.0), (2.0, 0.0)])
    dist = distance_to_feature(player, line)
    # 1 degree of latitude ≈ 111 km
    assert 110_000 < dist < 112_000


def test_distance_to_feature_polygon() -> None:
    """Distance from player inside a polygon is ~0."""
    player = Point(0.5, 0.5)
    poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    dist = distance_to_feature(player, poly)
    assert dist < 1  # Effectively 0 — player is inside


def test_distance_to_feature_polygon_outside() -> None:
    """Distance from player outside a polygon to its nearest edge."""
    player = Point(0.0, 2.0)  # 1 degree north of polygon top edge
    poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    dist = distance_to_feature(player, poly)
    # 1 degree of latitude ≈ 111 km
    assert 110_000 < dist < 112_000
