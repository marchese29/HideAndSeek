"""Tests for distance convention utilities."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from hideandseek.conventions import (
    format_distance_label,
    from_meters,
    get_default_hiding_zone_radius,
    get_default_inventory,
    to_meters,
)
from hideandseek.logic.endgame import effective_hiding_zone_radius_m
from hideandseek.models.types import DistanceConvention, MapSize
from tests.conftest import create_game, create_game_map

# ── to_meters / from_meters ─────────────────────────────────────────────


def test_to_meters_metric_identity():
    assert to_meters(500, DistanceConvention.metric) == 500


def test_to_meters_imperial():
    result = to_meters(1, DistanceConvention.imperial)
    assert result == pytest.approx(1609.344)


def test_from_meters_metric_identity():
    assert from_meters(500, DistanceConvention.metric) == 500


def test_from_meters_imperial():
    result = from_meters(1609.344, DistanceConvention.imperial)
    assert result == pytest.approx(1.0)


def test_roundtrip_imperial():
    """to_meters then from_meters should return the original value."""
    original = 5.0
    meters = to_meters(original, DistanceConvention.imperial)
    back = from_meters(meters, DistanceConvention.imperial)
    assert back == pytest.approx(original)


# ── format_distance_label ────────────────────────────────────────────────


def test_format_metric_meters():
    assert format_distance_label(500, DistanceConvention.metric) == '500 m'


def test_format_metric_kilometers():
    assert format_distance_label(1000, DistanceConvention.metric) == '1 km'


def test_format_metric_large():
    assert format_distance_label(5000, DistanceConvention.metric) == '5 km'


def test_format_imperial():
    assert format_distance_label(0.25, DistanceConvention.imperial) == '0.25 mi'


def test_format_imperial_whole():
    assert format_distance_label(10, DistanceConvention.imperial) == '10 mi'


# ── get_default_inventory ────────────────────────────────────────────────


def test_default_inventory_metric_small():
    inv = get_default_inventory(DistanceConvention.metric, MapSize.small)
    radar_distances = [s['distance'] for s in inv['radars']]
    thermo_distances = [s['distance'] for s in inv['thermometers']]
    assert radar_distances[0] == 500
    assert radar_distances[-2] == 160_000
    assert radar_distances[-1] is None
    assert len(radar_distances) == 10
    assert thermo_distances == [1_000, 5_000, 10_000, None]


def test_default_inventory_metric_medium():
    inv = get_default_inventory(DistanceConvention.metric, MapSize.medium)
    thermo_distances = [s['distance'] for s in inv['thermometers']]
    assert thermo_distances == [1_000, 5_000, 10_000, 15_000, None]


def test_default_inventory_metric_large():
    inv = get_default_inventory(DistanceConvention.metric, MapSize.large)
    thermo_distances = [s['distance'] for s in inv['thermometers']]
    assert thermo_distances == [1_000, 5_000, 10_000, 15_000, 75_000, None]


def test_default_inventory_imperial_small():
    inv = get_default_inventory(DistanceConvention.imperial, MapSize.small)
    radar_distances = [s['distance'] for s in inv['radars']]
    thermo_distances = [s['distance'] for s in inv['thermometers']]
    assert radar_distances == [0.25, 0.5, 1, 2, 5, 10, 25, 50, 100, None]
    assert thermo_distances == [0.5, 1, 5, None]


def test_default_inventory_imperial_large():
    inv = get_default_inventory(DistanceConvention.imperial, MapSize.large)
    thermo_distances = [s['distance'] for s in inv['thermometers']]
    assert thermo_distances == [0.5, 1, 5, 10, 25, None]


def test_default_inventory_special_raises():
    with pytest.raises(ValueError, match='special'):
        get_default_inventory(DistanceConvention.metric, MapSize.special)


# ── get_default_hiding_zone_radius ──────────────────────────────────────


def test_hiding_zone_metric_small():
    assert get_default_hiding_zone_radius(DistanceConvention.metric, MapSize.small) == 500


def test_hiding_zone_metric_medium():
    assert get_default_hiding_zone_radius(DistanceConvention.metric, MapSize.medium) == 500


def test_hiding_zone_metric_large():
    assert get_default_hiding_zone_radius(DistanceConvention.metric, MapSize.large) == 1_000


def test_hiding_zone_imperial_small():
    assert get_default_hiding_zone_radius(DistanceConvention.imperial, MapSize.small) == 0.25


def test_hiding_zone_imperial_large():
    assert get_default_hiding_zone_radius(DistanceConvention.imperial, MapSize.large) == 0.5


def test_hiding_zone_special_raises():
    with pytest.raises(ValueError, match='special'):
        get_default_hiding_zone_radius(DistanceConvention.metric, MapSize.special)


# ── effective_hiding_zone_radius_m fallback chain ─────────────────────


def test_effective_radius_game_override_takes_precedence(session: Session):
    """Game-level hiding_zone_radius_override beats map-level and code-level defaults."""
    gm = create_game_map(session, hiding_zone_radius=750)
    game = create_game(session, map_id=gm.id, hiding_zone_radius_override=999)
    result = effective_hiding_zone_radius_m(game)
    # 999 meters (metric convention, so no conversion)
    assert result == 999


def test_effective_radius_map_override_used_without_game_override(session: Session):
    """Map-level hiding_zone_radius used when game-level override is None."""
    gm = create_game_map(session, hiding_zone_radius=750)
    game = create_game(session, map_id=gm.id)
    result = effective_hiding_zone_radius_m(game)
    assert result == 750


def test_effective_radius_falls_back_to_code_default(session: Session):
    """Code-level default used when both overrides are None."""
    gm = create_game_map(session)  # hiding_zone_radius defaults to None
    game = create_game(session, map_id=gm.id)
    result = effective_hiding_zone_radius_m(game)
    # Default for metric medium is 500m
    assert result == 500
