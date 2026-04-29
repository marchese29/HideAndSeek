"""Overdue-timer queries for the reconciler.

Each function returns a list of IDs whose authoritative fire-time in Postgres
has passed and whose state is still in the pre-fire status. The reconciler
enqueues the existing Celery tasks for these IDs; task bodies re-check state
inside their own transaction, so a row advancing between query and task
execution is safely a no-op.

The three non-photo queries read from the future-deadline columns
(`Game.hiding_ends_at`, `Question.deadline_at`, `Game.found_claim_expires_at`)
and skip paused games via `Game.paused_at IS NULL`. The two photo queries
still resolve their windows in Python from start anchors + per-game settings;
they migrate to dedicated deadline columns in m8r.nah / z32.5.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from hideandseek_core.conventions import effective_photo_review_sec, effective_photo_submit_min
from hideandseek_core.db import get_session
from hideandseek_models.game import Game
from hideandseek_models.question import Question
from hideandseek_models.question_params import PhotoQuestionParams
from hideandseek_models.types import GameStatus, QuestionStatus, QuestionType


def find_overdue_hiding_games() -> list[uuid.UUID]:
    """Games whose hiding→seeking deadline has passed and are still in hiding."""
    session = get_session()
    return list(
        session.scalars(
            select(Game.id).where(
                Game.status == GameStatus.hiding,
                Game.hiding_ends_at.is_not(None),
                Game.hiding_ends_at <= func.now(),
                Game.paused_at.is_(None),
            )
        )
    )


def find_overdue_answerable_questions() -> list[uuid.UUID]:
    """Answerable questions whose auto-answer deadline has passed.

    Filters by Game.status == seeking so that ending or dissolving a game with
    an active answerable question naturally cancels its auto-answer (instead
    of requiring an explicit revoke). Paused games are skipped — resume shifts
    Question.deadline_at forward before clearing Game.paused_at.
    """
    session = get_session()
    return list(
        session.scalars(
            select(Question.id)
            .join(Game, Question.game_id == Game.id)
            .where(
                Game.status == GameStatus.seeking,
                Question.status == QuestionStatus.answerable,
                Question.question_type != QuestionType.photo,
                Question.deadline_at.is_not(None),
                Question.deadline_at <= func.now(),
                Game.paused_at.is_(None),
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
    now = datetime.now(UTC)
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
    now = datetime.now(UTC)
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
    return list(
        session.scalars(
            select(Game.id).where(
                Game.status.in_([GameStatus.hiding, GameStatus.seeking]),
                Game.found_claim_expires_at.is_not(None),
                Game.found_claim_expires_at <= func.now(),
                Game.paused_at.is_(None),
            )
        )
    )
