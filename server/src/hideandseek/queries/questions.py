"""Question queries."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from shapely.geometry.base import BaseGeometry
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from hideandseek.db import get_session
from hideandseek.models.game import Game
from hideandseek.models.inventory import InventorySlot
from hideandseek.models.question import Question
from hideandseek.models.types import (
    MATCHING_CATEGORIES,
    MEASURING_CATEGORIES,
    QuestionStatus,
    QuestionType,
    category_key,
)
from hideandseek.queries.features import get_map_feature_categories


def has_unanswered_question(game: Game) -> bool:
    """Return True if the game has any question not in a terminal status."""
    session = get_session()
    return (
        session.scalars(
            select(Question.id).where(
                Question.game_id == game.id,
                Question.status.not_in(
                    [
                        QuestionStatus.answered,
                        QuestionStatus.vetoed,
                        QuestionStatus.abandoned,
                    ]
                ),
            )
        ).first()
        is not None
    )


def get_question_count(game: Game) -> int:
    """Return the number of questions asked in a game (for sequencing)."""
    session = get_session()
    return len(session.scalars(select(Question.id).where(Question.game_id == game.id)).all())


def get_latest_total_exclusion(game: Game) -> BaseGeometry | None:
    """Return the most recent answered question's total_exclusion for a game."""
    session = get_session()
    question = session.scalars(
        select(Question)
        .where(
            Question.game_id == game.id,
            Question.status == QuestionStatus.answered,
        )
        .order_by(Question.sequence.desc())
        .limit(1)
    ).one_or_none()
    return question.total_exclusion if question else None


def get_active_question(game: Game) -> Question | None:
    """Return the active (non-terminal) question, or None."""
    session = get_session()
    return session.scalars(
        select(Question).where(
            Question.game_id == game.id,
            Question.status.not_in(
                [
                    QuestionStatus.answered,
                    QuestionStatus.vetoed,
                    QuestionStatus.abandoned,
                ]
            ),
        )
    ).one_or_none()


def get_question(question_id: uuid.UUID) -> Question | None:
    """Return a single question by ID."""
    session = get_session()
    return session.get(Question, question_id)


def list_answered_questions_after_sequence(game: Game, after_sequence: int) -> Sequence[Question]:
    """Return answered questions with sequence > after_sequence, ordered by sequence."""
    session = get_session()
    return session.scalars(
        select(Question)
        .where(
            Question.game_id == game.id,
            Question.status == QuestionStatus.answered,
            Question.sequence > after_sequence,
        )
        .order_by(Question.sequence)
    ).all()


def list_questions(game: Game) -> Sequence[Question]:
    """Return all questions for a game, chronologically.

    Eager-loads param relationships to avoid N+1 queries when building
    event parameters or history entries.
    """
    session = get_session()
    return (
        session.scalars(
            select(Question)
            .where(Question.game_id == game.id)
            .options(
                joinedload(Question.radar_params),
                joinedload(Question.thermometer_params),
                joinedload(Question.feature_params),
            )
            .order_by(Question.sequence)
        )
        .unique()
        .all()
    )


# ── Inventory slot queries ──────────────────────────────────────────────


def get_inventory_slots(game: Game) -> Sequence[InventorySlot]:
    """Return all inventory slots for a game, ordered by question_type then slot_index."""
    session = get_session()
    return session.scalars(
        select(InventorySlot)
        .where(InventorySlot.game == game)
        .order_by(InventorySlot.question_type, InventorySlot.slot_index)
    ).all()


def get_slot_by_index(
    game: Game, question_type: QuestionType, slot_index: int
) -> InventorySlot | None:
    """Return a specific slot by its type and index."""
    session = get_session()
    return session.scalars(
        select(InventorySlot).where(
            InventorySlot.game == game,
            InventorySlot.question_type == question_type,
            InventorySlot.slot_index == slot_index,
        )
    ).one_or_none()


def use_slot(slot: InventorySlot) -> InventorySlot:
    """Increment a slot's ask_count."""
    session = get_session()
    slot.ask_count += 1
    session.add(slot)
    session.flush()
    return slot


def create_inventory_slots(
    game: Game,
    default_inventory: dict,
) -> list[InventorySlot]:
    """Create InventorySlot rows from a map's default_inventory and feature categories.

    Radar/thermometer slots come from default_inventory.
    Matching/measuring slots are derived from the map's feature categories.
    """
    session = get_session()
    slots: list[InventorySlot] = []

    # Radar and thermometer slots from default_inventory
    for type_key, question_type in (
        ('radars', QuestionType.radar),
        ('thermometers', QuestionType.thermometer),
    ):
        for idx, slot_data in enumerate(default_inventory.get(type_key, [])):
            slot = InventorySlot(
                game=game,
                question_type=question_type,
                slot_index=idx,
                distance=slot_data.get('distance'),
            )
            session.add(slot)
            slots.append(slot)

    # Matching and measuring slots from map feature categories
    map_cats = get_map_feature_categories(game_map=game.game_map)
    # Sort by category_key for deterministic slot_index ordering
    sorted_cats = sorted(map_cats, key=lambda pair: category_key(pair[0], pair[1]))

    for question_type, type_categories in (
        (QuestionType.matching, MATCHING_CATEGORIES),
        (QuestionType.measuring, MEASURING_CATEGORIES),
    ):
        idx = 0
        for cat, cls in sorted_cats:
            if cat not in type_categories:
                continue
            slot = InventorySlot(
                game=game,
                question_type=question_type,
                slot_index=idx,
                category=cat,
                feature_class=cls,
            )
            session.add(slot)
            slots.append(slot)
            idx += 1

    session.flush()
    return slots
