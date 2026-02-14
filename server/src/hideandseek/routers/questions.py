"""Question asking, answering, and listing endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from hideandseek.db import get_session
from hideandseek.dependencies import get_game, get_player_in_game
from hideandseek.models.game import Game, Player
from hideandseek.models.types import GameStatus, PlayerRole, QuestionStatus, QuestionType
from hideandseek.queries import (
    create_question,
    get_avg_seeker_location,
    get_latest_location_for_player,
    get_question,
    get_question_count,
    has_unanswered_question,
    list_questions,
    update_game_inventory,
    update_question,
)
from hideandseek.schemas.request import AskQuestionRequest
from hideandseek.schemas.response import QuestionPreview, QuestionResponse

router = APIRouter(prefix='/games/{game_id}', tags=['questions'])


@router.post('/questions', response_model=QuestionResponse, status_code=201)
def ask_question(
    body: AskQuestionRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
    session: Session = Depends(get_session),
) -> QuestionResponse:
    """Ask a radar or thermometer question, spending an inventory slot."""
    if game.status != GameStatus.seeking:
        raise HTTPException(status_code=409, detail='Questions can only be asked during seeking.')
    if player.role != PlayerRole.seeker:
        raise HTTPException(status_code=403, detail='Only seekers can ask questions.')
    if has_unanswered_question(session, game.id):
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
    seeker_location = get_avg_seeker_location(session, game)
    if not seeker_location:
        raise HTTPException(status_code=409, detail='No seeker locations available.')

    # Remove the spent slot from inventory
    slots.pop(body.slot_index)
    inventory[slot_key] = slots
    update_game_inventory(session, game, inventory)

    sequence = get_question_count(session, game.id) + 1
    question = create_question(
        session,
        game_id=game.id,
        sequence=sequence,
        question_type=body.question_type,
        status=status,
        parameters=parameters,
        asked_by=player.id,
        seeker_location_start=seeker_location,
    )
    return QuestionResponse.from_model(question)


@router.post(
    '/questions/{question_id}/lock-in',
    response_model=QuestionResponse,
)
def lock_in_question(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
    session: Session = Depends(get_session),
) -> QuestionResponse:
    """Lock in the seeker's end position for a thermometer question."""
    question = get_question(session, question_id)
    if not question or question.game_id != game.id:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.status != QuestionStatus.in_progress:
        raise HTTPException(status_code=409, detail='Question is not in progress.')
    if question.asked_by != player.id:
        raise HTTPException(status_code=403, detail='Only the asking seeker can lock in.')

    # Get seeker's current location as the end point
    latest = get_latest_location_for_player(session, player.id, game.id)
    if not latest:
        raise HTTPException(status_code=409, detail='No location reported yet.')

    # Distance validation deferred (geo math TBD)
    question = update_question(
        session,
        question,
        {
            'seeker_location_end': latest.coordinates,
            'status': QuestionStatus.answerable,
        },
    )
    return QuestionResponse.from_model(question)


@router.get(
    '/questions/{question_id}/preview',
    response_model=QuestionPreview,
)
def preview_question(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    session: Session = Depends(get_session),
) -> QuestionPreview:
    """Live preview of what the answer would be. Geo math is stubbed."""
    question = get_question(session, question_id)
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
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
    session: Session = Depends(get_session),
) -> QuestionResponse:
    """Hider answers a question — snapshot location and compute answer."""
    if player.role != PlayerRole.hider:
        raise HTTPException(status_code=403, detail='Only the hider can answer questions.')

    question = get_question(session, question_id)
    if not question or question.game_id != game.id:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.status != QuestionStatus.answerable:
        raise HTTPException(status_code=409, detail='Question is not answerable.')

    # Snapshot hider's current location
    latest = get_latest_location_for_player(session, player.id, game.id)
    hider_location = latest.coordinates if latest else None

    # Geo math deferred — store placeholder answer + null exclusion
    question = update_question(
        session,
        question,
        {
            'hider_location': hider_location,
            'answer': 'pending',
            'exclusion': None,
            'answered_at': datetime.now(UTC),
            'status': QuestionStatus.answered,
        },
    )
    return QuestionResponse.from_model(question)


@router.get('/questions', response_model=list[QuestionResponse])
def list_game_questions(
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
    session: Session = Depends(get_session),
) -> list[QuestionResponse]:
    """Chronological list of all questions. Hider location hidden from seekers."""
    questions = list_questions(session, game.id)
    hide_hider = player.role == PlayerRole.seeker
    return [QuestionResponse.from_model(q, hide_hider_location=hide_hider) for q in questions]
