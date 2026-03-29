"""Unified event broadcast — SSE + push routing."""

from __future__ import annotations

from hideandseek.broadcast.emit import emit, emit_gameplay
from hideandseek.broadcast.events import (
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
    QuestionVetoedEvent,
    SeekerQuestionAnsweredEvent,
    StationElectionEvent,
)
from hideandseek.broadcast.subscribe import lobby_event_stream

__all__ = [
    'GamePlayerLeftEvent',
    'GameStartedEvent',
    'GameplayEvent',
    'HiderQuestionAnsweredEvent',
    'HostChangedEvent',
    'LobbyEvent',
    'PhaseChangedEvent',
    'PlayerJoinedEvent',
    'PlayerLeftEvent',
    'PlayerLocationEvent',
    'PlayerUpdatedEvent',
    'QuestionAbandonedEvent',
    'QuestionAnswerableEvent',
    'QuestionAskedEvent',
    'QuestionVetoedEvent',
    'SeekerQuestionAnsweredEvent',
    'StationElectionEvent',
    'emit',
    'emit_gameplay',
    'lobby_event_stream',
]
