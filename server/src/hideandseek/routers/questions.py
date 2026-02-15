"""Question asking, answering, and listing endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from hideandseek.db import get_session
from hideandseek.dependencies import get_game, get_player_in_game, get_push_service
from hideandseek.models.game import Game, Player
from hideandseek.models.types import (
    GameStatus,
    PlayerRole,
    PushEventType,
    QuestionStatus,
    QuestionType,
)
from hideandseek.push import PushService
from hideandseek.queries.device_tokens import get_device_tokens_for_game
from hideandseek.queries.location import get_avg_seeker_location, get_latest_location_for_player
from hideandseek.queries.questions import (
    create_question,
    get_question,
    get_question_count,
    has_unanswered_question,
    list_questions,
    update_game_inventory,
    update_question,
)
from hideandseek.schemas.request import AskQuestionRequest
from hideandseek.schemas.response import QuestionPreview, QuestionResponse

router = APIRouter(
    prefix='/games/{game_id}', tags=['questions'], dependencies=[Depends(get_session)]
)


@router.post('/questions', response_model=QuestionResponse, status_code=201)
def ask_question(
    body: AskQuestionRequest,
    background_tasks: BackgroundTasks,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
    push: PushService = Depends(get_push_service),
) -> QuestionResponse:
    """Ask a radar or thermometer question, spending an inventory slot."""
    if game.status != GameStatus.seeking:
        raise HTTPException(status_code=409, detail='Questions can only be asked during seeking.')
    if player.role != PlayerRole.seeker:
        raise HTTPException(status_code=403, detail='Only seekers can ask questions.')
    if has_unanswered_question(game.id):
        raise HTTPException(status_code=409, detail='There is already an unanswered question.')

    # Validate and consume inventory slot
    inventory = dict(game.inventory)
    slot_key = 'radars' if body.question_type == QuestionType.radar else 'thermometers'
    slots = list(inventory.get(slot_key, []))

    if body.slot_index < 0 or body.slot_index >= len(slots):
        raise HTTPException(status_code=422, detail='Invalid slot index.')

    slot = slots[body.slot_index]
    distance_m = slot.get('distance_m')

    # Custom slot requires client-provided distance
    if distance_m is None:
        if body.custom_distance_m is None:
            raise HTTPException(
                status_code=422, detail='custom_distance_m is required for custom slots.'
            )
        distance_m = body.custom_distance_m

    # Build parameters
    if body.question_type == QuestionType.radar:
        parameters = {'radius_m': distance_m}
        status = QuestionStatus.answerable
    else:
        parameters = {'min_travel_m': distance_m}
        status = QuestionStatus.in_progress

    # Compute seeker location (average of all seekers)
    seeker_location = get_avg_seeker_location(game)
    if not seeker_location:
        raise HTTPException(status_code=409, detail='No seeker locations available.')

    # Remove the spent slot from inventory
    slots.pop(body.slot_index)
    inventory[slot_key] = slots
    update_game_inventory(game, inventory)

    sequence = get_question_count(game.id) + 1
    question = create_question(
        game_id=game.id,
        sequence=sequence,
        question_type=body.question_type,
        status=status,
        parameters=parameters,
        asked_by=player.id,
        seeker_location_start=seeker_location,
    )

    # Push to hider(s)
    hider_tokens = get_device_tokens_for_game(game.id, role_filter=PlayerRole.hider)
    distance_label = f'{distance_m / 1000:g} km' if distance_m >= 1000 else f'{distance_m} m'
    if body.question_type == QuestionType.radar:
        alert = f'A {distance_label} radar question has been asked. Your answer timer is running.'
    else:
        alert = f'A {distance_label} thermometer question has started. The seeker is traveling.'
    background_tasks.add_task(
        push.send_to_tokens,
        hider_tokens,
        game.id,
        PushEventType.question_asked,
        alert=alert,
        question_id=question.id,
        question_type=body.question_type,
        question_status=status,
        parameters=parameters,
    )

    return QuestionResponse.from_model(question)


@router.post(
    '/questions/{question_id}/lock-in',
    response_model=QuestionResponse,
)
def lock_in_question(
    question_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
    push: PushService = Depends(get_push_service),
) -> QuestionResponse:
    """Lock in the seeker's end position for a thermometer question."""
    question = get_question(question_id)
    if not question or question.game_id != game.id:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.status != QuestionStatus.in_progress:
        raise HTTPException(status_code=409, detail='Question is not in progress.')
    if question.asked_by != player.id:
        raise HTTPException(status_code=403, detail='Only the asking seeker can lock in.')

    # Get seeker's current location as the end point
    latest = get_latest_location_for_player(player.id, game.id)
    if not latest:
        raise HTTPException(status_code=409, detail='No location reported yet.')

    # Distance validation deferred (geo math TBD)
    question = update_question(
        question,
        {
            'seeker_location_end': latest.coordinates,
            'status': QuestionStatus.answerable,
        },
    )

    # Push to hider(s)
    hider_tokens = get_device_tokens_for_game(game.id, role_filter=PlayerRole.hider)
    background_tasks.add_task(
        push.send_to_tokens,
        hider_tokens,
        game.id,
        PushEventType.question_answerable,
        alert='A thermometer question is ready for your answer.',
        question_id=question.id,
    )

    return QuestionResponse.from_model(question)


@router.get(
    '/questions/{question_id}/preview',
    response_model=QuestionPreview,
)
def preview_question(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
) -> QuestionPreview:
    """Live preview of what the answer would be. Geo math is stubbed."""
    question = get_question(question_id)
    if not question or question.game_id != game.id:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.status != QuestionStatus.answerable:
        raise HTTPException(status_code=409, detail='Question is not answerable.')

    # Geo math deferred — return placeholder
    return QuestionPreview(answer='pending', exclusion=None)


@router.post(
    '/questions/{question_id}/answer',
    response_model=QuestionResponse,
)
def answer_question(
    question_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
    push: PushService = Depends(get_push_service),
) -> QuestionResponse:
    """Hider answers a question — snapshot location and compute answer."""
    if player.role != PlayerRole.hider:
        raise HTTPException(status_code=403, detail='Only the hider can answer questions.')

    question = get_question(question_id)
    if not question or question.game_id != game.id:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.status != QuestionStatus.answerable:
        raise HTTPException(status_code=409, detail='Question is not answerable.')

    # Snapshot hider's current location
    latest = get_latest_location_for_player(player.id, game.id)
    hider_location = latest.coordinates if latest else None

    # Geo math deferred — store placeholder answer + null exclusion
    question = update_question(
        question,
        {
            'hider_location': hider_location,
            'answer': 'pending',
            'exclusion': None,
            'answered_at': datetime.now(UTC),
            'status': QuestionStatus.answered,
        },
    )

    # Push to all seekers
    seeker_tokens = get_device_tokens_for_game(game.id, role_filter=PlayerRole.seeker)
    alert = f'Question answered: {question.answer}! A new exclusion zone is on the map.'
    background_tasks.add_task(
        push.send_to_tokens,
        seeker_tokens,
        game.id,
        PushEventType.question_answered,
        alert=alert,
        question_id=question.id,
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
