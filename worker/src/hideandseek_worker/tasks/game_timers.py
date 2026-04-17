"""Game timer tasks: phase transitions and answer deadlines."""

from __future__ import annotations

import uuid

import structlog

from hideandseek_core.broadcast.emit import emit_gameplay
from hideandseek_core.broadcast.events import (
    FoundClaimExpiredEvent,
    HiderQuestionAnsweredEvent,
    PhaseChangedEvent,
    QuestionVetoedEvent,
    SeekerQuestionAnsweredEvent,
    StationElectionEvent,
)
from hideandseek_core.db import session_scope
from hideandseek_core.logic.answer import (
    answer_matching,
    answer_measuring,
    answer_radar,
    answer_tentacles,
    answer_thermometer,
    veto_immediate,
)
from hideandseek_core.logic.endgame import expire_found_claim
from hideandseek_core.logic.station import (
    resolve_station_at_transition,
    resolve_station_fallback,
)
from hideandseek_core.queries.games import (
    get_game_by_id,
    set_hider_station,
    set_station_ambiguous,
    update_game_status,
)
from hideandseek_core.queries.location import get_latest_location_for_player
from hideandseek_core.queries.questions import get_question
from hideandseek_models.types import (
    GameStatus,
    PlayerRole,
    PushEventType,
    QuestionStatus,
    QuestionType,
    StationElectionStatus,
)
from hideandseek_worker.celery_app import app
from hideandseek_worker.tasks.push import send_push

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
        if not game.status.is_hiding:
            logger.info('transition_skipped', game_id=game_id, status=game.status)
            return

        # Resolve station election
        stop, status = resolve_station_at_transition(game)
        if status == StationElectionStatus.auto_assigned and stop:
            set_hider_station(game, stop, StationElectionStatus.auto_assigned)
            logger.info('station_auto_assigned', game_id=game_id, stop_id=str(stop.id))
            send_push.delay(  # type: ignore[attr-defined]
                game_id,
                PushEventType.station_auto_assigned,
                role_filter='hider',
                alert=f'Your station was auto-assigned: {stop.name}',
            )
            emit_gameplay(
                StationElectionEvent(
                    game_id=game.id,
                    station_election_status=StationElectionStatus.auto_assigned,
                    hider_station_id=stop.id,
                )
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
            emit_gameplay(
                StationElectionEvent(
                    game_id=game.id,
                    station_election_status=StationElectionStatus.ambiguous,
                    hider_station_id=None,
                )
            )
        # elected: already set, nothing to do

        update_game_status(game, GameStatus.seeking)
        logger.info('transition_hiding_to_seeking', game_id=game_id)

        send_push.delay(  # type: ignore[attr-defined]
            game_id,
            PushEventType.phase_changed,
            alert='The seeking phase has begun! Start asking questions.',
        )

        assert game.seeking_started_at is not None
        emit_gameplay(
            PhaseChangedEvent(
                game_id=game.id,
                phase=game.status,
                seeking_started_at=game.seeking_started_at,
                station_election_status=game.station_election_status,
                hider_station_id=game.hider_station_id,
            )
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

        # Scheduled veto: veto instead of computing an answer
        if question.scheduled_veto:
            veto_immediate(question)
            game_id = str(question.game_id)
            logger.info('scheduled_veto_executed', question_id=question_id, game_id=game_id)
            send_push.delay(  # type: ignore[attr-defined]
                game_id,
                PushEventType.question_vetoed,
                role_filter='seeker',
                alert='The hider used a veto!',
                question_id=question_id,
                question_type=question.question_type,
            )
            emit_gameplay(QuestionVetoedEvent.from_question(question))
            return

        # Resolve ambiguous station before computing the answer
        if game.station_election_status == StationElectionStatus.ambiguous:
            stop = resolve_station_fallback(game)
            set_hider_station(game, stop, StationElectionStatus.auto_assigned)
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
            emit_gameplay(
                StationElectionEvent(
                    game_id=game.id,
                    station_election_status=StationElectionStatus.auto_assigned,
                    hider_station_id=stop.id,
                )
            )

        # Find the hider's latest location
        hiders = [p for p in game.players if p.role == PlayerRole.hider]
        if not hiders:
            logger.error('auto_answer_no_hider', game_id=str(game.id))
            return
        latest = get_latest_location_for_player(hiders[0], game)
        if not latest:
            logger.error('auto_answer_no_hider_location', game_id=str(game.id))
            return

        # Set hider location, compute answer + exclusion, persist
        question.hider_location = latest.coordinates

        if question.question_type == QuestionType.radar:
            answer_radar(question, game)
        elif question.question_type == QuestionType.thermometer:
            answer_thermometer(question, game)
        elif question.question_type == QuestionType.matching:
            answer_matching(question, game)
        elif question.question_type == QuestionType.measuring:
            answer_measuring(question, game)
        elif question.question_type == QuestionType.tentacles:
            answer_tentacles(question, game)
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

        emit_gameplay(HiderQuestionAnsweredEvent.from_question(question))
        emit_gameplay(SeekerQuestionAnsweredEvent.from_question(question))


@app.task
def auto_dismiss_found_claim(game_id: str) -> None:
    """Dismiss a pending found claim after the 2-minute deadline expires.

    Idempotent: no-op if the claim has already been confirmed, rejected, or if
    the game is no longer active.
    """
    with session_scope():
        game = get_game_by_id(uuid.UUID(game_id))
        if not game:
            logger.warning('found_claim_expire_game_not_found', game_id=game_id)
            return
        if not expire_found_claim(game):
            logger.info('found_claim_expire_skipped', game_id=game_id)
            return

        logger.info('found_claim_expired', game_id=game_id)
        emit_gameplay(FoundClaimExpiredEvent(game_id=game.id))
        send_push.delay(  # type: ignore[attr-defined]
            game_id,
            PushEventType.found_claim_expired,
            alert='The found claim timed out.',
        )
