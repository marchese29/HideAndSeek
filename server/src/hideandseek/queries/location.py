"""Location queries."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from hideandseek.db import db_read, db_write
from hideandseek.models.game import Game, Player
from hideandseek.models.location import LocationUpdate
from hideandseek.models.types import PlayerRole


@db_write
def create_location_update(
    session: Session,
    *,
    player_id: uuid.UUID,
    game_id: uuid.UUID,
    coordinates: dict,
    timestamp: datetime,
) -> LocationUpdate:
    """Store a location update."""
    lu = LocationUpdate(
        player_id=player_id,
        game_id=game_id,
        coordinates=coordinates,
        timestamp=timestamp,
    )
    session.add(lu)
    return lu


@dataclass
class VisiblePlayerData:
    """A player's latest location, ready for response transformation."""

    player: Player
    coordinates: dict
    timestamp: datetime


@db_read
def get_visible_players(session: Session, game: Game, caller: Player) -> list[VisiblePlayerData]:
    """Return the latest location of each player visible to the caller.

    Both hiders and seekers see all seekers (except themselves).
    Hiders are never visible during active gameplay.
    """
    # Subquery: latest location update per player in this game
    latest_sq = (
        select(
            LocationUpdate.player_id,
            func.max(LocationUpdate.id).label('max_id'),
        )
        .where(LocationUpdate.game_id == game.id)
        .group_by(LocationUpdate.player_id)  # type: ignore[arg-type]
        .subquery()
    )

    stmt = (
        select(LocationUpdate, Player)
        .join(latest_sq, LocationUpdate.id == latest_sq.c.max_id)  # type: ignore[arg-type]
        .join(Player, LocationUpdate.player_id == Player.id)  # type: ignore[arg-type]
        .where(
            Player.role == PlayerRole.seeker,
            Player.id != caller.id,
        )
    )

    results: list[VisiblePlayerData] = []
    for lu, player in session.exec(stmt).all():
        results.append(
            VisiblePlayerData(
                player=player,
                coordinates=lu.coordinates,
                timestamp=lu.timestamp,
            )
        )
    return results


@db_read
def get_location_history(session: Session, game_id: uuid.UUID) -> list[LocationUpdate]:
    """Return all location updates for a game, chronologically."""
    return list(
        session.exec(
            select(LocationUpdate)
            .where(LocationUpdate.game_id == game_id)
            .order_by(LocationUpdate.id)  # type: ignore[arg-type]
        ).all()
    )


@db_read
def get_latest_location_for_player(
    session: Session, player_id: uuid.UUID, game_id: uuid.UUID
) -> LocationUpdate | None:
    """Return the most recent location update for a player in a game."""
    return session.exec(
        select(LocationUpdate)
        .where(
            LocationUpdate.player_id == player_id,
            LocationUpdate.game_id == game_id,
        )
        .order_by(LocationUpdate.id.desc())  # type: ignore[union-attr]
        .limit(1)
    ).first()


@db_read
def get_avg_seeker_location(session: Session, game: Game) -> dict | None:
    """Compute the average position of all seekers based on their latest reports.

    Returns a GeoJSON Point dict or None if no seeker locations exist.
    """
    seekers = [p for p in game.players if p.role == PlayerRole.seeker]
    if not seekers:
        return None

    lngs: list[float] = []
    lats: list[float] = []
    for seeker in seekers:
        lu = get_latest_location_for_player(seeker.id, game.id)
        if lu:
            coords = lu.coordinates.get('coordinates', [])
            if len(coords) >= 2:
                lngs.append(coords[0])
                lats.append(coords[1])

    if not lngs:
        return None

    return {
        'type': 'Point',
        'coordinates': [sum(lngs) / len(lngs), sum(lats) / len(lats)],
    }
