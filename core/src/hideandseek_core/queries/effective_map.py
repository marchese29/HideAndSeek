"""Effective map resolution with exclusion filtering."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from hideandseek_core.db import get_session
from hideandseek_models.game import Game
from hideandseek_models.game_map import GameMap
from hideandseek_models.transit import Route, RouteStop, Stop


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


def get_effective_map_data(game: Game) -> EffectiveMapData:
    """Load map + transit data, filtering by exclusions."""
    session = get_session()
    excluded_stop_set = set(str(sid) for sid in game.excluded_stop_ids)
    excluded_route_set = set(str(rid) for rid in game.excluded_route_ids)

    # Load stops, excluding excluded ones
    stop_stmt = select(Stop).where(Stop.dataset_id == game.game_map.transit_dataset_id)
    if excluded_stop_set:
        stop_stmt = stop_stmt.where(~Stop.id.in_(excluded_stop_set))
    all_stops = list(session.scalars(stop_stmt).all())
    stop_id_set = {s.id for s in all_stops}

    # Load routes with their ordered stop IDs
    route_stmt = select(Route).where(Route.dataset_id == game.game_map.transit_dataset_id)
    if excluded_route_set:
        route_stmt = route_stmt.where(~Route.id.in_(excluded_route_set))
    all_routes = session.scalars(route_stmt).all()

    routes_with_stops: list[RouteWithStops] = []
    for route in all_routes:
        route_stops = session.scalars(
            select(RouteStop).where(RouteStop.route_id == route.id).order_by(RouteStop.sequence)
        ).all()
        stop_ids = [rs.stop_id for rs in route_stops if rs.stop_id in stop_id_set]
        routes_with_stops.append(RouteWithStops(route=route, stop_ids=stop_ids))

    return EffectiveMapData(game_map=game.game_map, stops=all_stops, routes=routes_with_stops)
