"""Question queries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select
from sqlalchemy.orm import Session

from hideandseek.db import db_read, db_write
from hideandseek.models.inventory import InventorySlot
from hideandseek.models.question import Question
from hideandseek.models.question_params import (
    FeatureQuestionParams,
    RadarParams,
    ThermometerParams,
)
from hideandseek.models.types import (
    FeatureCategory,
    QuestionStatus,
    QuestionType,
)
from hideandseek.resolution import MATCHING_CATEGORIES, MEASURING_CATEGORIES


@db_read
def has_unanswered_question(session: Session, game_id: uuid.UUID) -> bool:
    """Return True if the game has any question not in a terminal status."""
    return (
        session.scalars(
            select(Question.id).where(
                Question.game_id == game_id,
                Question.status.not_in([QuestionStatus.answered, QuestionStatus.vetoed]),
            )
        ).first()
        is not None
    )


@db_read
def get_question_count(session: Session, game_id: uuid.UUID) -> int:
    """Return the number of questions asked in a game (for sequencing)."""
    return len(session.scalars(select(Question.id).where(Question.game_id == game_id)).all())


@db_write
def create_question(
    session: Session,
    *,
    game_id: uuid.UUID,
    sequence: int,
    question_type: QuestionType,
    status: QuestionStatus,
    asked_by: uuid.UUID,
    seeker_location_start: Point,
    ask_count: int = 1,
) -> Question:
    """Create a question (without type-specific params — add those separately)."""
    q = Question(
        game_id=game_id,
        sequence=sequence,
        question_type=question_type,
        status=status,
        asked_by=asked_by,
        seeker_location_start=seeker_location_start,
        ask_count=ask_count,
    )
    if status == QuestionStatus.answerable:
        q.answerable_at = datetime.now(UTC)
    session.add(q)
    return q


@db_write
def create_radar_params(session: Session, question_id: uuid.UUID, radius: float) -> RadarParams:
    """Create radar-specific parameters for a question."""
    params = RadarParams(question_id=question_id, radius=radius)
    session.add(params)
    return params


@db_write
def create_thermometer_params(
    session: Session, question_id: uuid.UUID, min_travel: float
) -> ThermometerParams:
    """Create thermometer-specific parameters for a question."""
    params = ThermometerParams(question_id=question_id, min_travel=min_travel)
    session.add(params)
    return params


@db_write
def create_feature_params(
    session: Session,
    question_id: uuid.UUID,
    *,
    category: FeatureCategory,
    feature_class: int | None,
    source: str,
    seeker_feature_id: str,
    seeker_feature_name: str,
    seeker_distance: float,
) -> FeatureQuestionParams:
    """Create feature-specific parameters for a matching or measuring question."""
    params = FeatureQuestionParams(
        question_id=question_id,
        category=category,
        feature_class=feature_class,
        source=source,
        seeker_feature_id=seeker_feature_id,
        seeker_feature_name=seeker_feature_name,
        seeker_distance=seeker_distance,
    )
    session.add(params)
    return params


@db_read
def get_latest_total_exclusion(session: Session, game_id: uuid.UUID) -> BaseGeometry | None:
    """Return the most recent answered question's total_exclusion for a game."""
    question = session.scalars(
        select(Question)
        .where(
            Question.game_id == game_id,
            Question.status == QuestionStatus.answered,
        )
        .order_by(Question.sequence.desc())
        .limit(1)
    ).first()
    return question.total_exclusion if question else None


@db_read
def get_question(session: Session, question_id: uuid.UUID) -> Question | None:
    """Return a single question by ID."""
    return session.get(Question, question_id)


@db_read
def list_answered_questions_after_sequence(
    session: Session, game_id: uuid.UUID, after_sequence: int
) -> list[Question]:
    """Return answered questions with sequence > after_sequence, ordered by sequence."""
    return list(
        session.scalars(
            select(Question)
            .where(
                Question.game_id == game_id,
                Question.status == QuestionStatus.answered,
                Question.sequence > after_sequence,
            )
            .order_by(Question.sequence)
        ).all()
    )


@db_read
def list_questions(session: Session, game_id: uuid.UUID) -> list[Question]:
    """Return all questions for a game, chronologically."""
    return list(
        session.scalars(
            select(Question).where(Question.game_id == game_id).order_by(Question.sequence)
        ).all()
    )


@db_write
def update_question(session: Session, question: Question, updates: dict) -> Question:
    """Apply updates to a question."""
    for key, value in updates.items():
        setattr(question, key, value)
    if 'status' in updates and updates['status'] == QuestionStatus.answerable:
        question.answerable_at = datetime.now(UTC)
    session.add(question)
    return question


# ── Inventory slot queries ──────────────────────────────────────────────


@db_read
def get_inventory_slots(session: Session, game_id: uuid.UUID) -> list[InventorySlot]:
    """Return all inventory slots for a game, ordered by question_type then slot_index."""
    return list(
        session.scalars(
            select(InventorySlot)
            .where(InventorySlot.game_id == game_id)
            .order_by(InventorySlot.question_type, InventorySlot.slot_index)
        ).all()
    )


@db_read
def get_slot_by_index(
    session: Session, game_id: uuid.UUID, question_type: QuestionType, slot_index: int
) -> InventorySlot | None:
    """Return a specific slot by its type and index."""
    return session.scalars(
        select(InventorySlot).where(
            InventorySlot.game_id == game_id,
            InventorySlot.question_type == question_type,
            InventorySlot.slot_index == slot_index,
        )
    ).one_or_none()


@db_write
def use_slot(session: Session, slot: InventorySlot) -> InventorySlot:
    """Increment a slot's ask_count."""
    slot.ask_count += 1
    session.add(slot)
    return slot


@db_write
def create_inventory_slots(
    session: Session,
    game_id: uuid.UUID,
    default_inventory: dict,
    map_id: uuid.UUID,
) -> list[InventorySlot]:
    """Create InventorySlot rows from a map's default_inventory and feature categories.

    Radar/thermometer slots come from default_inventory.
    Matching/measuring slots are derived from the map's feature categories.
    """
    from hideandseek.queries.features import get_map_feature_categories
    from hideandseek.resolution import category_key

    slots: list[InventorySlot] = []

    # Radar and thermometer slots from default_inventory
    for type_key, question_type in (
        ('radars', QuestionType.radar),
        ('thermometers', QuestionType.thermometer),
    ):
        for idx, slot_data in enumerate(default_inventory.get(type_key, [])):
            slot = InventorySlot(
                game_id=game_id,
                question_type=question_type,
                slot_index=idx,
                distance=slot_data.get('distance'),
            )
            session.add(slot)
            slots.append(slot)

    # Matching and measuring slots from map feature categories
    map_cats = get_map_feature_categories(game_map_id=map_id)
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
                game_id=game_id,
                question_type=question_type,
                slot_index=idx,
                category=cat,
                feature_class=cls,
            )
            session.add(slot)
            slots.append(slot)
            idx += 1

    return slots
