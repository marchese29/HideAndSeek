from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hideandseek_models.base import Base
from hideandseek_models.types import FeatureCategory

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
