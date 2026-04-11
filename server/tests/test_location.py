from __future__ import annotations

import uuid
from collections.abc import Generator
from unittest.mock import patch

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hideandseek_models.types import GameStatus, PlayerRole
from tests.conftest import TEST_SECRET, create_game, create_player


def _headers(player_id: uuid.UUID) -> dict[str, str]:
    return {'X-Player-Id': str(player_id), 'X-Player-Secret': TEST_SECRET}


def _point(lng: float = -0.141, lat: float = 51.515) -> dict:
    return {'type': 'Point', 'coordinates': [lng, lat]}


@pytest.fixture(autouse=True)
def _patch_redis_for_emit() -> Generator[None, None, None]:
    server = fakeredis.FakeServer()
    fake = fakeredis.FakeRedis(server=server)
    with patch('hideandseek_core.broadcast.emit.get_sync_redis', return_value=fake):
        yield


# ── POST /games/{game_id}/location ──────────────────────────────────────────


def test_report_location(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    resp = client.post(
        f'/games/{game.id}/location',
        json={
            'coordinates': _point(),
            'timestamp': '2026-02-11T10:00:00Z',
        },
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204


def test_report_location_hider_during_hiding(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.hiding)
    hider = create_player(session, game.id, role=PlayerRole.hider)

    resp = client.post(
        f'/games/{game.id}/location',
        json={'coordinates': _point(), 'timestamp': '2026-02-11T10:00:00Z'},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204


def test_report_location_seeker_during_hiding_rejected(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.hiding)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    resp = client.post(
        f'/games/{game.id}/location',
        json={'coordinates': _point(), 'timestamp': '2026-02-11T10:00:00Z'},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 409


def test_report_location_in_lobby_rejected(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.lobby)
    player = create_player(session, game.id, role=PlayerRole.seeker)

    resp = client.post(
        f'/games/{game.id}/location',
        json={'coordinates': _point(), 'timestamp': '2026-02-11T10:00:00Z'},
        headers=_headers(player.id),
    )
    assert resp.status_code == 409


def test_report_location_when_finished_rejected(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.finished)
    player = create_player(session, game.id, role=PlayerRole.seeker)

    resp = client.post(
        f'/games/{game.id}/location',
        json={'coordinates': _point(), 'timestamp': '2026-02-11T10:00:00Z'},
        headers=_headers(player.id),
    )
    assert resp.status_code == 409


def test_report_location_not_in_game(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking)
    resp = client.post(
        f'/games/{game.id}/location',
        json={'coordinates': _point(), 'timestamp': '2026-02-11T10:00:00Z'},
        headers=_headers(uuid.uuid4()),
    )
    assert resp.status_code == 401


# ── GET /games/{game_id}/location-history ────────────────────────────────────


def test_location_history_when_finished(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking)
    player = create_player(session, game.id, role=PlayerRole.seeker)

    # Report some locations
    for i in range(3):
        client.post(
            f'/games/{game.id}/location',
            json={'coordinates': _point(i * 0.01, 51.5), 'timestamp': f'2026-02-11T10:0{i}:00Z'},
            headers=_headers(player.id),
        )

    # End the game
    game.status = GameStatus.finished
    game.join_code = None
    session.add(game)
    session.commit()

    resp = client.get(f'/games/{game.id}/location-history')
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3


def test_location_history_not_finished(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking)
    resp = client.get(f'/games/{game.id}/location-history')
    assert resp.status_code == 409
