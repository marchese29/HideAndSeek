"""Overdue-timer queries for the reconciler.

Each function returns a list of IDs whose authoritative fire-time in Postgres
has passed and whose state is still in the pre-fire status. The reconciler
enqueues the existing Celery tasks for these IDs; task bodies re-check state
inside their own transaction, so a row advancing between query and task
execution is safely a no-op.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from hideandseek_core.conventions import effective_photo_review_sec, effective_photo_submit_min
from hideandseek_core.db import get_session
from hideandseek_core.logic.endgame import FOUND_CLAIM_TIMEOUT_SECONDS
from hideandseek_models.game import Game
from hideandseek_models.question import Question
from hideandseek_models.question_params import PhotoQuestionParams
from hideandseek_models.types import GameStatus, QuestionStatus, QuestionType


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
                Question.question_type != QuestionType.photo,
                Question.answerable_at.is_not(None),
                deadline <= func.now(),
            )
        )
    )


def find_overdue_photo_submissions() -> list[uuid.UUID]:
    """Photo questions whose submit-window deadline has passed in `answerable`.

    Deadline = question.answerable_at + effective_photo_submit_min(game) minutes.
    The submit window is per-game (request override → map default → code default),
    so the deadline filter happens in Python after a SQL pre-filter on type/status.
    """
    session = get_session()
    rows = list(
        session.execute(
            select(Question, Game)
            .join(Game, Question.game_id == Game.id)
            .options(selectinload(Game.game_map))
            .where(
                Game.status == GameStatus.seeking,
                Question.status == QuestionStatus.answerable,
                Question.question_type == QuestionType.photo,
                Question.answerable_at.is_not(None),
            )
        )
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    overdue: list[uuid.UUID] = []
    for question, game in rows:
        assert question.answerable_at is not None
        elapsed = (now - question.answerable_at).total_seconds()
        if elapsed >= effective_photo_submit_min(game) * 60:
            overdue.append(question.id)
    return overdue


def find_overdue_photo_reviews() -> list[uuid.UUID]:
    """Submitted photo questions whose review-window deadline has passed.

    Deadline = photo_params.submitted_at + effective_photo_review_sec(game) seconds.
    """
    session = get_session()
    rows = list(
        session.execute(
            select(Question, PhotoQuestionParams, Game)
            .join(PhotoQuestionParams, PhotoQuestionParams.question_id == Question.id)
            .join(Game, Question.game_id == Game.id)
            .options(selectinload(Game.game_map))
            .where(
                Game.status == GameStatus.seeking,
                Question.status == QuestionStatus.submitted,
                Question.question_type == QuestionType.photo,
                PhotoQuestionParams.submitted_at.is_not(None),
            )
        )
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    overdue: list[uuid.UUID] = []
    for question, params, game in rows:
        assert params.submitted_at is not None
        elapsed = (now - params.submitted_at).total_seconds()
        if elapsed >= effective_photo_review_sec(game):
            overdue.append(question.id)
    return overdue


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
