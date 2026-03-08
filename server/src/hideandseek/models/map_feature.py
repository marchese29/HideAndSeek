from __future__ import annotations

import uuid

from shapely.geometry.base import BaseGeometry
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hideandseek.models.base import Base
from hideandseek.models.geo_types import ShapelyGeography
from hideandseek.models.types import FeatureCategory


class MapFeature(Base):
    __tablename__ = 'map_feature'
    __table_args__ = (UniqueConstraint('category', 'stable_id'),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    category: Mapped[FeatureCategory]
    stable_id: Mapped[str]
    name: Mapped[str]
    feature_class: Mapped[int | None] = mapped_column(default=None)
    shape: Mapped[BaseGeometry] = mapped_column(ShapelyGeography('GEOMETRY', srid=4326))


class GameMapFeature(Base):
    __tablename__ = 'game_map_feature'

    game_map_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('game_map.id'), primary_key=True)
    map_feature_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('map_feature.id'), primary_key=True
    )
