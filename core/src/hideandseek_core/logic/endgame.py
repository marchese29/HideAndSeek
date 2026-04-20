"""Endgame logic — hiding zone computation and endgame exclusions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from shapely.geometry.base import BaseGeometry

from hideandseek_core.conventions import get_default_hiding_zone_radius, to_meters
from hideandseek_core.exclusion import (
    EndgameExclusionResult,
    compute_endgame_exclusions,
    compute_hiding_zone,
)
from hideandseek_core.geo import distance
from hideandseek_core.queries.games import update_game_status
from hideandseek_core.queries.location import get_latest_location_for_player
from hideandseek_core.queries.questions import list_answered_questions_after_sequence
from hideandseek_core.queries.stops import get_candidate_stations as query_candidate_stations
from hideandseek_models.game import Game, Player
from hideandseek_models.transit import Stop
from hideandseek_models.types import EndReason, GameStatus

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

FOUND_CLAIM_TIMEOUT_SECONDS = 120


def effective_hiding_zone_radius_m(game: Game) -> float:
    """Compute effective hiding zone radius in meters for a game.

    Fallback chain: game-level override → map-level override → code-level default.
    Then doubled if the hider has played the expand powerup.
    """
    gm = game.game_map
    radius_conv = (
        game.hiding_zone_radius_override
        or gm.hiding_zone_radius
        or get_default_hiding_zone_radius(gm.convention, game.size)
    )
    base_m = to_meters(radius_conv, gm.convention)
    return base_m * 2 if game.hiding_zone_expanded else base_m


def get_endgame_exclusions(
    game: Game, station: Stop, after_sequence: int
) -> EndgameExclusionResult:
    """Compute endgame exclusion view for a station.

    Returns hiding zone geometry and per-question exclusions intersected with it,
    starting from questions after the given sequence number.
    """
    radius_m = effective_hiding_zone_radius_m(game)
    questions = list_answered_questions_after_sequence(game, after_sequence)
    return compute_endgame_exclusions(
        game.game_map.boundary, station.coordinates, radius_m, questions
    )


def get_candidate_stations(game: Game, offset: int, limit: int) -> Sequence[Stop]:
    """Return playable stops not fully covered by the game's total exclusion."""
    radius_m = effective_hiding_zone_radius_m(game)
    return query_candidate_stations(game, radius_m, offset, limit)


def compute_hiding_zone_for_station(game: Game, station: Stop) -> BaseGeometry:
    """Compute the hiding zone polygon for a station in a game."""
    radius_m = effective_hiding_zone_radius_m(game)
    return compute_hiding_zone(station.coordinates, radius_m, game.game_map.boundary)


def seeker_inside_hiding_zone(game: Game, seeker: Player) -> bool:
    """True if the seeker's latest reported location is within the hiding zone radius.

    Returns False if the seeker has no reported location or no station is elected.
    """
    if game.hider_station is None:
        return False
    latest = get_latest_location_for_player(seeker, game)
    if latest is None:
        return False
    dist_m = distance(latest.coordinates, game.hider_station.coordinates)
    return dist_m <= effective_hiding_zone_radius_m(game)


def record_found_claim(game: Game, seeker: Player) -> None:
    """Mark a pending found claim. Caller validates preconditions."""
    game.found_claim_at = datetime.now(UTC)
    game.found_claim_player_id = seeker.id
    logger.info(
        'found_claim_recorded',
        game_id=str(game.id),
        seeker_id=str(seeker.id),
    )


def confirm_found_claim(game: Game) -> None:
    """Finish the game with reason=found. Clears claim state."""
    seeker_id = game.found_claim_player_id
    game.found_claim_at = None
    game.found_claim_player_id = None
    game.end_reason = EndReason.found
    update_game_status(game, GameStatus.finished)
    logger.info(
        'found_claim_confirmed',
        game_id=str(game.id),
        seeker_id=str(seeker_id) if seeker_id else None,
    )
    logger.info(
        'game_ended',
        game_id=str(game.id),
        reason=EndReason.found.value,
    )


def reject_found_claim(game: Game) -> None:
    """Dismiss the pending claim. No game status change."""
    seeker_id = game.found_claim_player_id
    game.found_claim_at = None
    game.found_claim_player_id = None
    logger.info(
        'found_claim_rejected',
        game_id=str(game.id),
        seeker_id=str(seeker_id) if seeker_id else None,
    )


def expire_found_claim(game: Game) -> bool:
    """Clear a live found claim on auto-dismiss. Returns True if a claim was cleared.

    Idempotent: no-op if the claim is already cleared (confirmed, rejected, or the
    game already finished/dissolved).
    """
    if game.found_claim_at is None or not game.status.is_active:
        return False
    game.found_claim_at = None
    game.found_claim_player_id = None
    logger.info('found_claim_expired', game_id=str(game.id))
    return True


def expand_hiding_zone(game: Game) -> None:
    """Apply the one-time hiding-zone expansion. Doubles the effective radius.

    Raises ValueError if not seeking or if already expanded.
    """
    if not game.status.is_seeking:
        msg = 'Hiding zone can only be expanded during the seeking phase.'
        raise ValueError(msg)
    if game.hiding_zone_expanded:
        msg = 'Hiding zone has already been expanded.'
        raise ValueError(msg)
    game.hiding_zone_expanded = True
    logger.info(
        'hiding_zone_expanded',
        game_id=str(game.id),
        effective_radius_m=effective_hiding_zone_radius_m(game),
    )
