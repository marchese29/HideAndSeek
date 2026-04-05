"""Spatial queries for map-defined features."""

from __future__ import annotations

from collections.abc import Sequence

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import func, select

from hideandseek_core.db import get_session
from hideandseek_models.game import Game
from hideandseek_models.game_map import GameMap
from hideandseek_models.map_feature import GameMapFeature, MapFeature
from hideandseek_models.types import FeatureCategory


def get_map_feature_categories(
    game_map: GameMap,
) -> list[tuple[FeatureCategory, int | None]]:
    """Return distinct (category, feature_class) pairs available on a map."""
    session = get_session()
    stmt = (
        select(MapFeature.category, MapFeature.feature_class)
        .join(GameMapFeature)
        .where(GameMapFeature.game_map_id == game_map.id)
        .distinct()
    )
    rows = session.execute(stmt).all()
    return [(FeatureCategory(row[0]), row[1]) for row in rows]


def resolve_nearest_feature(
    category: FeatureCategory,
    location: Point,
    game_map: GameMap,
    feature_class: int | None = None,
) -> MapFeature | None:
    """Find the nearest feature of a category on a map, ordered by ST_Distance."""
    session = get_session()
    point_wkb = from_shape(location, srid=4326)
    stmt = (
        select(MapFeature)
        .join(GameMapFeature)
        .where(
            GameMapFeature.game_map_id == game_map.id,
            MapFeature.category == category,
        )
        .order_by(func.ST_Distance(MapFeature.shape, point_wkb))
        .limit(1)
    )
    if feature_class is not None:
        stmt = stmt.where(MapFeature.feature_class == feature_class)
    return session.scalars(stmt).one_or_none()


def resolve_containing_feature(
    category: FeatureCategory,
    location: Point,
    game_map: GameMap,
    feature_class: int | None = None,
) -> MapFeature | None:
    """Find the feature of a category that contains the given point."""
    session = get_session()
    point_wkb = from_shape(location, srid=4326)
    stmt = (
        select(MapFeature)
        .join(GameMapFeature)
        .where(
            GameMapFeature.game_map_id == game_map.id,
            MapFeature.category == category,
            func.ST_Covers(MapFeature.shape, point_wkb),
        )
        .limit(1)
    )
    if feature_class is not None:
        stmt = stmt.where(MapFeature.feature_class == feature_class)
    return session.scalars(stmt).one_or_none()


def get_features_by_category(
    game: Game,
    category: FeatureCategory,
    feature_class: int | None = None,
) -> Sequence[MapFeature]:
    """Return all features of a category on a game's map."""
    session = get_session()
    stmt = (
        select(MapFeature)
        .join(GameMapFeature)
        .where(
            GameMapFeature.game_map_id == game.map_id,
            MapFeature.category == category,
        )
    )
    if feature_class is not None:
        stmt = stmt.where(MapFeature.feature_class == feature_class)
    return session.scalars(stmt).all()
