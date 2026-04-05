"""Tests for endgame endpoints and supporting logic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from shapely import Point, Polygon
from shapely.geometry.base import BaseGeometry
from sqlalchemy.orm import Session

from hideandseek.exclusion import _buffer, compute_endgame_exclusions, exclude_radar
from hideandseek.queries.stops import get_nearest_playable_stop
from hideandseek_models.question import Question
from hideandseek_models.transit import Stop
from hideandseek_models.types import GameStatus, PlayerRole, QuestionStatus, QuestionType

from .conftest import (
    TEST_SECRET,
    create_game,
    create_game_map,
    create_player,
    create_transit_dataset,
)

# A ~10 km square around (0, 0).
GAME_MAP = Polygon([(-0.1, -0.1), (0.1, -0.1), (0.1, 0.1), (-0.1, 0.1), (-0.1, -0.1)])


def _headers(player_id: uuid.UUID) -> dict[str, str]:
    return {'X-Player-Id': str(player_id), 'X-Player-Secret': TEST_SECRET}


# ── compute_endgame_exclusions (unit tests, no DB) ─────────────────────


def _make_question(
    sequence: int,
    exclusion: BaseGeometry | None = None,
) -> Question:
    """Build a minimal Question for testing compute_endgame_exclusions."""
    return Question(
        id=uuid.uuid4(),
        game_id=uuid.uuid4(),
        sequence=sequence,
        question_type=QuestionType.radar,
        status=QuestionStatus.answered,
        asked_by=uuid.uuid4(),
        asked_at=datetime.now(UTC),
        seeker_location_start=Point(0, 0),
        answer='yes',
        exclusion=exclusion,
    )


def test_endgame_exclusions_intersect_with_hiding_zone() -> None:
    """Exclusion zones are intersected with the hiding zone circle."""
    # A large exclusion covering the entire game map
    large_exclusion = GAME_MAP
    q = _make_question(sequence=1, exclusion=large_exclusion)

    result = compute_endgame_exclusions(GAME_MAP, Point(0, 0), 500, [q])

    assert len(result.entries) == 1
    entry = result.entries[0]
    # The intersected exclusion should be within the hiding zone
    assert entry.exclusion is not None
    assert result.hiding_zone.contains(entry.exclusion)


def test_endgame_exclusions_cumulative() -> None:
    """total_exclusion accumulates across endgame-scoped questions."""
    # Two non-overlapping exclusions on opposite sides
    excl_left = Polygon([(-0.05, -0.01), (-0.03, -0.01), (-0.03, 0.01), (-0.05, 0.01)])
    excl_right = Polygon([(0.03, -0.01), (0.05, -0.01), (0.05, 0.01), (0.03, 0.01)])

    q1 = _make_question(sequence=1, exclusion=excl_left)
    q2 = _make_question(sequence=2, exclusion=excl_right)

    result = compute_endgame_exclusions(GAME_MAP, Point(0, 0), 10_000, [q1, q2])

    assert len(result.entries) == 2
    # First entry's total_exclusion is just the first exclusion
    assert result.entries[0].total_exclusion is not None
    # Second entry's total_exclusion should be larger (union of both)
    assert result.entries[1].total_exclusion is not None
    assert result.entries[1].total_exclusion.area > result.entries[0].total_exclusion.area


def test_endgame_exclusions_none_exclusion_skipped() -> None:
    """Questions with None exclusion don't affect cumulative total."""
    q1 = _make_question(sequence=1, exclusion=None)

    result = compute_endgame_exclusions(GAME_MAP, Point(0, 0), 500, [q1])

    assert len(result.entries) == 1
    assert result.entries[0].exclusion is None
    assert result.entries[0].total_exclusion is None


def test_endgame_hiding_zone_clipped_to_game_map() -> None:
    """Hiding zone circle is clipped to the game map boundary at the edge."""
    # Station at the corner of a large map — circle extends outside the boundary
    large_map = Polygon([(-0.1, -0.1), (0.1, -0.1), (0.1, 0.1), (-0.1, 0.1)])
    station = Point(-0.1, -0.1)  # corner

    result = compute_endgame_exclusions(large_map, station, 500, [])

    # The hiding zone should fit inside the game map
    assert large_map.contains(result.hiding_zone)
    # A full unclipped circle would extend outside — verify clipping reduced area
    full_circle = _buffer(station, 500)
    assert result.hiding_zone.area < full_circle.area


# ── Endgame exclusions endpoint (integration tests) ────────────────────


def _create_stop(session: Session, dataset_id: uuid.UUID, name: str = 'Central Station') -> Stop:
    """Create a stop in the dataset."""
    stop = Stop(
        stable_id=f'stop-{uuid.uuid4().hex[:8]}',
        dataset_id=dataset_id,
        name=name,
        coordinates=Point(0.5, 0.5),
    )
    session.add(stop)
    session.commit()
    session.refresh(stop)
    return stop


def test_endgame_exclusions_endpoint_seeking(session: Session, client: TestClient) -> None:
    """GET /endgame-exclusions returns exclusions when game is seeking."""
    ds = create_transit_dataset(session)
    gm = create_game_map(session, transit_dataset_id=ds.id)
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    stop = _create_stop(session, ds.id)

    resp = client.get(
        f'/games/{game.id}/endgame-exclusions',
        params={'station_id': str(stop.id), 'after_question': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert 'hiding_zone' in data
    assert 'entries' in data
    assert data['entries'] == []


def test_endgame_exclusions_with_answered_questions(session: Session, client: TestClient) -> None:
    """GET /endgame-exclusions returns intersected exclusions for answered questions."""
    ds = create_transit_dataset(session)
    gm = create_game_map(session, transit_dataset_id=ds.id)
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    stop = _create_stop(session, ds.id)

    # Create an answered question with exclusion
    exclusion = exclude_radar(gm.boundary, Point(0.5, 0.5), 500, hit=False)
    q = Question(
        game_id=game.id,
        sequence=1,
        question_type=QuestionType.radar,
        status=QuestionStatus.answered,
        asked_by=seeker.id,
        seeker_location_start=Point(0.5, 0.5),
        answer='no',
        exclusion=exclusion,
        total_exclusion=exclusion,
        answered_at=datetime.now(UTC),
    )
    session.add(q)
    session.commit()

    resp = client.get(
        f'/games/{game.id}/endgame-exclusions',
        params={'station_id': str(stop.id), 'after_question': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data['entries']) == 1
    assert data['entries'][0]['exclusion'] is not None
    assert data['entries'][0]['total_exclusion'] is not None


def test_endgame_exclusions_after_question_filters(session: Session, client: TestClient) -> None:
    """Questions before after_question are excluded from the response."""
    ds = create_transit_dataset(session)
    gm = create_game_map(session, transit_dataset_id=ds.id)
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    stop = _create_stop(session, ds.id)

    # Two answered questions
    for seq in (1, 2):
        q = Question(
            game_id=game.id,
            sequence=seq,
            question_type=QuestionType.radar,
            status=QuestionStatus.answered,
            asked_by=seeker.id,
            seeker_location_start=Point(0.5, 0.5),
            answer='no',
            answered_at=datetime.now(UTC),
        )
        session.add(q)
    session.commit()

    # after_question=1 should only return question with sequence=2
    resp = client.get(
        f'/games/{game.id}/endgame-exclusions',
        params={'station_id': str(stop.id), 'after_question': 1},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 200
    assert len(resp.json()['entries']) == 1
    assert resp.json()['entries'][0]['sequence'] == 2


def test_endgame_exclusions_409_if_not_seeking(session: Session, client: TestClient) -> None:
    """GET /endgame-exclusions returns 409 if game is not in seeking status."""
    ds = create_transit_dataset(session)
    gm = create_game_map(session, transit_dataset_id=ds.id)
    game = create_game(session, map_id=gm.id, status=GameStatus.lobby)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    resp = client.get(
        f'/games/{game.id}/endgame-exclusions',
        params={'station_id': str(uuid.uuid4()), 'after_question': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 409


def test_endgame_exclusions_404_invalid_station(session: Session, client: TestClient) -> None:
    """GET /endgame-exclusions returns 404 for a non-existent station."""
    gm = create_game_map(session)
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    resp = client.get(
        f'/games/{game.id}/endgame-exclusions',
        params={'station_id': str(uuid.uuid4()), 'after_question': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 404


def test_endgame_exclusions_422_wrong_dataset(session: Session, client: TestClient) -> None:
    """GET /endgame-exclusions returns 422 if station is from a different dataset."""
    ds1 = create_transit_dataset(session, name='Dataset 1')
    ds2 = create_transit_dataset(session, name='Dataset 2')
    gm = create_game_map(session, transit_dataset_id=ds1.id)
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    # Stop belongs to ds2, not ds1
    stop = Stop(
        stable_id='stop-wrong',
        dataset_id=ds2.id,
        name='Wrong Dataset Station',
        coordinates=Point(0.5, 0.5),
    )
    session.add(stop)
    session.commit()
    session.refresh(stop)

    resp = client.get(
        f'/games/{game.id}/endgame-exclusions',
        params={'station_id': str(stop.id), 'after_question': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 422


def test_endgame_exclusions_hider_403(session: Session, client: TestClient) -> None:
    """GET /endgame-exclusions returns 403 for hiders."""
    ds = create_transit_dataset(session)
    gm = create_game_map(session, transit_dataset_id=ds.id)
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    stop = _create_stop(session, ds.id)

    resp = client.get(
        f'/games/{game.id}/endgame-exclusions',
        params={'station_id': str(stop.id), 'after_question': 0},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 403


# ── Candidate stations endpoint ────────────────────────────────────────


def test_candidate_stations_409_if_not_seeking(session: Session, client: TestClient) -> None:
    """GET /candidate-stations returns 409 if game is not in seeking status."""
    gm = create_game_map(session)
    game = create_game(session, map_id=gm.id, status=GameStatus.lobby)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    resp = client.get(
        f'/games/{game.id}/candidate-stations',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 409


def test_candidate_stations_hider_403(session: Session, client: TestClient) -> None:
    """GET /candidate-stations returns 403 for hiders."""
    gm = create_game_map(session)
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, role=PlayerRole.hider)

    resp = client.get(
        f'/games/{game.id}/candidate-stations',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 403


def test_nearest_playable_stop(session: Session) -> None:
    """get_nearest_playable_stop returns the closest eligible stop."""
    gm = create_game_map(session, boundary=GAME_MAP)
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)

    # Create two stops inside the boundary at different distances from the query point
    near_stop = Stop(
        stable_id='near',
        dataset_id=gm.transit_dataset_id,
        name='Near Stop',
        coordinates=Point(0.01, 0.01),
    )
    far_stop = Stop(
        stable_id='far',
        dataset_id=gm.transit_dataset_id,
        name='Far Stop',
        coordinates=Point(0.05, 0.05),
    )
    session.add_all([near_stop, far_stop])
    session.flush()

    result = get_nearest_playable_stop(game, Point(0.0, 0.0))
    assert result is not None
    assert result.id == near_stop.id


def test_candidate_stations_returns_stops(session: Session, client: TestClient) -> None:
    """GET /candidate-stations returns playable stops."""
    gm = create_game_map(session, boundary=GAME_MAP)
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    stop = Stop(
        stable_id='cand',
        dataset_id=gm.transit_dataset_id,
        name='Candidate Stop',
        coordinates=Point(0.0, 0.0),
    )
    session.add(stop)
    session.flush()

    resp = client.get(
        f'/games/{game.id}/candidate-stations',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(s['id'] == str(stop.id) for s in data)
