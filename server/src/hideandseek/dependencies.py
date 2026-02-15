"""Shared FastAPI dependencies for the HideAndSeek API."""

from __future__ import annotations

import uuid

from fastapi import Depends, Header, HTTPException, Path, Request
from sqlmodel import select

from hideandseek.db import current_session
from hideandseek.models.game import Game, Player
from hideandseek.push import PushService


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
        raise HTTPException(status_code=404, detail='Game not found.')
    return game


def get_push_service(request: Request) -> PushService:
    """Retrieve the PushService from app state."""
    return request.app.state.push_service


def get_player_in_game(
    game: Game = Depends(get_game),
    client_id: uuid.UUID = Depends(get_client_id),
) -> Player:
    """Resolve the calling player via client_id + game, or 403.

    Requires the session ContextVar to be set (via router-level
    ``dependencies=[Depends(get_session)]``).
    """
    session = current_session()
    player = session.exec(
        select(Player).where(Player.client_id == client_id, Player.game_id == game.id)
    ).first()
    if not player:
        raise HTTPException(status_code=403, detail='You are not a player in this game.')
    return player
