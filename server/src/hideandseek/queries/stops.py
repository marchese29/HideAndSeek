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
    total_exclusion: BaseGeometry | None = get_latest_total_exclusion(game.id)

    conditions = _playable_conditions(game)

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


def _playable_conditions(game: Game) -> list:
    """Build common playable-stop filter conditions.

    Filters by dataset and game map boundary, excludes game-level excluded stops.
    """
    game_map = game.game_map
    boundary_wkb = sa.func.ST_GeomFromWKB(
        wkb.dumps(game_map.boundary, include_srid=False),
        4326,
    )

    conditions: list = [
        Stop.dataset_id == game_map.transit_dataset_id,
        sa.func.ST_Contains(boundary_wkb, Stop.coordinates),
    ]

    if game.excluded_stop_ids:
        conditions.append(~col(Stop.id).in_([str(sid) for sid in game.excluded_stop_ids]))

    return conditions


@db_read
def get_stops_near_point(
    session: Session,
    game: Game,
    location: Point,
    radius_m: float,
) -> list[Stop]:
    """Return playable stops within radius_m of a point. PostGIS only."""
    conditions = _playable_conditions(game)
    location_wkb = sa.func.ST_GeomFromWKB(
        wkb.dumps(location, include_srid=False),
        4326,
    )
    conditions.append(
        sa.func.ST_DWithin(
            sa.cast(Stop.coordinates, Geography(srid=4326)),
            sa.cast(location_wkb, Geography(srid=4326)),
            radius_m,
        )
    )

    stmt = select(Stop).where(*conditions).order_by(Stop.name)  # type: ignore[arg-type]
    return list(session.exec(stmt).all())


@db_read
def get_stops_within_radius_of_all(
    session: Session,
    game: Game,
    hider_locations: list[Point],
    radius_m: float,
) -> list[Stop]:
    """Return playable stops where ALL hider locations are within radius_m.

    Ordered by max distance (tightest fit first). PostGIS only.
    """
    if not hider_locations:
        return []

    conditions = _playable_conditions(game)
    for loc in hider_locations:
        loc_wkb = sa.func.ST_GeomFromWKB(wkb.dumps(loc, include_srid=False), 4326)
        conditions.append(
            sa.func.ST_DWithin(
                sa.cast(Stop.coordinates, Geography(srid=4326)),
                sa.cast(loc_wkb, Geography(srid=4326)),
                radius_m,
            )
        )

    # Order by max distance across all hiders (tightest fit)
    max_dist_exprs = []
    for loc in hider_locations:
        loc_wkb = sa.func.ST_GeomFromWKB(wkb.dumps(loc, include_srid=False), 4326)
        max_dist_exprs.append(
            sa.func.ST_Distance(
                sa.cast(Stop.coordinates, Geography(srid=4326)),
                sa.cast(loc_wkb, Geography(srid=4326)),
            )
        )
    max_dist = sa.func.greatest(*max_dist_exprs) if len(max_dist_exprs) > 1 else max_dist_exprs[0]

    stmt = (
        select(Stop).where(*conditions).order_by(max_dist)  # type: ignore[arg-type]
    )
    return list(session.exec(stmt).all())


@db_read
def get_stops_within_radius_of_any(
    session: Session,
    game: Game,
    hider_locations: list[Point],
    radius_m: float,
) -> list[Stop]:
    """Return playable stops where ANY hider location is within radius_m.

    Ordered by min distance (shortest min first). PostGIS only.
    """
    if not hider_locations:
        return []

    conditions = _playable_conditions(game)
    or_clauses = []
    for loc in hider_locations:
        loc_wkb = sa.func.ST_GeomFromWKB(wkb.dumps(loc, include_srid=False), 4326)
        or_clauses.append(
            sa.func.ST_DWithin(
                sa.cast(Stop.coordinates, Geography(srid=4326)),
                sa.cast(loc_wkb, Geography(srid=4326)),
                radius_m,
            )
        )
    conditions.append(sa.or_(*or_clauses))

    min_dist_exprs = []
    for loc in hider_locations:
        loc_wkb = sa.func.ST_GeomFromWKB(wkb.dumps(loc, include_srid=False), 4326)
        min_dist_exprs.append(
            sa.func.ST_Distance(
                sa.cast(Stop.coordinates, Geography(srid=4326)),
                sa.cast(loc_wkb, Geography(srid=4326)),
            )
        )
    min_dist = sa.func.least(*min_dist_exprs) if len(min_dist_exprs) > 1 else min_dist_exprs[0]

    stmt = (
        select(Stop).where(*conditions).order_by(min_dist)  # type: ignore[arg-type]
    )
    return list(session.exec(stmt).all())


@db_read
def get_closest_stop_to_any(
    session: Session,
    game: Game,
    hider_locations: list[Point],
) -> Stop | None:
    """Return the stop closest to any hider location. PostGIS only."""
    if not hider_locations:
        return None

    conditions = _playable_conditions(game)

    min_dist_exprs = []
    for loc in hider_locations:
        loc_wkb = sa.func.ST_GeomFromWKB(wkb.dumps(loc, include_srid=False), 4326)
        min_dist_exprs.append(
            sa.func.ST_Distance(
                sa.cast(Stop.coordinates, Geography(srid=4326)),
                sa.cast(loc_wkb, Geography(srid=4326)),
            )
        )
    min_dist = sa.func.least(*min_dist_exprs) if len(min_dist_exprs) > 1 else min_dist_exprs[0]

    stmt = (
        select(Stop)
        .where(*conditions)
        .order_by(min_dist)  # type: ignore[arg-type]
        .limit(1)
    )
    return session.exec(stmt).one_or_none()


@db_read
def validate_stop_playable(session: Session, game: Game, stop_id: uuid.UUID) -> Stop | None:
    """Return the stop if it's playable (in dataset, in boundary, not excluded). Otherwise None."""
    conditions = _playable_conditions(game)
    conditions.append(Stop.id == stop_id)
    stmt = select(Stop).where(*conditions)
    return session.exec(stmt).one_or_none()


@db_read
def all_hiders_within_radius(
    session: Session,
    stop: Stop,
    hider_locations: list[Point],
    radius_m: float,
) -> bool:
    """Check whether ALL hider locations are within radius_m of a stop. PostGIS only."""
    if not hider_locations:
        return False

    for loc in hider_locations:
        loc_wkb = sa.func.ST_GeomFromWKB(wkb.dumps(loc, include_srid=False), 4326)
        within = session.exec(
            select(
                sa.func.ST_DWithin(
                    sa.cast(Stop.coordinates, Geography(srid=4326)),
                    sa.cast(loc_wkb, Geography(srid=4326)),
                    radius_m,
                )
            ).where(Stop.id == stop.id)
        ).one()
        if not within:
            return False
    return True


@db_read
def get_nearest_playable_stop(session: Session, game: Game, location: Point) -> Stop | None:
    """Return the nearest playable stop to a location.

    Filters by: dataset membership, inside game map boundary, not excluded.
    Orders by distance to location (ascending). Requires PostGIS (uses ST_Distance).
    """
    conditions = _playable_conditions(game)
    location_wkb = sa.func.ST_GeomFromWKB(
        wkb.dumps(location, include_srid=False),
        4326,
    )

    stmt = (
        select(Stop)
        .where(*conditions)
        .order_by(sa.func.ST_Distance(Stop.coordinates, location_wkb))  # type: ignore[arg-type]
        .limit(1)
    )

    return session.exec(stmt).first()
