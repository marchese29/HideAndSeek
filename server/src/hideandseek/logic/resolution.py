"""Business logic for matching and measuring question resolution.

Layer responsibilities:
- geo.py — pure math (geodesic distance, distance_to_feature)
- queries/features.py — pure data access (spatial SQL)
- logic/resolution.py (this file) — business logic (answer computation, resolution strategy)
- routers/questions.py — HTTP orchestration
"""

from __future__ import annotations

from shapely.geometry import Point

from hideandseek.geo import distance_to_feature
from hideandseek.models.game_map import GameMap
from hideandseek.models.map_feature import MapFeature
from hideandseek.models.types import CONTAINMENT_CATEGORIES, FeatureCategory
from hideandseek.queries.features import resolve_containing_feature, resolve_nearest_feature


def resolve_matching_feature(
    category: FeatureCategory,
    location: Point,
    game_map: GameMap,
    feature_class: int | None,
) -> tuple[MapFeature | None, float]:
    """Resolve the relevant feature for matching.

    Containment categories use ST_Contains (may return None if player is outside
    all polygons). Other categories use nearest-feature resolution.
    Returns (feature, distance_m). distance_m is 0.0 when contained.
    """
    if category in CONTAINMENT_CATEGORIES:
        feature = resolve_containing_feature(
            category=category,
            location=location,
            game_map=game_map,
            feature_class=feature_class,
        )
    else:
        feature = resolve_nearest_feature(
            category=category,
            location=location,
            game_map=game_map,
            feature_class=feature_class,
        )

    if feature is None:
        return None, 0.0

    dist = distance_to_feature(location, feature.geometry)
    return feature, dist


def resolve_measuring_feature(
    category: FeatureCategory,
    location: Point,
    game_map: GameMap,
    feature_class: int | None,
) -> tuple[MapFeature, float]:
    """Resolve the nearest feature for measuring.

    Always uses nearest-feature resolution. Returns (feature, distance_m).
    Asserts that a feature exists — inventory slots guarantee map data is present.
    """
    feature = resolve_nearest_feature(
        category=category,
        location=location,
        game_map=game_map,
        feature_class=feature_class,
    )
    assert feature is not None  # slot exists → map has features for this category

    dist = distance_to_feature(location, feature.geometry)
    return feature, dist


def compute_matching_answer(
    seeker_feature: MapFeature | None, hider_feature: MapFeature | None
) -> str | None:
    """Compare stable_ids → 'yes' / 'no' / None (if either missing)."""
    if seeker_feature is None or hider_feature is None:
        return None
    return 'yes' if seeker_feature.stable_id == hider_feature.stable_id else 'no'


def compute_measuring_answer(
    seeker_distance: float | None, hider_distance: float | None
) -> str | None:
    """Compare distances → 'closer' / 'farther' / None (if either missing)."""
    if seeker_distance is None or hider_distance is None:
        return None
    return 'closer' if seeker_distance < hider_distance else 'farther'
