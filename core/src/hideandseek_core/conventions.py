"""Distance convention utilities — metric/imperial conversion and defaults.

Convention values are stored and transmitted in the map's convention units
(meters for metric, miles for imperial). Internal geo math always uses meters.
Conversion happens at the boundary in logic.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hideandseek_models.game_map import GameMap
from hideandseek_models.types import (
    DistanceConvention,
    FeatureCategory,
    MapSize,
    subjects_for_size,
)

if TYPE_CHECKING:
    from hideandseek_models.game import Game

_MILES_PER_METER = 1609.344


def to_meters(value: float, convention: DistanceConvention) -> float:
    """Convert a convention-unit value to meters."""
    if convention == DistanceConvention.imperial:
        return value * _MILES_PER_METER
    return value


def from_meters(meters: float, convention: DistanceConvention) -> float:
    """Convert meters to convention units."""
    if convention == DistanceConvention.imperial:
        return meters / _MILES_PER_METER
    return meters


def format_distance_label(value: float, convention: DistanceConvention) -> str:
    """Format a distance value for human-readable push notification labels.

    Metric: "500 m", "1 km", "5 km" (switches at >= 1000).
    Imperial: "0.25 mi", "1 mi", "10 mi".
    """
    if convention == DistanceConvention.imperial:
        return f'{value:g} mi'
    if value >= 1000:
        return f'{value / 1000:g} km'
    return f'{value:g} m'


# ── Default inventory constants ──────────────────────────────────────────────
#
# Keyed by (convention, size). The `special` size has no code-level defaults —
# maps with size=special must provide a default_inventory override.

_RADAR_METRIC = [500, 1_000, 2_000, 5_000, 10_000, 15_000, 40_000, 80_000, 160_000]
_RADAR_IMPERIAL = [0.25, 0.5, 1, 2, 5, 10, 25, 50, 100]

_THERMO_METRIC = {
    MapSize.small: [1_000, 5_000, 10_000],
    MapSize.medium: [1_000, 5_000, 10_000, 15_000],
    MapSize.large: [1_000, 5_000, 10_000, 15_000, 75_000],
}

_THERMO_IMPERIAL = {
    MapSize.small: [0.5, 1, 5],
    MapSize.medium: [0.5, 1, 5, 10],
    MapSize.large: [0.5, 1, 5, 10, 25],
}


# ── Hiding zone radius defaults ──────────────────────────────────────────

_HIDING_ZONE_METRIC = {
    MapSize.small: 500,
    MapSize.medium: 500,
    MapSize.large: 1_000,
}

_HIDING_ZONE_IMPERIAL = {
    MapSize.small: 0.25,
    MapSize.medium: 0.25,
    MapSize.large: 0.5,
}


_HIDING_TIME_MIN = {
    MapSize.small: 30,
    MapSize.medium: 60,
    MapSize.large: 180,
}


def get_default_hiding_time_min(size: MapSize) -> int:
    """Return the default hiding phase duration in minutes.

    Determined by map size (not convention). Raises ValueError for special-size
    maps (they must provide an override).
    """
    if size == MapSize.special:
        raise ValueError('special-size maps must provide a hiding_time_min override.')
    return _HIDING_TIME_MIN[size]


_DEFAULT_QUESTION_DELAY_MIN = 5

_DEFAULT_PHOTO_SUBMIT_MIN: dict[MapSize, int] = {
    MapSize.small: 10,
    MapSize.medium: 10,
    MapSize.large: 20,
}
_DEFAULT_PHOTO_REVIEW_SEC = 30


def resolve_hiding_time_min(
    *, request_override: int | None, map_default: int | None, size: MapSize
) -> int:
    """Resolve hiding time with three-level fallback: request → map → code default."""
    return request_override or map_default or get_default_hiding_time_min(size)


def resolve_base_question_delay_min(
    *, request_override: int | None, map_default: int | None
) -> int:
    """Resolve question delay with three-level fallback: request → map → code default."""
    return request_override or map_default or _DEFAULT_QUESTION_DELAY_MIN


def resolve_photo_submit_min(
    *, request_override: int | None, map_default: int | None, size: MapSize
) -> int:
    """Resolve photo submit window with three-level fallback: request → map → code default.

    Raises ValueError for special-size maps (no code-level default defined).
    """
    if size == MapSize.special:
        raise ValueError('special-size maps must provide a photo_submit_min override.')
    return request_override or map_default or _DEFAULT_PHOTO_SUBMIT_MIN[size]


def resolve_photo_review_sec(*, request_override: int | None, map_default: int | None) -> int:
    """Resolve photo review window with three-level fallback: request → map → code default."""
    return request_override or map_default or _DEFAULT_PHOTO_REVIEW_SEC


def effective_photo_review_sec(game: Game) -> int:
    """Resolve the effective photo review window for a game (three-level fallback)."""
    return resolve_photo_review_sec(
        request_override=game.photo_review_sec,
        map_default=game.game_map.default_photo_review_sec,
    )


def effective_photo_submit_min(game: Game) -> int:
    """Resolve the effective photo submit window for a game (three-level fallback)."""
    return resolve_photo_submit_min(
        request_override=game.photo_submit_min,
        map_default=game.game_map.default_photo_submit_min,
        size=game.size,
    )


def get_default_hiding_zone_radius(convention: DistanceConvention, size: MapSize) -> float:
    """Return the default hiding zone radius in convention units.

    Raises ValueError for special-size maps (they must provide an override).
    """
    if size == MapSize.special:
        raise ValueError('special-size maps must provide a hiding_zone_radius override.')

    if convention == DistanceConvention.imperial:
        return _HIDING_ZONE_IMPERIAL[size]
    return _HIDING_ZONE_METRIC[size]


# ── Default inventory constants ──────────────────────────────────────────────


def get_default_inventory(convention: DistanceConvention, size: MapSize) -> dict:
    """Return the default inventory template for a convention and map size.

    Raises ValueError for special-size maps (they must provide an override).
    """
    if size == MapSize.special:
        raise ValueError('special-size maps must provide a default_inventory override.')

    if convention == DistanceConvention.imperial:
        radars = _RADAR_IMPERIAL
        thermos = _THERMO_IMPERIAL[size]
    else:
        radars = _RADAR_METRIC
        thermos = _THERMO_METRIC[size]

    return {
        'radars': [{'distance': d} for d in radars] + [{'distance': None}],
        'thermometers': [{'distance': d} for d in thermos] + [{'distance': None}],
        'photos': [{'subject': s.value} for s in subjects_for_size(size)],
    }


def resolve_tentacle_distance(game_map: GameMap, category: FeatureCategory) -> float:
    """Look up the configured tentacle distance for a category on a map.

    Returns the distance in the map's convention units.
    Raises ValueError if the category is not configured for tentacles on this map.
    """
    for entry in game_map.tentacle_categories:
        if entry['category'] == category.value:
            return entry['distance']
    raise ValueError(f'Category {category} is not configured for tentacles on map {game_map.name}')
