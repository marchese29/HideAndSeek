"""Effective map resolution with exclusion filtering."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlmodel import Session, col, select

from hideandseek.db import db_read
from hideandseek.models.game import Game
from hideandseek.models.game_map import GameMap
from hideandseek.models.transit import Route, RouteStop, Stop


@dataclass
class RouteWithStops:
    """A route paired with its ordered stop IDs (after exclusion filtering)."""

    route: Route
    stop_ids: list[uuid.UUID]


@dataclass
class EffectiveMapData:
    """Resolved map + transit data with exclusions applied."""

    game_map: GameMap
    stops: list[Stop]
    routes: list[RouteWithStops]


@db_read
def get_effective_map_data(session: Session, game: Game) -> EffectiveMapData:
    """Load map + transit data, filtering by exclusions."""
    game_map = session.get(GameMap, game.map_id)
    assert game_map is not None

    excluded_stop_set = set(str(sid) for sid in game_map.excluded_stop_ids)
    excluded_route_set = set(str(rid) for rid in game_map.excluded_route_ids)

    # Load stops, excluding excluded ones
    all_stops = list(
        session.exec(
            select(Stop).where(
                Stop.dataset_id == game_map.transit_dataset_id,
                ~col(Stop.id).in_(excluded_stop_set) if excluded_stop_set else True,  # type: ignore[arg-type]
            )
        ).all()
    )
    stop_id_set = {s.id for s in all_stops}

    # Load routes with their ordered stop IDs
    all_routes = session.exec(
        select(Route).where(
            Route.dataset_id == game_map.transit_dataset_id,
            ~col(Route.id).in_(excluded_route_set) if excluded_route_set else True,  # type: ignore[arg-type]
        )
    ).all()

    routes_with_stops: list[RouteWithStops] = []
    for route in all_routes:
        route_stops = session.exec(
            select(RouteStop).where(RouteStop.route_id == route.id).order_by(RouteStop.sequence)  # type: ignore[arg-type]
        ).all()
        stop_ids = [rs.stop_id for rs in route_stops if rs.stop_id in stop_id_set]
        routes_with_stops.append(RouteWithStops(route=route, stop_ids=stop_ids))

    return EffectiveMapData(game_map=game_map, stops=all_stops, routes=routes_with_stops)
