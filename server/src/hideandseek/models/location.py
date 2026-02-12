from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel


class LocationUpdate(SQLModel, table=True):
    __tablename__ = 'location_update'  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    player_id: uuid.UUID = Field(foreign_key='player.id')
    game_id: uuid.UUID = Field(foreign_key='game.id')
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    coordinates: dict = Field(sa_type=sa.JSON)  # GeoJSON Point

    player: Player = Relationship(back_populates='location_updates')  # noqa: F821


# Avoid circular imports — resolved at runtime by SQLModel.
from hideandseek.models.game import Player  # noqa: E402

__all__ = ['LocationUpdate', 'Player']
