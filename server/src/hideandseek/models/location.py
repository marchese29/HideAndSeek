import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from shapely.geometry import Point
from sqlmodel import Field, Relationship, SQLModel

from hideandseek.models.geo_types import ShapelyGeometry


class LocationUpdate(SQLModel, table=True):
    model_config = {'arbitrary_types_allowed': True}  # type: ignore[assignment]
    __tablename__ = 'location_update'  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    player_id: uuid.UUID = Field(foreign_key='player.id')
    game_id: uuid.UUID = Field(foreign_key='game.id')
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    coordinates: Point = Field(sa_column=sa.Column(ShapelyGeometry('POINT', srid=4326)))

    player: 'Player' = Relationship(back_populates='location_updates')  # noqa: F821


# Avoid circular imports — resolved at runtime by SQLModel.
from hideandseek.models.game import Player  # noqa: E402

__all__ = ['LocationUpdate', 'Player']
