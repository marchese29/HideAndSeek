"""SSE endpoints for real-time lobby events."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, HTTPException
from sse_starlette.sse import EventSourceResponse

from hideandseek.broadcast.subscribe import lobby_event_stream
from hideandseek.db import get_session, session_scope
from hideandseek.models.game import Game, Player

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
