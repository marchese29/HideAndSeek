import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel

from hideandseek.models.types import QuestionStatus, QuestionType


class Question(SQLModel, table=True):
    __tablename__ = 'question'  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    game_id: uuid.UUID = Field(foreign_key='game.id', index=True)
    sequence: int
    question_type: QuestionType
    status: QuestionStatus = QuestionStatus.asked
    parameters: dict = Field(default_factory=dict, sa_type=sa.JSON)
    asked_by: uuid.UUID = Field(foreign_key='player.id')
    asked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    seeker_location_start: dict = Field(sa_type=sa.JSON)  # GeoJSON Point
    seeker_location_end: dict | None = Field(default=None, sa_type=sa.JSON)
    answered_at: datetime | None = None
    hider_location: dict | None = Field(default=None, sa_type=sa.JSON)
    answer: str | None = None
    exclusion: dict | None = Field(default=None, sa_type=sa.JSON)

    game: 'Game' = Relationship(back_populates='questions')  # noqa: F821


# Avoid circular imports — resolved at runtime by SQLModel.
from hideandseek.models.game import Game  # noqa: E402

__all__ = ['Question', 'Game']
