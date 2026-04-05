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
from hideandseek_core.queries.location import create_location_update, get_location_history
from hideandseek_models.game import Game, Player

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
    assert player.role is not None  # guaranteed during active gameplay
    coords = body.coordinates.coordinates
    point = Point(float(coords[0]), float(coords[1]))

    create_location_update(
        player=player,
        game=game,
        coordinates=point,
        timestamp=body.timestamp,
    )

    emit_gameplay(
        PlayerLocationEvent(
            game_id=game.id,
            player_id=player.id,
            name=player.name,
            color=player.color,
            role=player.role,
            coordinates=body.coordinates.model_dump(mode='json'),
            timestamp=body.timestamp,
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
