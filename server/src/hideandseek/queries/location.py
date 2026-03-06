"""Location queries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from shapely.geometry import Point
from sqlalchemy import func, select

from hideandseek.db import get_session
from hideandseek.models.game import Game, Player
from hideandseek.models.location import LocationUpdate
from hideandseek.models.types import PlayerRole


def create_location_update(
    *,
    player: Player,
    game: Game,
    coordinates: Point,
    timestamp: datetime,
) -> LocationUpdate:
    """Store a location update."""
    session = get_session()
    lu = LocationUpdate(
        player=player,
        game=game,
        coordinates=coordinates,
        timestamp=timestamp,
    )
    session.add(lu)
    session.flush()
    return lu


@dataclass
class VisiblePlayerData:
    """A player's latest location, ready for response transformation."""

    player: Player
    coordinates: Point
    timestamp: datetime


def get_visible_players(game: Game, caller: Player) -> list[VisiblePlayerData]:
    """Return the latest location of each player visible to the caller.

    Hiders see everyone (all hiders + all seekers) except themselves.
    Seekers see other seekers only — hiders are hidden from seekers.
    """
    session = get_session()
    # Subquery: latest location update per player in this game
    latest_sq = (
        select(
            LocationUpdate.player_id,
            func.max(LocationUpdate.id).label('max_id'),
        )
        .where(LocationUpdate.game == game)
        .group_by(LocationUpdate.player_id)
        .subquery()
    )

    stmt = (
        select(LocationUpdate, Player)
        .join(latest_sq, LocationUpdate.id == latest_sq.c.max_id)
        .join(Player, LocationUpdate.player_id == Player.id)
        .where(Player.id != caller.id)
    )

    # Seekers can only see other seekers
    if caller.role == PlayerRole.seeker:
        stmt = stmt.where(Player.role == PlayerRole.seeker)

    results: list[VisiblePlayerData] = []
    for lu, player in session.execute(stmt).all():
        results.append(
            VisiblePlayerData(
                player=player,
                coordinates=lu.coordinates,
                timestamp=lu.timestamp,
            )
        )
    return results


def get_location_history(game: Game) -> Sequence[LocationUpdate]:
    """Return all location updates for a game, chronologically."""
    session = get_session()
    return session.scalars(
        select(LocationUpdate).where(LocationUpdate.game == game).order_by(LocationUpdate.id)
    ).all()


def get_latest_location_for_player(player: Player, game: Game) -> LocationUpdate | None:
    """Return the most recent location update for a player in a game."""
    session = get_session()
    return session.scalars(
        select(LocationUpdate)
        .where(
            LocationUpdate.player == player,
            LocationUpdate.game == game,
        )
        .order_by(LocationUpdate.id.desc())
        .limit(1)
    ).one_or_none()
