"""Endgame endpoints — exclusion view and candidate stations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from hideandseek.dependencies import get_game, get_seeker_in_game
from hideandseek.schemas.response import EndgameExclusionsResponse
from hideandseek.validators import validate_endgame_station
from hideandseek_core.db import session_dependency
from hideandseek_core.logic.endgame import get_endgame_exclusions
from hideandseek_models.game import Game, Player

router = APIRouter(
    prefix='/games/{game_id}', tags=['endgame'], dependencies=[Depends(session_dependency)]
)


@router.get('/endgame-exclusions', response_model=EndgameExclusionsResponse)
def endgame_exclusions(
    station_id: uuid.UUID = Query(description='Stop ID to center the hiding zone on.'),
    after_question: int = Query(
        default=0, description='Only include questions with sequence > this value.'
    ),
    game: Game = Depends(get_game),
    _player: Player = Depends(get_seeker_in_game),
) -> EndgameExclusionsResponse:
    """Endgame exclusion view: per-question exclusions intersected with a hiding zone circle."""
    if not game.status.is_seeking:
        raise HTTPException(
            status_code=409, detail='Endgame view is only available during seeking.'
        )

    stop = validate_endgame_station(station_id, game)
    result = get_endgame_exclusions(game, stop, after_question)
    return EndgameExclusionsResponse.from_result(result)
