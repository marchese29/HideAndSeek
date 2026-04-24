from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hideandseek_models.base import Base
from hideandseek_models.types import FeatureCategory, PhotoReviewDecision, PhotoSubject

if TYPE_CHECKING:
    from hideandseek_models.question import Question


class RadarParams(Base):
    """Parameters for a radar question (one-to-one with Question)."""

    __tablename__ = 'radar_params'

    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('question.id'), primary_key=True)
    radius: Mapped[float]

    question: Mapped[Question] = relationship(back_populates='radar_params')


class ThermometerParams(Base):
    """Parameters for a thermometer question (one-to-one with Question).

    seeker_location_end is stored here because only thermometer questions have it.
    """

    __tablename__ = 'thermometer_params'

    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('question.id'), primary_key=True)
    min_travel: Mapped[float]

    question: Mapped[Question] = relationship(back_populates='thermometer_params')


class FeatureQuestionParams(Base):
    """Parameters for matching and measuring questions (one-to-one with Question).

    Seeker fields are required (validation rejects unresolvable categories).
    Hider fields are populated at answer time.
    """

    __tablename__ = 'feature_question_params'

    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('question.id'), primary_key=True)
    category: Mapped[FeatureCategory]
    feature_class: Mapped[int | None] = mapped_column(default=None)
    source: Mapped[str] = mapped_column(default='map_data')
    seeker_feature_id: Mapped[str]
    seeker_feature_name: Mapped[str]
    seeker_distance: Mapped[float]
    hider_feature_id: Mapped[str | None] = mapped_column(default=None)
    hider_feature_name: Mapped[str | None] = mapped_column(default=None)
    hider_distance: Mapped[float | None] = mapped_column(default=None)

    question: Mapped[Question] = relationship(back_populates='feature_params')


class TentacleQuestionParams(Base):
    """Parameters for a tentacles question (one-to-one with Question).

    Seeker fields (category, poi_ids, poi_names) are set at ask time.
    poi_names is denormalized (parallel to poi_ids) so event/param builders
    can resolve names without DB queries.
    Answer fields (hit, hider_feature_id) are populated at answer time.
    """

    __tablename__ = 'tentacle_question_params'

    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('question.id'), primary_key=True)
    category: Mapped[FeatureCategory]
    poi_ids: Mapped[list] = mapped_column(JSON)
    poi_names: Mapped[list] = mapped_column(JSON)
    hit: Mapped[bool | None] = mapped_column(default=None)
    hider_feature_id: Mapped[str | None] = mapped_column(default=None)

    question: Mapped[Question] = relationship(back_populates='tentacle_params')


class PhotoQuestionParams(Base):
    """Parameters for a photo question (one-to-one with Question).

    `subject` is set at ask time. Submission fields (`photo_object_key` or
    `is_null_answer`, plus `submitted_at` / `submitted_by`) are populated when
    the hider commits. Review fields are populated when a seeker accepts/rejects
    or when auto-accept fires on the review timer. On reject, the submission
    fields null out so another attempt can take over; the review fields carry
    the last review only (no full history).
    """

    __tablename__ = 'photo_question_params'

    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('question.id'), primary_key=True)
    subject: Mapped[PhotoSubject]
    photo_object_key: Mapped[str | None] = mapped_column(default=None)
    is_null_answer: Mapped[bool] = mapped_column(default=False)
    submitted_at: Mapped[datetime | None] = mapped_column(default=None)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('player.id'), default=None)
    review_decision: Mapped[PhotoReviewDecision | None] = mapped_column(default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(default=None)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('player.id'), default=None)

    question: Mapped[Question] = relationship(back_populates='photo_params')
