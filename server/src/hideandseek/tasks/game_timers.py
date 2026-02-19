"""Game timer tasks: phase transitions and answer deadlines."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog

from hideandseek.celery_app import app
from hideandseek.db import session_scope
from hideandseek.logic import answer_matching, answer_measuring, answer_radar, answer_thermometer
from hideandseek.models.types import (
    GameStatus,
    PlayerRole,
    PushEventType,
    QuestionStatus,
    QuestionType,
)
from hideandseek.queries.games import get_game_by_id, update_game_status
from hideandseek.queries.location import get_latest_location_for_player
from hideandseek.queries.questions import get_question, update_question
from hideandseek.tasks.push import send_push

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@app.task
def transition_hiding_to_seeking(game_id: str) -> None:
    """Transition a game from hiding to seeking after the hiding timer expires.

    Idempotent: no-op if the game is not in hiding status.
    """
    with session_scope():
        game = get_game_by_id(uuid.UUID(game_id))
        if not game:
            logger.warning('transition_game_not_found', game_id=game_id)
            return
        if game.status != GameStatus.hiding:
            logger.info('transition_skipped', game_id=game_id, status=game.status)
            return

        update_game_status(game, GameStatus.seeking)
        logger.info('transition_hiding_to_seeking', game_id=game_id)

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
    with session_scope():
        question = get_question(uuid.UUID(question_id))
        if not question:
            logger.warning('auto_answer_question_not_found', question_id=question_id)
            return
        if question.status != QuestionStatus.answerable:
            logger.info('auto_answer_skipped', question_id=question_id, status=question.status)
            return

        game = get_game_by_id(question.game_id)
        if not game:
            logger.warning('auto_answer_game_not_found', game_id=str(question.game_id))
            return

        # Find the hider's latest location
        hiders = [p for p in game.players if p.role == PlayerRole.hider]
        if not hiders:
            logger.error('auto_answer_no_hider', game_id=str(game.id))
            return
        latest = get_latest_location_for_player(hiders[0].id, game.id)
        if not latest:
            logger.error('auto_answer_no_hider_location', game_id=str(game.id))
            return
        hider_location = latest.coordinates

        # Compute answer
        if question.question_type == QuestionType.radar:
            answer, params_update = answer_radar(question, hider_location)

        elif question.question_type == QuestionType.thermometer:
            answer, params_update = answer_thermometer(question, hider_location)

        elif question.question_type == QuestionType.matching:
            answer, params_update = answer_matching(question, game, hider_location)

        elif question.question_type == QuestionType.measuring:
            answer, params_update = answer_measuring(question, game, hider_location)

        else:
            logger.error('auto_answer_unknown_type', question_type=question.question_type)
            return

        update_question(
            question,
            {
                'hider_location': hider_location,
                'answer': answer,
                'exclusion': None,
                'answered_at': datetime.now(UTC),
                'status': QuestionStatus.answered,
                'parameters': params_update,
            },
        )

        game_id = str(question.game_id)
        logger.info('auto_answer_question', question_id=question_id, game_id=game_id)

        send_push.delay(  # type: ignore[attr-defined]
            game_id,
            PushEventType.question_auto_answered,
            role_filter='seeker',
            alert='Question auto-answered! The hider ran out of time.',
            question_id=question_id,
            question_type=question.question_type,
            answer=question.answer,
        )
