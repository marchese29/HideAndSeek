"""Unified event broadcast — SSE + push routing."""

from __future__ import annotations

from hideandseek.broadcast.emit import emit, emit_gameplay
from hideandseek.broadcast.events import (
    GameplayEvent,
    GameStartedEvent,
    HostChangedEvent,
    LobbyEvent,
    PlayerJoinedEvent,
    PlayerLeftEvent,
    PlayerLocationEvent,
    PlayerUpdatedEvent,
)
from hideandseek.broadcast.subscribe import lobby_event_stream

__all__ = [
    'GameStartedEvent',
    'GameplayEvent',
    'HostChangedEvent',
    'LobbyEvent',
    'PlayerJoinedEvent',
    'PlayerLeftEvent',
    'PlayerLocationEvent',
    'PlayerUpdatedEvent',
    'emit',
    'emit_gameplay',
    'lobby_event_stream',
]
