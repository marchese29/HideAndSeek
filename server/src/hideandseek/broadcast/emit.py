"""Publish lobby events to Redis (SSE channel) and/or push (Celery task).

`emit(event)` is the safe default: it buffers the event on the active session
and publishes after `Session.commit()` lands. If the transaction rolls back,
the event is dropped silently. `emit_now(event)` is the immediate-publish
escape hatch — symmetric with the gameplay pair in `core/broadcast/emit.py`.
Routers should use `emit()`; `emit_now()` exists for completeness and has no
current callers.
"""

from __future__ import annotations

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from hideandseek.broadcast.events import (
    GameStartedEvent,
    HostChangedEvent,
    LobbyEvent,
    PlayerJoinedEvent,
    PlayerLeftEvent,
    PlayerUpdatedEvent,
)
from hideandseek.schemas.response import GameResponse, PlayerResponse
from hideandseek_core import db
from hideandseek_core.broadcast.emit import lobby_channel, publish_sse
from hideandseek_models.types import LobbyEventType

_PENDING_KEY = 'pending_lobby_emits'


def _publish_lobby(event: LobbyEvent) -> None:
    """Route a lobby event to the appropriate channels and publish.

    Internal helper shared by `emit` (after-commit) and `emit_now` (immediate).
    """
    match event:
        case PlayerJoinedEvent(game=game, player=player):
            data = PlayerResponse.from_model(player).model_dump(mode='json')
            publish_sse(lobby_channel(game.id), LobbyEventType.player_joined, data, required=True)

        case PlayerUpdatedEvent(game=game, player=player):
            data = PlayerResponse.from_model(player).model_dump(mode='json')
            publish_sse(lobby_channel(game.id), LobbyEventType.player_updated, data, required=True)

        case PlayerLeftEvent(game=game, player_id=player_id):
            data = {'player_id': str(player_id)}
            publish_sse(lobby_channel(game.id), LobbyEventType.player_left, data, required=True)

        case HostChangedEvent(game=game, new_host_player_id=new_host_player_id):
            data = {'new_host_player_id': str(new_host_player_id)}
            publish_sse(lobby_channel(game.id), LobbyEventType.host_changed, data, required=True)

        case GameStartedEvent(game=game):
            data = GameResponse.from_model(game).model_dump(mode='json')
            # SSE is best-effort for game_started — push is handled by the router
            publish_sse(lobby_channel(game.id), LobbyEventType.game_started, data, required=False)


def emit(event: LobbyEvent) -> None:
    """Buffer a lobby event for after-commit publish.

    Buffered on `Session.info`; flushed by an `after_commit` listener once the
    active transaction lands. Rollback drops the buffered events silently —
    no SSE leak from work that didn't happen.
    """
    session = db.get_session()
    pending = session.info.setdefault(_PENDING_KEY, [])
    pending.append(event)


def emit_now(event: LobbyEvent) -> None:
    """Publish a lobby event immediately, ignoring transactional state.

    Escape hatch for code paths that have no active session (or want to bypass
    the after-commit gate). No current callers — included for symmetry with
    `emit_gameplay_now`.
    """
    _publish_lobby(event)


@sa_event.listens_for(Session, 'after_commit')
def _flush_pending_lobby_emits(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, None)
    if not pending:
        return
    for evt in pending:
        _publish_lobby(evt)


@sa_event.listens_for(Session, 'after_rollback')
def _drop_pending_lobby_emits(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)
