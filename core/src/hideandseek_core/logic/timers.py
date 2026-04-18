"""Overdue-timer queries for the reconciler.

Each function returns a list of IDs whose authoritative fire-time in Postgres
has passed and whose state is still in the pre-fire status. The reconciler
enqueues the existing Celery tasks for these IDs; task bodies re-check state
inside their own transaction, so a row advancing between query and task
execution is safely a no-op.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from hideandseek_core.db import get_session
from hideandseek_core.logic.endgame import FOUND_CLAIM_TIMEOUT_SECONDS
from hideandseek_models.game import Game
from hideandseek_models.question import Question
from hideandseek_models.types import GameStatus, QuestionStatus


def find_overdue_hiding_games() -> list[uuid.UUID]:
    """Games whose hiding→seeking deadline has passed and are still in hiding."""
    session = get_session()
    # Deadline = hiding_started_at + (hiding_time_min * 1 minute)
    deadline = Game.hiding_started_at + func.make_interval(0, 0, 0, 0, 0, Game.hiding_time_min)
    return list(
        session.scalars(
            select(Game.id).where(
                Game.status == GameStatus.hiding,
                Game.hiding_started_at.is_not(None),
                deadline <= func.now(),
            )
        )
    )


def find_overdue_answerable_questions() -> list[uuid.UUID]:
    """Answerable questions whose auto-answer deadline has passed.

    Deadline = question.answerable_at + (game.base_question_delay_min * 1 minute).
    Filters by Game.status == seeking so that ending or dissolving a game with
    an active answerable question naturally cancels its auto-answer (instead
    of requiring an explicit revoke).
    """
    session = get_session()
    deadline = Question.answerable_at + func.make_interval(
        0, 0, 0, 0, 0, Game.base_question_delay_min
    )
    return list(
        session.scalars(
            select(Question.id)
            .join(Game, Question.game_id == Game.id)
            .where(
                Game.status == GameStatus.seeking,
                Question.status == QuestionStatus.answerable,
                Question.answerable_at.is_not(None),
                deadline <= func.now(),
            )
        )
    )


def find_overdue_found_claims() -> list[uuid.UUID]:
    """Games whose 2-minute found-claim window has elapsed with no resolution."""
    session = get_session()
    deadline = Game.found_claim_at + func.make_interval(
        0, 0, 0, 0, 0, 0, FOUND_CLAIM_TIMEOUT_SECONDS
    )
    return list(
        session.scalars(
            select(Game.id).where(
                Game.status.in_([GameStatus.hiding, GameStatus.seeking]),
                Game.found_claim_at.is_not(None),
                deadline <= func.now(),
            )
        )
    )
