"""Business logic for matching and measuring question resolution.

Layer responsibilities:
- geo.py — pure math (geodesic distance, distance_to_feature)
- queries/features.py — pure data access (spatial SQL)
- resolution.py (this file) — business logic (answer computation, availability)
- routers/questions.py — HTTP orchestration
"""

from __future__ import annotations

import uuid

from shapely.geometry import Point

from hideandseek.geo import distance_to_feature
from hideandseek.models.map_feature import MapFeature
from hideandseek.models.types import FeatureCategory, QuestionType
from hideandseek.queries.features import (
    get_map_feature_categories,
    resolve_containing_feature,
    resolve_nearest_feature,
)
from hideandseek.queries.questions import get_category_usages

# ── Category classification ──────────────────────────────────────────────

MATCHING_CATEGORIES: set[FeatureCategory] = {
    FeatureCategory.transit_line,
    FeatureCategory.administrative_area,
    FeatureCategory.landmass,
    FeatureCategory.commercial_airport,
    FeatureCategory.mountain,
    FeatureCategory.park,
    FeatureCategory.amusement_park,
    FeatureCategory.zoo,
    FeatureCategory.aquarium,
    FeatureCategory.golf_course,
    FeatureCategory.museum,
    FeatureCategory.movie_theater,
    FeatureCategory.hospital,
    FeatureCategory.library,
    FeatureCategory.foreign_consulate,
}

MEASURING_CATEGORIES: set[FeatureCategory] = {
    FeatureCategory.high_speed_train_line,
    FeatureCategory.rail_station,
    FeatureCategory.international_border,
    FeatureCategory.admin_division_border,
    FeatureCategory.coastline,
    FeatureCategory.commercial_airport,
    FeatureCategory.mountain,
    FeatureCategory.park,
    FeatureCategory.amusement_park,
    FeatureCategory.zoo,
    FeatureCategory.aquarium,
    FeatureCategory.golf_course,
    FeatureCategory.museum,
    FeatureCategory.movie_theater,
    FeatureCategory.hospital,
    FeatureCategory.library,
    FeatureCategory.foreign_consulate,
}

# Matching uses ST_Contains for these polygon categories (non-tiling — may return None)
CONTAINMENT_CATEGORIES: set[FeatureCategory] = {
    FeatureCategory.administrative_area,
    FeatureCategory.landmass,
}

# Categories that require a feature_class to disambiguate tiers
CLASSED_CATEGORIES: set[FeatureCategory] = {
    FeatureCategory.administrative_area,
}


def category_key(category: FeatureCategory, feature_class: int | None) -> str:
    """Build inventory key like 'hospital' or 'administrative_area:1'."""
    if feature_class is not None:
        return f'{category}:{feature_class}'
    return str(category)


def get_available_categories(
    map_id: uuid.UUID,
    question_type: QuestionType,
    game_id: uuid.UUID,
) -> list[tuple[FeatureCategory, int | None]]:
    """Categories available for asking.

    Availability is inclusion-based: a category is available if features for it
    exist on the map (via GameMapFeature). Filters by:
    1. Question type support (matching vs measuring)
    2. Already-used categories from CategoryUsage table
    """
    type_categories = (
        MATCHING_CATEGORIES if question_type == QuestionType.matching else MEASURING_CATEGORIES
    )

    usages = get_category_usages(game_id, question_type)
    used_keys: set[str] = {category_key(u.category, u.feature_class) for u in usages}

    map_cats = get_map_feature_categories(game_map_id=map_id)

    result: list[tuple[FeatureCategory, int | None]] = []
    for cat, cls in map_cats:
        if cat not in type_categories:
            continue
        key = category_key(cat, cls)
        if key in used_keys:
            continue
        result.append((cat, cls))

    return result


def resolve_feature_for_player(
    category: FeatureCategory,
    location: Point,
    game_map_id: uuid.UUID,
    feature_class: int | None = None,
    *,
    for_matching: bool = False,
) -> tuple[MapFeature | None, float]:
    """Resolve the relevant feature for a player.

    If for_matching and category is a containment category → resolve_containing_feature.
    Otherwise → resolve_nearest_feature. Computes distance via distance_to_feature.
    Returns (feature, distance_m). distance_m is 0.0 when contained.
    """
    if for_matching and category in CONTAINMENT_CATEGORIES:
        feature = resolve_containing_feature(
            category=category,
            location=location,
            game_map_id=game_map_id,
            feature_class=feature_class,
        )
    else:
        feature = resolve_nearest_feature(
            category=category,
            location=location,
            game_map_id=game_map_id,
            feature_class=feature_class,
        )

    if feature is None:
        return None, 0.0

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
