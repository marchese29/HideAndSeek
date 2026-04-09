from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hideandseek_models.base import Base
from hideandseek_models.types import (
    GameStatus,
    MapSize,
    PlayerColor,
    PlayerRole,
    StationElectionStatus,
)

if TYPE_CHECKING:
    from hideandseek_models.game_map import GameMap
    from hideandseek_models.inventory import InventorySlot
    from hideandseek_models.transit import Stop


class Game(Base):
    __tablename__ = 'game'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    map_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('game_map.id'))
    host_player_id: Mapped[uuid.UUID]
    status: Mapped[GameStatus] = mapped_column(default=GameStatus.lobby)
    join_code: Mapped[str | None] = mapped_column(unique=True, index=True, default=None)
    hiding_time_min: Mapped[int] = mapped_column(default=60)
    base_question_delay_min: Mapped[int] = mapped_column(default=5)
    size: Mapped[MapSize] = mapped_column(default=MapSize.medium)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    hiding_started_at: Mapped[datetime | None] = mapped_column(default=None)
    seeking_started_at: Mapped[datetime | None] = mapped_column(default=None)
    hider_station_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('stop.id'), default=None)
    station_election_status: Mapped[StationElectionStatus] = mapped_column(
        default=StationElectionStatus.pending
    )
    excluded_stop_ids: Mapped[list] = mapped_column(sa.JSON, default=list)
    excluded_route_ids: Mapped[list] = mapped_column(sa.JSON, default=list)
    hiding_zone_radius_override: Mapped[float | None] = mapped_column(default=None)

    game_map: Mapped[GameMap] = relationship(back_populates='games')
    hider_station: Mapped[Stop | None] = relationship()
    players: Mapped[list[Player]] = relationship(back_populates='game')
    inventory_slots: Mapped[list[InventorySlot]] = relationship(
        back_populates='game',
        order_by='InventorySlot.slot_index',
    )


class Player(Base):
    __tablename__ = 'player'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('game.id'))
    name: Mapped[str]
    color: Mapped[PlayerColor]
    role: Mapped[PlayerRole | None] = mapped_column(default=None)
    secret_hash: Mapped[str] = mapped_column(default='')

    game: Mapped[Game] = relationship(back_populates='players')

    def verify_secret(self, secret: str) -> bool:
        """Verify a raw secret against the stored SHA-256 hash."""
        actual_hash = hashlib.sha256(secret.encode()).hexdigest()
        return hmac.compare_digest(actual_hash, self.secret_hash)
