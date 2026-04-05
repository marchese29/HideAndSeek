"""Publish lobby and gameplay events to Redis (SSE channel) and/or push (Celery task)."""

from __future__ import annotations

import json
import uuid

import structlog

from hideandseek.broadcast.events import (
    FeatureEventParams,
    GamePlayerLeftEvent,
    GameplayEvent,
    GameStartedEvent,
    HiderQuestionAnsweredEvent,
    HostChangedEvent,
    LobbyEvent,
    PhaseChangedEvent,
    PlayerJoinedEvent,
    PlayerLeftEvent,
    PlayerLocationEvent,
    PlayerUpdatedEvent,
    QuestionAbandonedEvent,
    QuestionAnswerableEvent,
    QuestionAskedEvent,
    QuestionEventParams,
    QuestionVetoedEvent,
    RadarEventParams,
    SeekerQuestionAnsweredEvent,
    StationElectionEvent,
    ThermometerEventParams,
)
from hideandseek.redis_client import get_sync_redis
from hideandseek.schemas.response import GameResponse, PlayerResponse
from hideandseek_models.types import GameplayEventType, LobbyEventType, PlayerRole, PushEventType

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _serialize_event_params(params: QuestionEventParams) -> dict:
    """Serialize event parameters to a JSON-ready dict."""
    match params:
        case RadarEventParams(radius=radius):
            return {'type': 'radar', 'radius': radius}
        case ThermometerEventParams(min_travel=min_travel):
            return {'type': 'thermometer', 'min_travel': min_travel}
        case FeatureEventParams():
            return {
                'type': 'feature',
                'category': params.category,
                'feature_class': params.feature_class,
                'source': params.source,
                'seeker_feature_id': params.seeker_feature_id,
                'seeker_feature_name': params.seeker_feature_name,
                'seeker_distance': params.seeker_distance,
            }


def _lobby_channel(game_id: uuid.UUID) -> str:
    return f'game:{game_id}:lobby:events'


def _hider_channel(game_id: uuid.UUID) -> str:
    return f'game:{game_id}:hider-events'


def _seeker_channel(game_id: uuid.UUID) -> str:
    return f'game:{game_id}:seeker-events'


def _publish_sse(channel: str, event_type: str, data: dict, *, required: bool) -> None:
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


def emit(event: LobbyEvent) -> None:
    """Route a lobby event to the appropriate channels (SSE and/or push)."""
    match event:
        case PlayerJoinedEvent(game=game, player=player):
            data = PlayerResponse.from_model(player).model_dump(mode='json')
            _publish_sse(_lobby_channel(game.id), LobbyEventType.player_joined, data, required=True)

        case PlayerUpdatedEvent(game=game, player=player):
            data = PlayerResponse.from_model(player).model_dump(mode='json')
            _publish_sse(
                _lobby_channel(game.id), LobbyEventType.player_updated, data, required=True
            )

        case PlayerLeftEvent(game=game, player_id=player_id):
            data = {'player_id': str(player_id)}
            _publish_sse(_lobby_channel(game.id), LobbyEventType.player_left, data, required=True)

        case HostChangedEvent(game=game, new_host_player_id=new_host_player_id):
            data = {'new_host_player_id': str(new_host_player_id)}
            _publish_sse(_lobby_channel(game.id), LobbyEventType.host_changed, data, required=True)

        case GameStartedEvent(game=game):
            data = GameResponse.from_model(game).model_dump(mode='json')
            # SSE is best-effort for game_started — push is the primary channel
            _publish_sse(_lobby_channel(game.id), LobbyEventType.game_started, data, required=False)
            # Push via Celery
            from hideandseek.tasks.push import send_push  # noqa: PLC0415

            send_push.delay(  # type: ignore[attr-defined]
                str(game.id),
                PushEventType.game_started,
                alert='Game on! The hiding phase has begun.',
            )


def _both_channels(game_id: uuid.UUID, event_type: str, data: dict) -> None:
    """Publish identical data to both hider and seeker channels."""
    _publish_sse(_hider_channel(game_id), event_type, data, required=True)
    _publish_sse(_seeker_channel(game_id), event_type, data, required=True)


def emit_gameplay(event: GameplayEvent) -> None:
    """Route a gameplay event to the appropriate SSE channels."""
    match event:
        case PlayerLocationEvent(
            game_id=game_id,
            player_id=player_id,
            name=name,
            color=color,
            role=role,
            coordinates=coordinates,
            timestamp=timestamp,
        ):
            data = {
                'id': str(player_id),
                'name': name,
                'color': color,
                'role': role,
                'coordinates': coordinates,
                'timestamp': timestamp.isoformat(),
            }
            # Always publish to hider channel (hiders see everyone)
            _publish_sse(
                _hider_channel(game_id),
                GameplayEventType.player_location,
                data,
                required=True,
            )
            # Seeker location also goes to seeker channel
            if role == PlayerRole.seeker:
                _publish_sse(
                    _seeker_channel(game_id),
                    GameplayEventType.player_location,
                    data,
                    required=True,
                )

        case QuestionAskedEvent(game_id=game_id):
            data = {
                'question_id': str(event.question_id),
                'question_type': event.question_type,
                'status': event.status,
                'asked_by': str(event.asked_by),
                'slot_index': event.slot_index,
                'parameters': _serialize_event_params(event.parameters),
                'seeker_location_start': event.seeker_location_start.model_dump(mode='json'),
                'asked_at': event.asked_at.isoformat(),
                'ask_count': event.ask_count,
                'sequence': event.sequence,
            }
            _both_channels(game_id, GameplayEventType.question_asked, data)

        case QuestionAnswerableEvent(game_id=game_id):
            data = {
                'question_id': str(event.question_id),
                'question_type': event.question_type,
                'status': event.status,
                'seeker_location_end': event.seeker_location_end.model_dump(mode='json'),
            }
            _both_channels(game_id, GameplayEventType.question_answerable, data)

        case HiderQuestionAnsweredEvent(game_id=game_id):
            data = {
                'question_id': str(event.question_id),
                'question_type': event.question_type,
                'status': event.status,
                'answer': event.answer,
                'slot_index': event.slot_index,
                'asked_by': str(event.asked_by),
                'answered_at': event.answered_at.isoformat() if event.answered_at else None,
                'hider_location': event.hider_location.model_dump(mode='json')
                if event.hider_location
                else None,
                'hider_feature_id': event.hider_feature_id,
                'hider_feature_name': event.hider_feature_name,
                'hider_distance': event.hider_distance,
            }
            _publish_sse(
                _hider_channel(game_id),
                GameplayEventType.question_answered,
                data,
                required=True,
            )

        case SeekerQuestionAnsweredEvent(game_id=game_id):
            data = {
                'question_id': str(event.question_id),
                'question_type': event.question_type,
                'status': event.status,
                'answer': event.answer,
                'slot_index': event.slot_index,
                'asked_by': str(event.asked_by),
                'exclusion': event.exclusion.model_dump(mode='json') if event.exclusion else None,
                'total_exclusion': event.total_exclusion.model_dump(mode='json')
                if event.total_exclusion
                else None,
                'answered_at': event.answered_at.isoformat() if event.answered_at else None,
            }
            _publish_sse(
                _seeker_channel(game_id),
                GameplayEventType.question_answered,
                data,
                required=True,
            )

        case QuestionVetoedEvent(game_id=game_id):
            data = {
                'question_id': str(event.question_id),
                'question_type': event.question_type,
                'slot_index': event.slot_index,
            }
            _both_channels(game_id, GameplayEventType.question_vetoed, data)

        case QuestionAbandonedEvent(game_id=game_id):
            data = {
                'question_id': str(event.question_id),
                'question_type': event.question_type,
                'slot_index': event.slot_index,
            }
            _both_channels(game_id, GameplayEventType.question_abandoned, data)

        case PhaseChangedEvent(game_id=game_id):
            data = {
                'phase': event.phase,
                'seeking_started_at': event.seeking_started_at.isoformat(),
                'station_election_status': event.station_election_status,
                'hider_station_id': str(event.hider_station_id) if event.hider_station_id else None,
            }
            _both_channels(game_id, GameplayEventType.phase_changed, data)

        case StationElectionEvent(game_id=game_id):
            data = {
                'station_election_status': event.station_election_status,
                'hider_station_id': str(event.hider_station_id) if event.hider_station_id else None,
            }
            _publish_sse(
                _hider_channel(game_id),
                GameplayEventType.station_election,
                data,
                required=True,
            )

        case GamePlayerLeftEvent(game_id=game_id):
            data = {'player_id': str(event.player_id)}
            _both_channels(game_id, GameplayEventType.player_left, data)
