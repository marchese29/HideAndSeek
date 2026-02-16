"""Game and player queries."""

from __future__ import annotations

import random
import string
import uuid
from datetime import UTC, datetime

from sqlmodel import Session, select

from hideandseek.db import db_read, db_write
from hideandseek.models.game import Game, Player
from hideandseek.models.types import GameStatus


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
    timing: dict,
    inventory: dict,
) -> Game:
    """Create a game with a generated join code."""
    game = Game(
        map_id=map_id,
        host_client_id=host_client_id,
        join_code=generate_join_code(),
        timing=timing,
        inventory=inventory,
    )
    session.add(game)
    return game


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
) -> Player:
    """Create a player in a game via relationship append."""
    player = Player(client_id=client_id, game_id=game.id, name=name, color=color)
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
def update_game_status(
    session: Session, game: Game, status: GameStatus, *, clear_join_code: bool = False
) -> Game:
    """Update a game's status (and optionally clear join_code)."""
    game.status = status
    if status == GameStatus.hiding:
        game.hiding_started_at = datetime.now(UTC)
    elif status == GameStatus.seeking:
        game.seeking_started_at = datetime.now(UTC)
    if clear_join_code:
        game.join_code = None
    session.add(game)
    return game
