"""Request validation for questions.

Pure validation — raises HTTPException on invalid requests, returns nothing
(except validate_slot_request which returns the resolved InventorySlot, and
validate_answer_request which returns (Question, Point)).
Called from routers before business logic.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from shapely.geometry import Point

from hideandseek.models.game import Game
from hideandseek.models.inventory import InventorySlot
from hideandseek.models.question import Question
from hideandseek.models.transit import Stop
from hideandseek.models.types import (
    FeatureCategory,
    QuestionStatus,
    QuestionType,
    SlotType,
    StationElectionStatus,
)
from hideandseek.queries.location import get_latest_location_for_player
from hideandseek.queries.questions import (
    get_question,
    get_slot_by_index,
    is_category_used,
)
from hideandseek.queries.stops import get_stop_by_id
from hideandseek.resolution import (
    CLASSED_CATEGORIES,
    MATCHING_CATEGORIES,
    MEASURING_CATEGORIES,
    category_key,
    get_available_categories,
)


def validate_slot_request(
    slot_index: int,
    custom_distance: float | None,
    game: Game,
    slot_type: SlotType,
) -> InventorySlot:
    """Validate a radar/thermometer request. Returns the resolved slot.

    slot_index refers to the original template position (stable across the game),
    not the position within remaining unconsumed slots.
    """
    slot = get_slot_by_index(game.id, slot_type, slot_index)

    if slot is None:
        raise HTTPException(status_code=422, detail='Invalid slot index.')
    if slot.consumed_at is not None:
        raise HTTPException(status_code=409, detail='Slot has already been consumed.')
    if slot.distance is None and custom_distance is None:
        raise HTTPException(status_code=422, detail='custom_distance is required for custom slots.')

    return slot


def validate_category_request(
    category: FeatureCategory,
    feature_class: int | None,
    game: Game,
    question_type: QuestionType,
) -> None:
    """Validate a matching or measuring question request."""
    type_categories = (
        MATCHING_CATEGORIES if question_type == QuestionType.matching else MEASURING_CATEGORIES
    )
    if category not in type_categories:
        raise HTTPException(
            status_code=422,
            detail=f'{category} is not valid for {question_type} questions.',
        )
    if category in CLASSED_CATEGORIES and feature_class is None:
        raise HTTPException(
            status_code=422,
            detail=f'feature_class is required for {category}.',
        )

    if is_category_used(game.id, question_type, category, feature_class):
        key = category_key(category, feature_class)
        raise HTTPException(status_code=409, detail=f'Category {key} already used.')

    available = get_available_categories(
        map_id=game.map_id,
        question_type=question_type,
        game_id=game.id,
    )
    available_keys = {category_key(c, cls) for c, cls in available}
    key = category_key(category, feature_class)
    if key not in available_keys:
        raise HTTPException(status_code=422, detail=f'Category {key} is not available on this map.')


# ── Answer validation ────────────────────────────────────────────────────


def validate_answer_request(
    question_id: uuid.UUID, game: Game, player_id: uuid.UUID, player_role: str | None
) -> tuple[Question, Point]:
    """Validate an answer request. Returns (question, hider_location)."""
    if player_role != 'hider':
        raise HTTPException(status_code=403, detail='Only the hider can answer questions.')

    if game.station_election_status == StationElectionStatus.ambiguous:
        raise HTTPException(
            status_code=409,
            detail='Cannot answer questions while station is ambiguous. Elect a station first.',
        )

    question = get_question(question_id)
    if not question or question.game_id != game.id:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.status != QuestionStatus.answerable:
        raise HTTPException(status_code=409, detail='Question is not answerable.')

    latest = get_latest_location_for_player(player_id, game.id)
    if not latest:
        raise HTTPException(status_code=409, detail='No hider location available.')

    return question, latest.coordinates


# ── Endgame validation ──────────────────────────────────────────────────


def validate_endgame_station(station_id: uuid.UUID, game: Game) -> Stop:
    """Validate a station for endgame exclusion computation. Returns the stop."""
    stop = get_stop_by_id(station_id)
    if not stop:
        raise HTTPException(status_code=404, detail='Station not found.')
    if stop.dataset_id != game.game_map.transit_dataset_id:
        raise HTTPException(
            status_code=422, detail="Station does not belong to this game's transit dataset."
        )
    return stop
