"""SSE subscription — lobby event stream for connected clients."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

import structlog

from hideandseek.db import get_session, session_scope
from hideandseek.models.game import Game
from hideandseek.models.types import LobbyEventType
from hideandseek.redis_client import get_async_redis
from hideandseek.schemas.response import GameResponse

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _lobby_channel(game_id: uuid.UUID) -> str:
    return f'game:{game_id}:lobby:events'


async def lobby_event_stream(game_id: uuid.UUID) -> AsyncGenerator[dict, None]:
    """High-level SSE stream for the lobby.

    1. Subscribe to Redis channel BEFORE DB fetch (prevents race conditions).
    2. Fetch game state in a short-lived Session, yield as initial `game_state`.
    3. Forward Redis messages as SSE events.
    4. Clean up on disconnect.
    """
    redis = get_async_redis()
    if redis is None:
        msg = 'Redis unavailable — cannot subscribe to lobby events'
        raise RuntimeError(msg)

    pubsub = redis.pubsub()
    channel = _lobby_channel(game_id)
    await pubsub.subscribe(channel)
    logger.info('sse_subscribed', game_id=str(game_id), channel=channel)

    try:
        # Fetch current game state in a short-lived session
        with session_scope():
            game = get_session().get(Game, game_id)
            if game is None:
                return
            game_data = GameResponse.from_model(game).model_dump(mode='json')

        # Yield initial state
        yield {
            'event': LobbyEventType.game_state,
            'data': json.dumps(game_data),
        }

        # Drain Redis subscription and forward events
        async for message in pubsub.listen():
            if message['type'] != 'message':
                continue
            raw = message['data']
            if isinstance(raw, bytes):
                raw = raw.decode('utf-8')
            parsed = json.loads(raw)
            yield {
                'event': parsed['event'],
                'data': json.dumps(parsed['data']),
            }
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await redis.aclose()
        logger.info('sse_unsubscribed', game_id=str(game_id), channel=channel)
