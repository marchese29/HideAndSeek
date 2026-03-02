import uuid

from sqlmodel import Field, Relationship, SQLModel

from hideandseek.models.types import FeatureCategory, QuestionType


class InventorySlot(SQLModel, table=True):
    """A question slot in a game's inventory.

    Pre-populated at game creation from the map's default_inventory (radar/thermometer)
    and the map's feature categories (matching/measuring). Re-askable — ask_count tracks
    how many times the slot has been used.
    """

    __tablename__ = 'inventory_slot'  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    game_id: uuid.UUID = Field(foreign_key='game.id', index=True)
    question_type: QuestionType
    slot_index: int
    distance: float | None = None
    category: FeatureCategory | None = None
    feature_class: int | None = None
    ask_count: int = 0

    game: 'Game' = Relationship(back_populates='inventory_slots')  # noqa: F821


# Avoid circular imports — resolved at runtime by SQLModel.
from hideandseek.models.game import Game  # noqa: E402

__all__ = ['Game', 'InventorySlot']
