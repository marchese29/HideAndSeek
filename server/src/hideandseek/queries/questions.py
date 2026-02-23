"""Question queries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from sqlmodel import Session, select

from hideandseek.db import db_read, db_write
from hideandseek.models.inventory import CategoryUsage, InventorySlot
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
    SlotType,
)


@db_read
def has_unanswered_question(session: Session, game_id: uuid.UUID) -> bool:
    """Return True if the game has any question not yet in 'answered' status."""
    return (
        session.exec(
            select(Question.id).where(
                Question.game_id == game_id,
                Question.status != QuestionStatus.answered,
            )
        ).first()
        is not None
    )


@db_read
def get_question_count(session: Session, game_id: uuid.UUID) -> int:
    """Return the number of questions asked in a game (for sequencing)."""
    return len(session.exec(select(Question.id).where(Question.game_id == game_id)).all())


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
) -> Question:
    """Create a question (without type-specific params — add those separately)."""
    q = Question(
        game_id=game_id,
        sequence=sequence,
        question_type=question_type,
        status=status,
        asked_by=asked_by,
        seeker_location_start=seeker_location_start,
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
    question = session.exec(
        select(Question)
        .where(
            Question.game_id == game_id,
            Question.status == QuestionStatus.answered,
        )
        .order_by(Question.sequence.desc())  # type: ignore[arg-type]
        .limit(1)
    ).first()
    return question.total_exclusion if question else None


@db_read
def get_question(session: Session, question_id: uuid.UUID) -> Question | None:
    """Return a single question by ID."""
    return session.get(Question, question_id)


@db_read
def list_questions(session: Session, game_id: uuid.UUID) -> list[Question]:
    """Return all questions for a game, chronologically."""
    return list(
        session.exec(
            select(Question).where(Question.game_id == game_id).order_by(Question.sequence)  # type: ignore[arg-type]
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
def get_available_slots(
    session: Session, game_id: uuid.UUID, slot_type: SlotType
) -> list[InventorySlot]:
    """Return unconsumed slots of the given type, ordered by slot_index."""
    return list(
        session.exec(
            select(InventorySlot)
            .where(
                InventorySlot.game_id == game_id,
                InventorySlot.slot_type == slot_type,
                InventorySlot.consumed_at.is_(None),  # type: ignore[union-attr]
            )
            .order_by(InventorySlot.slot_index)  # type: ignore[arg-type]
        ).all()
    )


@db_write
def consume_slot(session: Session, slot: InventorySlot) -> InventorySlot:
    """Mark a slot as consumed."""
    slot.consumed_at = datetime.now(UTC)
    session.add(slot)
    return slot


@db_write
def create_inventory_slots(
    session: Session, game_id: uuid.UUID, default_inventory: dict
) -> list[InventorySlot]:
    """Create InventorySlot rows from a map's default_inventory template."""
    slots: list[InventorySlot] = []
    for slot_type_str in ('radars', 'thermometers'):
        slot_type = SlotType.radar if slot_type_str == 'radars' else SlotType.thermometer
        for idx, slot_data in enumerate(default_inventory.get(slot_type_str, [])):
            slot = InventorySlot(
                game_id=game_id,
                slot_type=slot_type,
                slot_index=idx,
                distance=slot_data.get('distance'),
            )
            session.add(slot)
            slots.append(slot)
    return slots


# ── Category usage queries ──────────────────────────────────────────────


@db_write
def record_category_usage(
    session: Session,
    game_id: uuid.UUID,
    question_type: QuestionType,
    category: FeatureCategory,
    feature_class: int | None,
) -> CategoryUsage:
    """Record that a category has been used for a question type in a game."""
    usage = CategoryUsage(
        game_id=game_id,
        question_type=question_type,
        category=category,
        feature_class=feature_class,
        consumed_at=datetime.now(UTC),
    )
    session.add(usage)
    return usage


@db_read
def get_category_usages(
    session: Session, game_id: uuid.UUID, question_type: QuestionType
) -> list[CategoryUsage]:
    """Return all category usages for a game and question type."""
    return list(
        session.exec(
            select(CategoryUsage).where(
                CategoryUsage.game_id == game_id,
                CategoryUsage.question_type == question_type,
            )
        ).all()
    )


@db_read
def is_category_used(
    session: Session,
    game_id: uuid.UUID,
    question_type: QuestionType,
    category: FeatureCategory,
    feature_class: int | None,
) -> bool:
    """Check whether a category has already been used."""
    stmt = select(CategoryUsage.id).where(
        CategoryUsage.game_id == game_id,
        CategoryUsage.question_type == question_type,
        CategoryUsage.category == category,
    )
    if feature_class is not None:
        stmt = stmt.where(CategoryUsage.feature_class == feature_class)
    else:
        stmt = stmt.where(CategoryUsage.feature_class.is_(None))  # type: ignore[union-attr]
    return session.exec(stmt).first() is not None
