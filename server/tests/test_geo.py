"""Tests for the geo module — geodesic distance utilities."""

from __future__ import annotations

import pytest
from shapely.geometry import Point

from hideandseek.geo import distance


def test_distance_same_point():
    p = Point(0.0, 0.0)
    assert distance(p, p) == 0.0


def test_distance_london_to_paris():
    # London (51.5074 N, 0.1278 W) to Paris (48.8566 N, 2.3522 E) ~ 343 km
    london = Point(-0.1278, 51.5074)
    paris = Point(2.3522, 48.8566)
    assert abs(distance(london, paris) - 343_000) < 1_000


def test_distance_symmetric():
    p1 = Point(-0.1, 51.5)
    p2 = Point(0.0, 51.0)
    assert distance(p1, p2) == pytest.approx(distance(p2, p1))
