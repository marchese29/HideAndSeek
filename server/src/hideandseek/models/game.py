from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel

from hideandseek.models.types import GameStatus, PlayerRole


class Game(SQLModel, table=True):
    __tablename__ = 'game'  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    map_id: uuid.UUID = Field(foreign_key='game_map.id')
    status: GameStatus = GameStatus.lobby
    join_code: str = Field(sa_column_kwargs={'unique': True, 'index': True})
    timing: dict = Field(default_factory=dict, sa_type=sa.JSON)  # TimingRules
    inventory: dict = Field(default_factory=dict, sa_type=sa.JSON)  # QuestionInventory
    created_at: datetime = Field(default_factory=datetime.utcnow)

    game_map: GameMap = Relationship(back_populates='games')  # noqa: F821
    players: list[Player] = Relationship(back_populates='game')
    questions: list[Question] = Relationship(back_populates='game')  # noqa: F821


class Player(SQLModel, table=True):
    __tablename__ = 'player'  # type: ignore[assignment]
    __table_args__ = (sa.UniqueConstraint('client_id', 'game_id'),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    client_id: uuid.UUID
    game_id: uuid.UUID = Field(foreign_key='game.id')
    name: str
    color: str
    role: PlayerRole

    game: Game = Relationship(back_populates='players')
    location_updates: list[LocationUpdate] = Relationship(  # noqa: F821
        back_populates='player',
    )


# Avoid circular imports — resolved at runtime by SQLModel.
from hideandseek.models.game_map import GameMap  # noqa: E402
from hideandseek.models.location import LocationUpdate  # noqa: E402
from hideandseek.models.question import Question  # noqa: E402

__all__ = ['Game', 'Player', 'GameMap', 'LocationUpdate', 'Question']
