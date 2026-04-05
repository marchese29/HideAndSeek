"""Typed lobby and gameplay event dataclasses."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from geojson_pydantic import Point as GeoJSONPoint
from geojson_pydantic.geometries import Geometry as GeoJSONGeometry
from shapely.geometry import mapping

from hideandseek.schemas.response import geom_or_none, point_or_none
from hideandseek_models.types import PlayerColor, PlayerRole, QuestionType

if TYPE_CHECKING:
    from hideandseek_models.game import Game, Player
    from hideandseek_models.question import Question


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


# ── Question parameter dataclasses ──────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RadarEventParams:
    """Radar question parameters."""

    radius: float


@dataclass(frozen=True, slots=True)
class ThermometerEventParams:
    """Thermometer question parameters."""

    min_travel: float


@dataclass(frozen=True, slots=True)
class FeatureEventParams:
    """Matching/measuring question parameters (seeker resolution only)."""

    category: str
    feature_class: int | None
    source: str
    seeker_feature_id: str
    seeker_feature_name: str
    seeker_distance: float


QuestionEventParams = RadarEventParams | ThermometerEventParams | FeatureEventParams


def build_event_params(question: Question) -> QuestionEventParams:
    """Build event parameters from a Question's param relationships."""
    if question.question_type == QuestionType.radar:
        rp = question.radar_params
        assert rp is not None
        return RadarEventParams(radius=rp.radius)
    elif question.question_type == QuestionType.thermometer:
        tp = question.thermometer_params
        assert tp is not None
        return ThermometerEventParams(min_travel=tp.min_travel)
    else:
        fp = question.feature_params
        assert fp is not None
        return FeatureEventParams(
            category=str(fp.category),
            feature_class=fp.feature_class,
            source=fp.source,
            seeker_feature_id=fp.seeker_feature_id,
            seeker_feature_name=fp.seeker_feature_name,
            seeker_distance=fp.seeker_distance,
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
    parameters: QuestionEventParams
    seeker_location_start: GeoJSONPoint
    asked_at: datetime
    ask_count: int
    sequence: int

    @staticmethod
    def from_question(question: Question) -> QuestionAskedEvent:
        return QuestionAskedEvent(
            game_id=question.game_id,
            question_id=question.id,
            question_type=question.question_type,
            status=question.status,
            asked_by=question.asked_by,
            slot_index=question.slot_index,
            parameters=build_event_params(question),
            seeker_location_start=GeoJSONPoint(**mapping(question.seeker_location_start)),
            asked_at=question.asked_at,
            ask_count=question.ask_count,
            sequence=question.sequence,
        )


@dataclass(frozen=True, slots=True)
class QuestionAnswerableEvent:
    """A thermometer question was locked in — both channels."""

    game_id: uuid.UUID
    question_id: uuid.UUID
    question_type: str
    status: str
    seeker_location_end: GeoJSONPoint

    @staticmethod
    def from_question(question: Question) -> QuestionAnswerableEvent:
        assert question.seeker_location_end is not None
        return QuestionAnswerableEvent(
            game_id=question.game_id,
            question_id=question.id,
            question_type=question.question_type,
            status=question.status,
            seeker_location_end=GeoJSONPoint(**mapping(question.seeker_location_end)),
        )


@dataclass(frozen=True, slots=True)
class HiderQuestionAnsweredEvent:
    """A question was answered — hider channel only.

    Carries answer-time delta fields only (ask-time fields were sent
    with QuestionAskedEvent). Includes hider-privileged data: location
    and feature resolution.
    """

    game_id: uuid.UUID
    question_id: uuid.UUID
    question_type: str
    status: str
    answer: str
    slot_index: int
    asked_by: uuid.UUID
    answered_at: datetime | None
    hider_location: GeoJSONPoint | None
    hider_feature_id: str | None
    hider_feature_name: str | None
    hider_distance: float | None

    @staticmethod
    def from_question(question: Question) -> HiderQuestionAnsweredEvent:
        assert question.answer is not None
        fp = question.feature_params
        return HiderQuestionAnsweredEvent(
            game_id=question.game_id,
            question_id=question.id,
            question_type=question.question_type,
            status=question.status,
            answer=question.answer,
            slot_index=question.slot_index,
            asked_by=question.asked_by,
            answered_at=question.answered_at,
            hider_location=point_or_none(question.hider_location),
            hider_feature_id=fp.hider_feature_id if fp else None,
            hider_feature_name=fp.hider_feature_name if fp else None,
            hider_distance=fp.hider_distance if fp else None,
        )


@dataclass(frozen=True, slots=True)
class SeekerQuestionAnsweredEvent:
    """A question was answered — seeker channel only (with exclusion geometry).

    Carries answer-time delta fields only. No hider-privileged data
    (no hider_location, no hider feature resolution).
    """

    game_id: uuid.UUID
    question_id: uuid.UUID
    question_type: str
    status: str
    answer: str
    slot_index: int
    asked_by: uuid.UUID
    exclusion: GeoJSONGeometry | None
    total_exclusion: GeoJSONGeometry | None
    answered_at: datetime | None

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
            answered_at=question.answered_at,
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
