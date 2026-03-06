"""Station election logic — election, transition, fallback, centroid."""

from __future__ import annotations

import uuid
from datetime import timedelta

from shapely.geometry import MultiPoint, Point

from hideandseek.logic.endgame import effective_hiding_zone_radius_m
from hideandseek.models.game import Game
from hideandseek.models.transit import Stop
from hideandseek.models.types import (
    PlayerRole,
    StationElectionStatus,
)
from hideandseek.queries.location import get_latest_location_for_player
from hideandseek.queries.stops import (
    all_hiders_within_radius,
    get_closest_stop_to_any,
    get_stops_within_radius_of_all,
    get_stops_within_radius_of_any,
    validate_stop_playable,
)


def _get_hider_locations(game: Game) -> list[Point]:
    """Fetch latest location for each hider in the game."""
    hiders = [p for p in game.players if p.role == PlayerRole.hider]
    locations = []
    for hider in hiders:
        latest = get_latest_location_for_player(hider, game)
        if latest:
            locations.append(latest.coordinates)
    return locations


def validate_station_election(game: Game, station_id: uuid.UUID) -> Stop:
    """Validate a station election request. Returns the stop.

    Raises ValueError if the stop is not playable or any hider is outside the radius.
    """
    stop = validate_stop_playable(game, station_id)
    if not stop:
        raise ValueError('Stop is not a playable station in this game.')

    radius_m = effective_hiding_zone_radius_m(game)
    hider_locations = _get_hider_locations(game)
    if not hider_locations:
        raise ValueError('No hider locations available.')

    if not all_hiders_within_radius(stop, hider_locations, radius_m):
        raise ValueError('Not all hiders are within the hiding zone radius of this station.')

    return stop


def resolve_station_at_transition(
    game: Game,
) -> tuple[Stop | None, StationElectionStatus]:
    """Resolve hider station at the hiding→seeking transition.

    If already elected, returns (None, elected) — no work needed.
    Otherwise finds valid candidates (stops where all hiders are within radius).
    Exactly 1 → auto_assigned. 0 or 2+ → ambiguous.
    """
    if game.station_election_status == StationElectionStatus.elected:
        return None, StationElectionStatus.elected

    radius_m = effective_hiding_zone_radius_m(game)
    hider_locations = _get_hider_locations(game)
    if not hider_locations:
        return None, StationElectionStatus.ambiguous

    candidates = get_stops_within_radius_of_all(game, hider_locations, radius_m)
    if len(candidates) == 1:
        return candidates[0], StationElectionStatus.auto_assigned
    return None, StationElectionStatus.ambiguous


def resolve_station_fallback(game: Game) -> Stop:
    """Resolve station via 3-tier cascade for ambiguity fallback.

    1. All hiders within radius → pick tightest fit
    2. Any hider within radius → pick shortest min distance
    3. Closest (stop, hider) pair

    Each query returns results ordered by its selection criterion,
    so index 0 is the best pick for that tier.
    """
    radius_m = effective_hiding_zone_radius_m(game)
    hider_locations = _get_hider_locations(game)

    # Tier 1: all hiders in radius — ordered by max hider distance (tightest fit first)
    candidates = get_stops_within_radius_of_all(game, hider_locations, radius_m)
    if candidates:
        return candidates[0]

    # Tier 2: any hider in radius — ordered by min hider distance (shortest first)
    candidates = get_stops_within_radius_of_any(game, hider_locations, radius_m)
    if candidates:
        return candidates[0]

    # Tier 3: absolute closest (stop, hider) pair across all combos
    stop = get_closest_stop_to_any(game, hider_locations)
    if stop:
        return stop

    raise RuntimeError('No playable stops found for fallback resolution.')


_HIDER_LOCATION_FRESHNESS = timedelta(minutes=1)


def compute_hider_centroid(game: Game) -> Point | None:
    """Compute the centroid of hiders with recent location updates.

    Finds the latest hider location update across all hiders, then averages
    the positions of all hiders whose latest update is within 1 minute of it.
    Returns None if no hider has a location update.
    """
    hiders = [p for p in game.players if p.role == PlayerRole.hider]
    if not hiders:
        return None

    locations = []
    for hider in hiders:
        latest = get_latest_location_for_player(hider, game)
        if latest:
            locations.append(latest)

    if not locations:
        return None

    newest = max(loc.timestamp for loc in locations)
    cutoff = newest - _HIDER_LOCATION_FRESHNESS

    fresh = [loc.coordinates for loc in locations if loc.timestamp >= cutoff]
    return MultiPoint(fresh).centroid
