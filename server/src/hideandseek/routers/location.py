"""Location reporting endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from geojson_pydantic import Point as GeoJSONPoint
from shapely.geometry import Point, mapping

from hideandseek.db import session_dependency
from hideandseek.dependencies import get_game, get_player_in_game
from hideandseek.models.game import Game, Player
from hideandseek.queries.location import (
    create_location_update,
    get_location_history,
    get_visible_players,
)
from hideandseek.schemas.request import LocationReportRequest
from hideandseek.schemas.response import (
    LocationHistoryEntry,
    LocationReportResponse,
    VisiblePlayer,
)

router = APIRouter(
    prefix='/games/{game_id}', tags=['location'], dependencies=[Depends(session_dependency)]
)


@router.post('/location', response_model=LocationReportResponse)
def report_location(
    body: LocationReportRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> LocationReportResponse:
    """Report the caller's location and receive visible player positions."""
    coords = body.coordinates.coordinates
    point = Point(float(coords[0]), float(coords[1]))

    create_location_update(
        player=player,
        game=game,
        coordinates=point,
        timestamp=body.timestamp,
    )

    visible = get_visible_players(game, player)
    return LocationReportResponse(
        players=[
            VisiblePlayer(
                player_id=vp.player.id,
                name=vp.player.name,
                color=vp.player.color,
                role=vp.player.role,
                coordinates=GeoJSONPoint(**mapping(vp.coordinates)),
                timestamp=vp.timestamp,
            )
            for vp in visible
        ]
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
