import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from sqlmodel import Field, Relationship, SQLModel

from hideandseek.models.geo_types import ShapelyGeometry
from hideandseek.models.types import QuestionStatus, QuestionType


class Question(SQLModel, table=True):
    model_config = {'arbitrary_types_allowed': True}  # type: ignore[assignment]
    __tablename__ = 'question'  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    game_id: uuid.UUID = Field(foreign_key='game.id', index=True)
    sequence: int
    question_type: QuestionType
    status: QuestionStatus = QuestionStatus.asked
    asked_by: uuid.UUID = Field(foreign_key='player.id')
    asked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    seeker_location_start: Point = Field(sa_column=sa.Column(ShapelyGeometry('POINT', srid=4326)))
    seeker_location_end: Point | None = Field(
        default=None, sa_column=sa.Column(ShapelyGeometry('POINT', srid=4326), nullable=True)
    )
    answerable_at: datetime | None = None
    answered_at: datetime | None = None
    hider_location: Point | None = Field(
        default=None, sa_column=sa.Column(ShapelyGeometry('POINT', srid=4326), nullable=True)
    )
    ask_count: int = 1
    answer: str | None = None
    exclusion: BaseGeometry | None = Field(
        default=None, sa_column=sa.Column(ShapelyGeometry('GEOMETRY', srid=4326), nullable=True)
    )
    total_exclusion: BaseGeometry | None = Field(
        default=None,
        sa_column=sa.Column(ShapelyGeometry('GEOMETRY', srid=4326), nullable=True),
    )

    game: 'Game' = Relationship(back_populates='questions')  # noqa: F821
    radar_params: 'RadarParams' = Relationship(  # noqa: F821
        back_populates='question',
        sa_relationship_kwargs={'uselist': False},
    )
    thermometer_params: 'ThermometerParams' = Relationship(  # noqa: F821
        back_populates='question',
        sa_relationship_kwargs={'uselist': False},
    )
    feature_params: 'FeatureQuestionParams' = Relationship(  # noqa: F821
        back_populates='question',
        sa_relationship_kwargs={'uselist': False},
    )


# Avoid circular imports — resolved at runtime by SQLModel.
from hideandseek.models.game import Game  # noqa: E402
from hideandseek.models.question_params import (  # noqa: E402
    FeatureQuestionParams,
    RadarParams,
    ThermometerParams,
)

__all__ = [
    'FeatureQuestionParams',
    'Game',
    'Question',
    'RadarParams',
    'ThermometerParams',
]
