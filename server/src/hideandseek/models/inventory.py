import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel

from hideandseek.models.types import FeatureCategory, QuestionType, SlotType


class InventorySlot(SQLModel, table=True):
    """A radar or thermometer slot in a game's question inventory.

    Pre-populated from the map's default_inventory when a game is created.
    Consumed by setting consumed_at (not deleted).
    """

    __tablename__ = 'inventory_slot'  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    game_id: uuid.UUID = Field(foreign_key='game.id', index=True)
    slot_type: SlotType
    slot_index: int
    distance_m: int | None = None
    consumed_at: datetime | None = None

    game: 'Game' = Relationship(back_populates='inventory_slots')  # noqa: F821


class CategoryUsage(SQLModel, table=True):
    """Tracks which matching/measuring categories have been used in a game.

    Created when a matching or measuring question is asked.
    """

    __tablename__ = 'category_usage'  # type: ignore[assignment]
    __table_args__ = (sa.UniqueConstraint('game_id', 'question_type', 'category', 'feature_class'),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    game_id: uuid.UUID = Field(foreign_key='game.id', index=True)
    question_type: QuestionType
    category: FeatureCategory
    feature_class: int | None = None
    consumed_at: datetime

    game: 'Game' = Relationship(back_populates='category_usages')  # noqa: F821


# Avoid circular imports — resolved at runtime by SQLModel.
from hideandseek.models.game import Game  # noqa: E402

__all__ = ['CategoryUsage', 'Game', 'InventorySlot']
