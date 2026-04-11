"""Location reporting endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from shapely.geometry import Point

from hideandseek.dependencies import get_game, get_player_in_game
from hideandseek.schemas.request import LocationReportRequest
from hideandseek.schemas.response import LocationHistoryEntry
from hideandseek_core.broadcast.emit import emit_gameplay
from hideandseek_core.broadcast.events import PlayerLocationEvent
from hideandseek_core.db import session_dependency
from hideandseek_core.logic.answer import preview_answer
from hideandseek_core.logic.station import (
    compute_candidate_station_ids,
    compute_hider_centroid,
    compute_not_in_zone,
)
from hideandseek_core.queries.location import create_location_update, get_location_history
from hideandseek_core.queries.questions import get_active_question
from hideandseek_models.game import Game, Player
from hideandseek_models.types import PlayerRole, QuestionStatus, StationElectionStatus

router = APIRouter(
    prefix='/games/{game_id}', tags=['location'], dependencies=[Depends(session_dependency)]
)


@router.post('/location', status_code=204)
def report_location(
    body: LocationReportRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> None:
    """Report the caller's location. Updates are broadcast via SSE."""
    if not game.status.is_active:
        raise HTTPException(
            status_code=409,
            detail='Location updates are only accepted during active gameplay.',
        )
    if game.status.is_hiding and player.role == PlayerRole.seeker:
        raise HTTPException(
            status_code=409,
            detail='Seekers cannot report location during the hiding phase.',
        )
    assert player.role is not None  # guaranteed during active gameplay
    coords = body.coordinates.coordinates
    point = Point(float(coords[0]), float(coords[1]))

    create_location_update(
        player=player,
        game=game,
        coordinates=point,
        timestamp=body.timestamp,
    )

    # Compute enrichment fields for hider location events.
    # The just-flushed LocationUpdate is visible in the same session.
    candidate_stations = None
    not_in_zone = None
    computed_answer = None

    if player.role == PlayerRole.hider:
        if game.station_election_status == StationElectionStatus.pending:
            candidate_stations = compute_candidate_station_ids(game)
        elif game.hider_station_id is not None:
            not_in_zone = compute_not_in_zone(game)
            active_q = get_active_question(game)
            if active_q is not None and active_q.status == QuestionStatus.answerable:
                hider_loc = compute_hider_centroid(game)
                if hider_loc is not None:
                    computed_answer = preview_answer(active_q, hider_loc, game)

    emit_gameplay(
        PlayerLocationEvent(
            game_id=game.id,
            player_id=player.id,
            name=player.name,
            color=player.color,
            role=player.role,
            coordinates=body.coordinates,
            timestamp=body.timestamp,
            candidate_stations=candidate_stations,
            not_in_zone=not_in_zone,
            computed_answer=computed_answer,
        )
    )


@router.get('/location-history', response_model=list[LocationHistoryEntry])
def location_history(
    game: Game = Depends(get_game),
) -> list[LocationHistoryEntry]:
    """Full location log for post-game replay. Only available when finished."""
    if not game.status.is_finished:
        raise HTTPException(
            status_code=409,
            detail='Location history is only available after the game ends.',
        )
    updates = get_location_history(game)
    return [LocationHistoryEntry.from_model(lu) for lu in updates]
