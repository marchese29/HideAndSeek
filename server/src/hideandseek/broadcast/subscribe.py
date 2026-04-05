"""SSE subscription — lobby and gameplay event streams for connected clients."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

import structlog

from hideandseek.queries.game_state import build_hider_game_state, build_seeker_game_state
from hideandseek.schemas.response import GameResponse
from hideandseek_core.db import get_session, session_scope
from hideandseek_core.redis_client import get_async_redis
from hideandseek_models.game import Game, Player
from hideandseek_models.types import GameplayEventType, LobbyEventType

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _lobby_channel(game_id: uuid.UUID) -> str:
    return f'game:{game_id}:lobby:events'


def _hider_channel(game_id: uuid.UUID) -> str:
    return f'game:{game_id}:hider-events'


def _seeker_channel(game_id: uuid.UUID) -> str:
    return f'game:{game_id}:seeker-events'


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


async def hider_state_stream(
    game_id: uuid.UUID, player_id: uuid.UUID
) -> AsyncGenerator[dict, None]:
    """SSE stream for hider gameplay state.

    1. Subscribe to Redis hider channel BEFORE DB fetch.
    2. Fetch full hider state, yield as initial ``game_state``.
    3. Forward Redis messages as SSE events.
    """
    redis = get_async_redis()
    if redis is None:
        msg = 'Redis unavailable — cannot subscribe to hider events'
        raise RuntimeError(msg)

    pubsub = redis.pubsub()
    channel = _hider_channel(game_id)
    await pubsub.subscribe(channel)
    logger.info('sse_subscribed', game_id=str(game_id), channel=channel)

    try:
        with session_scope():
            game = get_session().get(Game, game_id)
            player = get_session().get(Player, player_id)
            if game is None or player is None:
                return
            state_data = build_hider_game_state(game, player).model_dump(mode='json')

        yield {
            'event': GameplayEventType.game_state,
            'data': json.dumps(state_data),
        }

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


async def seeker_state_stream(
    game_id: uuid.UUID, player_id: uuid.UUID
) -> AsyncGenerator[dict, None]:
    """SSE stream for seeker gameplay state.

    1. Subscribe to Redis seeker channel BEFORE DB fetch.
    2. Fetch full seeker state, yield as initial ``game_state``.
    3. Forward Redis messages as SSE events.
    """
    redis = get_async_redis()
    if redis is None:
        msg = 'Redis unavailable — cannot subscribe to seeker events'
        raise RuntimeError(msg)

    pubsub = redis.pubsub()
    channel = _seeker_channel(game_id)
    await pubsub.subscribe(channel)
    logger.info('sse_subscribed', game_id=str(game_id), channel=channel)

    try:
        with session_scope():
            game = get_session().get(Game, game_id)
            player = get_session().get(Player, player_id)
            if game is None or player is None:
                return
            state_data = build_seeker_game_state(game, player).model_dump(mode='json')

        yield {
            'event': GameplayEventType.game_state,
            'data': json.dumps(state_data),
        }

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
