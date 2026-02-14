from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from hideandseek.models.types import GameStatus, PlayerRole
from tests.conftest import create_game, create_player


def _headers(client_id: uuid.UUID) -> dict[str, str]:
    return {'X-Client-Id': str(client_id)}


def _point(lng: float = -0.141, lat: float = 51.515) -> dict:
    return {'type': 'Point', 'coordinates': [lng, lat]}


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
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['players'] == []  # only player, so nobody else visible


def test_report_location_seeker_sees_other_seekers(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking)
    seeker1 = create_player(session, game.id, name='Seeker1', role=PlayerRole.seeker)
    seeker2 = create_player(session, game.id, name='Seeker2', role=PlayerRole.seeker)

    # seeker2 reports first
    client.post(
        f'/games/{game.id}/location',
        json={'coordinates': _point(0.1, 51.5), 'timestamp': '2026-02-11T10:00:00Z'},
        headers=_headers(seeker2.client_id),
    )

    # seeker1 reports and should see seeker2
    resp = client.post(
        f'/games/{game.id}/location',
        json={'coordinates': _point(-0.1, 51.5), 'timestamp': '2026-02-11T10:01:00Z'},
        headers=_headers(seeker1.client_id),
    )
    assert resp.status_code == 200
    players = resp.json()['players']
    assert len(players) == 1
    assert players[0]['name'] == 'Seeker2'


def test_hider_sees_seekers(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)

    # seeker reports
    client.post(
        f'/games/{game.id}/location',
        json={'coordinates': _point(), 'timestamp': '2026-02-11T10:00:00Z'},
        headers=_headers(seeker.client_id),
    )

    # hider reports and should see the seeker
    resp = client.post(
        f'/games/{game.id}/location',
        json={'coordinates': _point(0.0, 52.0), 'timestamp': '2026-02-11T10:01:00Z'},
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 200
    players = resp.json()['players']
    assert len(players) == 1
    assert players[0]['name'] == 'Seeker'


def test_seeker_does_not_see_hider(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)

    # hider reports
    client.post(
        f'/games/{game.id}/location',
        json={'coordinates': _point(), 'timestamp': '2026-02-11T10:00:00Z'},
        headers=_headers(hider.client_id),
    )

    # seeker reports — should NOT see the hider
    resp = client.post(
        f'/games/{game.id}/location',
        json={'coordinates': _point(0.0, 52.0), 'timestamp': '2026-02-11T10:01:00Z'},
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 200
    assert resp.json()['players'] == []


def test_report_location_not_in_game(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking)
    resp = client.post(
        f'/games/{game.id}/location',
        json={'coordinates': _point(), 'timestamp': '2026-02-11T10:00:00Z'},
        headers=_headers(uuid.uuid4()),
    )
    assert resp.status_code == 403


# ── GET /games/{game_id}/location-history ────────────────────────────────────


def test_location_history_when_finished(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking)
    player = create_player(session, game.id, role=PlayerRole.seeker)

    # Report some locations
    for i in range(3):
        client.post(
            f'/games/{game.id}/location',
            json={'coordinates': _point(i * 0.01, 51.5), 'timestamp': f'2026-02-11T10:0{i}:00Z'},
            headers=_headers(player.client_id),
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
