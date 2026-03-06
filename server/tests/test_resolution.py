"""Tests for resolution business logic."""

from __future__ import annotations

from shapely.geometry import Point, Polygon
from sqlalchemy.orm import Session

from hideandseek.logic.resolution import (
    compute_matching_answer,
    compute_measuring_answer,
    resolve_matching_feature,
    resolve_measuring_feature,
)
from hideandseek.models.types import FeatureCategory, category_key
from tests.conftest import (
    create_game_map,
    create_game_map_feature,
    create_map_feature,
)

# ── category_key ─────────────────────────────────────────────────────────────


def test_category_key_without_class():
    assert category_key(FeatureCategory.hospital, None) == 'hospital'


def test_category_key_with_class():
    assert category_key(FeatureCategory.administrative_area, 1) == 'administrative_area:1'


# ── resolve_measuring_feature ────────────────────────────────────────────────


def test_resolve_nearest_for_measuring(session: Session):
    """Non-containment category uses nearest resolution."""
    gm = create_game_map(session)
    hosp = create_map_feature(session, geometry=Point(0.5, 0.5))
    create_game_map_feature(session, gm.id, hosp.id)

    feature, dist = resolve_measuring_feature(
        category=FeatureCategory.hospital,
        location=Point(0.51, 0.51),
        game_map=gm,
        feature_class=None,
    )
    assert feature.id == hosp.id
    assert dist > 0


# ── resolve_matching_feature ────────────────────────────────────────────────


def test_resolve_containment_for_matching(session: Session):
    """Containment category (administrative_area) uses ST_Contains for matching."""
    gm = create_game_map(session)
    area = create_map_feature(
        session,
        category=FeatureCategory.administrative_area,
        stable_id='area-1',
        name='Test Area',
        feature_class=1,
        geometry=Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
    )
    create_game_map_feature(session, gm.id, area.id)

    # Inside polygon
    feature, dist = resolve_matching_feature(
        category=FeatureCategory.administrative_area,
        location=Point(0.5, 0.5),
        game_map=gm,
        feature_class=1,
    )
    assert feature is not None
    assert feature.id == area.id

    # Outside polygon
    feature, dist = resolve_matching_feature(
        category=FeatureCategory.administrative_area,
        location=Point(5.0, 5.0),
        game_map=gm,
        feature_class=1,
    )
    assert feature is None


def test_resolve_no_features_matching(session: Session):
    """Returns (None, 0.0) when no features exist for matching."""
    gm = create_game_map(session)
    feature, dist = resolve_matching_feature(
        category=FeatureCategory.hospital,
        location=Point(0.5, 0.5),
        game_map=gm,
        feature_class=None,
    )
    assert feature is None
    assert dist == 0.0


# ── compute_matching_answer ──────────────────────────────────────────────────


def test_compute_matching_yes(session: Session):
    feature = create_map_feature(session, stable_id='same')
    assert compute_matching_answer(feature, feature) == 'yes'


def test_compute_matching_no(session: Session):
    f1 = create_map_feature(session, stable_id='a')
    f2 = create_map_feature(session, stable_id='b')
    assert compute_matching_answer(f1, f2) == 'no'


def test_compute_matching_null_seeker():
    assert compute_matching_answer(None, None) is None


def test_compute_matching_null_hider(session: Session):
    f1 = create_map_feature(session, stable_id='a')
    assert compute_matching_answer(f1, None) is None


# ── compute_measuring_answer ─────────────────────────────────────────────────


def test_compute_measuring_closer():
    assert compute_measuring_answer(100.0, 200.0) == 'closer'


def test_compute_measuring_farther():
    assert compute_measuring_answer(300.0, 100.0) == 'farther'


def test_compute_measuring_null():
    assert compute_measuring_answer(None, 200.0) is None
    assert compute_measuring_answer(100.0, None) is None
