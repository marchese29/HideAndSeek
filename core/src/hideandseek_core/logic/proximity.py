"""Proximity tier tracking — seeker distance rings around the hiding zone."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from hideandseek_core.geo import distance
from hideandseek_core.logic.endgame import effective_hiding_zone_radius_m
from hideandseek_core.queries.location import (
    get_all_player_locations,
    get_latest_location_for_player,
)
from hideandseek_models.game import Game, Player
from hideandseek_models.types import PlayerRole, ProximityTier

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_TIER_ORDER: dict[ProximityTier, int] = {
    ProximityTier.none: 0,
    ProximityTier.approaching: 1,
    ProximityTier.near: 2,
    ProximityTier.entered: 3,
}


@dataclass(frozen=True, slots=True)
class ProximityResult:
    """What changed after evaluating proximity."""

    old_tier: ProximityTier
    new_tier: ProximityTier

    @property
    def changed(self) -> bool:
        return self.old_tier != self.new_tier

    @property
    def escalated(self) -> bool:
        return self.changed and _TIER_ORDER[self.new_tier] > _TIER_ORDER[self.old_tier]

    @property
    def deescalated(self) -> bool:
        return self.changed and _TIER_ORDER[self.new_tier] < _TIER_ORDER[self.old_tier]


def _distance_to_tier(distance_m: float, radius_m: float) -> ProximityTier:
    """Map a distance to a proximity tier based on threshold multipliers."""
    if distance_m <= radius_m:
        return ProximityTier.entered
    if distance_m <= 2 * radius_m:
        return ProximityTier.near
    if distance_m <= 4 * radius_m:
        return ProximityTier.approaching
    return ProximityTier.none


def evaluate_proximity(game: Game, reporting_seeker: Player) -> ProximityResult:
    """Recompute proximity tier after a seeker location update.

    Two-phase algorithm:
    1. Compute only the reporting seeker's distance — if closer than current
       tier, escalate immediately (no further queries).
    2. If not escalating, query all seekers' latest positions and find the
       closest tier across everyone. De-escalate if that tier is farther
       than the current game tier.

    Mutates game.proximity_tier if changed.
    """
    old_tier = game.proximity_tier
    station = game.hider_station
    if station is None:
        logger.debug('proximity_skipped', game_id=str(game.id), reason='no_station')
        return ProximityResult(old_tier=old_tier, new_tier=old_tier)

    radius_m = effective_hiding_zone_radius_m(game)
    station_coords = station.coordinates

    # Phase 1: check reporting seeker only.
    reporter_loc = get_latest_location_for_player(reporting_seeker, game)
    if reporter_loc is None:
        logger.debug('proximity_skipped', game_id=str(game.id), reason='no_seeker_location')
        return ProximityResult(old_tier=old_tier, new_tier=old_tier)

    reporter_dist = distance(reporter_loc.coordinates, station_coords)
    reporter_tier = _distance_to_tier(reporter_dist, radius_m)

    if _TIER_ORDER[reporter_tier] > _TIER_ORDER[old_tier]:
        # Escalate immediately.
        game.proximity_tier = reporter_tier
        logger.info(
            'proximity_changed',
            game_id=str(game.id),
            old_tier=old_tier.value,
            new_tier=reporter_tier.value,
            direction='escalated',
        )
        return ProximityResult(old_tier=old_tier, new_tier=reporter_tier)

    # Phase 2: check all seekers for possible de-escalation.
    all_locations = get_all_player_locations(game)
    closest_tier = ProximityTier.none
    for _player_id, loc_data in all_locations.items():
        if loc_data.player.role != PlayerRole.seeker:
            continue
        dist = distance(loc_data.coordinates, station_coords)
        tier = _distance_to_tier(dist, radius_m)
        if _TIER_ORDER[tier] > _TIER_ORDER[closest_tier]:
            closest_tier = tier

    if _TIER_ORDER[closest_tier] < _TIER_ORDER[old_tier]:
        # De-escalate to the closest remaining seeker's tier.
        game.proximity_tier = closest_tier
        logger.info(
            'proximity_changed',
            game_id=str(game.id),
            old_tier=old_tier.value,
            new_tier=closest_tier.value,
            direction='deescalated',
        )
        return ProximityResult(old_tier=old_tier, new_tier=closest_tier)

    return ProximityResult(old_tier=old_tier, new_tier=old_tier)
