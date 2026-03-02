"""Game and player queries."""

from __future__ import annotations

import random
import string
import uuid
from datetime import UTC, datetime

from sqlmodel import Session, select

from hideandseek.conventions import get_default_inventory
from hideandseek.db import db_read, db_write
from hideandseek.models.game import Game, Player
from hideandseek.models.types import (
    DistanceConvention,
    GameStatus,
    MapSize,
    PlayerRole,
    StationElectionStatus,
)
from hideandseek.queries.questions import create_inventory_slots


@db_read
def generate_join_code(session: Session, *, length: int = 4, max_attempts: int = 10) -> str:
    """Generate a unique random alphanumeric join code."""
    for _ in range(max_attempts):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        existing = session.exec(select(Game).where(Game.join_code == code)).first()
        if not existing:
            return code
    msg = f'Failed to generate unique join code after {max_attempts} attempts'
    raise RuntimeError(msg)


@db_write
def create_game(
    session: Session,
    *,
    map_id: uuid.UUID,
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
    game = Game(
        map_id=map_id,
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
    create_inventory_slots(game.id, inventory)

    return game


@db_read
def get_game_by_id(session: Session, game_id: uuid.UUID) -> Game | None:
    """Return a game by ID."""
    return session.get(Game, game_id)


@db_read
def find_game_by_join_code(session: Session, join_code: str) -> Game | None:
    """Find a game by its join code."""
    return session.exec(select(Game).where(Game.join_code == join_code.upper())).first()


@db_write
def add_player(
    session: Session,
    game: Game,
    *,
    client_id: uuid.UUID,
    name: str,
    color: str,
    role: PlayerRole | None = None,
) -> Player:
    """Create a player in a game via relationship append."""
    player = Player(client_id=client_id, game_id=game.id, name=name, color=color, role=role)
    game.players.append(player)
    return player


@db_read
def get_player(session: Session, player_id: uuid.UUID) -> Player | None:
    """Return a single player by ID."""
    return session.get(Player, player_id)


@db_write
def update_player(session: Session, player: Player, updates: dict) -> Player:
    """Apply partial updates to a player."""
    for key, value in updates.items():
        setattr(player, key, value)
    session.add(player)
    return player


@db_write
def update_game_status(session: Session, game: Game, status: GameStatus) -> Game:
    """Update a game's status. Clears join_code when entering hiding."""
    game.status = status
    if status == GameStatus.hiding:
        game.hiding_started_at = datetime.now(UTC)
        game.join_code = None
    elif status == GameStatus.seeking:
        game.seeking_started_at = datetime.now(UTC)
    session.add(game)
    return game


@db_write
def set_hider_station(
    session: Session,
    game: Game,
    station_id: uuid.UUID,
    status: StationElectionStatus,
) -> None:
    """Set the hider's station and election status on the game."""
    game.hider_station_id = station_id
    game.station_election_status = status
    session.add(game)


@db_write
def set_station_ambiguous(session: Session, game: Game) -> None:
    """Mark station election as ambiguous (0 or 2+ valid candidates)."""
    game.station_election_status = StationElectionStatus.ambiguous
    session.add(game)
