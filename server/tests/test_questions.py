from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from shapely.geometry import Point
from sqlmodel import Session

from hideandseek.models.game import Game, Player
from hideandseek.models.types import GameStatus, PlayerRole
from tests.conftest import (
    create_game,
    create_game_map,
    create_game_map_feature,
    create_map_feature,
    create_player,
)


def _headers(client_id: uuid.UUID) -> dict[str, str]:
    return {'X-Client-Id': str(client_id)}


def _point(lng: float = -0.141, lat: float = 51.515) -> dict:
    return {'type': 'Point', 'coordinates': [lng, lat]}


def _report_location(
    client: TestClient,
    game_id: uuid.UUID,
    player_client_id: uuid.UUID,
    lng: float = -0.141,
    lat: float = 51.515,
):
    """Helper to report a location for a player."""
    client.post(
        f'/games/{game_id}/location',
        json={'coordinates': _point(lng, lat), 'timestamp': '2026-02-11T10:00:00Z'},
        headers=_headers(player_client_id),
    )


def _setup_seeking_game(client: TestClient, session: Session) -> tuple[Game, Player, Player]:
    """Create a seeking game with a hider and seeker, both with reported locations."""
    game = create_game(session, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    _report_location(client, game.id, seeker.client_id, -0.1, 51.5)
    _report_location(client, game.id, hider.client_id, 0.0, 51.0)
    return game, hider, seeker


# ── POST /games/{game_id}/questions ──────────────────────────────────────────


def test_ask_radar_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data['question_type'] == 'radar'
    assert data['status'] == 'answerable'
    assert data['parameters'] == {'radius_m': 3000}
    assert data['sequence'] == 1
    assert data['answerable_at'] is not None


def test_ask_thermometer_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'thermometer', 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data['question_type'] == 'thermometer'
    assert data['status'] == 'in_progress'
    assert data['parameters'] == {'min_travel_m': 500}


def test_ask_custom_slot_requires_distance(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    # slot_index 2 is the custom radar slot (distance_m: null)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 2},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 422
    assert 'custom_distance_m' in resp.json()['detail']


def test_ask_custom_slot_with_distance(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 2, 'custom_distance_m': 4000},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    assert resp.json()['parameters'] == {'radius_m': 4000}


def test_ask_question_deducts_slot(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    # Ask radar slot 0 (3000m)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201

    # Answer the question so we can ask another
    resp = client.post(
        f'/games/{game.id}/questions/{resp.json()["id"]}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200

    # Check game inventory — should have one fewer radar slot
    game_resp = client.get(f'/games/{game.id}')
    radars = game_resp.json()['inventory']['radars']
    assert len(radars) == 2  # was 3, now 2


def test_ask_question_invalid_slot_index(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 99},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 422


def test_ask_question_not_seeking(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.lobby)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 409


def test_ask_question_hider_forbidden(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 0},
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 403


def test_ask_question_while_unanswered(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    # Ask first question
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201

    # Try to ask another while first is unanswered
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 409
    assert 'unanswered' in resp.json()['detail']


# ── POST /games/{game_id}/questions/{id}/lock-in ────────────────────────────


def test_lock_in_thermometer(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'thermometer', 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    # Report a new seeker location (simulates travel)
    _report_location(client, game.id, seeker.client_id, 0.1, 51.6)

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/lock-in',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'answerable'
    assert data['seeker_location_end'] is not None
    assert data['answerable_at'] is not None


def test_lock_in_wrong_status(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    # Ask a radar question (goes straight to answerable, not in_progress)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/lock-in',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 409


# ── POST /games/{game_id}/questions/{id}/answer ─────────────────────────────


def test_answer_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'answered'
    assert data['hider_location'] is not None
    assert data['answer'] == 'no'  # hider ~56 km from seeker, outside 3 km radar
    assert data['answered_at'] is not None


def test_answer_question_seeker_forbidden(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 403


# ── GET /games/{game_id}/questions ───────────────────────────────────────────


def test_list_questions(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)

    # Ask and answer a question
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'radar', 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']
    client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.client_id),
    )

    # List as seeker — hider_location should be hidden
    resp = client.get(
        f'/games/{game.id}/questions',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]['hider_location'] is None  # hidden from seekers

    # List as hider — hider_location should be visible
    resp = client.get(
        f'/games/{game.id}/questions',
        headers=_headers(hider.client_id),
    )
    data = resp.json()
    assert data[0]['hider_location'] is not None


# ── Matching / Measuring helpers ─────────────────────────────────────────────


def _setup_feature_game(client: TestClient, session: Session) -> tuple[Game, Player, Player]:
    """Create a seeking game with map features for matching/measuring tests.

    Two hospitals: one near the seeker (-0.115, 51.499), one near the hider (-0.06, 51.519).
    """
    gm = create_game_map(session)
    near_seeker = create_map_feature(
        session,
        name='Near Seeker Hospital',
        stable_id='hosp_near_seeker',
        geometry=Point(-0.117, 51.498),
    )
    near_hider = create_map_feature(
        session,
        name='Near Hider Hospital',
        stable_id='hosp_near_hider',
        geometry=Point(-0.059, 51.518),
    )
    create_game_map_feature(session, gm.id, near_seeker.id)
    create_game_map_feature(session, gm.id, near_hider.id)

    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    _report_location(client, game.id, seeker.client_id, -0.115, 51.499)
    _report_location(client, game.id, hider.client_id, -0.06, 51.519)
    return game, hider, seeker


# ── POST /questions — matching ───────────────────────────────────────────────


def test_ask_matching_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_feature_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'matching', 'category': 'hospital'},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data['question_type'] == 'matching'
    assert data['status'] == 'answerable'
    assert data['parameters']['category'] == 'hospital'
    assert data['parameters']['source'] == 'map_data'
    assert data['parameters']['seeker_resolution'] is not None
    assert data['parameters']['seeker_resolution']['feature_id'] == 'hosp_near_seeker'


def test_answer_matching_no(client: TestClient, session: Session):
    """Different nearest hospitals → answer 'no'."""
    game, hider, seeker = _setup_feature_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'matching', 'category': 'hospital'},
        headers=_headers(seeker.client_id),
    )
    q_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['answer'] == 'no'
    assert data['parameters']['hider_resolution']['feature_id'] == 'hosp_near_hider'


def test_answer_matching_yes(client: TestClient, session: Session):
    """Both players near the same hospital → answer 'yes'."""
    gm = create_game_map(session)
    hosp = create_map_feature(
        session,
        name='Shared Hospital',
        stable_id='hosp_shared',
        geometry=Point(-0.1, 51.5),
    )
    create_game_map_feature(session, gm.id, hosp.id)

    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    # Both near the same hospital
    _report_location(client, game.id, seeker.client_id, -0.101, 51.501)
    _report_location(client, game.id, hider.client_id, -0.099, 51.499)

    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'matching', 'category': 'hospital'},
        headers=_headers(seeker.client_id),
    )
    q_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.json()['answer'] == 'yes'


def test_matching_category_already_used(client: TestClient, session: Session):
    game, hider, seeker = _setup_feature_game(client, session)
    # Ask and answer a matching question
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'matching', 'category': 'hospital'},
        headers=_headers(seeker.client_id),
    )
    q_id = resp.json()['id']
    client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )

    # Try same category again
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'matching', 'category': 'hospital'},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 409
    assert 'already used' in resp.json()['detail']


def test_matching_missing_category(client: TestClient, session: Session):
    game, hider, seeker = _setup_feature_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'matching'},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 422
    assert 'category' in resp.json()['detail']


def test_matching_category_not_on_map(client: TestClient, session: Session):
    game, hider, seeker = _setup_feature_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'matching', 'category': 'zoo'},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 422
    assert 'not available' in resp.json()['detail']


def test_matching_consumes_inventory(client: TestClient, session: Session):
    game, hider, seeker = _setup_feature_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'matching', 'category': 'hospital'},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201

    # Check inventory
    game_resp = client.get(f'/games/{game.id}')
    assert 'hospital' in game_resp.json()['inventory']['matching_used']


# ── POST /questions — measuring ──────────────────────────────────────────────


def test_ask_measuring_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_feature_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'measuring', 'category': 'hospital'},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data['question_type'] == 'measuring'
    assert data['status'] == 'answerable'
    assert data['parameters']['seeker_resolution'] is not None


def test_answer_measuring_farther(client: TestClient, session: Session):
    """Seeker farther from nearest hospital than hider → 'farther'."""
    game, hider, seeker = _setup_feature_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'measuring', 'category': 'hospital'},
        headers=_headers(seeker.client_id),
    )
    q_id = resp.json()['id']
    seeker_dist = resp.json()['parameters']['seeker_resolution']['distance_m']

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )
    data = resp.json()
    hider_dist = data['parameters']['hider_resolution']['distance_m']
    # Seeker is ~250m from their hospital, hider is ~150m from theirs
    # So seeker is farther
    assert data['answer'] == 'farther'
    assert seeker_dist > hider_dist


def test_answer_measuring_closer(client: TestClient, session: Session):
    """Seeker closer to nearest hospital than hider → 'closer'."""
    gm = create_game_map(session)
    hosp = create_map_feature(
        session,
        name='Central Hospital',
        stable_id='hosp_central',
        geometry=Point(-0.1, 51.5),
    )
    create_game_map_feature(session, gm.id, hosp.id)

    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    # Seeker very close, hider far
    _report_location(client, game.id, seeker.client_id, -0.1001, 51.5001)
    _report_location(client, game.id, hider.client_id, -0.2, 51.6)

    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'measuring', 'category': 'hospital'},
        headers=_headers(seeker.client_id),
    )
    q_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.json()['answer'] == 'closer'


def test_measuring_category_already_used(client: TestClient, session: Session):
    game, hider, seeker = _setup_feature_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'measuring', 'category': 'hospital'},
        headers=_headers(seeker.client_id),
    )
    q_id = resp.json()['id']
    client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )

    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'measuring', 'category': 'hospital'},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 409


def test_measuring_missing_category(client: TestClient, session: Session):
    game, hider, seeker = _setup_feature_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions',
        json={'question_type': 'measuring'},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 422
