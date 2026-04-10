from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from shapely.geometry import MultiPolygon
from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hideandseek_models.base import Base
from hideandseek_models.geo_types import ShapelyGeometry
from hideandseek_models.types import DistanceConvention, MapSize

if TYPE_CHECKING:
    from hideandseek_models.game import Game
    from hideandseek_models.transit import TransitDataset


class GameMap(Base):
    __tablename__ = 'game_map'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str]
    size: Mapped[MapSize]
    convention: Mapped[DistanceConvention] = mapped_column(default=DistanceConvention.metric)
    transit_dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('transit_dataset.id'))
    boundary: Mapped[MultiPolygon] = mapped_column(ShapelyGeometry('MULTIPOLYGON', srid=4326))
    districts: Mapped[list] = mapped_column(JSON, default=list)
    district_classes: Mapped[list] = mapped_column(JSON, default=list)
    default_inventory: Mapped[dict] = mapped_column(JSON, default=dict)
    default_hiding_time_min: Mapped[int | None] = mapped_column(default=None)
    default_base_question_delay_min: Mapped[int | None] = mapped_column(default=None)
    hiding_zone_radius: Mapped[float | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(default=None)

    transit_dataset: Mapped[TransitDataset] = relationship()

    games: Mapped[list[Game]] = relationship(back_populates='game_map')
