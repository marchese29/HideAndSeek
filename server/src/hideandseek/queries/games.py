"""Game and player queries."""

from __future__ import annotations

import random
import string
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from hideandseek.conventions import get_default_inventory
from hideandseek.db import get_session
from hideandseek.models.game import Game, Player
from hideandseek.models.game_map import GameMap
from hideandseek.models.transit import Stop
from hideandseek.models.types import (
    DistanceConvention,
    GameStatus,
    MapSize,
    PlayerColor,
    PlayerRole,
    StationElectionStatus,
)
from hideandseek.queries.questions import create_inventory_slots


def generate_join_code(*, length: int = 4, max_attempts: int = 10) -> str:
    """Generate a unique random alphanumeric join code."""
    session = get_session()
    for _ in range(max_attempts):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        existing = session.scalars(select(Game).where(Game.join_code == code)).one_or_none()
        if not existing:
            return code
    msg = f'Failed to generate unique join code after {max_attempts} attempts'
    raise RuntimeError(msg)


def create_game(
    *,
    game_map: GameMap,
    host_client_id: uuid.UUID,
    hiding_time_min: int,
    base_question_delay_min: int,
    default_inventory: dict,
    convention: DistanceConvention = DistanceConvention.metric,
    size: MapSize = MapSize.medium,
    excluded_stop_ids: list[uuid.UUID] | None = None,
    excluded_route_ids: list[uuid.UUID] | None = None,
) -> Game:
    """Create a game with a generated join code and inventory slots from map template.

    When default_inventory is empty, falls back to code-level defaults
    based on the map's convention and size.
    """
    session = get_session()
    game = Game(
        game_map=game_map,
        host_client_id=host_client_id,
        join_code=generate_join_code(),
        hiding_time_min=hiding_time_min,
        base_question_delay_min=base_question_delay_min,
        excluded_stop_ids=[str(sid) for sid in excluded_stop_ids] if excluded_stop_ids else [],
        excluded_route_ids=[str(rid) for rid in excluded_route_ids] if excluded_route_ids else [],
    )
    session.add(game)
    session.flush()  # Materialize game.id for FK references

    inventory = default_inventory if default_inventory else get_default_inventory(convention, size)
    create_inventory_slots(game, inventory)

    return game


def get_game_by_id(game_id: uuid.UUID) -> Game | None:
    """Return a game by ID."""
    session = get_session()
    return session.get(Game, game_id)


def find_game_by_join_code(join_code: str) -> Game | None:
    """Find a game by its join code."""
    session = get_session()
    return session.scalars(select(Game).where(Game.join_code == join_code.upper())).one_or_none()


def add_player(
    game: Game,
    *,
    client_id: uuid.UUID,
    name: str,
    color: PlayerColor,
    role: PlayerRole | None = None,
) -> Player:
    """Create a player in a game via relationship append."""
    session = get_session()
    player = Player(client_id=client_id, name=name, color=color, role=role)
    game.players.append(player)
    session.flush()
    return player


def get_player(player_id: uuid.UUID) -> Player | None:
    """Return a single player by ID."""
    session = get_session()
    return session.get(Player, player_id)


def update_game_status(game: Game, status: GameStatus) -> Game:
    """Update a game's status. Clears join_code when entering hiding."""
    session = get_session()
    game.status = status
    if status == GameStatus.hiding:
        game.hiding_started_at = datetime.now(UTC)
        game.join_code = None
    elif status == GameStatus.seeking:
        game.seeking_started_at = datetime.now(UTC)
    session.add(game)
    session.flush()
    return game


def delete_player(player: Player) -> None:
    """Delete a player row and expire the parent game's player list."""
    session = get_session()
    game = player.game
    session.delete(player)
    session.flush()
    session.expire(game, ['players'])


def set_hider_station(
    game: Game,
    station: Stop,
    status: StationElectionStatus,
) -> None:
    """Set the hider's station and election status on the game."""
    session = get_session()
    game.hider_station = station
    game.station_election_status = status
    session.add(game)
    session.flush()


def set_station_ambiguous(game: Game) -> None:
    """Mark station election as ambiguous (0 or 2+ valid candidates)."""
    session = get_session()
    game.station_election_status = StationElectionStatus.ambiguous
    session.add(game)
    session.flush()
