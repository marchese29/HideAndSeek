"""Location update processing — enrichment, proximity, and freeze mechanics."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from shapely.geometry import Point

from hideandseek_core.geo import distance as geo_distance
from hideandseek_core.logic.answer import preview_answer
from hideandseek_core.logic.proximity import ProximityResult, evaluate_proximity
from hideandseek_core.logic.station import (
    _FREEZE_DEPARTURE_THRESHOLD_M,
    clear_freeze_locations,
    compute_candidate_station_ids,
    compute_freeze_departed,
    compute_hider_centroid,
    compute_not_in_zone,
    set_freeze_locations,
)
from hideandseek_core.queries.location import (
    create_location_update,
    get_latest_location_for_player,
)
from hideandseek_core.queries.questions import get_active_question
from hideandseek_models.game import Game, Player
from hideandseek_models.types import (
    PlayerRole,
    ProximityTier,
    QuestionStatus,
    StationElectionStatus,
)


@dataclass(frozen=True, slots=True)
class LocationEnrichment:
    """Computed state from a location update — router dispatches events based on this."""

    # Hider enrichment (all None for seeker updates).
    candidate_stations: list[uuid.UUID] | None = None
    not_in_zone: list[uuid.UUID] | None = None
    computed_answer: str | None = None
    freeze_departed: list[uuid.UUID] | None = None

    # Proximity change (None for hider updates or pre-election seekers).
    proximity: ProximityResult | None = None

    # Edge-triggered push flag — true when the reporting hider just became freeze-departed.
    freeze_departure_push: bool = False


def process_location_update(
    game: Game,
    player: Player,
    coordinates: Point,
    timestamp: datetime,
) -> LocationEnrichment:
    """Process a location update: persist, compute enrichment, evaluate proximity/freeze.

    Handles both hider and seeker updates.  All DB mutations (location row,
    freeze_location, proximity_tier) happen here; the caller is responsible for
    event emission and push dispatch.
    """
    assert player.role is not None

    # ── Pre-check: was this hider already freeze-departed? ───────────
    was_freeze_departed = False
    if (
        player.role == PlayerRole.hider
        and game.proximity_tier == ProximityTier.entered
        and player.freeze_location is not None
    ):
        prior = get_latest_location_for_player(player, game)
        if prior:
            was_freeze_departed = (
                geo_distance(player.freeze_location, prior.coordinates)
                > _FREEZE_DEPARTURE_THRESHOLD_M
            )

    # ── Persist location ─────────────────────────────────────────────
    create_location_update(player=player, game=game, coordinates=coordinates, timestamp=timestamp)

    # ── Proximity tier tracking (seeker, seeking, post-election) ─────
    proximity_result: ProximityResult | None = None
    if (
        player.role == PlayerRole.seeker
        and game.status.is_seeking
        and game.station_election_status
        in (StationElectionStatus.elected, StationElectionStatus.auto_assigned)
    ):
        proximity_result = evaluate_proximity(game, player)

        # Freeze / unfreeze on tier transition to/from entered.
        if proximity_result.changed:
            if proximity_result.new_tier == ProximityTier.entered:
                set_freeze_locations(game)
            elif proximity_result.old_tier == ProximityTier.entered:
                clear_freeze_locations(game)

    # ── Hider enrichment ─────────────────────────────────────────────
    candidate_stations: list[uuid.UUID] | None = None
    not_in_zone: list[uuid.UUID] | None = None
    computed_answer: str | None = None
    freeze_departed: list[uuid.UUID] | None = None
    freeze_departure_push = False

    if player.role == PlayerRole.hider:
        if game.station_election_status in (
            StationElectionStatus.pending,
            StationElectionStatus.ambiguous,
        ):
            candidate_stations = compute_candidate_station_ids(game)
        elif game.hider_station_id is not None:
            not_in_zone = compute_not_in_zone(game)
            active_q = get_active_question(game)
            if active_q is not None and active_q.status == QuestionStatus.answerable:
                hider_loc = compute_hider_centroid(game)
                if hider_loc is not None:
                    computed_answer = preview_answer(active_q, hider_loc, game)

            # Freeze departure detection.
            if game.proximity_tier == ProximityTier.entered:
                freeze_departed = compute_freeze_departed(game)
                if not was_freeze_departed and player.id in (freeze_departed or []):
                    freeze_departure_push = True

    return LocationEnrichment(
        candidate_stations=candidate_stations,
        not_in_zone=not_in_zone,
        computed_answer=computed_answer,
        freeze_departed=freeze_departed,
        proximity=proximity_result,
        freeze_departure_push=freeze_departure_push,
    )
