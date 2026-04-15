"""Proximity tier tracking tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import fakeredis
import pytest
from shapely.geometry import Point
from sqlalchemy.orm import Session

from hideandseek_core.logic.proximity import ProximityResult, _distance_to_tier, evaluate_proximity
from hideandseek_models.types import (
    GameStatus,
    MapSize,
    PlayerRole,
    ProximityTier,
    StationElectionStatus,
)
from tests.conftest import (
    create_game,
    create_game_map,
    create_location_update,
    create_player,
    create_stop,
    create_transit_dataset,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

# The hider station is at (0, 0). For a medium/metric game the effective hiding
# zone radius is 500 m (default).  At the equator, 1 degree of longitude ≈
# 111 320 m, so we can place seekers at known metric distances:
#   0.005° ≈ 556 m  (just outside 1× = 500 m → near)
#   0.009° ≈ 1002 m (just outside 2× = 1000 m → approaching)
#   0.018° ≈ 2004 m (just outside 4× = 2000 m → none)
#
# We use longitude offsets at latitude 0 so distance ≈ degrees * 111320 m.

STATION_COORDS = Point(0.0, 0.0)  # hider station at origin

# Distances relative to 500 m hiding zone radius:
#   entered  : ≤ 500 m  (1×)
#   near     : ≤ 1000 m (2×)
#   approaching: ≤ 2000 m (4×)
#   none     : > 2000 m

INSIDE_ZONE = Point(0.003, 0.0)  # ~334 m → entered
NEAR_ZONE = Point(0.007, 0.0)  # ~779 m → near
APPROACHING_ZONE = Point(0.015, 0.0)  # ~1670 m → approaching
FAR_AWAY = Point(0.03, 0.0)  # ~3340 m → none


@pytest.fixture(autouse=True)
def _patch_redis() -> Generator[None, None, None]:
    server = fakeredis.FakeServer()
    fake = fakeredis.FakeRedis(server=server)
    with patch('hideandseek_core.broadcast.emit.get_sync_redis', return_value=fake):
        yield


def _seeking_game_with_station(session: Session) -> tuple:
    """Create a seeking game with an elected hider station at STATION_COORDS."""
    ds = create_transit_dataset(session)
    gm = create_game_map(session, transit_dataset_id=ds.id)
    stop = create_stop(session, ds.id, coordinates=STATION_COORDS)
    game = create_game(
        session,
        map_id=gm.id,
        status=GameStatus.seeking,
        hider_station_id=stop.id,
        station_election_status=StationElectionStatus.elected,
        size=MapSize.medium,
    )
    return game, stop


# ── _distance_to_tier unit tests ─────────────────────────────────────────────


class TestDistanceToTier:
    def test_inside_zone(self):
        assert _distance_to_tier(400, 500) == ProximityTier.entered

    def test_at_zone_boundary(self):
        assert _distance_to_tier(500, 500) == ProximityTier.entered

    def test_near(self):
        assert _distance_to_tier(800, 500) == ProximityTier.near

    def test_at_near_boundary(self):
        assert _distance_to_tier(1000, 500) == ProximityTier.near

    def test_approaching(self):
        assert _distance_to_tier(1500, 500) == ProximityTier.approaching

    def test_at_approaching_boundary(self):
        assert _distance_to_tier(2000, 500) == ProximityTier.approaching

    def test_far_away(self):
        assert _distance_to_tier(2001, 500) == ProximityTier.none


# ── ProximityResult tests ────────────────────────────────────────────────────


class TestProximityResult:
    def test_no_change(self):
        r = ProximityResult(old_tier=ProximityTier.none, new_tier=ProximityTier.none)
        assert not r.changed
        assert not r.escalated
        assert not r.deescalated

    def test_escalation(self):
        r = ProximityResult(old_tier=ProximityTier.none, new_tier=ProximityTier.approaching)
        assert r.changed
        assert r.escalated
        assert not r.deescalated

    def test_deescalation(self):
        r = ProximityResult(old_tier=ProximityTier.entered, new_tier=ProximityTier.near)
        assert r.changed
        assert not r.escalated
        assert r.deescalated


# ── evaluate_proximity integration tests ─────────────────────────────────────


class TestEvaluateProximity:
    def test_seeker_far_away_no_change(self, session: Session):
        game, _ = _seeking_game_with_station(session)
        seeker = create_player(session, game.id, role=PlayerRole.seeker)
        create_location_update(session, seeker.id, game.id, coordinates=FAR_AWAY)

        result = evaluate_proximity(game, seeker)

        assert not result.changed
        assert game.proximity_tier == ProximityTier.none

    def test_escalate_to_approaching(self, session: Session):
        game, _ = _seeking_game_with_station(session)
        seeker = create_player(session, game.id, role=PlayerRole.seeker)
        create_location_update(session, seeker.id, game.id, coordinates=APPROACHING_ZONE)

        result = evaluate_proximity(game, seeker)

        assert result.escalated
        assert result.new_tier == ProximityTier.approaching
        assert game.proximity_tier == ProximityTier.approaching

    def test_escalate_to_entered(self, session: Session):
        game, _ = _seeking_game_with_station(session)
        seeker = create_player(session, game.id, role=PlayerRole.seeker)
        create_location_update(session, seeker.id, game.id, coordinates=INSIDE_ZONE)

        result = evaluate_proximity(game, seeker)

        assert result.escalated
        assert result.new_tier == ProximityTier.entered
        assert game.proximity_tier == ProximityTier.entered

    def test_escalate_skips_intermediate_tiers(self, session: Session):
        """A seeker jumping from far away to inside the zone skips approaching and near."""
        game, _ = _seeking_game_with_station(session)
        seeker = create_player(session, game.id, role=PlayerRole.seeker)
        create_location_update(session, seeker.id, game.id, coordinates=INSIDE_ZONE)

        result = evaluate_proximity(game, seeker)

        assert result.old_tier == ProximityTier.none
        assert result.new_tier == ProximityTier.entered

    def test_deescalate_when_seeker_pulls_back(self, session: Session):
        game, _ = _seeking_game_with_station(session)
        game.proximity_tier = ProximityTier.entered
        seeker = create_player(session, game.id, role=PlayerRole.seeker)
        create_location_update(session, seeker.id, game.id, coordinates=FAR_AWAY)

        result = evaluate_proximity(game, seeker)

        assert result.deescalated
        assert result.new_tier == ProximityTier.none
        assert game.proximity_tier == ProximityTier.none

    def test_deescalate_to_closest_seeker_tier(self, session: Session):
        """De-escalation drops to the closest remaining seeker, not all the way to none."""
        game, _ = _seeking_game_with_station(session)
        game.proximity_tier = ProximityTier.entered

        seeker_a = create_player(session, game.id, role=PlayerRole.seeker, name='Seeker A')
        seeker_b = create_player(session, game.id, role=PlayerRole.seeker, name='Seeker B')

        # Seeker A is in the approaching zone, seeker B just reported from far away.
        create_location_update(session, seeker_a.id, game.id, coordinates=APPROACHING_ZONE)
        create_location_update(session, seeker_b.id, game.id, coordinates=FAR_AWAY)

        result = evaluate_proximity(game, seeker_b)

        assert result.deescalated
        assert result.new_tier == ProximityTier.approaching
        assert game.proximity_tier == ProximityTier.approaching

    def test_no_deescalation_while_any_seeker_is_close(self, session: Session):
        """Tier stays if another seeker is still at the current tier."""
        game, _ = _seeking_game_with_station(session)
        game.proximity_tier = ProximityTier.entered

        seeker_a = create_player(session, game.id, role=PlayerRole.seeker, name='Seeker A')
        seeker_b = create_player(session, game.id, role=PlayerRole.seeker, name='Seeker B')

        # Seeker A is still inside the zone, seeker B reports from far away.
        create_location_update(session, seeker_a.id, game.id, coordinates=INSIDE_ZONE)
        create_location_update(session, seeker_b.id, game.id, coordinates=FAR_AWAY)

        result = evaluate_proximity(game, seeker_b)

        assert not result.changed
        assert game.proximity_tier == ProximityTier.entered

    def test_no_station_returns_unchanged(self, session: Session):
        """No hider station → no proximity evaluation."""
        game = create_game(session, status=GameStatus.seeking)
        seeker = create_player(session, game.id, role=PlayerRole.seeker)
        create_location_update(session, seeker.id, game.id, coordinates=INSIDE_ZONE)

        result = evaluate_proximity(game, seeker)

        assert not result.changed

    def test_no_location_returns_unchanged(self, session: Session):
        """Seeker with no location updates → no proximity evaluation."""
        game, _ = _seeking_game_with_station(session)
        seeker = create_player(session, game.id, role=PlayerRole.seeker)

        result = evaluate_proximity(game, seeker)

        assert not result.changed

    def test_hider_locations_ignored(self, session: Session):
        """Hider locations should not count for de-escalation (only seekers matter)."""
        game, _ = _seeking_game_with_station(session)
        game.proximity_tier = ProximityTier.approaching

        seeker = create_player(session, game.id, role=PlayerRole.seeker, name='Seeker')
        hider = create_player(session, game.id, role=PlayerRole.hider, name='Hider')

        # Hider is inside the zone, seeker is far away.
        create_location_update(session, hider.id, game.id, coordinates=INSIDE_ZONE)
        create_location_update(session, seeker.id, game.id, coordinates=FAR_AWAY)

        result = evaluate_proximity(game, seeker)

        # Should de-escalate to none (only seeker position matters).
        assert result.deescalated
        assert result.new_tier == ProximityTier.none
