"""Typed lobby event dataclasses."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
