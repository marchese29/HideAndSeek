"""Stop queries."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from geoalchemy2 import Geography, Geometry
from shapely import wkb
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from sqlmodel import Session, col, select

from hideandseek.db import db_read
from hideandseek.models.game import Game
from hideandseek.models.transit import Stop
from hideandseek.queries.questions import get_latest_total_exclusion


@db_read
def get_stop_by_id(session: Session, stop_id: uuid.UUID) -> Stop | None:
    """Return a single stop by ID."""
    return session.get(Stop, stop_id)


@db_read
def get_candidate_stations(
    session: Session,
    game: Game,
    radius_m: float,
    offset: int,
    limit: int,
) -> list[Stop]:
    """Return playable stops whose hiding zone circle is not fully covered by total_exclusion.

    Only includes stops inside the game map boundary. Requires PostGIS — uses ST_Buffer
    on geography for accurate metric circles and ST_Covers for coverage checks.
    """
    game_map = game.game_map
    dataset_id = game_map.transit_dataset_id
    excluded_stop_ids = game.excluded_stop_ids

    total_exclusion: BaseGeometry | None = get_latest_total_exclusion(game.id)

    # Boundary filter: stop must be inside the game map
    boundary_wkb = sa.func.ST_GeomFromWKB(
        wkb.dumps(game_map.boundary, include_srid=False),
        4326,
    )

    conditions = [
        Stop.dataset_id == dataset_id,
        sa.func.ST_Contains(boundary_wkb, Stop.coordinates),
    ]

    if excluded_stop_ids:
        conditions.append(~col(Stop.id).in_([str(sid) for sid in excluded_stop_ids]))

    if total_exclusion is not None:
        total_exclusion_wkb = sa.func.ST_GeomFromWKB(
            wkb.dumps(total_exclusion, include_srid=False),
            4326,
        )

        # Build hiding zone circle for each stop via geography cast for metric accuracy
        hiding_circle = sa.func.ST_Buffer(
            sa.cast(Stop.coordinates, Geography(srid=4326)),
            radius_m,
        ).cast(Geometry(srid=4326))

        conditions.append(~sa.func.ST_Covers(total_exclusion_wkb, hiding_circle))

    stmt = (
        select(Stop)
        .where(*conditions)
        .order_by(Stop.name)  # type: ignore[arg-type]
        .offset(offset)
        .limit(limit)
    )

    return list(session.exec(stmt).all())


@db_read
def get_nearest_playable_stop(session: Session, game: Game, location: Point) -> Stop | None:
    """Return the nearest playable stop to a location.

    Filters by: dataset membership, inside game map boundary, not excluded.
    Orders by distance to location (ascending). Requires PostGIS (uses ST_Distance).
    """
    game_map = game.game_map
    excluded_stop_ids = game.excluded_stop_ids

    boundary_wkb = sa.func.ST_GeomFromWKB(
        wkb.dumps(game_map.boundary, include_srid=False),
        4326,
    )
    location_wkb = sa.func.ST_GeomFromWKB(
        wkb.dumps(location, include_srid=False),
        4326,
    )

    conditions = [
        Stop.dataset_id == game_map.transit_dataset_id,
        sa.func.ST_Contains(boundary_wkb, Stop.coordinates),
    ]

    if excluded_stop_ids:
        conditions.append(~col(Stop.id).in_([str(sid) for sid in excluded_stop_ids]))

    stmt = (
        select(Stop)
        .where(*conditions)
        .order_by(sa.func.ST_Distance(Stop.coordinates, location_wkb))  # type: ignore[arg-type]
        .limit(1)
    )

    return session.exec(stmt).first()
