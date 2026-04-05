"""Publish lobby events to Redis (SSE channel) and/or push (Celery task)."""

from __future__ import annotations

from hideandseek.broadcast.events import (
    GameStartedEvent,
    HostChangedEvent,
    LobbyEvent,
    PlayerJoinedEvent,
    PlayerLeftEvent,
    PlayerUpdatedEvent,
)
from hideandseek.schemas.response import GameResponse, PlayerResponse
from hideandseek_core.broadcast.emit import lobby_channel, publish_sse
from hideandseek_models.types import LobbyEventType


def emit(event: LobbyEvent) -> None:
    """Route a lobby event to the appropriate channels (SSE and/or push)."""
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
