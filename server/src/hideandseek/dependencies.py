"""Shared FastAPI dependencies for the HideAndSeek API."""

from __future__ import annotations

import uuid

from fastapi import Depends, Header, HTTPException, Path
from sqlmodel import Session, select

from hideandseek.db import get_session
from hideandseek.models.game import Game, Player


def get_client_id(x_client_id: uuid.UUID = Header()) -> uuid.UUID:
    """Extract and validate the X-Client-Id header."""
    return x_client_id


def get_game(
    game_id: uuid.UUID = Path(),
    session: Session = Depends(get_session),
) -> Game:
    """Resolve game_id path param to a Game, or 404."""
    game = session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail='Game not found.')
    return game


def get_player_in_game(
    game: Game = Depends(get_game),
    client_id: uuid.UUID = Depends(get_client_id),
    session: Session = Depends(get_session),
) -> Player:
    """Resolve the calling player via client_id + game, or 403."""
    player = session.exec(
        select(Player).where(Player.client_id == client_id, Player.game_id == game.id)
    ).first()
    if not player:
        raise HTTPException(status_code=403, detail='You are not a player in this game.')
    return player
