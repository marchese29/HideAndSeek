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

from hideandseek_core.logic.endgame import seeker_inside_hiding_zone
from hideandseek_core.queries.location import get_latest_location_for_player
from hideandseek_core.queries.questions import get_question, get_slot_by_index
from hideandseek_core.queries.stops import get_stop_by_id
from hideandseek_models.game import Game, Player
from hideandseek_models.inventory import InventorySlot
from hideandseek_models.question import Question
from hideandseek_models.transit import Stop
from hideandseek_models.types import (
    QuestionStatus,
    QuestionType,
    StationElectionStatus,
)


def validate_slot_request(
    slot_index: int,
    custom_distance: float | None,
    game: Game,
    question_type: QuestionType,
) -> InventorySlot:
    """Validate a question request by looking up the slot.

    For radar/thermometer: validates custom_distance when slot.distance is None.
    For matching/measuring: slot lookup is sufficient (category is on the slot).
    """
    slot = get_slot_by_index(game, question_type, slot_index)

    if slot is None:
        raise HTTPException(status_code=422, detail='Invalid slot index.')
    if (
        question_type in (QuestionType.radar, QuestionType.thermometer)
        and slot.distance is None
        and custom_distance is None
    ):
        raise HTTPException(status_code=422, detail='custom_distance is required for custom slots.')
    if question_type == QuestionType.photo and slot.photo_subject is None:
        raise HTTPException(status_code=422, detail='Slot is missing a photo subject.')

    return slot


# ── Answer validation ────────────────────────────────────────────────────


def validate_answer_request(
    question_id: uuid.UUID, game: Game, player: Player
) -> tuple[Question, Point]:
    """Validate an answer request. Returns (question, hider_location)."""
    if player.role != 'hider':
        raise HTTPException(status_code=403, detail='Only the hider can answer questions.')

    if game.station_election_status == StationElectionStatus.ambiguous:
        raise HTTPException(
            status_code=409,
            detail='Cannot answer questions while station is ambiguous. Elect a station first.',
        )

    question = get_question(question_id)
    if not question or question.game != game:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.status != QuestionStatus.answerable:
        raise HTTPException(status_code=409, detail='Question is not answerable.')

    latest = get_latest_location_for_player(player, game)
    if not latest:
        raise HTTPException(status_code=409, detail='No hider location available.')

    return question, latest.coordinates


# ── Randomize validation ──────────────────────────────────────────────


def validate_randomize_request(question_id: uuid.UUID, game: Game, player: Player) -> Question:
    """Validate a randomize request. Returns the question."""
    if player.role != 'hider':
        raise HTTPException(status_code=403, detail='Only the hider can randomize questions.')

    question = get_question(question_id)
    if not question or question.game != game:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.status != QuestionStatus.answerable:
        raise HTTPException(status_code=409, detail='Question is not answerable.')

    return question


# ── Abandon validation ────────────────────────────────────────────────


def validate_abandon_request(question_id: uuid.UUID, game: Game, player: Player) -> Question:
    """Validate an abandon request. Returns the question."""
    if player.role != 'seeker':
        raise HTTPException(status_code=403, detail='Only the seeker can abandon questions.')

    question = get_question(question_id)
    if not question or question.game != game:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.status not in (QuestionStatus.answerable, QuestionStatus.in_progress):
        raise HTTPException(status_code=409, detail='Question cannot be abandoned.')

    return question


# ── Lock-in validation ─────────────────────────────────────────────────


def validate_lock_in_request(
    question_id: uuid.UUID, game: Game, player: Player
) -> tuple[Question, Point]:
    """Validate a thermometer lock-in request. Returns (question, seeker_end_location)."""
    question = get_question(question_id)
    if not question or question.game != game:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.question_type != QuestionType.thermometer:
        raise HTTPException(status_code=409, detail='Only thermometer questions can be locked in.')
    if question.status != QuestionStatus.in_progress:
        raise HTTPException(status_code=409, detail='Question is not in progress.')
    if question.asked_by_player != player:
        raise HTTPException(status_code=403, detail='Only the asking seeker can lock in.')

    latest = get_latest_location_for_player(player, game)
    if not latest:
        raise HTTPException(status_code=409, detail='No location reported yet.')

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


def validate_found_claim(game: Game, seeker: Player) -> None:
    """Seeker-side claim: seeking phase, station elected, in-zone, no pending claim."""
    if not game.status.is_seeking:
        raise HTTPException(status_code=409, detail='Found claims are only allowed during seeking.')
    if game.hider_station is None:
        raise HTTPException(status_code=409, detail='No station has been elected yet.')
    if game.found_claim_expires_at is not None:
        raise HTTPException(status_code=409, detail='A found claim is already pending.')
    if not seeker_inside_hiding_zone(game, seeker):
        raise HTTPException(
            status_code=409, detail='You must be inside the hiding zone to claim found.'
        )


def validate_found_decision(game: Game) -> None:
    """Hider-side confirm/reject: game still seeking with a live pending claim."""
    if not game.status.is_seeking:
        raise HTTPException(status_code=409, detail='No active found claim.')
    if game.found_claim_expires_at is None:
        raise HTTPException(status_code=409, detail='No pending found claim.')
