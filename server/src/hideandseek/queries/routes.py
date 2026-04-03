"""Route queries for gameplay state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from geoalchemy2 import Geometry
from shapely import wkb
from shapely.geometry import LineString, MultiLineString
from sqlalchemy import select

from hideandseek.db import get_session
from hideandseek.models.game import Game
from hideandseek.models.transit import Route, RouteStop, Stop
from hideandseek.queries.stops import playable_conditions


@dataclass
class GameplayRoute:
    """A route with its clipped shape and ordered playable stop IDs."""

    route: Route
    clipped_shape: LineString | MultiLineString
    stop_ids: list[uuid.UUID]


def get_gameplay_routes(game: Game) -> list[GameplayRoute]:
    """Return routes for the game's transit dataset, clipped to the game boundary.

    Uses PostGIS ST_Intersection to clip route shapes server-side so only
    the portion within the play area is transferred. Routes that don't
    intersect the boundary or have zero playable stops are omitted.
    """
    session = get_session()

    boundary_wkb = sa.func.ST_GeomFromWKB(
        wkb.dumps(game.game_map.boundary, include_srid=False),
        4326,
    )

    # Cast geography → geometry for ST_Intersection, then back for WKB output
    clipped_expr = sa.func.ST_Intersection(
        sa.cast(Route.shape, Geometry(srid=4326)),
        boundary_wkb,
    )

    # Playable stop ID set
    playable_stmt = select(Stop.id).where(*playable_conditions(game))
    playable_ids = set(session.scalars(playable_stmt).all())

    # Routes with clipped shapes in one query
    route_stmt = select(Route, sa.func.ST_AsEWKB(clipped_expr).label('clipped')).where(
        Route.dataset_id == game.game_map.transit_dataset_id,
        ~sa.func.ST_IsEmpty(clipped_expr),
    )
    if game.excluded_route_ids:
        route_stmt = route_stmt.where(~Route.id.in_([str(rid) for rid in game.excluded_route_ids]))

    result: list[GameplayRoute] = []
    for route, clipped_wkb in session.execute(route_stmt).all():
        shape = wkb.loads(bytes(clipped_wkb))
        if not isinstance(shape, (LineString, MultiLineString)):
            continue

        route_stops = session.scalars(
            select(RouteStop.stop_id)
            .where(RouteStop.route_id == route.id)
            .order_by(RouteStop.sequence)
        ).all()
        stop_ids = [sid for sid in route_stops if sid in playable_ids]
        if stop_ids:
            result.append(GameplayRoute(route=route, clipped_shape=shape, stop_ids=stop_ids))

    return result
