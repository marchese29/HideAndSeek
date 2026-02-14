import uuid

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel

from hideandseek.models.types import MapSize


class GameMap(SQLModel, table=True):
    __tablename__ = 'game_map'  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    size: MapSize
    transit_dataset_id: uuid.UUID = Field(foreign_key='transit_dataset.id')
    boundary: dict = Field(sa_type=sa.JSON)  # GeoJSON Polygon
    excluded_stop_ids: list = Field(default_factory=list, sa_type=sa.JSON)
    excluded_route_ids: list = Field(default_factory=list, sa_type=sa.JSON)
    districts: list = Field(default_factory=list, sa_type=sa.JSON)
    district_classes: list = Field(default_factory=list, sa_type=sa.JSON)
    default_inventory: dict = Field(default_factory=dict, sa_type=sa.JSON)
    notes: str | None = None

    transit_dataset: 'TransitDataset' = Relationship()  # noqa: F821

    games: list['Game'] = Relationship(back_populates='game_map')  # noqa: F821


# Avoid circular imports — these are resolved at runtime by SQLModel.
from hideandseek.models.game import Game  # noqa: E402
from hideandseek.models.transit import TransitDataset  # noqa: E402

__all__ = ['GameMap', 'Game', 'TransitDataset']
