"""Location reporting endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from hideandseek.db import get_session
from hideandseek.dependencies import get_game, get_player_in_game
from hideandseek.models.game import Game, Player
from hideandseek.models.types import GameStatus
from hideandseek.queries import create_location_update, get_location_history, get_visible_players
from hideandseek.schemas.request import LocationReportRequest
from hideandseek.schemas.response import (
    LocationHistoryEntry,
    LocationReportResponse,
    VisiblePlayer,
)

router = APIRouter(prefix='/games/{game_id}', tags=['location'])


@router.post('/location', response_model=LocationReportResponse)
def report_location(
    body: LocationReportRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
    session: Session = Depends(get_session),
) -> LocationReportResponse:
    """Report the caller's location and receive visible player positions."""
    create_location_update(
        session,
        player_id=player.id,
        game_id=game.id,
        coordinates=body.coordinates.model_dump(),
        timestamp=body.timestamp,
    )

    visible = get_visible_players(session, game, player)
    return LocationReportResponse(
        players=[
            VisiblePlayer(
                player_id=vp.player.id,
                name=vp.player.name,
                color=vp.player.color,
                role=vp.player.role,
                coordinates=vp.coordinates,
                timestamp=vp.timestamp,
            )
            for vp in visible
        ]
    )


@router.get('/location-history', response_model=list[LocationHistoryEntry])
def location_history(
    game: Game = Depends(get_game),
    session: Session = Depends(get_session),
) -> list[LocationHistoryEntry]:
    """Full location log for post-game replay. Only available when finished."""
    if game.status != GameStatus.finished:
        raise HTTPException(
            status_code=409,
            detail='Location history is only available after the game ends.',
        )
    updates = get_location_history(session, game.id)
    return [LocationHistoryEntry.from_model(lu) for lu in updates]
