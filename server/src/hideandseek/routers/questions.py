"""Question asking, answering, and listing endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from geojson_pydantic import Point as GeoJSONPoint
from shapely.geometry import Point as ShapelyPoint

from hideandseek.celery_app import app as celery_app
from hideandseek.conventions import format_distance_label
from hideandseek.db import get_session
from hideandseek.dependencies import (
    get_game,
    get_hider_in_game,
    get_player_in_game,
    get_seeker_in_game,
)
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
    PushEventType,
    QuestionStatus,
    QuestionType,
)
from hideandseek.queries.location import create_location_update, get_latest_location_for_player
from hideandseek.queries.questions import (
    get_question,
    has_unanswered_question,
    list_questions,
    update_question,
)
from hideandseek.schemas.request import AskQuestionRequest
from hideandseek.schemas.response import (
    AskQuestionResponse,
    ExclusionsResponse,
    QuestionDetailResponse,
    QuestionExclusionEntry,
    QuestionSummaryResponse,
    geom_or_none,
)
from hideandseek.tasks.game_timers import auto_answer_question
from hideandseek.tasks.push import send_push
from hideandseek.validators import validate_answer_request, validate_slot_request

router = APIRouter(
    prefix='/games/{game_id}', tags=['questions'], dependencies=[Depends(get_session)]
)


def _schedule_auto_answer(game: Game, question_id: uuid.UUID) -> None:
    delay_minutes = game.base_question_delay_min
    auto_answer_question.apply_async(  # type: ignore[attr-defined]
        args=[str(question_id)],
        countdown=delay_minutes * 60,
        task_id=f'answer_deadline:{question_id}',
    )


def _validate_can_ask(game: Game) -> None:
    """Common pre-ask validation: game must be seeking, no unanswered question."""
    if game.status != GameStatus.seeking:
        raise HTTPException(status_code=409, detail='Questions can only be asked during seeking.')
    if has_unanswered_question(game.id):
        raise HTTPException(status_code=409, detail='There is already an unanswered question.')


def _record_seeker_location(location: GeoJSONPoint, player: Player, game: Game) -> ShapelyPoint:
    """Record the seeker's location from the request body and return as shapely Point."""
    seeker_location = ShapelyPoint(location.coordinates[0], location.coordinates[1])
    create_location_update(
        player_id=player.id,
        game_id=game.id,
        coordinates=seeker_location,
        timestamp=datetime.now(UTC),
    )
    return seeker_location


# ── Ask endpoints (per-type) ─────────────────────────────────────────────


@router.post('/questions/radar', response_model=AskQuestionResponse, status_code=201)
def ask_radar_question(
    body: AskQuestionRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_seeker_in_game),
) -> AskQuestionResponse:
    """Ask a radar question, spending a radar inventory slot."""
    _validate_can_ask(game)
    seeker_location = _record_seeker_location(body.location, player, game)

    slot = validate_slot_request(body.slot_index, body.custom_distance, game, QuestionType.radar)
    question = ask_radar(game, player.id, seeker_location, slot, body.custom_distance)
    _schedule_auto_answer(game, question.id)

    rp = question.radar_params
    assert rp is not None
    distance_label = format_distance_label(rp.radius, game.game_map.convention)
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_asked,
        role_filter='hider',
        alert=f'A {distance_label} radar question has been asked. Your answer timer is running.',
        question_id=str(question.id),
        question_type=QuestionType.radar,
        question_status=QuestionStatus.answerable,
    )

    return AskQuestionResponse.from_model(question)


@router.post('/questions/thermometer', response_model=AskQuestionResponse, status_code=201)
def ask_thermometer_question(
    body: AskQuestionRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_seeker_in_game),
) -> AskQuestionResponse:
    """Ask a thermometer question, spending a thermometer inventory slot."""
    _validate_can_ask(game)
    seeker_location = _record_seeker_location(body.location, player, game)

    slot = validate_slot_request(
        body.slot_index, body.custom_distance, game, QuestionType.thermometer
    )
    question = ask_thermometer(game, player.id, seeker_location, slot, body.custom_distance)

    tp = question.thermometer_params
    assert tp is not None
    distance_label = format_distance_label(tp.min_travel, game.game_map.convention)
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_asked,
        role_filter='hider',
        alert=f'A {distance_label} thermometer question has started. The seeker is traveling.',
        question_id=str(question.id),
        question_type=QuestionType.thermometer,
        question_status=QuestionStatus.in_progress,
    )

    return AskQuestionResponse.from_model(question)


@router.post('/questions/matching', response_model=AskQuestionResponse, status_code=201)
def ask_matching_question(
    body: AskQuestionRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_seeker_in_game),
) -> AskQuestionResponse:
    """Ask a matching question about a feature category."""
    _validate_can_ask(game)
    seeker_location = _record_seeker_location(body.location, player, game)

    slot = validate_slot_request(body.slot_index, body.custom_distance, game, QuestionType.matching)

    try:
        question = ask_matching(game, player.id, seeker_location, slot)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    _schedule_auto_answer(game, question.id)

    fp = question.feature_params
    assert fp is not None
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_asked,
        role_filter='hider',
        alert=(
            f'A matching question about {fp.category} has been asked. Your answer timer is running.'
        ),
        question_id=str(question.id),
        question_type=QuestionType.matching,
        question_status=QuestionStatus.answerable,
    )

    return AskQuestionResponse.from_model(question)


@router.post('/questions/measuring', response_model=AskQuestionResponse, status_code=201)
def ask_measuring_question(
    body: AskQuestionRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_seeker_in_game),
) -> AskQuestionResponse:
    """Ask a measuring question about a feature category."""
    _validate_can_ask(game)
    seeker_location = _record_seeker_location(body.location, player, game)

    slot = validate_slot_request(
        body.slot_index, body.custom_distance, game, QuestionType.measuring
    )

    try:
        question = ask_measuring(game, player.id, seeker_location, slot)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    _schedule_auto_answer(game, question.id)

    fp = question.feature_params
    assert fp is not None
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_asked,
        role_filter='hider',
        alert=(
            f'A measuring question about {fp.category} has been asked. '
            f'Your answer timer is running.'
        ),
        question_id=str(question.id),
        question_type=QuestionType.measuring,
        question_status=QuestionStatus.answerable,
    )

    return AskQuestionResponse.from_model(question)


# ── Lock-in and answer ───────────────────────────────────────────────────


@router.post(
    '/questions/thermometer/{question_id}/lock-in',
    response_model=QuestionDetailResponse,
)
def lock_in_question(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> QuestionDetailResponse:
    """Lock in the seeker's end position for a thermometer question."""
    question = get_question(question_id)
    if not question or question.game_id != game.id:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.question_type != QuestionType.thermometer:
        raise HTTPException(status_code=409, detail='Only thermometer questions can be locked in.')
    if question.status != QuestionStatus.in_progress:
        raise HTTPException(status_code=409, detail='Question is not in progress.')
    if question.asked_by != player.id:
        raise HTTPException(status_code=403, detail='Only the asking seeker can lock in.')

    latest = get_latest_location_for_player(player.id, game.id)
    if not latest:
        raise HTTPException(status_code=409, detail='No location reported yet.')

    update_question(
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

    return QuestionDetailResponse.from_model(question)


@router.post(
    '/questions/{question_id}/answer',
    response_model=QuestionDetailResponse,
)
def answer_question(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> QuestionDetailResponse:
    """Hider answers a question — snapshot location, compute answer and exclusion."""
    question, hider_location = validate_answer_request(question_id, game, player.id, player.role)

    # Revoke the auto-answer deadline
    if not celery_app.conf.task_always_eager:
        celery_app.control.revoke(f'answer_deadline:{question.id}', terminate=False)

    # Set hider location, compute answer + exclusion, persist
    update_question(question, {'hider_location': hider_location})

    if question.question_type == QuestionType.radar:
        answer_radar(question, game)
    elif question.question_type == QuestionType.thermometer:
        answer_thermometer(question, game)
    elif question.question_type == QuestionType.matching:
        answer_matching(question, game)
    elif question.question_type == QuestionType.measuring:
        answer_measuring(question, game)
    else:
        raise HTTPException(
            status_code=422, detail=f'Unsupported question type: {question.question_type}'
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

    return QuestionDetailResponse.from_model(question)


# ── Veto ─────────────────────────────────────────────────────────────────


@router.post(
    '/questions/{question_id}/veto',
    response_model=QuestionDetailResponse,
)
def veto_question(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> QuestionDetailResponse:
    """Hider vetoes a question — no answer, no exclusion zone."""
    question, _hider_location = validate_answer_request(question_id, game, player.id, player.role)

    # Revoke the auto-answer deadline
    if not celery_app.conf.task_always_eager:
        celery_app.control.revoke(f'answer_deadline:{question.id}', terminate=False)

    update_question(question, {'status': QuestionStatus.vetoed, 'answered_at': datetime.now(UTC)})

    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_vetoed,
        role_filter='seeker',
        alert='The hider used a veto!',
        question_id=str(question.id),
        question_type=question.question_type,
    )

    return QuestionDetailResponse.from_model(question)


# ── List + detail + exclusions ────────────────────────────────────────────


@router.get('/questions', response_model=list[QuestionSummaryResponse])
def list_game_questions(
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> list[QuestionSummaryResponse]:
    """Chronological list of all questions — whitelist summary only."""
    questions = list_questions(game.id)
    return [QuestionSummaryResponse.from_model(q) for q in questions]


@router.get('/questions/{question_id}', response_model=QuestionDetailResponse)
def get_question_detail(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    _player: Player = Depends(get_hider_in_game),
) -> QuestionDetailResponse:
    """Full question detail — hider only."""
    question = get_question(question_id)
    if not question or question.game_id != game.id:
        raise HTTPException(status_code=404, detail='Question not found.')
    return QuestionDetailResponse.from_model(question)


@router.get('/exclusions', response_model=ExclusionsResponse)
def get_exclusions(
    game: Game = Depends(get_game),
    _player: Player = Depends(get_seeker_in_game),
) -> ExclusionsResponse:
    """Seeker tactical map — per-question exclusion geometry."""
    questions = list_questions(game.id)
    entries = [
        QuestionExclusionEntry(
            question_id=q.id,
            sequence=q.sequence,
            question_type=q.question_type,
            exclusion=geom_or_none(q.exclusion),
        )
        for q in questions
        if q.status == QuestionStatus.answered
    ]
    # total_exclusion from the last answered question
    answered = [q for q in questions if q.status == QuestionStatus.answered]
    total = geom_or_none(answered[-1].total_exclusion) if answered else None
    return ExclusionsResponse(exclusions=entries, total_exclusion=total)
