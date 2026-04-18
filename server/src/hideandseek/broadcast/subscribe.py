"""SSE subscription — lobby and gameplay event streams for connected clients."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

import structlog

from hideandseek.queries.game_state import build_hider_game_state, build_seeker_game_state
from hideandseek.schemas.response import GameResponse
from hideandseek_core.broadcast.emit import (
    SseChannel,
    hider_channel,
    lobby_channel,
    seeker_channel,
)
from hideandseek_core.db import get_session, session_scope
from hideandseek_core.redis_client import get_async_redis
from hideandseek_models.game import Game, Player
from hideandseek_models.types import GameplayEventType, LobbyEventType

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def _read_snapshot_seq(redis, seq_key: str) -> int:  # noqa: ANN001
    """Return the current per-channel sequence counter (0 if unset)."""
    value = await redis.get(seq_key)
    if value is None:
        return 0
    if isinstance(value, bytes):
        value = value.decode()
    return int(value)


async def _forward_messages(
    pubsub,  # noqa: ANN001
    snap_seq: int,
) -> AsyncGenerator[dict, None]:
    """Forward Redis pub/sub messages as SSE dicts, skipping pre-snapshot events.

    Each published envelope looks like ``{"sequence": N, "event": "...", "data": {...}}``.
    Drop events with ``sequence <= snap_seq`` — already reflected in the snapshot —
    so the client sees a clean, monotonically increasing id sequence.
    """
    async for message in pubsub.listen():
        if message['type'] != 'message':
            continue
        raw = message['data']
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')
        parsed = json.loads(raw)
        seq = int(parsed['sequence'])
        if seq <= snap_seq:
            continue
        yield {
            'event': parsed['event'],
            'data': json.dumps(parsed['data']),
            'id': str(seq),
        }


async def lobby_event_stream(game_id: uuid.UUID) -> AsyncGenerator[dict, None]:
    """High-level SSE stream for the lobby.

    1. Subscribe to Redis channel BEFORE DB fetch (prevents race conditions).
    2. Read the current sequence counter.
    3. Fetch game state in a short-lived Session, yield as initial ``game_state``.
    4. Forward Redis messages, skipping any with sequence <= snapshot seq.
    """
    redis = get_async_redis()
    if redis is None:
        msg = 'Redis unavailable — cannot subscribe to lobby events'
        raise RuntimeError(msg)

    pubsub = redis.pubsub()
    channel = lobby_channel(game_id)
    await pubsub.subscribe(channel.pubsub)
    logger.info('sse_subscribed', game_id=str(game_id), channel=channel.pubsub)

    try:
        snap_seq = await _read_snapshot_seq(redis, channel.seq)

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
            'id': str(snap_seq),
        }

        async for frame in _forward_messages(pubsub, snap_seq):
            yield frame
    finally:
        await pubsub.unsubscribe(channel.pubsub)
        await pubsub.aclose()
        await redis.aclose()
        logger.info('sse_unsubscribed', game_id=str(game_id), channel=channel.pubsub)


async def _gameplay_state_stream(
    game_id: uuid.UUID,
    player_id: uuid.UUID,
    channel: SseChannel,
    build_snapshot,  # noqa: ANN001
) -> AsyncGenerator[dict, None]:
    """Shared gameplay SSE streaming loop for hider and seeker channels."""
    redis = get_async_redis()
    if redis is None:
        msg = 'Redis unavailable — cannot subscribe to gameplay events'
        raise RuntimeError(msg)

    pubsub = redis.pubsub()
    await pubsub.subscribe(channel.pubsub)
    logger.info('sse_subscribed', game_id=str(game_id), channel=channel.pubsub)

    try:
        snap_seq = await _read_snapshot_seq(redis, channel.seq)

        with session_scope():
            game = get_session().get(Game, game_id)
            player = get_session().get(Player, player_id)
            if game is None or player is None:
                return
            state_data = build_snapshot(game, player).model_dump(mode='json')

        yield {
            'event': GameplayEventType.game_state,
            'data': json.dumps(state_data),
            'id': str(snap_seq),
        }

        async for frame in _forward_messages(pubsub, snap_seq):
            yield frame
    finally:
        await pubsub.unsubscribe(channel.pubsub)
        await pubsub.aclose()
        await redis.aclose()
        logger.info('sse_unsubscribed', game_id=str(game_id), channel=channel.pubsub)


async def hider_state_stream(
    game_id: uuid.UUID, player_id: uuid.UUID
) -> AsyncGenerator[dict, None]:
    """SSE stream for hider gameplay state."""
    async for frame in _gameplay_state_stream(
        game_id, player_id, hider_channel(game_id), build_hider_game_state
    ):
        yield frame


async def seeker_state_stream(
    game_id: uuid.UUID, player_id: uuid.UUID
) -> AsyncGenerator[dict, None]:
    """SSE stream for seeker gameplay state."""
    async for frame in _gameplay_state_stream(
        game_id, player_id, seeker_channel(game_id), build_seeker_game_state
    ):
        yield frame
