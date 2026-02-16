"""Question queries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import Session, select

from hideandseek.db import db_read, db_write
from hideandseek.models.game import Game
from hideandseek.models.question import Question
from hideandseek.models.types import QuestionStatus, QuestionType


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
    parameters: dict,
    asked_by: uuid.UUID,
    seeker_location_start: dict,
) -> Question:
    """Create a question."""
    q = Question(
        game_id=game_id,
        sequence=sequence,
        question_type=question_type,
        status=status,
        parameters=parameters,
        asked_by=asked_by,
        seeker_location_start=seeker_location_start,
    )
    if status == QuestionStatus.answerable:
        q.answerable_at = datetime.now(UTC)
    session.add(q)
    return q


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


@db_write
def update_game_inventory(session: Session, game: Game, inventory: dict) -> Game:
    """Update a game's inventory."""
    game.inventory = inventory
    session.add(game)
    return game
