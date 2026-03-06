"""Stop queries."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geography, Geometry
from shapely import wkb
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select

from hideandseek.db import get_session
from hideandseek.models.game import Game
from hideandseek.models.transit import Stop
from hideandseek.queries.questions import get_latest_total_exclusion


def get_stop_by_id(stop_id: uuid.UUID) -> Stop | None:
    """Return a single stop by ID."""
    session = get_session()
    return session.get(Stop, stop_id)


def get_candidate_stations(
    game: Game,
    radius_m: float,
    offset: int,
    limit: int,
) -> Sequence[Stop]:
    """Return playable stops whose hiding zone circle is not fully covered by total_exclusion.

    Only includes stops inside the game map boundary. Requires PostGIS — uses ST_Buffer
    on geography for accurate metric circles and ST_Covers for coverage checks.
    """
    session = get_session()
    total_exclusion: BaseGeometry | None = get_latest_total_exclusion(game)

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

    stmt = select(Stop).where(*conditions).order_by(Stop.name).offset(offset).limit(limit)

    return session.scalars(stmt).all()


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
        conditions.append(~Stop.id.in_([str(sid) for sid in game.excluded_stop_ids]))

    return conditions


def get_stops_near_point(
    game: Game,
    location: Point,
    radius_m: float,
) -> Sequence[Stop]:
    """Return playable stops within radius_m of a point. PostGIS only."""
    session = get_session()
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

    stmt = select(Stop).where(*conditions).order_by(Stop.name)
    return session.scalars(stmt).all()


def get_stops_within_radius_of_all(
    game: Game,
    hider_locations: list[Point],
    radius_m: float,
) -> Sequence[Stop]:
    """Return playable stops where ALL hider locations are within radius_m.

    Ordered by max distance (tightest fit first). PostGIS only.
    """
    if not hider_locations:
        return []

    session = get_session()
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

    stmt = select(Stop).where(*conditions).order_by(max_dist)
    return session.scalars(stmt).all()


def get_stops_within_radius_of_any(
    game: Game,
    hider_locations: list[Point],
    radius_m: float,
) -> Sequence[Stop]:
    """Return playable stops where ANY hider location is within radius_m.

    Ordered by min distance (shortest min first). PostGIS only.
    """
    if not hider_locations:
        return []

    session = get_session()
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

    stmt = select(Stop).where(*conditions).order_by(min_dist)
    return session.scalars(stmt).all()


def get_closest_stop_to_any(
    game: Game,
    hider_locations: list[Point],
) -> Stop | None:
    """Return the stop closest to any hider location. PostGIS only."""
    if not hider_locations:
        return None

    session = get_session()
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

    stmt = select(Stop).where(*conditions).order_by(min_dist).limit(1)
    return session.scalars(stmt).one_or_none()


def validate_stop_playable(game: Game, stop_id: uuid.UUID) -> Stop | None:
    """Return the stop if it's playable (in dataset, in boundary, not excluded). Otherwise None."""
    session = get_session()
    conditions = _playable_conditions(game)
    conditions.append(Stop.id == stop_id)
    stmt = select(Stop).where(*conditions)
    return session.scalars(stmt).one_or_none()


def all_hiders_within_radius(
    stop: Stop,
    hider_locations: list[Point],
    radius_m: float,
) -> bool:
    """Check whether ALL hider locations are within radius_m of a stop. PostGIS only."""
    if not hider_locations:
        return False

    session = get_session()
    for loc in hider_locations:
        loc_wkb = sa.func.ST_GeomFromWKB(wkb.dumps(loc, include_srid=False), 4326)
        within = session.scalars(
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


def get_nearest_playable_stop(game: Game, location: Point) -> Stop | None:
    """Return the nearest playable stop to a location.

    Filters by: dataset membership, inside game map boundary, not excluded.
    Orders by distance to location (ascending). Requires PostGIS (uses ST_Distance).
    """
    session = get_session()
    conditions = _playable_conditions(game)
    location_wkb = sa.func.ST_GeomFromWKB(
        wkb.dumps(location, include_srid=False),
        4326,
    )

    stmt = (
        select(Stop)
        .where(*conditions)
        .order_by(sa.func.ST_Distance(Stop.coordinates, location_wkb))
        .limit(1)
    )

    return session.scalars(stmt).one_or_none()
