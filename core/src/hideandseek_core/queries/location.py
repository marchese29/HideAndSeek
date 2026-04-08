"""Location queries."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from shapely.geometry import Point
from sqlalchemy import delete, func, select

from hideandseek_core.db import get_session
from hideandseek_models.game import Game, Player
from hideandseek_models.location import LocationUpdate


def delete_player_locations(player: Player, game: Game) -> None:
    """Delete all location updates for a player in a game."""
    session = get_session()
    session.execute(
        delete(LocationUpdate).where(
            LocationUpdate.player_id == player.id,
            LocationUpdate.game_id == game.id,
        )
    )
    session.flush()


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


def get_location_history(game: Game) -> Sequence[LocationUpdate]:
    """Return all location updates for a game, chronologically."""
    session = get_session()
    return session.scalars(
        select(LocationUpdate).where(LocationUpdate.game == game).order_by(LocationUpdate.id)
    ).all()


def get_all_player_locations(game: Game) -> dict[uuid.UUID, VisiblePlayerData]:
    """Return the latest location per player in a game. No caller or role filtering."""
    session = get_session()
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
    )
    result: dict[uuid.UUID, VisiblePlayerData] = {}
    for lu, player in session.execute(stmt).all():
        result[player.id] = VisiblePlayerData(
            player=player,
            coordinates=lu.coordinates,
            timestamp=lu.timestamp,
        )
    return result


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
