"""Typed lobby and gameplay event dataclasses."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from geojson_pydantic.geometries import Geometry as GeoJSONGeometry

from hideandseek.models.types import PlayerColor, PlayerRole
from hideandseek.schemas.response import geom_or_none

if TYPE_CHECKING:
    from hideandseek.models.game import Game, Player
    from hideandseek.models.question import Question


# ── Lobby events ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PlayerJoinedEvent:
    game: Game
    player: Player


@dataclass(frozen=True, slots=True)
class PlayerUpdatedEvent:
    game: Game
    player: Player


@dataclass(frozen=True, slots=True)
class PlayerLeftEvent:
    game: Game
    player_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class HostChangedEvent:
    game: Game
    new_host_player_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class GameStartedEvent:
    game: Game


LobbyEvent = (
    PlayerJoinedEvent | PlayerUpdatedEvent | PlayerLeftEvent | HostChangedEvent | GameStartedEvent
)


# ── Gameplay events ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PlayerLocationEvent:
    game_id: uuid.UUID
    player_id: uuid.UUID
    name: str
    color: PlayerColor
    role: PlayerRole
    coordinates: dict  # Pre-serialized GeoJSON Point
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class QuestionAskedEvent:
    """A seeker asked a question — both channels."""

    game_id: uuid.UUID
    question_id: uuid.UUID
    question_type: str
    status: str
    asked_by: uuid.UUID
    slot_index: int

    @staticmethod
    def from_question(question: Question) -> QuestionAskedEvent:
        return QuestionAskedEvent(
            game_id=question.game_id,
            question_id=question.id,
            question_type=question.question_type,
            status=question.status,
            asked_by=question.asked_by,
            slot_index=question.slot_index,
        )


@dataclass(frozen=True, slots=True)
class QuestionAnswerableEvent:
    """A thermometer question was locked in — both channels."""

    game_id: uuid.UUID
    question_id: uuid.UUID
    question_type: str
    status: str

    @staticmethod
    def from_question(question: Question) -> QuestionAnswerableEvent:
        return QuestionAnswerableEvent(
            game_id=question.game_id,
            question_id=question.id,
            question_type=question.question_type,
            status=question.status,
        )


@dataclass(frozen=True, slots=True)
class HiderQuestionAnsweredEvent:
    """A question was answered — hider channel only (no geometry)."""

    game_id: uuid.UUID
    question_id: uuid.UUID
    question_type: str
    status: str
    answer: str
    slot_index: int
    asked_by: uuid.UUID

    @staticmethod
    def from_question(question: Question) -> HiderQuestionAnsweredEvent:
        assert question.answer is not None
        return HiderQuestionAnsweredEvent(
            game_id=question.game_id,
            question_id=question.id,
            question_type=question.question_type,
            status=question.status,
            answer=question.answer,
            slot_index=question.slot_index,
            asked_by=question.asked_by,
        )


@dataclass(frozen=True, slots=True)
class SeekerQuestionAnsweredEvent:
    """A question was answered — seeker channel only (with exclusion geometry)."""

    game_id: uuid.UUID
    question_id: uuid.UUID
    question_type: str
    status: str
    answer: str
    slot_index: int
    asked_by: uuid.UUID
    exclusion: GeoJSONGeometry | None
    total_exclusion: GeoJSONGeometry | None

    @staticmethod
    def from_question(question: Question) -> SeekerQuestionAnsweredEvent:
        assert question.answer is not None
        return SeekerQuestionAnsweredEvent(
            game_id=question.game_id,
            question_id=question.id,
            question_type=question.question_type,
            status=question.status,
            answer=question.answer,
            slot_index=question.slot_index,
            asked_by=question.asked_by,
            exclusion=geom_or_none(question.exclusion),
            total_exclusion=geom_or_none(question.total_exclusion),
        )


@dataclass(frozen=True, slots=True)
class QuestionVetoedEvent:
    """A question was vetoed — both channels."""

    game_id: uuid.UUID
    question_id: uuid.UUID
    question_type: str
    slot_index: int

    @staticmethod
    def from_question(question: Question) -> QuestionVetoedEvent:
        return QuestionVetoedEvent(
            game_id=question.game_id,
            question_id=question.id,
            question_type=question.question_type,
            slot_index=question.slot_index,
        )


@dataclass(frozen=True, slots=True)
class QuestionAbandonedEvent:
    """A question was abandoned — both channels."""

    game_id: uuid.UUID
    question_id: uuid.UUID
    question_type: str
    slot_index: int

    @staticmethod
    def from_question(question: Question) -> QuestionAbandonedEvent:
        return QuestionAbandonedEvent(
            game_id=question.game_id,
            question_id=question.id,
            question_type=question.question_type,
            slot_index=question.slot_index,
        )


@dataclass(frozen=True, slots=True)
class PhaseChangedEvent:
    """Game transitioned from hiding to seeking — both channels."""

    game_id: uuid.UUID
    phase: str
    seeking_started_at: datetime
    station_election_status: str
    hider_station_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class StationElectionEvent:
    """Station election status changed — hider channel only."""

    game_id: uuid.UUID
    station_election_status: str
    hider_station_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class GamePlayerLeftEvent:
    """A player left during active gameplay — both channels."""

    game_id: uuid.UUID
    player_id: uuid.UUID


GameplayEvent = (
    PlayerLocationEvent
    | QuestionAskedEvent
    | QuestionAnswerableEvent
    | HiderQuestionAnsweredEvent
    | SeekerQuestionAnsweredEvent
    | QuestionVetoedEvent
    | QuestionAbandonedEvent
    | PhaseChangedEvent
    | StationElectionEvent
    | GamePlayerLeftEvent
)
