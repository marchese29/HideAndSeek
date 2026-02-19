"""Question asking, answering, and listing endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from hideandseek.celery_app import app as celery_app
from hideandseek.db import get_session
from hideandseek.dependencies import get_game, get_player_in_game
from hideandseek.logic import (
    answer_matching,
    answer_measuring,
    answer_radar,
    answer_thermometer,
    ask_matching,
    ask_measuring,
    ask_radar,
    ask_thermometer,
)
from hideandseek.models.game import Game, Player
from hideandseek.models.types import (
    GameStatus,
    PlayerRole,
    PushEventType,
    QuestionStatus,
    QuestionType,
)
from hideandseek.queries.location import get_avg_seeker_location, get_latest_location_for_player
from hideandseek.queries.questions import (
    get_question,
    has_unanswered_question,
    list_questions,
    update_question,
)
from hideandseek.schemas.request import AskQuestionRequest
from hideandseek.schemas.response import QuestionResponse
from hideandseek.tasks.game_timers import auto_answer_question
from hideandseek.tasks.push import send_push
from hideandseek.validators import (
    validate_answer_request,
    validate_matching_request,
    validate_measuring_request,
    validate_slot_request,
)

router = APIRouter(
    prefix='/games/{game_id}', tags=['questions'], dependencies=[Depends(get_session)]
)


def _schedule_auto_answer(game: Game, question_id: uuid.UUID) -> None:
    delay_minutes = game.timing.get('location_question_delay_min', 5)
    auto_answer_question.apply_async(  # type: ignore[attr-defined]
        args=[str(question_id)],
        countdown=delay_minutes * 60,
        task_id=f'answer_deadline:{question_id}',
    )


@router.post('/questions', response_model=QuestionResponse, status_code=201)
def ask_question(
    body: AskQuestionRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> QuestionResponse:
    """Ask a question, spending an inventory slot or category."""
    if game.status != GameStatus.seeking:
        raise HTTPException(status_code=409, detail='Questions can only be asked during seeking.')
    if player.role != PlayerRole.seeker:
        raise HTTPException(status_code=403, detail='Only seekers can ask questions.')
    if has_unanswered_question(game.id):
        raise HTTPException(status_code=409, detail='There is already an unanswered question.')

    seeker_location = get_avg_seeker_location(game)
    if not seeker_location:
        raise HTTPException(status_code=409, detail='No seeker locations available.')

    if body.question_type == QuestionType.radar:
        validate_slot_request(body, game)
        assert body.slot_index is not None  # guaranteed by validator

        question = ask_radar(
            game, player.id, seeker_location, body.slot_index, body.custom_distance_m
        )
        _schedule_auto_answer(game, question.id)

        distance_m = question.parameters['radius_m']
        distance_label = f'{distance_m / 1000:g} km' if distance_m >= 1000 else f'{distance_m} m'
        send_push.delay(  # type: ignore[attr-defined]
            str(game.id),
            PushEventType.question_asked,
            role_filter='hider',
            alert=(
                f'A {distance_label} radar question has been asked. Your answer timer is running.'
            ),
            question_id=str(question.id),
            question_type=QuestionType.radar,
            question_status=QuestionStatus.answerable,
            parameters=question.parameters,
        )

        return QuestionResponse.from_model(question)

    if body.question_type == QuestionType.thermometer:
        validate_slot_request(body, game)
        assert body.slot_index is not None  # guaranteed by validator

        question = ask_thermometer(
            game, player.id, seeker_location, body.slot_index, body.custom_distance_m
        )

        distance_m = question.parameters['min_travel_m']
        distance_label = f'{distance_m / 1000:g} km' if distance_m >= 1000 else f'{distance_m} m'
        send_push.delay(  # type: ignore[attr-defined]
            str(game.id),
            PushEventType.question_asked,
            role_filter='hider',
            alert=(
                f'A {distance_label} thermometer question has started. The seeker is traveling.'
            ),
            question_id=str(question.id),
            question_type=QuestionType.thermometer,
            question_status=QuestionStatus.in_progress,
            parameters=question.parameters,
        )

        return QuestionResponse.from_model(question)

    if body.question_type == QuestionType.matching:
        validate_matching_request(body, game)
        assert body.category is not None  # guaranteed by validator

        question = ask_matching(game, player.id, seeker_location, body.category, body.feature_class)
        _schedule_auto_answer(game, question.id)

        send_push.delay(  # type: ignore[attr-defined]
            str(game.id),
            PushEventType.question_asked,
            role_filter='hider',
            alert=(
                f'A matching question about {body.category} has been asked. '
                f'Your answer timer is running.'
            ),
            question_id=str(question.id),
            question_type=QuestionType.matching,
            question_status=QuestionStatus.answerable,
            parameters=question.parameters,
        )

        return QuestionResponse.from_model(question)

    if body.question_type == QuestionType.measuring:
        validate_measuring_request(body, game)
        assert body.category is not None  # guaranteed by validator

        question = ask_measuring(
            game, player.id, seeker_location, body.category, body.feature_class
        )
        _schedule_auto_answer(game, question.id)

        send_push.delay(  # type: ignore[attr-defined]
            str(game.id),
            PushEventType.question_asked,
            role_filter='hider',
            alert=(
                f'A measuring question about {body.category} has been asked. '
                f'Your answer timer is running.'
            ),
            question_id=str(question.id),
            question_type=QuestionType.measuring,
            question_status=QuestionStatus.answerable,
            parameters=question.parameters,
        )

        return QuestionResponse.from_model(question)

    raise HTTPException(status_code=422, detail=f'Unsupported question type: {body.question_type}')


@router.post(
    '/questions/{question_id}/lock-in',
    response_model=QuestionResponse,
)
def lock_in_question(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> QuestionResponse:
    """Lock in the seeker's end position for a thermometer question."""
    question = get_question(question_id)
    if not question or question.game_id != game.id:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.status != QuestionStatus.in_progress:
        raise HTTPException(status_code=409, detail='Question is not in progress.')
    if question.asked_by != player.id:
        raise HTTPException(status_code=403, detail='Only the asking seeker can lock in.')

    latest = get_latest_location_for_player(player.id, game.id)
    if not latest:
        raise HTTPException(status_code=409, detail='No location reported yet.')

    question = update_question(
        question,
        {
            'seeker_location_end': latest.coordinates,
            'status': QuestionStatus.answerable,
        },
    )

    _schedule_auto_answer(game, question.id)

    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_answerable,
        role_filter='hider',
        alert='A thermometer question is ready for your answer.',
        question_id=str(question.id),
    )

    return QuestionResponse.from_model(question)


@router.post(
    '/questions/{question_id}/answer',
    response_model=QuestionResponse,
)
def answer_question(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> QuestionResponse:
    """Hider answers a question — snapshot location and compute answer."""
    question, hider_location = validate_answer_request(question_id, game, player.id, player.role)

    # Revoke the auto-answer deadline
    if not celery_app.conf.task_always_eager:
        celery_app.control.revoke(f'answer_deadline:{question.id}', terminate=False)

    # Compute answer based on question type
    if question.question_type == QuestionType.radar:
        answer, params_update = answer_radar(question, hider_location)

    elif question.question_type == QuestionType.thermometer:
        answer, params_update = answer_thermometer(question, hider_location)

    elif question.question_type == QuestionType.matching:
        answer, params_update = answer_matching(question, game, hider_location)

    elif question.question_type == QuestionType.measuring:
        answer, params_update = answer_measuring(question, game, hider_location)

    else:
        raise HTTPException(
            status_code=422, detail=f'Unsupported question type: {question.question_type}'
        )

    question = update_question(
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

    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_answered,
        role_filter='seeker',
        alert=f'Question answered: {question.answer}!',
        question_id=str(question.id),
        question_type=question.question_type,
        answer=question.answer,
    )

    return QuestionResponse.from_model(question)


@router.get('/questions', response_model=list[QuestionResponse])
def list_game_questions(
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> list[QuestionResponse]:
    """Chronological list of all questions. Hider location hidden from seekers."""
    questions = list_questions(game.id)
    hide_hider = player.role == PlayerRole.seeker
    return [QuestionResponse.from_model(q, hide_hider_location=hide_hider) for q in questions]
