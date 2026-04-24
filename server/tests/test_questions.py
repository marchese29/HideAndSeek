from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hideandseek_core.db import get_session
from hideandseek_models.game import Game, Player
from hideandseek_models.inventory import InventorySlot
from hideandseek_models.question import Question
from hideandseek_models.types import (
    DistanceConvention,
    FeatureCategory,
    GameStatus,
    PhotoSubject,
    PlayerRole,
    QuestionStatus,
    QuestionType,
)
from tests.conftest import (
    TEST_SECRET,
    create_game,
    create_game_map,
    create_game_map_feature,
    create_map_feature,
    create_player,
)


def _headers(player_id: uuid.UUID) -> dict[str, str]:
    return {'X-Player-Id': str(player_id), 'X-Player-Secret': TEST_SECRET}


def _point(lng: float = -0.141, lat: float = 51.515) -> dict:
    return {'type': 'Point', 'coordinates': [lng, lat]}


def _report_location(
    client: TestClient,
    game_id: uuid.UUID,
    player_id: uuid.UUID,
    lng: float = -0.141,
    lat: float = 51.515,
):
    """Helper to report a location for a player."""
    client.post(
        f'/games/{game_id}/location',
        json={'coordinates': _point(lng, lat), 'timestamp': '2026-02-11T10:00:00Z'},
        headers=_headers(player_id),
    )


def _setup_seeking_game(client: TestClient, session: Session) -> tuple[Game, Player, Player]:
    """Create a seeking game with a hider and seeker, both with reported locations."""
    game = create_game(session, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    _report_location(client, game.id, seeker.id, -0.1, 51.5)
    _report_location(client, game.id, hider.id, 0.0, 51.0)
    return game, hider, seeker


def _ask_question(
    client: TestClient,
    game_id: uuid.UUID,
    seeker_id: uuid.UUID,
    question_type: str = 'radar',
    slot_index: int = 0,
    lng: float = -0.1,
    lat: float = 51.5,
    custom_distance: float | None = None,
) -> uuid.UUID:
    """Ask a question and return its ID from the DB."""
    body: dict = {'location': _point(lng, lat), 'slot_index': slot_index}
    if custom_distance is not None:
        body['custom_distance'] = custom_distance
    resp = client.post(
        f'/games/{game_id}/questions/{question_type}',
        json=body,
        headers=_headers(seeker_id),
    )
    assert resp.status_code == 204

    session = get_session()
    question = session.scalars(
        select(Question).where(Question.game_id == game_id).order_by(Question.sequence.desc())
    ).first()
    assert question is not None
    return question.id


def _get_latest_question(game_id: uuid.UUID) -> Question:
    """Return the most recent question for a game from the DB."""
    session = get_session()
    question = session.scalars(
        select(Question).where(Question.game_id == game_id).order_by(Question.sequence.desc())
    ).first()
    assert question is not None
    return question


def _get_question_by_id(question_id: uuid.UUID) -> Question:
    """Return a question by ID from the DB, with param relationships loaded."""
    session = get_session()
    question = session.get(Question, question_id)
    assert question is not None
    return question


# ── POST /games/{game_id}/questions/radar ────────────────────────────────────


def test_ask_radar_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204


def test_ask_custom_slot_requires_distance(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    # slot_index 2 is the custom radar slot (distance: null)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 2},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 422
    assert 'custom_distance' in resp.json()['detail']


def test_ask_custom_slot_with_distance(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 2, 'custom_distance': 4000},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204


def test_ask_question_deducts_slot(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    q_id = _ask_question(client, game.id, seeker.id)
    client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.id),
    )
    game_resp = client.get(f'/games/{game.id}')
    radar_slots = game_resp.json()['inventory']['radar_slots']
    assert len(radar_slots) == 3
    assert radar_slots[0]['ask_count'] == 1


def test_ask_question_invalid_slot_index(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 99},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 422


def test_ask_question_not_seeking(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.lobby)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 409


def test_ask_question_hider_forbidden(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 403


def test_ask_question_while_unanswered(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    # Ask first question
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204

    # Try to ask another while first is unanswered
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 409
    assert 'unanswered' in resp.json()['detail']


def test_reask_radar_slot(client: TestClient, session: Session):
    """Re-asking the same radar slot increments ask_count."""
    game, hider, seeker = _setup_seeking_game(client, session)
    q1_id = _ask_question(client, game.id, seeker.id)
    client.post(
        f'/games/{game.id}/questions/{q1_id}/answer',
        headers=_headers(hider.id),
    )
    _ask_question(client, game.id, seeker.id)
    q2 = _get_latest_question(game.id)
    assert q2.ask_count == 2


# ── POST /games/{game_id}/questions/thermometer ──────────────────────────────


def test_ask_thermometer_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/thermometer',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204


# ── POST /games/{game_id}/questions/thermometer/{id}/lock-in ─────────────────


def test_lock_in_thermometer(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id, question_type='thermometer')

    # Report a new seeker location (simulates travel)
    _report_location(client, game.id, seeker.id, 0.1, 51.6)

    resp = client.post(
        f'/games/{game.id}/questions/thermometer/{question_id}/lock-in',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204


def test_thermometer_full_flow(client: TestClient, session: Session):
    """Ask thermometer → lock-in → answer — full lifecycle."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id, question_type='thermometer')

    _report_location(client, game.id, seeker.id, -0.05, 51.3)

    resp = client.post(
        f'/games/{game.id}/questions/thermometer/{question_id}/lock-in',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    # Verify via DB
    question = _get_latest_question(game.id)
    assert question.status == QuestionStatus.answered
    assert question.answer == 'closer'
    assert question.thermometer_params is not None
    assert question.thermometer_params.min_travel == 500


def test_lock_in_wrong_status(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    # Ask a radar question (goes straight to answerable, not in_progress)
    question_id = _ask_question(client, game.id, seeker.id)

    resp = client.post(
        f'/games/{game.id}/questions/thermometer/{question_id}/lock-in',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 409


# ── POST /games/{game_id}/questions/{id}/answer ──────────────────────────────


def test_answer_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    # Verify via DB
    q = _get_question_by_id(question_id)
    assert q.status == QuestionStatus.answered
    assert q.hider_location is not None
    assert q.answer == 'no'
    assert q.answered_at is not None
    assert q.ask_count == 1


def test_answer_question_seeker_forbidden(client: TestClient, session: Session):
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 403


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
        shape=Point(-0.117, 51.498),
    )
    near_hider = create_map_feature(
        session,
        name='Near Hider Hospital',
        stable_id='hosp_near_hider',
        shape=Point(-0.059, 51.518),
    )
    create_game_map_feature(session, gm.id, near_seeker.id)
    create_game_map_feature(session, gm.id, near_hider.id)

    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    _report_location(client, game.id, seeker.id, -0.115, 51.499)
    _report_location(client, game.id, hider.id, -0.06, 51.519)
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
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204


def test_answer_matching_no(client: TestClient, session: Session):
    """Different nearest hospitals → answer 'no'."""
    game, hider, seeker = _setup_feature_game(client, session)
    slot_idx = _get_matching_slot_index(client, game, 'hospital')
    q_id = _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='matching',
        slot_index=slot_idx,
        lng=-0.115,
        lat=51.499,
    )

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    q = _get_question_by_id(q_id)
    assert q.answer == 'no'
    assert q.feature_params is not None
    assert q.feature_params.hider_feature_id == 'hosp_near_hider'


def test_answer_matching_yes(client: TestClient, session: Session):
    """Both players near the same hospital → answer 'yes'."""
    gm = create_game_map(session)
    hosp = create_map_feature(
        session,
        name='Shared Hospital',
        stable_id='hosp_shared',
        shape=Point(-0.1, 51.5),
    )
    create_game_map_feature(session, gm.id, hosp.id)

    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    # Both near the same hospital
    _report_location(client, game.id, seeker.id, -0.101, 51.501)
    _report_location(client, game.id, hider.id, -0.099, 51.499)

    slot_idx = _get_matching_slot_index(client, game, 'hospital')
    q_id = _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='matching',
        slot_index=slot_idx,
        lng=-0.101,
        lat=51.501,
    )

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    assert _get_question_by_id(q_id).answer == 'yes'


def test_reask_matching_slot(client: TestClient, session: Session):
    """Re-asking the same matching slot increments ask_count."""
    game, hider, seeker = _setup_feature_game(client, session)
    slot_idx = _get_matching_slot_index(client, game, 'hospital')
    q1_id = _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='matching',
        slot_index=slot_idx,
        lng=-0.115,
        lat=51.499,
    )
    client.post(f'/games/{game.id}/questions/{q1_id}/answer', headers=_headers(hider.id))
    _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='matching',
        slot_index=slot_idx,
        lng=-0.115,
        lat=51.499,
    )
    assert _get_latest_question(game.id).ask_count == 2


def test_matching_no_feature_on_map(client: TestClient, session: Session):
    """Matching slot_index for a category not on the map → 422 (invalid slot index)."""
    game, hider, seeker = _setup_seeking_game(client, session)
    # No map features → no matching slots exist
    resp = client.post(
        f'/games/{game.id}/questions/matching',
        json={'location': _point(-0.115, 51.499), 'slot_index': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 422


def test_matching_consumes_inventory(client: TestClient, session: Session):
    """After asking a matching question, the category appears in the questions list."""
    game, hider, seeker = _setup_feature_game(client, session)
    slot_idx = _get_matching_slot_index(client, game, 'hospital')
    resp = client.post(
        f'/games/{game.id}/questions/matching',
        json={'location': _point(-0.115, 51.499), 'slot_index': slot_idx},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204

    # Verify via DB
    latest = _get_latest_question(game.id)
    assert latest.question_type == QuestionType.matching


# ── POST /questions/measuring ────────────────────────────────────────────────


def test_ask_measuring_question(client: TestClient, session: Session):
    game, hider, seeker = _setup_feature_game(client, session)
    slot_idx = _get_measuring_slot_index(client, game, 'hospital')
    resp = client.post(
        f'/games/{game.id}/questions/measuring',
        json={'location': _point(-0.115, 51.499), 'slot_index': slot_idx},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204


def test_answer_measuring_farther(client: TestClient, session: Session):
    """Seeker farther from nearest hospital than hider → 'farther'."""
    game, hider, seeker = _setup_feature_game(client, session)
    slot_idx = _get_measuring_slot_index(client, game, 'hospital')
    q_id = _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='measuring',
        slot_index=slot_idx,
        lng=-0.115,
        lat=51.499,
    )

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    q = _get_question_by_id(q_id)
    assert q.answer == 'farther'
    assert q.feature_params is not None
    assert q.feature_params.hider_distance is not None
    assert q.feature_params.seeker_distance > q.feature_params.hider_distance


def test_answer_measuring_closer(client: TestClient, session: Session):
    """Seeker closer to nearest hospital than hider → 'closer'."""
    gm = create_game_map(session)
    hosp = create_map_feature(
        session,
        name='Central Hospital',
        stable_id='hosp_central',
        shape=Point(-0.1, 51.5),
    )
    create_game_map_feature(session, gm.id, hosp.id)

    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    # Seeker very close, hider far
    _report_location(client, game.id, seeker.id, -0.1001, 51.5001)
    _report_location(client, game.id, hider.id, -0.2, 51.6)

    slot_idx = _get_measuring_slot_index(client, game, 'hospital')
    q_id = _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='measuring',
        slot_index=slot_idx,
        lng=-0.1001,
        lat=51.5001,
    )

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    assert _get_question_by_id(q_id).answer == 'closer'


def test_reask_measuring_slot(client: TestClient, session: Session):
    """Re-asking the same measuring slot increments ask_count."""
    game, hider, seeker = _setup_feature_game(client, session)
    slot_idx = _get_measuring_slot_index(client, game, 'hospital')

    q1_id = _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='measuring',
        slot_index=slot_idx,
        lng=-0.115,
        lat=51.499,
    )
    client.post(
        f'/games/{game.id}/questions/{q1_id}/answer',
        headers=_headers(hider.id),
    )

    _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='measuring',
        slot_index=slot_idx,
        lng=-0.115,
        lat=51.499,
    )
    assert _get_latest_question(game.id).ask_count == 2


# ── Exclusion zone integration tests ──────────────────────────────────────────


# ── Veto tests ────────────────────────────────────────────────────────────────


def test_veto_question(client: TestClient, session: Session):
    """Veto sets status=vetoed, no answer, no hider_location, no exclusion."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/veto',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    q = _get_question_by_id(question_id)
    assert q.status == QuestionStatus.vetoed
    assert q.answer is None
    assert q.hider_location is None
    assert q.answered_at is not None


def test_veto_then_reask(client: TestClient, session: Session):
    """After veto, the same slot can be re-asked with incremented ask_count."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)
    client.post(
        f'/games/{game.id}/questions/{question_id}/veto',
        headers=_headers(hider.id),
    )
    _ask_question(client, game.id, seeker.id)
    latest = _get_latest_question(game.id)
    assert latest.ask_count == 2
    assert latest.status == QuestionStatus.answerable


def test_veto_non_answerable(client: TestClient, session: Session):
    """Vetoing an already-answered question returns 409."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    # Answer first
    client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.id),
    )

    # Try to veto an answered question
    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/veto',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 409


def test_veto_as_seeker(client: TestClient, session: Session):
    """Seekers cannot veto — returns 403."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/veto',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 403


# ── Scheduled veto tests ──────────────────────────────────────────────────────


def test_scheduled_veto_sets_flag(client: TestClient, session: Session):
    """Calling veto with scheduled=true keeps question answerable and sets the flag."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/veto?scheduled=true',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    q = _get_question_by_id(question_id)
    assert q.status == QuestionStatus.answerable
    assert q.answer is None
    assert q.answered_at is None


def test_scheduled_veto_answer_overrides(client: TestClient, session: Session):
    """Hider can answer normally after scheduling a veto — answer wins."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)
    client.post(
        f'/games/{game.id}/questions/{question_id}/veto?scheduled=true',
        headers=_headers(hider.id),
    )
    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    q = _get_question_by_id(question_id)
    assert q.status == QuestionStatus.answered
    assert q.answer is not None


def test_scheduled_veto_immediate_still_works(client: TestClient, session: Session):
    """Calling veto without scheduled flag still vetoes immediately."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/veto',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    assert _get_question_by_id(question_id).status == QuestionStatus.vetoed


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
    _report_location(client, game.id, seeker.id, -0.1, 51.5)
    _report_location(client, game.id, hider.id, 0.0, 51.0)
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
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204

    # Verify via DB
    q = _get_latest_question(game.id)
    assert q.radar_params is not None
    assert q.radar_params.radius == 1  # 1 mile


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
    _report_location(client, game.id, seeker.id, -0.1, 51.5)
    # Hider ~1556 m away (within 1 mile ≈ 1609 m)
    _report_location(client, game.id, hider.id, -0.1, 51.514)

    q_id = _ask_question(client, game.id, seeker.id)

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    assert _get_question_by_id(q_id).answer == 'yes'


def test_imperial_measuring_distances_in_miles(client: TestClient, session: Session):
    """Measuring question stores seeker/hider distances in miles."""
    gm = create_game_map(session, convention=DistanceConvention.imperial)
    hosp = create_map_feature(
        session,
        name='Hospital',
        stable_id='hosp_imp',
        shape=Point(-0.1, 51.5),
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
    _report_location(client, game.id, seeker.id, -0.1001, 51.5001)
    # Hider far from hospital
    _report_location(client, game.id, hider.id, -0.2, 51.6)

    slot_idx = _get_measuring_slot_index(client, game, 'hospital')
    q_id = _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='measuring',
        slot_index=slot_idx,
        lng=-0.1001,
        lat=51.5001,
    )

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    q = _get_question_by_id(q_id)
    assert q.answer == 'closer'  # seeker much closer
    assert q.feature_params is not None
    assert q.feature_params.hider_distance is not None
    # Seeker is ~10-15 meters from hospital → should be a small fraction of a mile
    assert q.feature_params.seeker_distance < 0.1  # less than 0.1 miles
    # Hider ~8 miles from hospital
    assert q.feature_params.hider_distance > 1  # more than 1 mile


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


def test_tentacles_inventory_slots_created(client: TestClient, session: Session):
    """When map has tentacle_categories, inventory includes tentacles slots."""
    gm = create_game_map(
        session,
        tentacle_categories=[
            {'category': 'museum', 'distance': 2000},
            {'category': 'hospital', 'distance': 3000},
        ],
    )
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    inv = client.get(
        f'/games/{game.id}/inventory',
        headers=_headers(game.host_player_id),
    ).json()
    slots = inv['tentacles_slots']
    assert len(slots) == 2
    # Sorted by category: hospital < museum
    assert slots[0]['category'] == 'hospital'
    assert slots[0]['distance'] == 3000
    assert slots[1]['category'] == 'museum'
    assert slots[1]['distance'] == 2000


# ── Tentacles helpers ────────────────────────────────────────────────────────


def _setup_tentacles_game(client: TestClient, session: Session) -> tuple[Game, Player, Player, int]:
    """Create a seeking game with tentacles config and two POIs within the circle.

    Map boundary is (0,0)→(1,1). Museum POIs at (0.3, 0.3) and (0.7, 0.7).
    Tentacle distance is 200000m (~200km), large enough to cover the map.
    Seeker at (0.5, 0.5), hider at (0.31, 0.31) — near museum_a.
    Returns (game, hider, seeker, tentacles_slot_index).
    """
    gm = create_game_map(
        session,
        tentacle_categories=[{'category': 'museum', 'distance': 200000}],
    )
    museum_a = create_map_feature(
        session,
        name='Museum A',
        stable_id='museum_a',
        category=FeatureCategory.museum,
        shape=Point(0.3, 0.3),
    )
    museum_b = create_map_feature(
        session,
        name='Museum B',
        stable_id='museum_b',
        category=FeatureCategory.museum,
        shape=Point(0.7, 0.7),
    )
    create_game_map_feature(session, gm.id, museum_a.id)
    create_game_map_feature(session, gm.id, museum_b.id)

    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    _report_location(client, game.id, seeker.id, 0.5, 0.5)
    _report_location(client, game.id, hider.id, 0.31, 0.31)

    inv = client.get(f'/games/{game.id}/inventory', headers=_headers(seeker.id)).json()
    slot_idx = inv['tentacles_slots'][0]['slot_index']
    return game, hider, seeker, slot_idx


# ── POST /questions/tentacles ────────────────────────────────────────────────


def test_ask_tentacles_creates_question(client: TestClient, session: Session):
    """Asking a tentacles question creates a question with correct params."""
    game, hider, seeker, slot_idx = _setup_tentacles_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/tentacles',
        json={'location': _point(0.5, 0.5), 'slot_index': slot_idx},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204

    q = _get_latest_question(game.id)
    assert q.question_type == QuestionType.tentacles
    assert q.status == QuestionStatus.answerable
    assert q.tentacle_params is not None
    assert set(q.tentacle_params.poi_ids) == {'museum_a', 'museum_b'}


def test_answer_tentacles_hit(client: TestClient, session: Session):
    """Hider near museum_a → answer is 'museum_a', hit=True."""
    game, hider, seeker, slot_idx = _setup_tentacles_game(client, session)
    q_id = _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='tentacles',
        slot_index=slot_idx,
        lng=0.5,
        lat=0.5,
    )

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    q = _get_question_by_id(q_id)
    assert q.answer == 'museum_a'
    assert q.tentacle_params is not None
    assert q.tentacle_params.hit is True
    assert q.tentacle_params.hider_feature_id == 'museum_a'
    assert q.exclusion is not None
    assert q.total_exclusion is not None


def test_answer_tentacles_miss(client: TestClient, session: Session):
    """Hider far away → answer is 'miss', hit=False."""
    # Use a small tentacle distance so hider is outside the circle
    gm = create_game_map(
        session,
        tentacle_categories=[{'category': 'museum', 'distance': 100}],
    )
    museum = create_map_feature(
        session,
        name='Museum',
        stable_id='museum_far',
        category=FeatureCategory.museum,
        shape=Point(0.5, 0.5),
    )
    create_game_map_feature(session, gm.id, museum.id)

    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    _report_location(client, game.id, seeker.id, 0.5, 0.5)
    _report_location(client, game.id, hider.id, 0.9, 0.9)

    inv = client.get(f'/games/{game.id}/inventory', headers=_headers(seeker.id)).json()
    slot_idx = inv['tentacles_slots'][0]['slot_index']

    q_id = _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='tentacles',
        slot_index=slot_idx,
        lng=0.5,
        lat=0.5,
    )

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    q = _get_question_by_id(q_id)
    assert q.answer == 'miss'
    assert q.tentacle_params is not None
    assert q.tentacle_params.hit is False
    assert q.exclusion is not None


def test_answer_tentacles_empty_pois_is_miss(client: TestClient, session: Session):
    """Zero POIs in circle → guaranteed miss."""
    # Tentacle category configured but no features on the map for it
    gm = create_game_map(
        session,
        tentacle_categories=[{'category': 'museum', 'distance': 200000}],
    )
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    _report_location(client, game.id, seeker.id, 0.5, 0.5)
    _report_location(client, game.id, hider.id, 0.5, 0.5)

    inv = client.get(f'/games/{game.id}/inventory', headers=_headers(seeker.id)).json()
    slot_idx = inv['tentacles_slots'][0]['slot_index']

    q_id = _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='tentacles',
        slot_index=slot_idx,
        lng=0.5,
        lat=0.5,
    )

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    q = _get_question_by_id(q_id)
    assert q.answer == 'miss'
    assert q.tentacle_params is not None
    assert q.tentacle_params.hit is False
    assert q.tentacle_params.poi_ids == []


def test_veto_tentacles(client: TestClient, session: Session):
    """Hider can veto a tentacles question."""
    game, hider, seeker, slot_idx = _setup_tentacles_game(client, session)
    q_id = _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='tentacles',
        slot_index=slot_idx,
        lng=0.5,
        lat=0.5,
    )

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/veto',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204
    assert _get_question_by_id(q_id).status == QuestionStatus.vetoed


def test_abandon_tentacles(client: TestClient, session: Session):
    """Seeker can abandon a tentacles question."""
    game, hider, seeker, slot_idx = _setup_tentacles_game(client, session)
    q_id = _ask_question(
        client,
        game.id,
        seeker.id,
        question_type='tentacles',
        slot_index=slot_idx,
        lng=0.5,
        lat=0.5,
    )

    resp = client.post(
        f'/games/{game.id}/questions/{q_id}/abandon',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204
    assert _get_question_by_id(q_id).status == QuestionStatus.abandoned


# ── POST /games/{game_id}/questions/{question_id}/abandon ─────────────────────


def test_abandon_answerable_question(client: TestClient, session: Session):
    """Seeker can abandon an answerable question — status becomes abandoned."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/abandon',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204

    q = _get_question_by_id(question_id)
    assert q.status == QuestionStatus.abandoned
    assert q.answer is None
    assert q.hider_location is None
    assert q.answered_at is not None


def test_abandon_in_progress_thermometer(client: TestClient, session: Session):
    """Seeker can abandon an in_progress thermometer before lock-in."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id, question_type='thermometer')

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/abandon',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204

    assert _get_latest_question(game.id).status == QuestionStatus.abandoned


def test_abandon_as_hider_forbidden(client: TestClient, session: Session):
    """Hider cannot abandon — returns 403."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/abandon',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 403


def test_abandon_already_answered(client: TestClient, session: Session):
    """Cannot abandon an already-answered question — returns 409."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    # Answer first
    client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.id),
    )

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/abandon',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 409


def test_abandon_then_reask(client: TestClient, session: Session):
    """After abandon, seeker can ask a new question (not blocked by one-at-a-time rule)."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    client.post(
        f'/games/{game.id}/questions/{question_id}/abandon',
        headers=_headers(seeker.id),
    )

    # Should be able to ask a new question
    _ask_question(client, game.id, seeker.id)
    assert _get_latest_question(game.id).ask_count == 2


# ── GET /games/{game_id}/questions/preview ���─────────────────────────────────


def test_preview_radar(client: TestClient, session: Session):
    """Radar preview returns a boundary geometry."""
    game, hider, seeker = _setup_seeking_game(client, session)
    # Use coords inside the game map boundary (0,0)→(1,1)
    resp = client.get(
        f'/games/{game.id}/questions/preview',
        params={'question_type': 'radar', 'slot_index': 0, 'lat': 0.5, 'lng': 0.5},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['boundary'] is not None
    assert data['boundary']['type'] in ('LineString', 'MultiLineString', 'Polygon')
    assert data['feature_preview'] is None


def test_preview_radar_custom_slot(client: TestClient, session: Session):
    """Custom radar slot requires custom_distance."""
    game, hider, seeker = _setup_seeking_game(client, session)
    # Find the custom slot (last radar slot, distance=null)
    inv = client.get(f'/games/{game.id}/inventory').json()
    custom_idx = None
    for slot in inv['radar_slots']:
        if slot['distance'] is None:
            custom_idx = slot['slot_index']
    assert custom_idx is not None

    # Without custom_distance → 422
    resp = client.get(
        f'/games/{game.id}/questions/preview',
        params={'question_type': 'radar', 'slot_index': custom_idx, 'lat': 0.5, 'lng': 0.5},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 422

    # With custom_distance → 200
    resp = client.get(
        f'/games/{game.id}/questions/preview',
        params={
            'question_type': 'radar',
            'slot_index': custom_idx,
            'lat': 0.5,
            'lng': 0.5,
            'custom_distance': 5000,
        },
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 200


def test_preview_thermometer(client: TestClient, session: Session):
    """Thermometer preview returns a bisector line."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.get(
        f'/games/{game.id}/questions/preview',
        params={
            'question_type': 'thermometer',
            'slot_index': 0,
            'lat': 0.4,
            'lng': 0.4,
            'end_lat': 0.6,
            'end_lng': 0.6,
        },
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['boundary']['type'] in ('LineString', 'MultiLineString', 'Polygon')
    assert data['feature_preview'] is None


def test_preview_thermometer_missing_end(client: TestClient, session: Session):
    """Thermometer preview without end coords returns 422."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.get(
        f'/games/{game.id}/questions/preview',
        params={'question_type': 'thermometer', 'slot_index': 0, 'lat': 0.5, 'lng': 0.5},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 422


def _setup_feature_preview_game(
    client: TestClient, session: Session
) -> tuple[Game, Player, Player]:
    """Create a seeking game with features inside the default game map boundary.

    Default game map is (0,0)→(1,1). Features at (0.2, 0.2) and (0.8, 0.8).
    Seeker at (0.3, 0.3) — close to but not on top of feature A.
    """
    gm = create_game_map(session)
    feat_a = create_map_feature(
        session, name='Hospital A', stable_id='hosp_a', shape=Point(0.2, 0.2)
    )
    feat_b = create_map_feature(
        session, name='Hospital B', stable_id='hosp_b', shape=Point(0.8, 0.8)
    )
    create_game_map_feature(session, gm.id, feat_a.id)
    create_game_map_feature(session, gm.id, feat_b.id)

    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    _report_location(client, game.id, seeker.id, 0.3, 0.3)
    _report_location(client, game.id, hider.id, 0.7, 0.7)
    return game, hider, seeker


def test_preview_matching(client: TestClient, session: Session):
    """Matching preview returns boundary + feature_preview."""
    game, hider, seeker = _setup_feature_preview_game(client, session)
    slot_idx = _get_matching_slot_index(client, game, 'hospital')
    resp = client.get(
        f'/games/{game.id}/questions/preview',
        params={
            'question_type': 'matching',
            'slot_index': slot_idx,
            'lat': 0.3,
            'lng': 0.3,
        },
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['boundary'] is not None
    assert data['feature_preview'] is not None
    assert 'feature_id' in data['feature_preview']
    assert 'name' in data['feature_preview']
    assert 'distance' in data['feature_preview']


def test_preview_measuring(client: TestClient, session: Session):
    """Measuring preview returns boundary + feature_preview."""
    game, hider, seeker = _setup_feature_preview_game(client, session)
    slot_idx = _get_measuring_slot_index(client, game, 'hospital')
    resp = client.get(
        f'/games/{game.id}/questions/preview',
        params={
            'question_type': 'measuring',
            'slot_index': slot_idx,
            'lat': 0.3,
            'lng': 0.3,
        },
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['boundary'] is not None
    assert data['feature_preview'] is not None


def test_preview_tentacles(client: TestClient, session: Session):
    """Tentacles preview returns boundary + tentacle_pois."""
    gm = create_game_map(
        session,
        tentacle_categories=[{'category': 'museum', 'distance': 200000}],
    )
    feat_a = create_map_feature(
        session,
        name='Museum A',
        stable_id='mus_a',
        category=FeatureCategory.museum,
        shape=Point(0.3, 0.3),
    )
    feat_b = create_map_feature(
        session,
        name='Museum B',
        stable_id='mus_b',
        category=FeatureCategory.museum,
        shape=Point(0.7, 0.7),
    )
    create_game_map_feature(session, gm.id, feat_a.id)
    create_game_map_feature(session, gm.id, feat_b.id)

    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    _report_location(client, game.id, seeker.id, 0.5, 0.5)

    inv = client.get(f'/games/{game.id}/inventory', headers=_headers(seeker.id)).json()
    slot_idx = inv['tentacles_slots'][0]['slot_index']

    resp = client.get(
        f'/games/{game.id}/questions/preview',
        params={'question_type': 'tentacles', 'slot_index': slot_idx, 'lat': 0.5, 'lng': 0.5},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['boundary'] is not None
    assert data['feature_preview'] is None
    assert data['tentacle_pois'] is not None
    assert len(data['tentacle_pois']) == 2
    poi_ids = {p['feature_id'] for p in data['tentacle_pois']}
    assert poi_ids == {'mus_a', 'mus_b'}


def test_preview_tentacles_empty(client: TestClient, session: Session):
    """Tentacles preview with no POIs in range returns empty tentacle_pois."""
    gm = create_game_map(
        session,
        tentacle_categories=[{'category': 'museum', 'distance': 1}],
    )
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    _report_location(client, game.id, seeker.id, 0.5, 0.5)

    inv = client.get(f'/games/{game.id}/inventory', headers=_headers(seeker.id)).json()
    slot_idx = inv['tentacles_slots'][0]['slot_index']

    resp = client.get(
        f'/games/{game.id}/questions/preview',
        params={'question_type': 'tentacles', 'slot_index': slot_idx, 'lat': 0.5, 'lng': 0.5},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['tentacle_pois'] == []


def test_preview_either_role(client: TestClient, session: Session):
    """Both hider and seeker can call the preview endpoint."""
    game, hider, seeker = _setup_seeking_game(client, session)
    params = {'question_type': 'radar', 'slot_index': 0, 'lat': 0.5, 'lng': 0.5}

    resp_seeker = client.get(
        f'/games/{game.id}/questions/preview', params=params, headers=_headers(seeker.id)
    )
    resp_hider = client.get(
        f'/games/{game.id}/questions/preview', params=params, headers=_headers(hider.id)
    )
    assert resp_seeker.status_code == 200
    assert resp_hider.status_code == 200


def test_preview_invalid_slot(client: TestClient, session: Session):
    """Invalid slot_index returns 422."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.get(
        f'/games/{game.id}/questions/preview',
        params={'question_type': 'radar', 'slot_index': 999, 'lat': 0.5, 'lng': 0.5},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 422


def test_preview_no_side_effects(client: TestClient, session: Session):
    """Preview does not create questions or mutate inventory."""
    game, hider, seeker = _setup_seeking_game(client, session)

    session_db = get_session()
    count_stmt = select(func.count()).select_from(Question).where(Question.game_id == game.id)
    q_count_before = session_db.scalar(count_stmt)

    client.get(
        f'/games/{game.id}/questions/preview',
        params={'question_type': 'radar', 'slot_index': 0, 'lat': 0.5, 'lng': 0.5},
        headers=_headers(seeker.id),
    )

    q_count_after = session_db.scalar(count_stmt)
    assert q_count_before == q_count_after


# ── Randomize tests ──────────────────────────────────────────────────────────


def test_randomize_radar_question(client: TestClient, session: Session):
    """Randomize terminates original, creates replacement, restores original slot ask_count."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id, question_type='radar', slot_index=0)

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/randomize',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    # Original question is now randomized
    original = _get_question_by_id(question_id)
    assert original.status == QuestionStatus.randomized
    assert original.answered_at is not None

    # A new replacement question was created
    replacement = _get_latest_question(game.id)
    assert replacement.id != question_id
    assert replacement.question_type == QuestionType.radar
    assert replacement.status == QuestionStatus.answerable
    assert replacement.asked_by == seeker.id  # Seeker is still the asker


def test_randomize_restores_original_slot(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
):
    """Randomize decrements the original slot's ask_count back to 0."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id, question_type='radar', slot_index=1)

    # Before randomize: slot 1 should have ask_count=1
    db = get_session()
    slot = db.scalars(
        select(InventorySlot).where(
            InventorySlot.game == game,
            InventorySlot.question_type == QuestionType.radar,
            InventorySlot.slot_index == 1,
        )
    ).one()
    assert slot.ask_count == 1

    # Force random.choice to pick the first element so the replacement is
    # deterministic and never re-picks slot 1 (slot 0 will be first eligible).
    monkeypatch.setattr('hideandseek_core.logic.ask.random.choice', lambda seq: seq[0])

    client.post(
        f'/games/{game.id}/questions/{question_id}/randomize',
        headers=_headers(hider.id),
    )

    db.refresh(slot)
    assert slot.ask_count == 0


def test_randomize_seeker_forbidden(client: TestClient, session: Session):
    """Seekers cannot randomize — returns 403."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/randomize',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 403


def test_randomize_non_answerable(client: TestClient, session: Session):
    """Randomizing an already-answered question returns 409."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id)

    # Answer first
    client.post(
        f'/games/{game.id}/questions/{question_id}/answer',
        headers=_headers(hider.id),
    )

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/randomize',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 409


def test_randomize_no_eligible_slots(client: TestClient, session: Session):
    """If all same-type slots have ask_count > 0, randomize returns 409."""
    game, hider, seeker = _setup_seeking_game(client, session)

    # Ask all 3 radar slots, then veto each (so ask_count > 0 on all)
    for slot_idx in range(3):
        qid = _ask_question(
            client,
            game.id,
            seeker.id,
            question_type='radar',
            slot_index=slot_idx,
            custom_distance=1.0 if slot_idx == 2 else None,
        )
        client.post(
            f'/games/{game.id}/questions/{qid}/veto',
            headers=_headers(hider.id),
        )

    # Ask slot 0 again (ask_count=2)
    question_id = _ask_question(client, game.id, seeker.id, question_type='radar', slot_index=0)

    # All slots now have ask_count > 0; randomize should fail
    # (slot 0 will be restored to ask_count=1 during randomize check,
    #  but we check eligibility before calling randomize_question)
    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/randomize',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 409


def test_randomize_then_answer_replacement(client: TestClient, session: Session):
    """After randomize, the hider can answer the replacement question."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id, question_type='radar', slot_index=0)

    client.post(
        f'/games/{game.id}/questions/{question_id}/randomize',
        headers=_headers(hider.id),
    )

    replacement = _get_latest_question(game.id)
    resp = client.post(
        f'/games/{game.id}/questions/{replacement.id}/answer',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204
    db = get_session()
    db.refresh(replacement)
    assert replacement.status == QuestionStatus.answered


def test_randomize_thermometer_starts_in_progress(client: TestClient, session: Session):
    """Thermometer replacement starts in in_progress — seeker must travel again."""
    game, hider, seeker = _setup_seeking_game(client, session)

    # Ask thermometer and lock in so it becomes answerable
    question_id = _ask_question(
        client, game.id, seeker.id, question_type='thermometer', slot_index=0
    )
    _report_location(client, game.id, seeker.id, -0.2, 51.6)
    client.post(
        f'/games/{game.id}/questions/thermometer/{question_id}/lock-in',
        headers=_headers(seeker.id),
    )

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/randomize',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    replacement = _get_latest_question(game.id)
    assert replacement.question_type == QuestionType.thermometer
    assert replacement.status == QuestionStatus.in_progress


# ── POST /questions/photo ────────────────────────────────────────────────────


def test_ask_photo_question(client: TestClient, session: Session):
    """Photo ask creates an answerable question with PhotoQuestionParams."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/photo',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204

    question = _get_latest_question(game.id)
    assert question.question_type == QuestionType.photo
    assert question.status == QuestionStatus.answerable
    assert question.answerable_at is not None
    assert question.photo_params is not None
    assert question.photo_params.subject == PhotoSubject.tree
    assert question.photo_params.photo_object_key is None
    assert question.photo_params.submitted_at is None


def test_ask_photo_invalid_slot_type(client: TestClient, session: Session):
    """slot_index pointing to a radar slot (under photo type) is 422."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/photo',
        json={'location': _point(-0.1, 51.5), 'slot_index': 99},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 422


def test_ask_photo_hider_forbidden(client: TestClient, session: Session):
    """Only seekers can ask photo questions."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/photo',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 403


def test_ask_photo_not_seeking(client: TestClient, session: Session):
    """Photo ask during lobby is 409."""
    game = create_game(session, status=GameStatus.lobby)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    resp = client.post(
        f'/games/{game.id}/questions/photo',
        json={'location': _point(-0.1, 51.5), 'slot_index': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 409


def test_preview_photo_returns_422(client: TestClient, session: Session):
    """Photo preview is not supported — 422 with a helpful message."""
    game, hider, seeker = _setup_seeking_game(client, session)
    resp = client.get(
        f'/games/{game.id}/questions/preview',
        params={'question_type': 'photo', 'slot_index': 0, 'lat': 0.5, 'lng': 0.5},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 422
    assert 'photo' in resp.json()['detail'].lower()


def test_randomize_photo_question(client: TestClient, session: Session):
    """Hider can randomize an answerable photo question."""
    game, hider, seeker = _setup_seeking_game(client, session)
    question_id = _ask_question(client, game.id, seeker.id, question_type='photo', slot_index=0)

    resp = client.post(
        f'/games/{game.id}/questions/{question_id}/randomize',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    original = _get_question_by_id(question_id)
    assert original.status == QuestionStatus.randomized

    replacement = _get_latest_question(game.id)
    assert replacement.id != question_id
    assert replacement.question_type == QuestionType.photo
    assert replacement.status == QuestionStatus.answerable
    assert replacement.photo_params is not None
    assert replacement.photo_params.subject in {
        PhotoSubject.tree,
        PhotoSubject.sky,
        PhotoSubject.selfie,
    }
