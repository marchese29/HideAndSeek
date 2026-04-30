"""Publish gameplay events to Redis SSE channels.

Two public entry points share one routing implementation:

- `emit_gameplay(event)` — buffers the event on the active session and publishes
  after `Session.commit()` lands. This is the safe default for any code path
  running inside `session_dependency` (router) or `session_scope` (worker /
  script). If the transaction rolls back, buffered events are dropped silently.
- `emit_gameplay_now(event)` — publishes immediately, no transactional gating.
  Reserved for worker timer task bodies where the reconciler's retry loop makes
  leaked events self-healing. Don't use in routers.

The corresponding pair for lobby events lives in `server/broadcast/emit.py`.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import NamedTuple

import structlog
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from hideandseek_core import db
from hideandseek_core.broadcast.events import (
    FoundClaimEvent,
    FoundClaimExpiredEvent,
    FoundClaimRejectedEvent,
    GameDissolvedEvent,
    GameEndedEvent,
    GameHostChangedEvent,
    GamePlayerLeftEvent,
    GameplayEvent,
    GameTimerPausedEvent,
    GameTimerResumedEvent,
    HiderQuestionAnsweredEvent,
    HidingZoneExpandedEvent,
    PhaseChangedEvent,
    PhotoQueuedEvent,
    PhotoRejectedEvent,
    PhotoSubmittedEvent,
    PhotoUnqueuedEvent,
    PlayerLocationEvent,
    ProximityDeescalatedEvent,
    ProximityEscalatedEvent,
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

_PENDING_KEY = 'pending_gameplay_emits'


class SseChannel(NamedTuple):
    """Pair of Redis keys for one SSE channel: pub/sub channel name + monotonic seq counter."""

    pubsub: str
    seq: str


def lobby_channel(game_id: uuid.UUID) -> SseChannel:
    """Redis keys for lobby events (pub/sub channel + sequence counter)."""
    return SseChannel(
        pubsub=f'game:{game_id}:lobby:events',
        seq=f'game:{game_id}:lobby:seq',
    )


def hider_channel(game_id: uuid.UUID) -> SseChannel:
    """Redis keys for hider gameplay events."""
    return SseChannel(
        pubsub=f'game:{game_id}:hider-events',
        seq=f'game:{game_id}:hider:seq',
    )


def seeker_channel(game_id: uuid.UUID) -> SseChannel:
    """Redis keys for seeker gameplay events."""
    return SseChannel(
        pubsub=f'game:{game_id}:seeker-events',
        seq=f'game:{game_id}:seeker:seq',
    )


# Lua: atomically increment the per-channel sequence and publish an envelope
# that carries the sequence alongside event type + pre-serialized data JSON.
# Keeping INCR + PUBLISH in one round-trip guarantees the sequence embedded in
# the message matches its pub/sub delivery order even when multiple publishers
# contend on the same channel.
_INCR_AND_PUBLISH_LUA = """
local seq = redis.call('INCR', KEYS[1])
local msg = '{"sequence":' .. seq .. ',"event":"' .. ARGV[1] .. '","data":' .. ARGV[2] .. '}'
redis.call('PUBLISH', KEYS[2], msg)
return seq
"""

# event_type values come from our own enums (GameplayEventType, LobbyEventType).
# Validate here as defense in depth since the Lua script splices them as-is.
_EVENT_TYPE_RE = re.compile(r'^[a-z][a-z0-9_]*$')


def publish_sse(
    channel: SseChannel,
    event_type: str,
    data: dict,
    *,
    required: bool,
) -> None:
    """Atomically increment the channel's sequence counter and publish an event.

    required=True: exception propagates (no fallback).
    required=False: log and swallow (dual-channel events — push still delivers).
    """
    if not _EVENT_TYPE_RE.match(event_type):
        msg = f'invalid SSE event_type: {event_type!r}'
        raise ValueError(msg)

    client = get_sync_redis()
    if client is None:
        if required:
            msg = 'Redis unavailable for required SSE event'
            raise RuntimeError(msg)
        logger.warning('sse_publish_skipped', event_type=event_type, reason='redis_unavailable')
        return

    data_json = json.dumps(data)
    try:
        client.eval(_INCR_AND_PUBLISH_LUA, 2, channel.seq, channel.pubsub, event_type, data_json)
    except Exception:
        if required:
            raise
        logger.exception('sse_publish_failed', event_type=event_type, channel=channel.pubsub)


def _both_channels(game_id: uuid.UUID, event_type: str, data: dict) -> None:
    """Publish identical data to both hider and seeker channels."""
    publish_sse(hider_channel(game_id), event_type, data, required=True)
    publish_sse(seeker_channel(game_id), event_type, data, required=True)


def _publish_gameplay(event: GameplayEvent) -> None:
    """Route a gameplay event to the appropriate SSE channels and publish.

    Internal helper shared by both `emit_gameplay` (after-commit) and
    `emit_gameplay_now` (immediate). Contains the per-event-type routing logic.
    """
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

        case GameEndedEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.game_ended, data)

        case HidingZoneExpandedEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.hiding_zone_expanded, data)

        case ProximityEscalatedEvent():
            data = event.model_dump(mode='json')
            publish_sse(
                hider_channel(event.game_id),
                GameplayEventType.proximity_escalated,
                data,
                required=True,
            )

        case ProximityDeescalatedEvent():
            data = event.model_dump(mode='json')
            publish_sse(
                hider_channel(event.game_id),
                GameplayEventType.proximity_deescalated,
                data,
                required=True,
            )

        case FoundClaimEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.found_claim, data)

        case FoundClaimRejectedEvent():
            data = event.model_dump(mode='json')
            publish_sse(
                seeker_channel(event.game_id),
                GameplayEventType.found_claim_rejected,
                data,
                required=True,
            )

        case FoundClaimExpiredEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.found_claim_expired, data)

        case PhotoQueuedEvent():
            data = event.model_dump(mode='json')
            publish_sse(
                hider_channel(event.game_id),
                GameplayEventType.photo_queued,
                data,
                required=True,
            )

        case PhotoUnqueuedEvent():
            data = event.model_dump(mode='json')
            publish_sse(
                hider_channel(event.game_id),
                GameplayEventType.photo_unqueued,
                data,
                required=True,
            )

        case PhotoSubmittedEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.photo_submitted, data)

        case PhotoRejectedEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.photo_rejected, data)

        case GameTimerPausedEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.game_timer_paused, data)

        case GameTimerResumedEvent():
            data = event.model_dump(mode='json')
            _both_channels(event.game_id, GameplayEventType.game_timer_resumed, data)


def emit_gameplay(event: GameplayEvent) -> None:
    """Buffer a gameplay event for after-commit publish.

    The event is appended to a list on `Session.info`; a SQLAlchemy
    `after_commit` listener flushes the buffer to Redis once the active
    transaction lands. If the transaction rolls back, the buffered events are
    dropped silently — no SSE leak from work that didn't happen.

    Use this from any code path running inside `session_dependency` (router) or
    `session_scope` (background task / script). It is the safe default.
    """
    session = db.get_session()
    pending = session.info.setdefault(_PENDING_KEY, [])
    pending.append(event)


def emit_gameplay_now(event: GameplayEvent) -> None:
    """Publish a gameplay event immediately, ignoring transactional state.

    Reserved for worker timer task bodies where the reconciler's retry loop
    makes leaked events self-healing. Don't use in routers — request handlers
    should always go through the after-commit `emit_gameplay`.
    """
    _publish_gameplay(event)


@sa_event.listens_for(Session, 'after_commit')
def _flush_pending_gameplay_emits(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, None)
    if not pending:
        return
    for evt in pending:
        _publish_gameplay(evt)


@sa_event.listens_for(Session, 'after_rollback')
def _drop_pending_gameplay_emits(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)
