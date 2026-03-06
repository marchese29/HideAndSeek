"""Endgame logic — hiding zone computation and endgame exclusions."""

from __future__ import annotations

from collections.abc import Sequence

from shapely.geometry.base import BaseGeometry

from hideandseek.conventions import get_default_hiding_zone_radius, to_meters
from hideandseek.exclusion import (
    EndgameExclusionResult,
    compute_endgame_exclusions,
    compute_hiding_zone,
)
from hideandseek.models.game import Game
from hideandseek.models.transit import Stop
from hideandseek.queries.questions import list_answered_questions_after_sequence
from hideandseek.queries.stops import get_candidate_stations as query_candidate_stations


def effective_hiding_zone_radius_m(game: Game) -> float:
    """Compute effective hiding zone radius in meters for a game.

    Fallback chain: game-level override → map-level override → code-level default.
    """
    gm = game.game_map
    radius_conv = (
        game.hiding_zone_radius_override
        or gm.hiding_zone_radius
        or get_default_hiding_zone_radius(gm.convention, gm.size)
    )
    return to_meters(radius_conv, gm.convention)


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
