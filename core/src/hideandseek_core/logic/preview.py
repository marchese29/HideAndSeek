"""Question preview — computes the dividing boundary for a question configuration.

Read-only: no questions created, no inventory consumed, no state mutated.
Convention conversion boundary lives here (same as ask.py / answer.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from hideandseek_core.conventions import from_meters, resolve_tentacle_distance, to_meters
from hideandseek_core.exclusion import (
    boundary_matching,
    boundary_measuring,
    boundary_radar,
    boundary_tentacles,
    boundary_thermometer,
)
from hideandseek_core.logic.resolution import resolve_matching_feature, resolve_measuring_feature
from hideandseek_core.queries.features import get_features_by_category, get_features_within_distance
from hideandseek_models.game import Game
from hideandseek_models.inventory import InventorySlot
from hideandseek_models.types import DistanceConvention, QuestionType


@dataclass(frozen=True, slots=True)
class TentaclePOIPreview:
    """A POI in a tentacles preview — feature info + location."""

    feature_id: str
    name: str
    location: Point


@dataclass(frozen=True, slots=True)
class PreviewResult:
    """Result of a question preview computation."""

    boundary: BaseGeometry
    feature_id: str | None = None
    feature_name: str | None = None
    feature_distance: float | None = None  # convention units
    tentacle_pois: list[TentaclePOIPreview] | None = None


def preview_question(
    question_type: QuestionType,
    game: Game,
    slot: InventorySlot,
    location: Point,
    custom_distance: float | None = None,
    seeker_location_end: Point | None = None,
) -> PreviewResult:
    """Compute the dividing boundary for a question configuration.

    Dispatches to the appropriate boundary function based on question type.
    For matching/measuring, also resolves the seeker's feature and includes
    it in the result.
    """
    game_map = game.game_map
    boundary_geom = game_map.boundary
    convention = game_map.convention

    if question_type == QuestionType.radar:
        radius_m = to_meters(slot.distance or custom_distance, convention)  # type: ignore[arg-type]
        return PreviewResult(boundary=boundary_radar(boundary_geom, location, radius_m))

    if question_type == QuestionType.thermometer:
        assert seeker_location_end is not None
        return PreviewResult(
            boundary=boundary_thermometer(boundary_geom, location, seeker_location_end)
        )

    if question_type == QuestionType.tentacles:
        return _preview_tentacles(game, slot, location, boundary_geom, convention)

    if question_type == QuestionType.matching:
        return _preview_matching(game, slot, location, boundary_geom, convention)

    # measuring
    return _preview_measuring(game, slot, location, boundary_geom, convention)


def _preview_matching(
    game: Game,
    slot: InventorySlot,
    location: Point,
    boundary_geom: BaseGeometry,
    convention: DistanceConvention,
) -> PreviewResult:
    """Preview for a matching question — Voronoi cell boundary + feature info."""
    assert slot.category is not None

    seeker_feature, seeker_dist = resolve_matching_feature(
        category=slot.category,
        location=location,
        game_map=game.game_map,
        feature_class=slot.feature_class,
    )
    if seeker_feature is None:
        raise ValueError(f'No feature found for category {slot.category} near the given location.')

    features = get_features_by_category(
        game, category=slot.category, feature_class=slot.feature_class
    )
    seeker_poi = seeker_feature.shape
    other_pois = [f.shape for f in features if f.stable_id != seeker_feature.stable_id]

    if not other_pois:
        raise ValueError(f'Only one feature exists for category {slot.category}; cannot preview.')

    return PreviewResult(
        boundary=boundary_matching(boundary_geom, seeker_poi, other_pois),
        feature_id=seeker_feature.stable_id,
        feature_name=seeker_feature.name,
        feature_distance=from_meters(seeker_dist, convention),
    )


def _preview_measuring(
    game: Game,
    slot: InventorySlot,
    location: Point,
    boundary_geom: BaseGeometry,
    convention: DistanceConvention,
) -> PreviewResult:
    """Preview for a measuring question — buffer ring boundary + feature info."""
    assert slot.category is not None

    seeker_feature, seeker_dist = resolve_measuring_feature(
        category=slot.category,
        location=location,
        game_map=game.game_map,
        feature_class=slot.feature_class,
    )

    features = get_features_by_category(
        game, category=slot.category, feature_class=slot.feature_class
    )
    pois = [f.shape for f in features]

    return PreviewResult(
        boundary=boundary_measuring(boundary_geom, seeker_dist, pois),
        feature_id=seeker_feature.stable_id,
        feature_name=seeker_feature.name,
        feature_distance=from_meters(seeker_dist, convention),
    )


def _preview_tentacles(
    game: Game,
    slot: InventorySlot,
    location: Point,
    boundary_geom: BaseGeometry,
    convention: DistanceConvention,
) -> PreviewResult:
    """Preview for a tentacles question — distance circle + Voronoi edges + POI list.

    Raises ValueError if any feature has non-Point geometry.
    """
    assert slot.category is not None

    distance_m = to_meters(resolve_tentacle_distance(game.game_map, slot.category), convention)
    features = get_features_within_distance(game, slot.category, location, distance_m)

    for f in features:
        if not isinstance(f.shape, Point):
            raise ValueError(
                f'Feature {f.stable_id} has {f.shape.geom_type} geometry; '
                f'tentacles requires Point geometry only.'
            )

    pois = [cast(Point, f.shape) for f in features]
    return PreviewResult(
        boundary=boundary_tentacles(boundary_geom, location, distance_m, pois),
        tentacle_pois=[
            TentaclePOIPreview(feature_id=f.stable_id, name=f.name, location=cast(Point, f.shape))
            for f in features
        ],
    )
