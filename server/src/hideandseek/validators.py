"""Request validation for questions.

Pure validation — raises HTTPException on invalid requests, returns nothing.
Called from routers before business logic.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from shapely.geometry import Point

from hideandseek.models.game import Game
from hideandseek.models.question import Question
from hideandseek.models.types import QuestionInventory, QuestionStatus, QuestionType
from hideandseek.queries.location import get_latest_location_for_player
from hideandseek.queries.questions import get_question
from hideandseek.resolution import (
    CLASSED_CATEGORIES,
    MATCHING_CATEGORIES,
    MEASURING_CATEGORIES,
    category_key,
    get_available_categories,
)
from hideandseek.schemas.request import AskQuestionRequest


def validate_slot_request(body: AskQuestionRequest, game: Game) -> None:
    """Validate a radar/thermometer request."""
    if body.slot_index is None:
        raise HTTPException(status_code=422, detail='slot_index is required for radar/thermometer.')

    inventory = QuestionInventory(**game.inventory)
    slots = inventory.radars if body.question_type == QuestionType.radar else inventory.thermometers

    if body.slot_index < 0 or body.slot_index >= len(slots):
        raise HTTPException(status_code=422, detail='Invalid slot index.')

    if slots[body.slot_index].distance_m is None and body.custom_distance_m is None:
        raise HTTPException(
            status_code=422, detail='custom_distance_m is required for custom slots.'
        )


def validate_matching_request(body: AskQuestionRequest, game: Game) -> None:
    """Validate a matching question request."""
    if body.category is None:
        raise HTTPException(status_code=422, detail='category is required for matching questions.')
    if body.category not in MATCHING_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f'{body.category} is not valid for matching questions.',
        )
    if body.category in CLASSED_CATEGORIES and body.feature_class is None:
        raise HTTPException(
            status_code=422,
            detail=f'feature_class is required for {body.category}.',
        )

    inventory = QuestionInventory(**game.inventory)
    key = category_key(body.category, body.feature_class)
    if key in inventory.matching_used:
        raise HTTPException(status_code=409, detail=f'Category {key} already used.')

    available = get_available_categories(
        map_id=game.map_id,
        question_type=QuestionType.matching,
        inventory=game.inventory,
    )
    available_keys = {category_key(c, cls) for c, cls in available}
    if key not in available_keys:
        raise HTTPException(status_code=422, detail=f'Category {key} is not available on this map.')


def validate_measuring_request(body: AskQuestionRequest, game: Game) -> None:
    """Validate a measuring question request."""
    if body.category is None:
        raise HTTPException(status_code=422, detail='category is required for measuring questions.')
    if body.category not in MEASURING_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f'{body.category} is not valid for measuring questions.',
        )
    if body.category in CLASSED_CATEGORIES and body.feature_class is None:
        raise HTTPException(
            status_code=422,
            detail=f'feature_class is required for {body.category}.',
        )

    inventory = QuestionInventory(**game.inventory)
    key = category_key(body.category, body.feature_class)
    if key in inventory.measuring_used:
        raise HTTPException(status_code=409, detail=f'Category {key} already used.')

    available = get_available_categories(
        map_id=game.map_id,
        question_type=QuestionType.measuring,
        inventory=game.inventory,
    )
    available_keys = {category_key(c, cls) for c, cls in available}
    if key not in available_keys:
        raise HTTPException(status_code=422, detail=f'Category {key} is not available on this map.')


# ── Answer validation ────────────────────────────────────────────────────


def validate_answer_request(
    question_id: uuid.UUID, game: Game, player_id: uuid.UUID, player_role: str | None
) -> tuple[Question, Point]:
    """Validate an answer request. Returns (question, hider_location)."""
    if player_role != 'hider':
        raise HTTPException(status_code=403, detail='Only the hider can answer questions.')

    question = get_question(question_id)
    if not question or question.game_id != game.id:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.status != QuestionStatus.answerable:
        raise HTTPException(status_code=409, detail='Question is not answerable.')

    latest = get_latest_location_for_player(player_id, game.id)
    if not latest:
        raise HTTPException(status_code=409, detail='No hider location available.')

    return question, latest.coordinates
