from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hideandseek.models.base import Base
from hideandseek.models.geo_types import ShapelyGeometry
from hideandseek.models.types import QuestionStatus, QuestionType

if TYPE_CHECKING:
    from hideandseek.models.game import Game, Player
    from hideandseek.models.question_params import (
        FeatureQuestionParams,
        RadarParams,
        ThermometerParams,
    )


class Question(Base):
    __tablename__ = 'question'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('game.id'), index=True)
    sequence: Mapped[int]
    question_type: Mapped[QuestionType]
    status: Mapped[QuestionStatus] = mapped_column(default=QuestionStatus.asked)
    asked_by: Mapped[uuid.UUID] = mapped_column(ForeignKey('player.id'))
    asked_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    seeker_location_start: Mapped[Point] = mapped_column(ShapelyGeometry('POINT', srid=4326))
    seeker_location_end: Mapped[Point | None] = mapped_column(
        ShapelyGeometry('POINT', srid=4326), nullable=True, default=None
    )
    answerable_at: Mapped[datetime | None] = mapped_column(default=None)
    answered_at: Mapped[datetime | None] = mapped_column(default=None)
    hider_location: Mapped[Point | None] = mapped_column(
        ShapelyGeometry('POINT', srid=4326), nullable=True, default=None
    )
    ask_count: Mapped[int] = mapped_column(default=1)
    scheduled_veto: Mapped[bool] = mapped_column(default=False)
    answer: Mapped[str | None] = mapped_column(default=None)
    exclusion: Mapped[BaseGeometry | None] = mapped_column(
        ShapelyGeometry('GEOMETRY', srid=4326), nullable=True, default=None
    )
    total_exclusion: Mapped[BaseGeometry | None] = mapped_column(
        ShapelyGeometry('GEOMETRY', srid=4326), nullable=True, default=None
    )

    game: Mapped[Game] = relationship(back_populates='questions')
    asked_by_player: Mapped[Player] = relationship(foreign_keys=[asked_by])
    radar_params: Mapped[RadarParams | None] = relationship(
        back_populates='question',
        uselist=False,
    )
    thermometer_params: Mapped[ThermometerParams | None] = relationship(
        back_populates='question',
        uselist=False,
    )
    feature_params: Mapped[FeatureQuestionParams | None] = relationship(
        back_populates='question',
        uselist=False,
    )
