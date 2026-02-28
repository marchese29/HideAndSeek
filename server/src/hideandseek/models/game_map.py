import uuid

import sqlalchemy as sa
from shapely.geometry import Polygon
from sqlmodel import Field, Relationship, SQLModel

from hideandseek.models.geo_types import ShapelyGeometry
from hideandseek.models.types import DistanceConvention, MapSize


class GameMap(SQLModel, table=True):
    model_config = {'arbitrary_types_allowed': True}  # type: ignore[assignment]
    __tablename__ = 'game_map'  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    size: MapSize
    convention: DistanceConvention = DistanceConvention.metric
    transit_dataset_id: uuid.UUID = Field(foreign_key='transit_dataset.id')
    boundary: Polygon = Field(sa_column=sa.Column(ShapelyGeometry('POLYGON', srid=4326)))
    districts: list = Field(default_factory=list, sa_type=sa.JSON)
    district_classes: list = Field(default_factory=list, sa_type=sa.JSON)
    feature_classes: list = Field(default_factory=list, sa_type=sa.JSON)
    default_inventory: dict = Field(default_factory=dict, sa_type=sa.JSON)
    hiding_zone_radius: float | None = None
    notes: str | None = None

    transit_dataset: 'TransitDataset' = Relationship()  # noqa: F821

    games: list['Game'] = Relationship(back_populates='game_map')  # noqa: F821


# Avoid circular imports — these are resolved at runtime by SQLModel.
from hideandseek.models.game import Game  # noqa: E402
from hideandseek.models.transit import TransitDataset  # noqa: E402

__all__ = ['GameMap', 'Game', 'TransitDataset']
