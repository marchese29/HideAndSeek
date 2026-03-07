from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from shapely.geometry import Point
from sqlalchemy.orm import Session

from hideandseek.models.game import Game, Player
from hideandseek.models.types import DistanceConvention, GameStatus, PlayerRole
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


# ── POST /games/{game_id}/questions/radar ────────────────────────────────────


def test_ask_radar_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data['question_type'] == 'radar'
    assert data['status'] == 'answerable'
    assert data['ask_count'] == 1
    assert data['parameters']['type'] == 'radar'
    assert data['parameters']['radius'] == 3000
    assert data['sequence'] == 1
    # Ask response is slim — no answer-time fields
    assert 'answerable_at' not in data
    assert 'answered_at' not in data
    assert 'answer' not in data
    assert 'seeker_location_end' not in data
    assert 'hider_location' not in data


def test_ask_custom_slot_requires_distance(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    # slot_index 2 is the custom radar slot (distance: null)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 2},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 422
    assert 'custom_distance' in resp.json()['detail']


def test_ask_custom_slot_with_distance(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 2, 'custom_distance': 4000},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    assert resp.json()['parameters']['radius'] == 4000


def test_ask_question_deducts_slot(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    # Ask radar slot 0 (3000m)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201

    # Answer the question so we can ask another
    resp = client.post(
        f'/games/{game.id}/questions/{resp.json()["id"]}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200

    # Inventory shows ask_count incremented
    game_resp = client.get(f'/games/{game.id}')
    radar_slots = game_resp.json()['inventory']['radar_slots']
    assert len(radar_slots) == 3
    assert radar_slots[0]['ask_count'] == 1  # used once


def test_ask_question_invalid_slot_index(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 99},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 422


def test_ask_question_not_seeking(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.lobby)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 409


def test_ask_question_hider_forbidden(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 403


def test_ask_question_while_unanswered(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    # Ask first question
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201

    # Try to ask another while first is unanswered
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 409
    assert 'unanswered' in resp.json()['detail']


def test_reask_radar_slot(client: TestClient, session: Session):
    """Re-asking the same radar slot increments ask_count."""
    game, hider, seeker = _setup_seeking_game(client, session)

    # First ask
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    assert resp.json()['ask_count'] == 1
    q1_id = resp.json()['id']

    # Answer
    client.post(
        f'/games/{game.id}/questions/{q1_id}/answer',
        headers=_headers(hider.client_id),
    )

    # Re-ask same slot
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    assert resp.json()['ask_count'] == 2


# ── POST /games/{game_id}/questions/thermometer ──────────────────────────────


def test_ask_thermometer_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/thermometer',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data['question_type'] == 'thermometer'
    assert data['status'] == 'in_progress'
    assert data['parameters']['type'] == 'thermometer'
    assert data['parameters']['min_travel'] == 500


# ── POST /games/{game_id}/questions/thermometer/{id}/lock-in ─────────────────


def test_lock_in_thermometer(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/thermometer',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    # Report a new seeker location (simulates travel)
    _report_location(client, game.id, seeker.client_id, 0.1, 51.6)

    resp = client.post(
        f'/games/{game.id}/questions/thermometer/{question_id}/lock-in',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'answerable'
    assert data['seeker_location_end'] is not None


def test_thermometer_full_flow(client: TestClient, session: Session):
    """Ask thermometer → lock-in → answer — full lifecycle."""
    game, hider, seeker = _setup_seeking_game(client, session)

    # Ask thermometer question
    resp = client.post(
        f'/games/{game.id}/questions/thermometer',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    question_id = resp.json()['id']
    assert resp.json()['status'] == 'in_progress'

    # Seeker moves closer to hider and reports location
    _report_location(client, game.id, seeker.client_id, -0.05, 51.3)

    # Lock in
    resp = client.post(
        f'/games/{game.id}/questions/thermometer/{question_id}/lock-in',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    assert resp.json()['status'] == 'answerable'

    # Hider answers
    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'answered'
    assert data['answer'] == 'closer'  # seeker moved closer to hider
    assert data['parameters']['type'] == 'thermometer'
    assert data['parameters']['min_travel'] == 500


def test_lock_in_wrong_status(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    # Ask a radar question (goes straight to answerable, not in_progress)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/thermometer/{question_id}/lock-in',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 409


# ── POST /games/{game_id}/questions/{id}/answer ──────────────────────────────


def test_answer_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
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
    assert data['ask_count'] == 1
    # Detail response has no exclusion fields
    assert 'exclusion' not in data
    assert 'total_exclusion' not in data


def test_answer_question_seeker_forbidden(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
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
    """Summary list returns whitelist fields only — no params, locations, or geometry."""
    game, hider, seeker = _setup_seeking_game(client, session)

    # Ask and answer a question
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']
    client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.client_id),
    )

    # List as seeker — summary only
    resp = client.get(
        f'/games/{game.id}/questions',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    q = data[0]
    # Whitelist fields present
    assert 'id' in q
    assert 'sequence' in q
    assert 'question_type' in q
    assert 'status' in q
    assert 'ask_count' in q
    assert 'asked_by' in q
    assert 'asked_at' in q
    assert 'answer' in q
    # No detail fields
    assert 'parameters' not in q
    assert 'hider_location' not in q
    assert 'seeker_location_start' not in q
    assert 'exclusion' not in q
    assert 'total_exclusion' not in q

    # List as hider — same summary shape
    resp = client.get(
        f'/games/{game.id}/questions',
        headers=_headers(hider.client_id),
    )
    data = resp.json()
    assert 'parameters' not in data[0]
    assert 'hider_location' not in data[0]


# ── GET /games/{game_id}/questions/{question_id} ─────────────────────────────


def test_question_detail_hider_only(client: TestClient, session: Session):
    """Hider can get question detail; seeker gets 403."""
    game, hider, seeker = _setup_seeking_game(client, session)

    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    # Hider can access
    resp = client.get(
        f'/games/{game.id}/questions/{question_id}',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['parameters']['type'] == 'radar'
    assert data['seeker_location_start'] is not None
    assert data['ask_count'] == 1
    # No exclusion fields on detail
    assert 'exclusion' not in data
    assert 'total_exclusion' not in data

    # Seeker gets 403
    resp = client.get(
        f'/games/{game.id}/questions/{question_id}',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 403


# ── GET /games/{game_id}/exclusions ──────────────────────────────────────────


def test_exclusions_seeker_only(client: TestClient, session: Session):
    """Hider gets 403 on /exclusions; seeker gets geometry."""
    game, hider, seeker = _setup_seeking_game(client, session)

    # Ask + answer a question to generate exclusion
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']
    client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.client_id),
    )

    # Hider gets 403
    resp = client.get(
        f'/games/{game.id}/exclusions',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 403

    # Seeker gets exclusion data
    resp = client.get(
        f'/games/{game.id}/exclusions',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data['exclusions']) == 1
    assert data['exclusions'][0]['question_id'] == question_id
    # Exclusion may be None if geometry is empty (seeker outside map boundary)
    assert 'exclusion' in data['exclusions'][0]


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


def _get_matching_slot_index(client: TestClient, game: Game, category: str) -> int:
    """Find the slot_index for a matching slot with the given category."""
    inv = client.get(f'/games/{game.id}/inventory').json()
    for slot in inv['matching_slots']:
        if slot['category'] == category:
            return slot['slot_index']
    raise ValueError(f'No matching slot for category {category}')


def _get_measuring_slot_index(client: TestClient, game: Game, category: str) -> int:
    """Find the slot_index for a measuring slot with the given category."""
    inv = client.get(f'/games/{game.id}/inventory').json()
    for slot in inv['measuring_slots']:
        if slot['category'] == category:
            return slot['slot_index']
    raise ValueError(f'No measuring slot for category {category}')


# ── POST /questions/matching ─────────────────────────────────────────────────


def test_ask_matching_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_feature_game(client, session)
    slot_idx = _get_matching_slot_index(client, game, 'hospital')
    resp = client.post(
        f'/games/{game.id}/questions/matching',
        json={'location': _point(-0.115, 51.499), 'slot_index': slot_idx},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data['question_type'] == 'matching'
    assert data['status'] == 'answerable'
    assert data['ask_count'] == 1
    assert data['parameters']['type'] == 'matching'
    assert data['parameters']['category'] == 'hospital'
    assert data['parameters']['source'] == 'map_data'
    assert data['parameters']['seeker_resolution'] is not None
    assert data['parameters']['seeker_resolution']['feature_id'] == 'hosp_near_seeker'


def test_answer_matching_no(client: TestClient, session: Session):
    """Different nearest hospitals → answer 'no'."""
    game, hider, seeker = _setup_feature_game(client, session)
    slot_idx = _get_matching_slot_index(client, game, 'hospital')
    resp = client.post(
        f'/games/{game.id}/questions/matching',
        json={'location': _point(-0.115, 51.499), 'slot_index': slot_idx},
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

    slot_idx = _get_matching_slot_index(client, game, 'hospital')
    resp = client.post(
        f'/games/{game.id}/questions/matching',
        json={'location': _point(-0.101, 51.501), 'slot_index': slot_idx},
        headers=_headers(seeker.client_id),
    )
    q_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.json()['answer'] == 'yes'


def test_reask_matching_slot(client: TestClient, session: Session):
    """Re-asking the same matching slot increments ask_count."""
    game, hider, seeker = _setup_feature_game(client, session)
    slot_idx = _get_matching_slot_index(client, game, 'hospital')

    # Ask and answer a matching question
    resp = client.post(
        f'/games/{game.id}/questions/matching',
        json={'location': _point(-0.115, 51.499), 'slot_index': slot_idx},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    assert resp.json()['ask_count'] == 1
    q_id = resp.json()['id']
    client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )

    # Re-ask same slot
    resp = client.post(
        f'/games/{game.id}/questions/matching',
        json={'location': _point(-0.115, 51.499), 'slot_index': slot_idx},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    assert resp.json()['ask_count'] == 2


def test_matching_no_feature_on_map(client: TestClient, session: Session):
    """Matching slot_index for a category not on the map → 422 (invalid slot index)."""
    game, hider, seeker = _setup_seeking_game(client, session)
    # No map features → no matching slots exist
    resp = client.post(
        f'/games/{game.id}/questions/matching',
        json={'location': _point(-0.115, 51.499), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 422


def test_matching_consumes_inventory(client: TestClient, session: Session):
    """After asking a matching question, the category appears in the questions list."""
    game, hider, seeker = _setup_feature_game(client, session)
    slot_idx = _get_matching_slot_index(client, game, 'hospital')
    resp = client.post(
        f'/games/{game.id}/questions/matching',
        json={'location': _point(-0.115, 51.499), 'slot_index': slot_idx},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201

    # Verify via question summary list
    resp = client.get(
        f'/games/{game.id}/questions',
        headers=_headers(seeker.client_id),
    )
    assert len(resp.json()) == 1
    assert resp.json()[0]['question_type'] == 'matching'


# ── POST /questions/measuring ────────────────────────────────────────────────


def test_ask_measuring_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_feature_game(client, session)
    slot_idx = _get_measuring_slot_index(client, game, 'hospital')
    resp = client.post(
        f'/games/{game.id}/questions/measuring',
        json={'location': _point(-0.115, 51.499), 'slot_index': slot_idx},
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
    slot_idx = _get_measuring_slot_index(client, game, 'hospital')
    resp = client.post(
        f'/games/{game.id}/questions/measuring',
        json={'location': _point(-0.115, 51.499), 'slot_index': slot_idx},
        headers=_headers(seeker.client_id),
    )
    q_id = resp.json()['id']
    seeker_dist = resp.json()['parameters']['seeker_resolution']['distance']

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )
    data = resp.json()
    hider_dist = data['parameters']['hider_resolution']['distance']
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

    slot_idx = _get_measuring_slot_index(client, game, 'hospital')
    resp = client.post(
        f'/games/{game.id}/questions/measuring',
        json={'location': _point(-0.1001, 51.5001), 'slot_index': slot_idx},
        headers=_headers(seeker.client_id),
    )
    q_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.json()['answer'] == 'closer'


def test_reask_measuring_slot(client: TestClient, session: Session):
    """Re-asking the same measuring slot increments ask_count."""
    game, hider, seeker = _setup_feature_game(client, session)
    slot_idx = _get_measuring_slot_index(client, game, 'hospital')

    resp = client.post(
        f'/games/{game.id}/questions/measuring',
        json={'location': _point(-0.115, 51.499), 'slot_index': slot_idx},
        headers=_headers(seeker.client_id),
    )
    assert resp.json()['ask_count'] == 1
    q_id = resp.json()['id']
    client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )

    resp = client.post(
        f'/games/{game.id}/questions/measuring',
        json={'location': _point(-0.115, 51.499), 'slot_index': slot_idx},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    assert resp.json()['ask_count'] == 2


# ── Exclusion zone integration tests ──────────────────────────────────────────


def test_radar_answer_has_no_exclusion_in_detail(client: TestClient, session: Session):
    """Answered radar question detail response has no exclusion fields."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert 'exclusion' not in data
    assert 'total_exclusion' not in data


def test_exclusions_accumulate(client: TestClient, session: Session):
    """Exclusions endpoint accumulates entries across answered questions."""
    game, hider, seeker = _setup_seeking_game(client, session)

    # Ask + answer first radar question (slot 0)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    q1_id = resp.json()['id']
    client.post(
        f'/games/{game.id}/questions/{q1_id}/answer',
        headers=_headers(hider.client_id),
    )

    resp = client.get(
        f'/games/{game.id}/exclusions',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data['exclusions']) == 1

    # Ask + answer second radar question (slot 1)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.05, 51.52), 'slot_index': 1},
        headers=_headers(seeker.client_id),
    )
    q2_id = resp.json()['id']
    client.post(
        f'/games/{game.id}/questions/{q2_id}/answer',
        headers=_headers(hider.client_id),
    )

    resp = client.get(
        f'/games/{game.id}/exclusions',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data['exclusions']) == 2


# ── Veto tests ────────────────────────────────────────────────────────────────


def test_veto_question(client: TestClient, session: Session):
    """Veto sets status=vetoed, no answer, no hider_location, no exclusion."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/veto',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'vetoed'
    assert data['answer'] is None
    assert data['hider_location'] is None
    assert data['answered_at'] is not None


def test_veto_then_reask(client: TestClient, session: Session):
    """After veto, the same slot can be re-asked with incremented ask_count."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    # Veto
    client.post(
        f'/games/{game.id}/questions/{question_id}/veto',
        headers=_headers(hider.client_id),
    )

    # Re-ask same slot
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    assert resp.json()['ask_count'] == 2
    assert resp.json()['status'] == 'answerable'


def test_veto_non_answerable(client: TestClient, session: Session):
    """Vetoing an already-answered question returns 409."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    # Answer first
    client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.client_id),
    )

    # Try to veto an answered question
    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/veto',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 409


def test_veto_as_seeker(client: TestClient, session: Session):
    """Seekers cannot veto — returns 403."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/veto',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 403


def test_veto_no_exclusion_generated(client: TestClient, session: Session):
    """Vetoed question should not appear in exclusions list."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    client.post(
        f'/games/{game.id}/questions/{question_id}/veto',
        headers=_headers(hider.client_id),
    )

    # Exclusions endpoint should have no entries
    resp = client.get(
        f'/games/{game.id}/exclusions',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    assert len(resp.json()['exclusions']) == 0
    assert resp.json()['total_exclusion'] is None


# ── Scheduled veto tests ──────────────────────────────────────────────────────


def test_scheduled_veto_sets_flag(client: TestClient, session: Session):
    """Calling veto with scheduled=true keeps question answerable and sets the flag."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/veto?scheduled=true',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'answerable'  # NOT vetoed yet
    assert data['answer'] is None
    assert data['answered_at'] is None


def test_scheduled_veto_answer_overrides(client: TestClient, session: Session):
    """Hider can answer normally after scheduling a veto — answer wins."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    # Schedule veto
    client.post(
        f'/games/{game.id}/questions/{question_id}/veto?scheduled=true',
        headers=_headers(hider.client_id),
    )

    # Answer normally — overrides the scheduled veto
    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200
    assert resp.json()['status'] == 'answered'
    assert resp.json()['answer'] is not None


def test_scheduled_veto_immediate_still_works(client: TestClient, session: Session):
    """Calling veto without scheduled flag still vetoes immediately."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/veto',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200
    assert resp.json()['status'] == 'vetoed'


# ── Imperial convention tests ──────────────────────────────────────────────


def _setup_imperial_seeking_game(
    client: TestClient, session: Session
) -> tuple[Game, Player, Player]:
    """Create a seeking game on an imperial map with hider and seeker."""
    gm = create_game_map(session, convention=DistanceConvention.imperial)
    inventory = {
        'radars': [{'distance': 1}],  # 1 mile ≈ 1609 m
        'thermometers': [{'distance': 0.5}],
    }
    game = create_game(
        session,
        map_id=gm.id,
        status=GameStatus.seeking,
        inventory_template=inventory,
    )
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    _report_location(client, game.id, seeker.client_id, -0.1, 51.5)
    _report_location(client, game.id, hider.client_id, 0.0, 51.0)
    return game, hider, seeker


def test_imperial_game_response_convention(client: TestClient, session: Session):
    """GameResponse should include convention='imperial' for imperial maps."""
    game, _, _ = _setup_imperial_seeking_game(client, session)
    resp = client.get(f'/games/{game.id}')
    assert resp.status_code == 200
    assert resp.json()['convention'] == 'imperial'


def test_imperial_radar_stores_miles(client: TestClient, session: Session):
    """Radar params should store the value in miles (convention units)."""
    game, hider, seeker = _setup_imperial_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    assert resp.json()['parameters']['radius'] == 1  # 1 mile


def test_imperial_radar_conversion_for_answer(client: TestClient, session: Session):
    """Imperial radar answer uses converted distance (miles → meters).

    Seeker at (-0.1, 51.5), hider at (-0.1, 51.514). Distance ~1556 m.
    1 mile = 1609 m → hider IS within 1 mile → answer should be 'yes'.
    If conversion didn't happen, 1 (raw) < 1556 (meters) → wrong 'no'.
    """
    gm = create_game_map(session, convention=DistanceConvention.imperial)
    inventory = {'radars': [{'distance': 1}], 'thermometers': []}
    game = create_game(
        session,
        map_id=gm.id,
        status=GameStatus.seeking,
        inventory_template=inventory,
    )
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    _report_location(client, game.id, seeker.client_id, -0.1, 51.5)
    # Hider ~1556 m away (within 1 mile ≈ 1609 m)
    _report_location(client, game.id, hider.client_id, -0.1, 51.514)

    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    q_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200
    assert resp.json()['answer'] == 'yes'


def test_imperial_measuring_distances_in_miles(client: TestClient, session: Session):
    """Measuring question stores seeker/hider distances in miles."""
    gm = create_game_map(session, convention=DistanceConvention.imperial)
    hosp = create_map_feature(
        session,
        name='Hospital',
        stable_id='hosp_imp',
        geometry=Point(-0.1, 51.5),
    )
    create_game_map_feature(session, gm.id, hosp.id)

    inventory = {'radars': [], 'thermometers': []}
    game = create_game(
        session,
        map_id=gm.id,
        status=GameStatus.seeking,
        inventory_template=inventory,
    )
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    # Seeker very close to hospital
    _report_location(client, game.id, seeker.client_id, -0.1001, 51.5001)
    # Hider far from hospital
    _report_location(client, game.id, hider.client_id, -0.2, 51.6)

    slot_idx = _get_measuring_slot_index(client, game, 'hospital')
    resp = client.post(
        f'/games/{game.id}/questions/measuring',
        json={'location': _point(-0.1001, 51.5001), 'slot_index': slot_idx},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    seeker_dist = resp.json()['parameters']['seeker_resolution']['distance']
    # Seeker is ~10-15 meters from hospital → should be a small fraction of a mile
    assert seeker_dist < 0.1  # less than 0.1 miles

    q_id = resp.json()['id']
    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['answer'] == 'closer'  # seeker much closer
    hider_dist = data['parameters']['hider_resolution']['distance']
    # Hider ~8 miles from hospital
    assert hider_dist > 1  # more than 1 mile


# ── Inventory includes matching/measuring slots ──────────────────────────────


def test_inventory_includes_feature_slots(client: TestClient, session: Session):
    """When map has features, inventory includes matching and measuring slots."""
    game, hider, seeker = _setup_feature_game(client, session)
    inv = client.get(f'/games/{game.id}/inventory').json()
    assert len(inv['matching_slots']) > 0
    assert len(inv['measuring_slots']) > 0
    # Hospital should appear in both matching and measuring
    matching_cats = {s['category'] for s in inv['matching_slots']}
    measuring_cats = {s['category'] for s in inv['measuring_slots']}
    assert 'hospital' in matching_cats
    assert 'hospital' in measuring_cats


# ── POST /games/{game_id}/questions/{question_id}/abandon ─────────────────────


def test_abandon_answerable_question(client: TestClient, session: Session):
    """Seeker can abandon an answerable question — status becomes abandoned."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/abandon',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'abandoned'
    assert data['answer'] is None
    assert data['hider_location'] is None
    assert data['answered_at'] is not None


def test_abandon_in_progress_thermometer(client: TestClient, session: Session):
    """Seeker can abandon an in_progress thermometer before lock-in."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/thermometer',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.json()['status'] == 'in_progress'
    question_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/abandon',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    assert resp.json()['status'] == 'abandoned'


def test_abandon_as_hider_forbidden(client: TestClient, session: Session):
    """Hider cannot abandon — returns 403."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/abandon',
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 403


def test_abandon_already_answered(client: TestClient, session: Session):
    """Cannot abandon an already-answered question — returns 409."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    # Answer first
    client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.client_id),
    )

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/abandon',
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 409


def test_abandon_then_reask(client: TestClient, session: Session):
    """After abandon, seeker can ask a new question (not blocked by one-at-a-time rule)."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    question_id = resp.json()['id']

    client.post(
        f'/games/{game.id}/questions/{question_id}/abandon',
        headers=_headers(seeker.client_id),
    )

    # Should be able to ask a new question
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 201
    assert resp.json()['ask_count'] == 2
