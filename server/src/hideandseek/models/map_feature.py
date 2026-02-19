import uuid

import sqlalchemy as sa
from shapely.geometry.base import BaseGeometry
from sqlmodel import Field, SQLModel

from hideandseek.models.geo_types import ShapelyGeometry
from hideandseek.models.types import FeatureCategory


class MapFeature(SQLModel, table=True):
    model_config = {'arbitrary_types_allowed': True}  # type: ignore[assignment]
    __tablename__ = 'map_feature'  # type: ignore[assignment]
    __table_args__ = (sa.UniqueConstraint('category', 'stable_id'),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    category: FeatureCategory
    stable_id: str
    name: str
    feature_class: int | None = None
    geometry: BaseGeometry = Field(sa_column=sa.Column(ShapelyGeometry('GEOMETRY', srid=4326)))


class GameMapFeature(SQLModel, table=True):
    __tablename__ = 'game_map_feature'  # type: ignore[assignment]

    game_map_id: uuid.UUID = Field(foreign_key='game_map.id', primary_key=True)
    map_feature_id: uuid.UUID = Field(foreign_key='map_feature.id', primary_key=True)
