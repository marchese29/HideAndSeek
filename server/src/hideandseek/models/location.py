from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from shapely.geometry import Point
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hideandseek.models.base import Base
from hideandseek.models.geo_types import ShapelyGeometry

if TYPE_CHECKING:
    from hideandseek.models.game import Game, Player


class LocationUpdate(Base):
    __tablename__ = 'location_update'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('player.id'))
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('game.id'))
    timestamp: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    coordinates: Mapped[Point] = mapped_column(ShapelyGeometry('POINT', srid=4326))

    player: Mapped[Player] = relationship(back_populates='location_updates')
    game: Mapped[Game] = relationship()
