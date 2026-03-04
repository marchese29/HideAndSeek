"""Shared FastAPI dependencies for the HideAndSeek API."""

from __future__ import annotations

import uuid

import structlog
from fastapi import Depends, Header, HTTPException, Path, Request
from sqlalchemy import select

from hideandseek.db import current_session
from hideandseek.models.game import Game, Player
from hideandseek.models.types import PlayerRole

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def get_client_id(x_client_id: uuid.UUID = Header()) -> uuid.UUID:
    """Extract and validate the X-Client-Id header."""
    return x_client_id


def get_game(
    game_id: uuid.UUID = Path(),
) -> Game:
    """Resolve game_id path param to a Game, or 404.

    Requires the session ContextVar to be set (via router-level
    ``dependencies=[Depends(get_session)]``).
    """
    session = current_session()
    game = session.get(Game, game_id)
    if not game:
        logger.warning('game_not_found', game_id=str(game_id))
        raise HTTPException(status_code=404, detail='Game not found.')
    return game


def get_player_in_game(
    game: Game = Depends(get_game),
    client_id: uuid.UUID = Depends(get_client_id),
) -> Player:
    """Resolve the calling player via client_id + game, or 403.

    Requires the session ContextVar to be set (via router-level
    ``dependencies=[Depends(get_session)]``).
    """
    session = current_session()
    player = session.scalars(
        select(Player).where(Player.client_id == client_id, Player.game_id == game.id)
    ).one_or_none()
    if not player:
        logger.warning('player_not_in_game', client_id=str(client_id), game_id=str(game.id))
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


def get_optional_client_id(request: Request) -> uuid.UUID | None:
    """Extract X-Client-Id header if present, otherwise None."""
    raw = request.headers.get('x-client-id')
    if raw is None:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def get_optional_player_in_game(
    game: Game = Depends(get_game),
    client_id: uuid.UUID | None = Depends(get_optional_client_id),
) -> Player | None:
    """Resolve the calling player if X-Client-Id is present, otherwise None."""
    if client_id is None:
        return None
    session = current_session()
    return session.scalars(
        select(Player).where(Player.client_id == client_id, Player.game_id == game.id)
    ).one_or_none()
