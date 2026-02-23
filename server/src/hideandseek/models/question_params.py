import uuid

from sqlmodel import Field, Relationship, SQLModel

from hideandseek.models.types import FeatureCategory


class RadarParams(SQLModel, table=True):
    """Parameters for a radar question (one-to-one with Question)."""

    __tablename__ = 'radar_params'  # type: ignore[assignment]

    question_id: uuid.UUID = Field(foreign_key='question.id', primary_key=True)
    radius: float

    question: 'Question' = Relationship(back_populates='radar_params')  # noqa: F821


class ThermometerParams(SQLModel, table=True):
    """Parameters for a thermometer question (one-to-one with Question).

    seeker_location_end is stored here because only thermometer questions have it.
    """

    model_config = {'arbitrary_types_allowed': True}  # type: ignore[assignment]
    __tablename__ = 'thermometer_params'  # type: ignore[assignment]

    question_id: uuid.UUID = Field(foreign_key='question.id', primary_key=True)
    min_travel: float

    question: 'Question' = Relationship(back_populates='thermometer_params')  # noqa: F821


class FeatureQuestionParams(SQLModel, table=True):
    """Parameters for matching and measuring questions (one-to-one with Question).

    Seeker fields are required (validation rejects unresolvable categories).
    Hider fields are populated at answer time.
    """

    __tablename__ = 'feature_question_params'  # type: ignore[assignment]

    question_id: uuid.UUID = Field(foreign_key='question.id', primary_key=True)
    category: FeatureCategory
    feature_class: int | None = None
    source: str = 'map_data'
    seeker_feature_id: str
    seeker_feature_name: str
    seeker_distance: float
    hider_feature_id: str | None = None
    hider_feature_name: str | None = None
    hider_distance: float | None = None

    question: 'Question' = Relationship(back_populates='feature_params')  # noqa: F821


# Avoid circular imports — resolved at runtime by SQLModel.
from hideandseek.models.question import Question  # noqa: E402

__all__ = ['FeatureQuestionParams', 'Question', 'RadarParams', 'ThermometerParams']
