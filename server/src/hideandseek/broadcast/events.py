"""Typed lobby and gameplay event dataclasses."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from hideandseek.models.types import PlayerColor, PlayerRole

if TYPE_CHECKING:
    from hideandseek.models.game import Game, Player


@dataclass(frozen=True, slots=True)
class PlayerJoinedEvent:
    game: Game
    player: Player


@dataclass(frozen=True, slots=True)
class PlayerUpdatedEvent:
    game: Game
    player: Player


@dataclass(frozen=True, slots=True)
class PlayerLeftEvent:
    game: Game
    player_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class HostChangedEvent:
    game: Game
    new_host_player_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class GameStartedEvent:
    game: Game


LobbyEvent = (
    PlayerJoinedEvent | PlayerUpdatedEvent | PlayerLeftEvent | HostChangedEvent | GameStartedEvent
)


@dataclass(frozen=True, slots=True)
class PlayerLocationEvent:
    game_id: uuid.UUID
    player_id: uuid.UUID
    name: str
    color: PlayerColor
    role: PlayerRole
    coordinates: dict  # Pre-serialized GeoJSON Point
    timestamp: datetime


GameplayEvent = PlayerLocationEvent
