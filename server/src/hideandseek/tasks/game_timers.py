"""Game timer tasks: phase transitions and answer deadlines."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlmodel import Session, select

from hideandseek.celery_app import app
from hideandseek.db import engine
from hideandseek.geo import geojson_distance
from hideandseek.models.game import Game
from hideandseek.models.location import LocationUpdate
from hideandseek.models.question import Question
from hideandseek.models.types import (
    GameStatus,
    PlayerRole,
    PushEventType,
    QuestionStatus,
    QuestionType,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@app.task
def transition_hiding_to_seeking(game_id: str) -> None:
    """Transition a game from hiding to seeking after the hiding timer expires.

    Idempotent: no-op if the game is not in hiding status.
    """
    with Session(engine) as session:
        game = session.get(Game, uuid.UUID(game_id))
        if not game:
            logger.warning('transition_game_not_found', game_id=game_id)
            return
        if game.status != GameStatus.hiding:
            logger.info('transition_skipped', game_id=game_id, status=game.status)
            return

        game.status = GameStatus.seeking
        game.seeking_started_at = datetime.now(UTC)
        session.add(game)
        session.commit()

        logger.info('transition_hiding_to_seeking', game_id=game_id)

    from hideandseek.tasks.push import send_push

    send_push.delay(  # type: ignore[attr-defined]
        game_id,
        PushEventType.phase_changed,
        alert='The seeking phase has begun! Start asking questions.',
    )


@app.task
def auto_answer_question(question_id: str) -> None:
    """Auto-answer a question after the answer deadline expires.

    Idempotent: no-op if the question is not in answerable status.
    """
    with Session(engine) as session:
        question = session.get(Question, uuid.UUID(question_id))
        if not question:
            logger.warning('auto_answer_question_not_found', question_id=question_id)
            return
        if question.status != QuestionStatus.answerable:
            logger.info('auto_answer_skipped', question_id=question_id, status=question.status)
            return

        game = session.get(Game, question.game_id)
        if not game:
            logger.warning('auto_answer_game_not_found', game_id=str(question.game_id))
            return

        # Find the hider and snapshot their latest location
        hiders = [p for p in game.players if p.role == PlayerRole.hider]
        hider_location: dict | None = None
        if hiders:
            latest = session.exec(
                select(LocationUpdate)
                .where(
                    LocationUpdate.player_id == hiders[0].id,
                    LocationUpdate.game_id == game.id,
                )
                .order_by(LocationUpdate.id.desc())  # type: ignore[union-attr]
                .limit(1)
            ).first()
            if latest:
                hider_location = latest.coordinates

        # Compute answer from distance, or fall back to 'pending' if no hider location
        if hider_location:
            if question.question_type == QuestionType.radar:
                dist = geojson_distance(question.seeker_location_start, hider_location)
                question.answer = 'yes' if dist <= question.parameters['radius_m'] else 'no'
            else:
                dist_start = geojson_distance(question.seeker_location_start, hider_location)
                # seeker_location_end is guaranteed set after lock-in
                dist_end = geojson_distance(question.seeker_location_end, hider_location)  # type: ignore[arg-type]
                question.answer = 'closer' if dist_end < dist_start else 'farther'
        else:
            question.answer = 'pending'
        question.exclusion = None
        question.hider_location = hider_location
        question.answered_at = datetime.now(UTC)
        question.status = QuestionStatus.answered
        session.add(question)
        session.commit()

        game_id = str(question.game_id)
        logger.info('auto_answer_question', question_id=question_id, game_id=game_id)

    from hideandseek.tasks.push import send_push

    send_push.delay(  # type: ignore[attr-defined]
        game_id,
        PushEventType.question_auto_answered,
        role_filter='seeker',
        alert='Question auto-answered! The hider ran out of time.',
        question_id=question_id,
        question_type=question.question_type,
        answer=question.answer,
    )
