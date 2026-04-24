from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hideandseek_models.base import Base
from hideandseek_models.types import FeatureCategory, PhotoSubject, QuestionType

if TYPE_CHECKING:
    from hideandseek_models.game import Game


class InventorySlot(Base):
    """A question slot in a game's inventory.

    Pre-populated at game creation from the map's default_inventory (radar/thermometer)
    and the map's feature categories (matching/measuring). Re-askable — ask_count tracks
    how many times the slot has been used.
    """

    __tablename__ = 'inventory_slot'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('game.id'), index=True)
    question_type: Mapped[QuestionType]
    slot_index: Mapped[int]
    distance: Mapped[float | None] = mapped_column(default=None)
    category: Mapped[FeatureCategory | None] = mapped_column(default=None)
    feature_class: Mapped[int | None] = mapped_column(default=None)
    photo_subject: Mapped[PhotoSubject | None] = mapped_column(default=None)
    ask_count: Mapped[int] = mapped_column(default=0)

    game: Mapped[Game] = relationship(back_populates='inventory_slots')
