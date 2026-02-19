"""Spatial queries for map-defined features."""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import func
from sqlmodel import Session, select

from hideandseek.db import db_read
from hideandseek.models.map_feature import GameMapFeature, MapFeature
from hideandseek.models.types import FeatureCategory


@db_read
def resolve_nearest_feature(
    session: Session,
    category: FeatureCategory,
    location: Point,
    game_map_id: uuid.UUID,
    feature_class: int | None = None,
) -> MapFeature | None:
    """Find the nearest feature of a category on a map, ordered by ST_Distance."""
    point_wkb = from_shape(location, srid=4326)
    stmt = (
        select(MapFeature)
        .join(GameMapFeature)  # type: ignore[arg-type]
        .where(
            GameMapFeature.game_map_id == game_map_id,
            MapFeature.category == category,
        )
        .order_by(func.ST_Distance(MapFeature.geometry, point_wkb))  # type: ignore[arg-type]
        .limit(1)
    )
    if feature_class is not None:
        stmt = stmt.where(MapFeature.feature_class == feature_class)
    return session.exec(stmt).first()


@db_read
def resolve_containing_feature(
    session: Session,
    category: FeatureCategory,
    location: Point,
    game_map_id: uuid.UUID,
    feature_class: int | None = None,
) -> MapFeature | None:
    """Find the feature of a category that contains the given point."""
    point_wkb = from_shape(location, srid=4326)
    stmt = (
        select(MapFeature)
        .join(GameMapFeature)  # type: ignore[arg-type]
        .where(
            GameMapFeature.game_map_id == game_map_id,
            MapFeature.category == category,
            func.ST_Contains(MapFeature.geometry, point_wkb),
        )
        .limit(1)
    )
    if feature_class is not None:
        stmt = stmt.where(MapFeature.feature_class == feature_class)
    return session.exec(stmt).first()


@db_read
def get_map_feature_categories(
    session: Session,
    game_map_id: uuid.UUID,
) -> list[tuple[FeatureCategory, int | None]]:
    """Return distinct (category, feature_class) pairs available on a map."""
    stmt = (
        select(MapFeature.category, MapFeature.feature_class)
        .join(GameMapFeature)  # type: ignore[arg-type]
        .where(GameMapFeature.game_map_id == game_map_id)
        .distinct()
    )
    rows = session.exec(stmt).all()
    return [(FeatureCategory(row[0]), row[1]) for row in rows]  # type: ignore[index]
