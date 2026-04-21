"""Station election logic — election, transition, fallback, representative hider pick."""

from __future__ import annotations

import uuid

import structlog
from shapely.geometry import Point

from hideandseek_core.geo import distance as geo_distance
from hideandseek_core.logic.endgame import effective_hiding_zone_radius_m
from hideandseek_core.queries.location import get_latest_location_for_player
from hideandseek_core.queries.stops import (
    all_hiders_within_radius,
    get_closest_stop_to_any,
    get_stops_within_radius_of_all,
    get_stops_within_radius_of_any,
    validate_stop_playable,
)
from hideandseek_models.game import Game
from hideandseek_models.transit import Stop
from hideandseek_models.types import (
    PlayerRole,
    StationElectionStatus,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _get_hider_locations(game: Game) -> list[Point]:
    """Fetch latest location for each hider in the game."""
    hiders = [p for p in game.players if p.role == PlayerRole.hider]
    locations = []
    for hider in hiders:
        latest = get_latest_location_for_player(hider, game)
        if latest:
            locations.append(latest.coordinates)
    return locations


def _get_hider_locations_by_player(game: Game) -> list[tuple[uuid.UUID, Point]]:
    """Fetch latest location for each hider, paired with player ID."""
    hiders = [p for p in game.players if p.role == PlayerRole.hider]
    result = []
    for hider in hiders:
        latest = get_latest_location_for_player(hider, game)
        if latest:
            result.append((hider.id, latest.coordinates))
    return result


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
        logger.warning(
            'station_ambiguous',
            game_id=str(game.id),
            reason='no_hider_locations',
            candidate_count=0,
        )
        return None, StationElectionStatus.ambiguous

    candidates = get_stops_within_radius_of_all(game, hider_locations, radius_m)
    if len(candidates) == 1:
        logger.info(
            'station_elected',
            game_id=str(game.id),
            stop_id=str(candidates[0].id),
            candidate_count=1,
        )
        return candidates[0], StationElectionStatus.auto_assigned
    reason = 'zero_candidates' if not candidates else 'multiple_candidates'
    logger.warning(
        'station_ambiguous',
        game_id=str(game.id),
        reason=reason,
        candidate_count=len(candidates),
    )
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
        logger.info(
            'station_fallback_used',
            game_id=str(game.id),
            stop_id=str(candidates[0].id),
            tier='all_fit',
        )
        return candidates[0]

    # Tier 2: any hider in radius — ordered by min hider distance (shortest first)
    candidates = get_stops_within_radius_of_any(game, hider_locations, radius_m)
    if candidates:
        logger.info(
            'station_fallback_used',
            game_id=str(game.id),
            stop_id=str(candidates[0].id),
            tier='any_fit',
        )
        return candidates[0]

    # Tier 3: absolute closest (stop, hider) pair across all combos
    stop = get_closest_stop_to_any(game, hider_locations)
    if stop:
        logger.info(
            'station_fallback_used',
            game_id=str(game.id),
            stop_id=str(stop.id),
            tier='closest_pair',
        )
        return stop

    raise RuntimeError('No playable stops found for fallback resolution.')


def representative_hider_location(game: Game) -> Point | None:
    """Return the coordinates of the hider whose latest location is most recent.

    Hiders are expected to stick together, so the freshest fix is a good proxy for
    the group. No time filter — a stale fix still represents "last known position"
    of a stationary group and is better than nothing.
    Returns None if no hider has any location update.
    """
    hiders = [p for p in game.players if p.role == PlayerRole.hider]
    if not hiders:
        logger.debug(
            'representative_hider_location_unavailable',
            game_id=str(game.id),
            reason='no_hiders',
        )
        return None

    locations = []
    for hider in hiders:
        latest = get_latest_location_for_player(hider, game)
        if latest:
            locations.append(latest)

    if not locations:
        logger.debug(
            'representative_hider_location_unavailable',
            game_id=str(game.id),
            reason='no_locations',
        )
        return None

    latest = max(locations, key=lambda loc: loc.timestamp)
    return latest.coordinates


def compute_candidate_station_ids(game: Game) -> list[uuid.UUID]:
    """Stop IDs where ALL hiders are within hiding_zone_radius.

    For use during hiding phase with pending election status.
    Returns empty list if no candidates (hiders too spread out).
    """
    radius_m = effective_hiding_zone_radius_m(game)
    hider_locations = _get_hider_locations(game)
    if not hider_locations:
        return []
    candidates = get_stops_within_radius_of_all(game, hider_locations, radius_m)
    return [s.id for s in candidates]


def compute_not_in_zone(game: Game) -> list[uuid.UUID]:
    """Player IDs of hiders whose latest location is outside the hiding zone.

    For use after station election. Empty list means all hiders are in zone.
    Uses geodesic distance (pure math, no DB round-trip per hider).
    """
    stop = game.hider_station
    if stop is None:
        return []
    radius_m = effective_hiding_zone_radius_m(game)
    hider_entries = _get_hider_locations_by_player(game)
    return [
        player_id
        for player_id, loc in hider_entries
        if geo_distance(stop.coordinates, loc) > radius_m
    ]


# ── Freeze mechanics ──────────────────────────────────────────────────

_FREEZE_DEPARTURE_THRESHOLD_M = 50.0


def set_freeze_locations(game: Game) -> None:
    """Capture each hider's current position as their freeze location.

    Called when proximity_tier escalates to ``entered``.  Hiders without a
    recent location update are skipped (freeze_location stays None).
    """
    hiders = [p for p in game.players if p.role == PlayerRole.hider]
    for hider in hiders:
        latest = get_latest_location_for_player(hider, game)
        hider.freeze_location = latest.coordinates if latest else None
    logger.debug(
        'freeze_locations_set',
        game_id=str(game.id),
        hider_count=len(hiders),
    )


def clear_freeze_locations(game: Game) -> None:
    """Clear freeze locations for all hiders.

    Called when proximity_tier de-escalates from ``entered``.
    """
    hiders = [p for p in game.players if p.role == PlayerRole.hider]
    for hider in hiders:
        hider.freeze_location = None
    logger.debug('freeze_locations_cleared', game_id=str(game.id))


def compute_freeze_departed(game: Game) -> list[uuid.UUID]:
    """Player IDs of hiders who moved >50 m from their freeze position.

    Skips hiders whose freeze_location is None (no position captured).
    """
    hiders = [p for p in game.players if p.role == PlayerRole.hider]
    departed: list[uuid.UUID] = []
    for hider in hiders:
        if hider.freeze_location is None:
            continue
        latest = get_latest_location_for_player(hider, game)
        if not latest:
            continue
        if geo_distance(hider.freeze_location, latest.coordinates) > _FREEZE_DEPARTURE_THRESHOLD_M:
            departed.append(hider.id)
    return departed
