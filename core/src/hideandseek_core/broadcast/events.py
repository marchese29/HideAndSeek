"""Typed gameplay event schemas (Pydantic).

Gameplay event models auto-register for OpenAPI schema injection via
the ``GameplayEventSchema`` base class.  Parameter models are standalone
``BaseModel`` subclasses — pulled into the spec automatically as ``$defs``
when their parent event is processed.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar, Literal

from geojson_pydantic import Point as GeoJSONPoint
from geojson_pydantic.geometries import Geometry as GeoJSONGeometry
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import mapping

from hideandseek_core.conventions import resolve_tentacle_distance
from hideandseek_core.geo_helpers import geom_or_none, point_or_none
from hideandseek_models.types import (
    EndReason,
    PhotoSubject,
    PlayerColor,
    PlayerRole,
    ProximityTier,
    QuestionStatus,
    QuestionType,
    StationElectionStatus,
)

if TYPE_CHECKING:
    from hideandseek_models.question import Question


# ── Question parameter models ──────────────────────────────────────────


class RadarEventParams(BaseModel):
    """Radar question parameters."""

    model_config = ConfigDict(frozen=True)

    type: Literal['radar'] = 'radar'
    radius: float


class ThermometerEventParams(BaseModel):
    """Thermometer question parameters."""

    model_config = ConfigDict(frozen=True)

    type: Literal['thermometer'] = 'thermometer'
    min_travel: float


class FeatureEventParams(BaseModel):
    """Matching/measuring question parameters (seeker resolution only)."""

    model_config = ConfigDict(frozen=True)

    type: Literal['feature'] = 'feature'
    category: str
    feature_class: int | None
    source: str
    seeker_feature_id: str
    seeker_feature_name: str
    seeker_distance: float


class TentacleEventParams(BaseModel):
    """Tentacles question parameters — category, distance, and in-circle POIs."""

    model_config = ConfigDict(frozen=True)

    type: Literal['tentacles'] = 'tentacles'
    category: str = Field(description='POI category (e.g. museum, hospital).')
    distance: float = Field(description='Tentacle distance in convention units.')
    poi_ids: list[str] = Field(description='Stable IDs of POIs within the distance circle.')
    poi_names: list[str] = Field(description='Human-readable names, matching poi_ids order.')


class PhotoEventParams(BaseModel):
    """Photo question parameters — subject only; labels resolve client-side."""

    model_config = ConfigDict(frozen=True)

    type: Literal['photo'] = 'photo'
    subject: PhotoSubject


QuestionEventParams = (
    RadarEventParams
    | ThermometerEventParams
    | FeatureEventParams
    | TentacleEventParams
    | PhotoEventParams
)


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
    elif question.question_type == QuestionType.photo:
        pp = question.photo_params
        assert pp is not None
        return PhotoEventParams(subject=pp.subject)
    elif question.question_type == QuestionType.tentacles:
        tp = question.tentacle_params
        assert tp is not None
        return TentacleEventParams(
            category=str(tp.category),
            distance=resolve_tentacle_distance(question.game.game_map, tp.category),
            poi_ids=list(tp.poi_ids),
            poi_names=list(tp.poi_names),
        )
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


# ── Auto-registering base class ───────────────────────────────────────


class GameplayEventSchema(BaseModel):
    """Base for gameplay SSE event schemas.  Auto-registered for OpenAPI injection."""

    model_config = ConfigDict(frozen=True)

    _registry: ClassVar[set[type[GameplayEventSchema]]] = set()

    game_id: uuid.UUID = Field(exclude=True)

    def __init_subclass__(cls, **kwargs):  # noqa: ANN003
        super().__init_subclass__(**kwargs)
        GameplayEventSchema._registry.add(cls)

    @classmethod
    def registered_schemas(cls) -> Sequence[type[GameplayEventSchema]]:
        """Return all registered gameplay event schemas."""
        return list(cls._registry)


# ── Gameplay events ───────────────────────────────────────────────────


class PlayerLocationEvent(GameplayEventSchema):
    player_id: uuid.UUID
    name: str
    color: PlayerColor
    role: PlayerRole
    coordinates: GeoJSONPoint
    timestamp: datetime

    # Enrichment fields — populated for hider location events only.
    candidate_stations: list[uuid.UUID] | None = None
    not_in_zone: list[uuid.UUID] | None = None
    computed_answer: str | None = None
    freeze_departed: list[uuid.UUID] | None = None


class QuestionAskedEvent(GameplayEventSchema):
    """A seeker asked a question — both channels."""

    question_id: uuid.UUID
    question_type: QuestionType
    status: QuestionStatus
    asked_by: uuid.UUID
    slot_index: int
    parameters: QuestionEventParams = Field(discriminator='type')
    seeker_location_start: GeoJSONPoint
    asked_at: datetime
    ask_count: int
    sequence: int
    question_deadline: datetime | None

    @staticmethod
    def from_question(question: Question, *, base_question_delay_min: int) -> QuestionAskedEvent:
        deadline = (
            question.answerable_at + timedelta(minutes=base_question_delay_min)
            if question.answerable_at
            else None
        )
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
            question_deadline=deadline,
        )


class QuestionAnswerableEvent(GameplayEventSchema):
    """A thermometer question was locked in — both channels."""

    question_id: uuid.UUID
    question_type: QuestionType
    status: QuestionStatus
    seeker_location_end: GeoJSONPoint
    question_deadline: datetime

    @staticmethod
    def from_question(
        question: Question, *, base_question_delay_min: int
    ) -> QuestionAnswerableEvent:
        assert question.seeker_location_end is not None
        assert question.answerable_at is not None
        return QuestionAnswerableEvent(
            game_id=question.game_id,
            question_id=question.id,
            question_type=question.question_type,
            status=question.status,
            seeker_location_end=GeoJSONPoint(**mapping(question.seeker_location_end)),
            question_deadline=question.answerable_at + timedelta(minutes=base_question_delay_min),
        )


class HiderQuestionAnsweredEvent(GameplayEventSchema):
    """A question was answered — hider channel only.

    Carries answer-time delta fields only (ask-time fields were sent
    with QuestionAskedEvent). Includes hider-privileged data: location
    and feature resolution.
    """

    question_id: uuid.UUID
    sequence: int
    question_type: QuestionType
    status: QuestionStatus
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
        tp = question.tentacle_params

        hider_feature_id: str | None = None
        hider_feature_name: str | None = None
        hider_distance: float | None = None

        if fp:
            hider_feature_id = fp.hider_feature_id
            hider_feature_name = fp.hider_feature_name
            hider_distance = fp.hider_distance
        elif tp and tp.hider_feature_id:
            hider_feature_id = tp.hider_feature_id
            try:
                idx = list(tp.poi_ids).index(tp.hider_feature_id)
                hider_feature_name = list(tp.poi_names)[idx]
            except (ValueError, IndexError):
                pass

        return HiderQuestionAnsweredEvent(
            game_id=question.game_id,
            question_id=question.id,
            sequence=question.sequence,
            question_type=question.question_type,
            status=question.status,
            answer=question.answer,
            slot_index=question.slot_index,
            asked_by=question.asked_by,
            answered_at=question.answered_at,
            hider_location=point_or_none(question.hider_location),
            hider_feature_id=hider_feature_id,
            hider_feature_name=hider_feature_name,
            hider_distance=hider_distance,
        )


class SeekerQuestionAnsweredEvent(GameplayEventSchema):
    """A question was answered — seeker channel only (with exclusion geometry).

    Carries answer-time delta fields only. No hider-privileged data
    (no hider_location, no hider feature resolution).
    """

    question_id: uuid.UUID
    sequence: int
    question_type: QuestionType
    status: QuestionStatus
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
            sequence=question.sequence,
            question_type=question.question_type,
            status=question.status,
            answer=question.answer,
            slot_index=question.slot_index,
            asked_by=question.asked_by,
            exclusion=geom_or_none(question.exclusion),
            total_exclusion=geom_or_none(question.total_exclusion),
            answered_at=question.answered_at,
        )


class QuestionVetoedEvent(GameplayEventSchema):
    """A question was vetoed — both channels."""

    question_id: uuid.UUID
    question_type: QuestionType
    slot_index: int

    @staticmethod
    def from_question(question: Question) -> QuestionVetoedEvent:
        return QuestionVetoedEvent(
            game_id=question.game_id,
            question_id=question.id,
            question_type=question.question_type,
            slot_index=question.slot_index,
        )


class QuestionAbandonedEvent(GameplayEventSchema):
    """A question was abandoned — both channels."""

    question_id: uuid.UUID
    question_type: QuestionType
    slot_index: int

    @staticmethod
    def from_question(question: Question) -> QuestionAbandonedEvent:
        return QuestionAbandonedEvent(
            game_id=question.game_id,
            question_id=question.id,
            question_type=question.question_type,
            slot_index=question.slot_index,
        )


class PhaseChangedEvent(GameplayEventSchema):
    """Game transitioned from hiding to seeking — both channels."""

    phase: str
    seeking_started_at: datetime
    station_election_status: StationElectionStatus
    hider_station_id: uuid.UUID | None


class StationElectionEvent(GameplayEventSchema):
    """Station election status changed — hider channel only."""

    station_election_status: StationElectionStatus
    hider_station_id: uuid.UUID | None


class GamePlayerLeftEvent(GameplayEventSchema):
    """A player left during active gameplay — both channels."""

    player_id: uuid.UUID


class GameHostChangedEvent(GameplayEventSchema):
    """Host transferred during active gameplay — both channels."""

    new_host_player_id: uuid.UUID


class GameDissolvedEvent(GameplayEventSchema):
    """Game dissolved during active gameplay — both channels."""

    reason: str


class GameEndedEvent(GameplayEventSchema):
    """Game finished — host ended it or seekers found the hiders. Both channels."""

    reason: EndReason


class HidingZoneExpandedEvent(GameplayEventSchema):
    """Hiding zone expanded by the hider — both channels."""

    effective_radius: float = Field(
        description='New effective hiding zone radius in convention units.'
    )


class ProximityEscalatedEvent(GameplayEventSchema):
    """Seekers moved closer — hider channel only."""

    proximity_tier: ProximityTier


class ProximityDeescalatedEvent(GameplayEventSchema):
    """All seekers pulled back — hider channel only."""

    proximity_tier: ProximityTier


class FoundClaimEvent(GameplayEventSchema):
    """A seeker claims to have found the hiders — both channels."""

    seeker_player_id: uuid.UUID
    deadline_utc: datetime


class FoundClaimRejectedEvent(GameplayEventSchema):
    """Hiders rejected the found claim — seeker channel only."""


class FoundClaimExpiredEvent(GameplayEventSchema):
    """Found claim timed out — both channels."""


class PhotoQueuedEvent(GameplayEventSchema):
    """A hider uploaded a photo but did not submit — hider channel only."""

    question_id: uuid.UUID
    sequence: int
    queued_by: uuid.UUID
    uploaded_at: datetime


class PhotoUnqueuedEvent(GameplayEventSchema):
    """A hider cleared the queued photo — hider channel only."""

    question_id: uuid.UUID
    sequence: int


class PhotoSubmittedEvent(GameplayEventSchema):
    """A hider (or auto-submit) committed the photo — both channels."""

    question_id: uuid.UUID
    sequence: int
    status: QuestionStatus
    submitted_at: datetime
    submitted_by: uuid.UUID | None
    is_null_answer: bool
    review_deadline: datetime

    @staticmethod
    def from_question(question: Question, *, review_deadline: datetime) -> PhotoSubmittedEvent:
        pp = question.photo_params
        assert pp is not None
        assert pp.submitted_at is not None
        return PhotoSubmittedEvent(
            game_id=question.game_id,
            question_id=question.id,
            sequence=question.sequence,
            status=question.status,
            submitted_at=pp.submitted_at,
            submitted_by=pp.submitted_by,
            is_null_answer=pp.is_null_answer,
            review_deadline=review_deadline,
        )


class PhotoRejectedEvent(GameplayEventSchema):
    """A seeker rejected a submitted photo — both channels.

    Status reverts to `answerable` and `new_submit_deadline` is the fresh
    submit-window expiry both clients should render against.
    """

    question_id: uuid.UUID
    sequence: int
    reviewed_by: uuid.UUID
    rejected_at: datetime
    new_submit_deadline: datetime

    @staticmethod
    def from_question(question: Question, *, new_submit_deadline: datetime) -> PhotoRejectedEvent:
        pp = question.photo_params
        assert pp is not None
        assert pp.reviewed_by is not None
        assert pp.reviewed_at is not None
        return PhotoRejectedEvent(
            game_id=question.game_id,
            question_id=question.id,
            sequence=question.sequence,
            reviewed_by=pp.reviewed_by,
            rejected_at=pp.reviewed_at,
            new_submit_deadline=new_submit_deadline,
        )


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
    | GameHostChangedEvent
    | GameDissolvedEvent
    | GameEndedEvent
    | HidingZoneExpandedEvent
    | ProximityEscalatedEvent
    | ProximityDeescalatedEvent
    | FoundClaimEvent
    | FoundClaimRejectedEvent
    | FoundClaimExpiredEvent
    | PhotoQueuedEvent
    | PhotoUnqueuedEvent
    | PhotoSubmittedEvent
    | PhotoRejectedEvent
)
