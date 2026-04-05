"""SSE endpoints for real-time lobby events."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, HTTPException
from sse_starlette.sse import EventSourceResponse

from hideandseek.broadcast.subscribe import (
    hider_state_stream,
    lobby_event_stream,
    seeker_state_stream,
)
from hideandseek.db import get_session, session_scope
from hideandseek_models.game import Game, Player
from hideandseek_models.types import PlayerRole

router = APIRouter(prefix='/games', tags=['games'])


@router.get('/{game_id}/lobby/events', include_in_schema=False)
async def lobby_sse(
    game_id: uuid.UUID,
    x_player_id: uuid.UUID = Header(),
    x_player_secret: str = Header(),
) -> EventSourceResponse:
    """Server-Sent Events stream for lobby updates.

    Yields an initial ``game_state`` event with the full current state,
    then real-time events (player_joined, player_updated, player_left,
    host_changed, game_started) as they occur.
    """
    # Short-lived session for auth — SSE streams outlive the request so we
    # don't use router-level session_dependency.
    with session_scope():
        session = get_session()
        player = session.get(Player, x_player_id)
        if player is None or not player.verify_secret(x_player_secret):
            raise HTTPException(status_code=401, detail='Invalid or unknown player credentials.')
        game = session.get(Game, game_id)
        if game is None:
            raise HTTPException(status_code=404, detail='Game not found.')
        if not game.status.is_lobby:
            raise HTTPException(status_code=409, detail='Game is not in lobby.')
        if player.game_id != game_id:
            raise HTTPException(status_code=403, detail='You are not a player in this game.')

    return EventSourceResponse(lobby_event_stream(game_id), ping=15)


@router.get('/{game_id}/hider-state', include_in_schema=False)
async def hider_state_sse(
    game_id: uuid.UUID,
    x_player_id: uuid.UUID = Header(),
    x_player_secret: str = Header(),
) -> EventSourceResponse:
    """SSE stream for hider gameplay state.

    Yields an initial ``game_state`` event with the full hider snapshot,
    then streams role-appropriate deltas from the hider Redis channel.
    """
    with session_scope():
        session = get_session()
        player = session.get(Player, x_player_id)
        if player is None or not player.verify_secret(x_player_secret):
            raise HTTPException(status_code=401, detail='Invalid or unknown player credentials.')
        game = session.get(Game, game_id)
        if game is None:
            raise HTTPException(status_code=404, detail='Game not found.')
        if not game.status.is_active:
            raise HTTPException(status_code=409, detail='Game is not in an active phase.')
        if player.game_id != game_id:
            raise HTTPException(status_code=403, detail='You are not a player in this game.')
        if player.role != PlayerRole.hider:
            raise HTTPException(status_code=403, detail='Only hiders can access this endpoint.')

    return EventSourceResponse(hider_state_stream(game_id, x_player_id), ping=15)


@router.get('/{game_id}/seeker-state', include_in_schema=False)
async def seeker_state_sse(
    game_id: uuid.UUID,
    x_player_id: uuid.UUID = Header(),
    x_player_secret: str = Header(),
) -> EventSourceResponse:
    """SSE stream for seeker gameplay state.

    Yields an initial ``game_state`` event with the full seeker snapshot,
    then streams role-appropriate deltas from the seeker Redis channel.
    """
    with session_scope():
        session = get_session()
        player = session.get(Player, x_player_id)
        if player is None or not player.verify_secret(x_player_secret):
            raise HTTPException(status_code=401, detail='Invalid or unknown player credentials.')
        game = session.get(Game, game_id)
        if game is None:
            raise HTTPException(status_code=404, detail='Game not found.')
        if not game.status.is_active:
            raise HTTPException(status_code=409, detail='Game is not in an active phase.')
        if player.game_id != game_id:
            raise HTTPException(status_code=403, detail='You are not a player in this game.')
        if player.role != PlayerRole.seeker:
            raise HTTPException(status_code=403, detail='Only seekers can access this endpoint.')

    return EventSourceResponse(seeker_state_stream(game_id, x_player_id), ping=15)
