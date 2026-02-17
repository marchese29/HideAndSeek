"""Tests for the geo module — haversine distance and GeoJSON helper."""

from __future__ import annotations

import pytest

from hideandseek.geo import geojson_distance, haversine


def _point(lng: float, lat: float) -> dict:
    return {'type': 'Point', 'coordinates': [lng, lat]}


# ── haversine ────────────────────────────────────────────────────────────────


def test_haversine_same_point():
    assert haversine(0.0, 0.0, 0.0, 0.0) == 0.0


def test_haversine_london_to_paris():
    # London (51.5074 N, 0.1278 W) to Paris (48.8566 N, 2.3522 E) ≈ 343 km
    dist = haversine(51.5074, -0.1278, 48.8566, 2.3522)
    assert abs(dist - 343_000) < 1_000  # within 1 km


def test_haversine_symmetric():
    d1 = haversine(51.5, -0.1, 51.0, 0.0)
    d2 = haversine(51.0, 0.0, 51.5, -0.1)
    assert d1 == pytest.approx(d2)


# ── geojson_distance ─────────────────────────────────────────────────────────


def test_geojson_distance_same_point():
    p = _point(0.0, 0.0)
    assert geojson_distance(p, p) == 0.0


def test_geojson_distance_known():
    # Same London-to-Paris check via GeoJSON points
    london = _point(-0.1278, 51.5074)
    paris = _point(2.3522, 48.8566)
    assert abs(geojson_distance(london, paris) - 343_000) < 1_000


def test_geojson_distance_matches_haversine():
    p1 = _point(-0.1, 51.5)
    p2 = _point(0.0, 51.0)
    assert geojson_distance(p1, p2) == pytest.approx(haversine(51.5, -0.1, 51.0, 0.0))
