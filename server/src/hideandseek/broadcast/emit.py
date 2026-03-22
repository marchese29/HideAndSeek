"""Publish lobby events to Redis (SSE channel) and/or push (Celery task)."""

from __future__ import annotations

import json
import uuid

import structlog

from hideandseek.broadcast.events import (
    GameStartedEvent,
    HostChangedEvent,
    LobbyEvent,
    PlayerJoinedEvent,
    PlayerLeftEvent,
    PlayerUpdatedEvent,
)
from hideandseek.models.types import LobbyEventType, PushEventType
from hideandseek.redis_client import get_sync_redis
from hideandseek.schemas.response import GameResponse, PlayerResponse

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _lobby_channel(game_id: uuid.UUID) -> str:
    return f'game:{game_id}:lobby:events'


def _publish_sse(game_id: uuid.UUID, event_type: str, data: dict, *, required: bool) -> None:
    """Publish a serialized event to the Redis SSE channel.

    required=True: exception propagates (lobby-only events — no fallback).
    required=False: log and swallow (dual-channel events — push still delivers).
    """
    client = get_sync_redis()
    if client is None:
        if required:
            msg = 'Redis unavailable for required SSE event'
            raise RuntimeError(msg)
        logger.warning('sse_publish_skipped', event_type=event_type, reason='redis_unavailable')
        return

    message = json.dumps({'event': event_type, 'data': data})
    try:
        client.publish(_lobby_channel(game_id), message)
    except Exception:
        if required:
            raise
        logger.exception('sse_publish_failed', event_type=event_type, game_id=str(game_id))


def emit(event: LobbyEvent) -> None:
    """Route a lobby event to the appropriate channels (SSE and/or push)."""
    match event:
        case PlayerJoinedEvent(game=game, player=player):
            data = PlayerResponse.from_model(player).model_dump(mode='json')
            _publish_sse(game.id, LobbyEventType.player_joined, data, required=True)

        case PlayerUpdatedEvent(game=game, player=player):
            data = PlayerResponse.from_model(player).model_dump(mode='json')
            _publish_sse(game.id, LobbyEventType.player_updated, data, required=True)

        case PlayerLeftEvent(game=game, player_id=player_id):
            data = {'player_id': str(player_id)}
            _publish_sse(game.id, LobbyEventType.player_left, data, required=True)

        case HostChangedEvent(game=game, new_host_player_id=new_host_player_id):
            data = {'new_host_player_id': str(new_host_player_id)}
            _publish_sse(game.id, LobbyEventType.host_changed, data, required=True)

        case GameStartedEvent(game=game):
            data = GameResponse.from_model(game).model_dump(mode='json')
            # SSE is best-effort for game_started — push is the primary channel
            _publish_sse(game.id, LobbyEventType.game_started, data, required=False)
            # Push via Celery
            from hideandseek.tasks.push import send_push  # noqa: PLC0415

            send_push.delay(  # type: ignore[attr-defined]
                str(game.id),
                PushEventType.game_started,
                alert='Game on! The hiding phase has begun.',
            )
