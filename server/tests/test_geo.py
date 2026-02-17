"""Tests for the geo module — haversine distance and shapely Point helper."""

from __future__ import annotations

import pytest
from shapely.geometry import Point

from hideandseek.geo import distance, haversine

# ── haversine ────────────────────────────────────────────────────────────────


def test_haversine_same_point():
    assert haversine((0.0, 0.0), (0.0, 0.0)) == 0.0


def test_haversine_london_to_paris():
    # London (51.5074 N, 0.1278 W) to Paris (48.8566 N, 2.3522 E) ~ 343 km
    dist = haversine((51.5074, -0.1278), (48.8566, 2.3522))
    assert abs(dist - 343_000) < 1_000  # within 1 km


def test_haversine_symmetric():
    d1 = haversine((51.5, -0.1), (51.0, 0.0))
    d2 = haversine((51.0, 0.0), (51.5, -0.1))
    assert d1 == pytest.approx(d2)


# ── distance ─────────────────────────────────────────────────────────────────


def test_distance_same_point():
    p = Point(0.0, 0.0)
    assert distance(p, p) == 0.0


def test_distance_known():
    # Same London-to-Paris check via shapely Points (x=lng, y=lat)
    london = Point(-0.1278, 51.5074)
    paris = Point(2.3522, 48.8566)
    assert abs(distance(london, paris) - 343_000) < 1_000


def test_distance_matches_haversine():
    p1 = Point(-0.1, 51.5)
    p2 = Point(0.0, 51.0)
    assert distance(p1, p2) == pytest.approx(haversine((51.5, -0.1), (51.0, 0.0)))
