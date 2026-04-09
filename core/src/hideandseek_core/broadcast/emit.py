"""Publish gameplay events to Redis SSE channels."""

from __future__ import annotations

import json
import uuid

import structlog

from hideandseek_core.broadcast.events import (
    GameDissolvedEvent,
    GameHostChangedEvent,
    GamePlayerLeftEvent,
    GameplayEvent,
    HiderQuestionAnsweredEvent,
    PhaseChangedEvent,
    PlayerLocationEvent,
    QuestionAbandonedEvent,
    QuestionAnswerableEvent,
    QuestionAskedEvent,
    QuestionVetoedEvent,
    SeekerQuestionAnsweredEvent,
    StationElectionEvent,
)
from hideandseek_core.redis_client import get_sync_redis
from hideandseek_models.types import GameplayEventType, PlayerRole

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def lobby_channel(game_id: uuid.UUID) -> str:
    """Redis channel name for lobby events."""
    return f'game:{game_id}:lobby:events'


def hider_channel(game_id: uuid.UUID) -> str:
    """Redis channel name for hider gameplay events."""
    return f'game:{game_id}:hider-events'


def seeker_channel(game_id: uuid.UUID) -> str:
    """Redis channel name for seeker gameplay events."""
    return f'game:{game_id}:seeker-events'


def publish_sse(channel: str, event_type: str, data: dict, *, required: bool) -> None:
    """Publish a serialized event to a Redis SSE channel.

    required=True: exception propagates (no fallback).
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
        client.publish(channel, message)
    except Exception:
        if required:
            raise
        logger.exception('sse_publish_failed', event_type=event_type, channel=channel)


def _both_channels(game_id: uuid.UUID, event_type: str, data: dict) -> None:
    """Publish identical data to both hider and seeker channels."""
    publish_sse(hider_channel(game_id), event_type, data, required=True)
    publish_sse(seeker_channel(game_id), event_type, data, required=True)


def emit_gameplay(event: GameplayEvent) -> None:
    """Route a gameplay event to the appropriate SSE channels."""
    match event:
        case PlayerLocationEvent():
            data = event.model_dump(mode='json')
            publish_sse(
                hider_channel(event.game_id),
                GameplayEventType.player_location,
                data,
                required=True,
            )
            if event.role == PlayerRole.seeker:
                publish_sse(
                    seeker_channel(event.game_id),
                    GameplayEventType.player_location,
                    data,
                    required=True,
                )

        case QuestionAskedEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.question_asked, data)

        case QuestionAnswerableEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.question_answerable, data)

        case HiderQuestionAnsweredEvent():
            data = event.model_dump(mode='json')
            publish_sse(
                hider_channel(event.game_id),
                GameplayEventType.question_answered,
                data,
                required=True,
            )

        case SeekerQuestionAnsweredEvent():
            data = event.model_dump(mode='json')
            publish_sse(
                seeker_channel(event.game_id),
                GameplayEventType.question_answered,
                data,
                required=True,
            )

        case QuestionVetoedEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.question_vetoed, data)

        case QuestionAbandonedEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.question_abandoned, data)

        case PhaseChangedEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.phase_changed, data)

        case StationElectionEvent():
            data = event.model_dump(mode='json')
            publish_sse(
                hider_channel(event.game_id),
                GameplayEventType.station_election,
                data,
                required=True,
            )

        case GamePlayerLeftEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.player_left, data)

        case GameHostChangedEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.host_changed, data)

        case GameDissolvedEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.game_dissolved, data)
