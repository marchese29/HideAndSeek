"""Game timer tasks: phase transitions and answer deadlines."""

from __future__ import annotations

import uuid

import structlog

from hideandseek.celery_app import app
from hideandseek.db import session_scope
from hideandseek.logic import (
    answer_matching,
    answer_measuring,
    answer_radar,
    answer_thermometer,
    resolve_station_at_transition,
    resolve_station_fallback,
)
from hideandseek.models.types import (
    GameStatus,
    PlayerRole,
    PushEventType,
    QuestionStatus,
    QuestionType,
    StationElectionStatus,
)
from hideandseek.queries.games import (
    get_game_by_id,
    set_hider_station,
    set_station_ambiguous,
    update_game_status,
)
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

        # Resolve station election
        stop, status = resolve_station_at_transition(game)
        if status == StationElectionStatus.auto_assigned and stop:
            set_hider_station(game, stop.id, StationElectionStatus.auto_assigned)
            logger.info('station_auto_assigned', game_id=game_id, stop_id=str(stop.id))
            send_push.delay(  # type: ignore[attr-defined]
                game_id,
                PushEventType.station_auto_assigned,
                role_filter='hider',
                alert=f'Your station was auto-assigned: {stop.name}',
            )
        elif status == StationElectionStatus.ambiguous:
            set_station_ambiguous(game)
            logger.info('station_ambiguous', game_id=game_id)
            send_push.delay(  # type: ignore[attr-defined]
                game_id,
                PushEventType.station_ambiguous,
                role_filter='hider',
                alert='Station could not be determined. Please select your station.',
            )
        # elected: already set, nothing to do

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

        # Resolve ambiguous station before computing the answer
        if game.station_election_status == StationElectionStatus.ambiguous:
            stop = resolve_station_fallback(game)
            set_hider_station(game, stop.id, StationElectionStatus.auto_assigned)
            logger.info(
                'station_auto_resolved',
                game_id=str(game.id),
                stop_id=str(stop.id),
            )
            send_push.delay(  # type: ignore[attr-defined]
                str(game.id),
                PushEventType.station_auto_resolved,
                role_filter='hider',
                alert=f'Your station was auto-resolved: {stop.name}',
            )

        # Find the hider's latest location
        hiders = [p for p in game.players if p.role == PlayerRole.hider]
        if not hiders:
            logger.error('auto_answer_no_hider', game_id=str(game.id))
            return
        latest = get_latest_location_for_player(hiders[0].id, game.id)
        if not latest:
            logger.error('auto_answer_no_hider_location', game_id=str(game.id))
            return

        # Set hider location, compute answer + exclusion, persist
        update_question(question, {'hider_location': latest.coordinates})

        if question.question_type == QuestionType.radar:
            answer_radar(question, game)
        elif question.question_type == QuestionType.thermometer:
            answer_thermometer(question, game)
        elif question.question_type == QuestionType.matching:
            answer_matching(question, game)
        elif question.question_type == QuestionType.measuring:
            answer_measuring(question, game)
        else:
            logger.error('auto_answer_unknown_type', question_type=question.question_type)
            return

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
