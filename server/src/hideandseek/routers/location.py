"""Location reporting endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from shapely.geometry import Point

from hideandseek.dependencies import get_game, get_player_in_game
from hideandseek.schemas.request import LocationReportRequest
from hideandseek.schemas.response import LocationHistoryEntry
from hideandseek_core.broadcast.emit import emit_gameplay
from hideandseek_core.broadcast.events import (
    PlayerLocationEvent,
    ProximityDeescalatedEvent,
    ProximityEscalatedEvent,
)
from hideandseek_core.db import session_dependency
from hideandseek_core.logic.location import process_location_update
from hideandseek_core.queries.location import get_location_history
from hideandseek_models.game import Game, Player
from hideandseek_models.types import (
    PlayerRole,
    ProximityTier,
    PushEventType,
)
from hideandseek_worker.tasks.push import send_push

_ESCALATION_ALERTS: dict[ProximityTier, str] = {
    ProximityTier.approaching: 'Seekers are in your area',
    ProximityTier.near: 'Seekers are getting close',
    ProximityTier.entered: 'Seekers are in your hiding zone \u2014 stay put!',
}

_DEESCALATION_ALERTS: dict[ProximityTier, str] = {
    ProximityTier.near: 'Seekers left your zone \u2014 you may reposition',
    ProximityTier.approaching: 'Seekers have pulled back',
    ProximityTier.none: 'Seekers are no longer nearby',
}

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

    result = process_location_update(game, player, point, body.timestamp)

    emit_gameplay(
        PlayerLocationEvent(
            game_id=game.id,
            player_id=player.id,
            name=player.name,
            color=player.color,
            role=player.role,
            coordinates=body.coordinates,
            timestamp=body.timestamp,
            candidate_stations=result.candidate_stations,
            not_in_zone=result.not_in_zone,
            computed_answer=result.computed_answer,
            freeze_departed=result.freeze_departed,
        )
    )

    if result.proximity is not None and result.proximity.changed:
        if result.proximity.escalated:
            emit_gameplay(
                ProximityEscalatedEvent(
                    game_id=game.id,
                    proximity_tier=result.proximity.new_tier,
                )
            )
            send_push.delay(  # type: ignore[attr-defined]
                str(game.id),
                PushEventType.proximity_escalated,
                role_filter='hider',
                alert=_ESCALATION_ALERTS.get(result.proximity.new_tier),
            )
        else:
            emit_gameplay(
                ProximityDeescalatedEvent(
                    game_id=game.id,
                    proximity_tier=result.proximity.new_tier,
                )
            )
            send_push.delay(  # type: ignore[attr-defined]
                str(game.id),
                PushEventType.proximity_deescalated,
                role_filter='hider',
                alert=_DEESCALATION_ALERTS.get(result.proximity.new_tier),
            )

    if result.freeze_departure_push:
        send_push.delay(  # type: ignore[attr-defined]
            str(game.id),
            PushEventType.freeze_departed,
            role_filter='hider',
            alert='A hider moved during freeze \u2014 stay in your spots!',
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
