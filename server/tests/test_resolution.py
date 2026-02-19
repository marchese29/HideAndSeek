"""Tests for resolution business logic."""

from __future__ import annotations

from shapely.geometry import Point, Polygon
from sqlmodel import Session

from hideandseek.models.types import FeatureCategory, QuestionType
from hideandseek.resolution import (
    category_key,
    compute_matching_answer,
    compute_measuring_answer,
    get_available_categories,
    resolve_feature_for_player,
)
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


# ── get_available_categories ─────────────────────────────────────────────────


def test_available_categories_filters_by_type(session: Session):
    """Only matching-supported categories returned for matching."""
    gm = create_game_map(session)
    hosp = create_map_feature(session, category=FeatureCategory.hospital)
    # rail_station is measuring-only
    rail = create_map_feature(
        session,
        category=FeatureCategory.rail_station,
        stable_id='rail-1',
        name='Station',
    )
    create_game_map_feature(session, gm.id, hosp.id)
    create_game_map_feature(session, gm.id, rail.id)

    matching = get_available_categories(
        map_id=gm.id,
        question_type=QuestionType.matching,
        inventory={'matching_used': [], 'measuring_used': []},
    )
    measuring = get_available_categories(
        map_id=gm.id,
        question_type=QuestionType.measuring,
        inventory={'matching_used': [], 'measuring_used': []},
    )

    matching_cats = {c for c, _ in matching}
    measuring_cats = {c for c, _ in measuring}
    assert FeatureCategory.hospital in matching_cats
    assert FeatureCategory.rail_station not in matching_cats
    assert FeatureCategory.rail_station in measuring_cats
    assert FeatureCategory.hospital in measuring_cats


def test_available_categories_excludes_used(session: Session):
    gm = create_game_map(session)
    hosp = create_map_feature(session, category=FeatureCategory.hospital)
    create_game_map_feature(session, gm.id, hosp.id)

    avail = get_available_categories(
        map_id=gm.id,
        question_type=QuestionType.matching,
        inventory={'matching_used': ['hospital'], 'measuring_used': []},
    )
    assert len(avail) == 0


# ── resolve_feature_for_player ───────────────────────────────────────────────


def test_resolve_nearest_for_measuring(session: Session):
    """Non-containment category uses nearest resolution."""
    gm = create_game_map(session)
    hosp = create_map_feature(session, geometry=Point(0.5, 0.5))
    create_game_map_feature(session, gm.id, hosp.id)

    feature, dist = resolve_feature_for_player(
        category=FeatureCategory.hospital,
        location=Point(0.51, 0.51),
        game_map_id=gm.id,
        for_matching=False,
    )
    assert feature is not None
    assert feature.id == hosp.id
    assert dist > 0


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
    feature, dist = resolve_feature_for_player(
        category=FeatureCategory.administrative_area,
        location=Point(0.5, 0.5),
        game_map_id=gm.id,
        feature_class=1,
        for_matching=True,
    )
    assert feature is not None
    assert feature.id == area.id

    # Outside polygon
    feature, dist = resolve_feature_for_player(
        category=FeatureCategory.administrative_area,
        location=Point(5.0, 5.0),
        game_map_id=gm.id,
        feature_class=1,
        for_matching=True,
    )
    assert feature is None


def test_resolve_no_features(session: Session):
    """Returns (None, 0.0) when no features exist."""
    gm = create_game_map(session)
    feature, dist = resolve_feature_for_player(
        category=FeatureCategory.hospital,
        location=Point(0.5, 0.5),
        game_map_id=gm.id,
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
