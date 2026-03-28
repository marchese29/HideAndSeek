"""Shared FastAPI dependencies for the HideAndSeek API."""

from __future__ import annotations

import uuid

import structlog
from fastapi import Depends, Header, HTTPException, Path, Request

from hideandseek.db import get_session
from hideandseek.models.game import Game, Player
from hideandseek.models.types import PlayerRole

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def get_authenticated_player_id(
    x_player_id: uuid.UUID = Header(),
    x_player_secret: str = Header(),
) -> uuid.UUID:
    """Extract and validate X-Player-Id + X-Player-Secret headers.

    Looks up the Player by PK and verifies the secret hash.
    """
    session = get_session()
    player = session.get(Player, x_player_id)
    if player is None or not player.verify_secret(x_player_secret):
        raise HTTPException(status_code=401, detail='Invalid or unknown player credentials.')
    return x_player_id


def get_game(
    game_id: uuid.UUID = Path(),
) -> Game:
    """Resolve game_id path param to a Game, or 404.

    Requires the session ContextVar to be set (via router-level
    ``dependencies=[Depends(session_dependency)]``).
    """
    session = get_session()
    game = session.get(Game, game_id)
    if not game:
        logger.warning('game_not_found', game_id=str(game_id))
        raise HTTPException(status_code=404, detail='Game not found.')
    return game


def get_player_in_game(
    game: Game = Depends(get_game),
    player_id: uuid.UUID = Depends(get_authenticated_player_id),
) -> Player:
    """Resolve the calling player via authenticated player_id + game, or 403."""
    session = get_session()
    player = session.get(Player, player_id)
    if not player or player.game_id != game.id:
        logger.warning('player_not_in_game', player_id=str(player_id), game_id=str(game.id))
        raise HTTPException(status_code=403, detail='You are not a player in this game.')
    return player


def get_hider_in_game(
    player: Player = Depends(get_player_in_game),
) -> Player:
    """Resolve the calling player and verify they are the hider, or 403."""
    if player.role != PlayerRole.hider:
        raise HTTPException(status_code=403, detail='Only hiders can access this endpoint.')
    return player


def get_seeker_in_game(
    player: Player = Depends(get_player_in_game),
) -> Player:
    """Resolve the calling player and verify they are a seeker, or 403."""
    if player.role != PlayerRole.seeker:
        raise HTTPException(status_code=403, detail='Only seekers can access this endpoint.')
    return player


def get_optional_player_id(request: Request) -> uuid.UUID | None:
    """Extract and validate X-Player-Id + X-Player-Secret if present, otherwise None."""
    raw_id = request.headers.get('x-player-id')
    raw_secret = request.headers.get('x-player-secret')
    if raw_id is None or raw_secret is None:
        return None
    try:
        player_id = uuid.UUID(raw_id)
    except ValueError:
        return None
    session = get_session()
    player = session.get(Player, player_id)
    if player is None or not player.verify_secret(raw_secret):
        return None
    return player_id


def get_optional_player_in_game(
    game: Game = Depends(get_game),
    player_id: uuid.UUID | None = Depends(get_optional_player_id),
) -> Player | None:
    """Resolve the calling player if auth headers are present, otherwise None."""
    if player_id is None:
        return None
    session = get_session()
    player = session.get(Player, player_id)
    if not player or player.game_id != game.id:
        return None
    return player
