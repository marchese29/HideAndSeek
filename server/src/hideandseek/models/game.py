import uuid
from datetime import UTC, datetime
from typing import Optional

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel

from hideandseek.models.types import GameStatus, PlayerRole


class Game(SQLModel, table=True):
    __tablename__ = 'game'  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    map_id: uuid.UUID = Field(foreign_key='game_map.id')
    host_client_id: uuid.UUID
    status: GameStatus = GameStatus.lobby
    join_code: str | None = Field(default=None, sa_column_kwargs={'unique': True, 'index': True})
    timing: dict = Field(default_factory=dict, sa_type=sa.JSON)  # TimingRules
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    hiding_started_at: datetime | None = None
    seeking_started_at: datetime | None = None
    hider_station_id: uuid.UUID | None = Field(default=None, foreign_key='stop.id')
    hiding_zone_radius_override: float | None = None

    game_map: 'GameMap' = Relationship(back_populates='games')  # noqa: F821
    hider_station: Optional['Stop'] = Relationship()  # noqa: F821
    players: list['Player'] = Relationship(back_populates='game')
    questions: list['Question'] = Relationship(back_populates='game')  # noqa: F821
    inventory_slots: list['InventorySlot'] = Relationship(  # noqa: F821
        back_populates='game',
        sa_relationship_kwargs={'order_by': 'InventorySlot.slot_index'},
    )
    category_usages: list['CategoryUsage'] = Relationship(back_populates='game')  # noqa: F821


class Player(SQLModel, table=True):
    __tablename__ = 'player'  # type: ignore[assignment]
    __table_args__ = (sa.UniqueConstraint('client_id', 'game_id'),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    client_id: uuid.UUID
    game_id: uuid.UUID = Field(foreign_key='game.id')
    name: str
    color: str
    role: PlayerRole | None = None

    game: Game = Relationship(back_populates='players')
    location_updates: list['LocationUpdate'] = Relationship(  # noqa: F821
        back_populates='player',
    )


# Avoid circular imports — resolved at runtime by SQLModel.
from hideandseek.models.game_map import GameMap  # noqa: E402
from hideandseek.models.inventory import CategoryUsage, InventorySlot  # noqa: E402
from hideandseek.models.location import LocationUpdate  # noqa: E402
from hideandseek.models.question import Question  # noqa: E402
from hideandseek.models.transit import Stop  # noqa: E402

__all__ = [
    'CategoryUsage',
    'Game',
    'GameMap',
    'InventorySlot',
    'LocationUpdate',
    'Player',
    'Question',
    'Stop',
]
