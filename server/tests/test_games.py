from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from hideandseek.models.types import GameStatus, PlayerRole, RouteType
from tests.conftest import create_game, create_game_map, create_player


def _headers(client_id: uuid.UUID | None = None) -> dict[str, str]:
    return {'X-Client-Id': str(client_id or uuid.uuid4())}


# ── POST /games ──────────────────────────────────────────────────────────────


def test_create_game(client: TestClient, session: Session):
    gm = create_game_map(session)
    resp = client.post(
        '/games',
        json={'map_id': str(gm.id)},
        headers=_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data['status'] == 'lobby'
    assert data['map_id'] == str(gm.id)
    assert len(data['join_code']) == 4
    assert data['players'] == []


def test_create_game_map_not_found(client: TestClient):
    resp = client.post(
        '/games',
        json={'map_id': str(uuid.uuid4())},
        headers=_headers(),
    )
    assert resp.status_code == 404


# ── POST /games/join ─────────────────────────────────────────────────────────


def test_join_game(client: TestClient, session: Session):
    create_game(session, join_code='ABCD')
    client_id = uuid.uuid4()
    resp = client.post(
        '/games/join',
        json={'join_code': 'ABCD', 'name': 'Alice', 'color': '#FF0000'},
        headers=_headers(client_id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data['player_id'] is not None
    assert len(data['game']['players']) == 1
    assert data['game']['players'][0]['name'] == 'Alice'
    assert data['game']['players'][0]['role'] is None


def test_join_game_invalid_code(client: TestClient):
    resp = client.post(
        '/games/join',
        json={'join_code': 'ZZZZ', 'name': 'Bob', 'color': '#0000FF'},
        headers=_headers(),
    )
    assert resp.status_code == 404


def test_join_game_not_in_lobby(client: TestClient, session: Session):
    create_game(session, join_code='WXYZ', status=GameStatus.hiding)
    resp = client.post(
        '/games/join',
        json={'join_code': 'WXYZ', 'name': 'Charlie', 'color': '#00FF00'},
        headers=_headers(),
    )
    assert resp.status_code == 409


# ── GET /games/{game_id} ────────────────────────────────────────────────────


def test_get_game_state(client: TestClient, session: Session):
    game = create_game(session)
    create_player(session, game.id, name='Alice', role=PlayerRole.hider)
    resp = client.get(f'/games/{game.id}')
    assert resp.status_code == 200
    data = resp.json()
    assert data['id'] == str(game.id)
    assert len(data['players']) == 1
    assert data['players'][0]['role'] == 'hider'


def test_get_game_not_found(client: TestClient):
    resp = client.get(f'/games/{uuid.uuid4()}')
    assert resp.status_code == 404


# ── PATCH /games/{game_id}/players/{player_id} ──────────────────────────────


def test_update_player_role(client: TestClient, session: Session):
    game = create_game(session)
    player = create_player(session, game.id)
    resp = client.patch(
        f'/games/{game.id}/players/{player.id}',
        json={'role': 'seeker'},
    )
    assert resp.status_code == 200
    assert resp.json()['role'] == 'seeker'


def test_update_player_name_and_color(client: TestClient, session: Session):
    game = create_game(session)
    player = create_player(session, game.id, name='Old', color='#000000')
    resp = client.patch(
        f'/games/{game.id}/players/{player.id}',
        json={'name': 'New', 'color': '#FFFFFF'},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['name'] == 'New'
    assert data['color'] == '#FFFFFF'


def test_update_player_not_found(client: TestClient, session: Session):
    game = create_game(session)
    resp = client.patch(
        f'/games/{game.id}/players/{uuid.uuid4()}',
        json={'role': 'hider'},
    )
    assert resp.status_code == 404


# ── POST /games/{game_id}/start ─────────────────────────────────────────────


def test_start_game(client: TestClient, session: Session):
    game = create_game(session)
    create_player(session, game.id, role=PlayerRole.hider)
    create_player(session, game.id, role=PlayerRole.seeker)
    resp = client.post(f'/games/{game.id}/start')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'hiding'


def test_start_game_no_players(client: TestClient, session: Session):
    game = create_game(session)
    resp = client.post(f'/games/{game.id}/start')
    assert resp.status_code == 409


def test_start_game_unassigned_roles(client: TestClient, session: Session):
    game = create_game(session)
    create_player(session, game.id, role=None)
    resp = client.post(f'/games/{game.id}/start')
    assert resp.status_code == 409
    assert 'assigned roles' in resp.json()['detail']


def test_start_game_missing_hider(client: TestClient, session: Session):
    game = create_game(session)
    create_player(session, game.id, role=PlayerRole.seeker)
    create_player(session, game.id, role=PlayerRole.seeker)
    resp = client.post(f'/games/{game.id}/start')
    assert resp.status_code == 409
    assert 'hider' in resp.json()['detail']


def test_start_game_missing_seeker(client: TestClient, session: Session):
    game = create_game(session)
    create_player(session, game.id, role=PlayerRole.hider)
    resp = client.post(f'/games/{game.id}/start')
    assert resp.status_code == 409
    assert 'seeker' in resp.json()['detail']


def test_start_game_not_in_lobby(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking)
    resp = client.post(f'/games/{game.id}/start')
    assert resp.status_code == 409


# ── POST /games/{game_id}/end ───────────────────────────────────────────────


def test_end_game(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking)
    resp = client.post(f'/games/{game.id}/end')
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'finished'
    assert data['join_code'] is None


def test_end_game_from_hiding(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.hiding)
    resp = client.post(f'/games/{game.id}/end')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'finished'


def test_end_game_from_lobby(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.lobby)
    resp = client.post(f'/games/{game.id}/end')
    assert resp.status_code == 409


def test_end_game_already_finished(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.finished, join_code=None)
    resp = client.post(f'/games/{game.id}/end')
    assert resp.status_code == 409


# ── GET /games/{game_id}/map ────────────────────────────────────────────────


def test_get_effective_map(client: TestClient, session: Session):
    from hideandseek.models.transit import Route, RouteStop, Stop

    game = create_game(session)
    game_map = session.get(type(game), game.id)
    assert game_map is not None

    # Add some transit data
    from hideandseek.models.game_map import GameMap

    gm = session.get(GameMap, game.map_id)
    assert gm is not None
    ds_id = gm.transit_dataset_id

    stop = Stop(
        stable_id='OXCIRC',
        dataset_id=ds_id,
        name='Oxford Circus',
        coordinates={'type': 'Point', 'coordinates': [-0.141, 51.515]},
    )
    route = Route(
        stable_id='central',
        dataset_id=ds_id,
        name='Central Line',
        color='#DC241F',
        route_type=RouteType.metro,
        shape={'type': 'LineString', 'coordinates': [[-0.141, 51.515], [-0.138, 51.514]]},
    )
    session.add(stop)
    session.add(route)
    session.commit()
    session.refresh(stop)
    session.refresh(route)

    rs = RouteStop(route_id=route.id, stop_id=stop.id, sequence=0)
    session.add(rs)
    session.commit()

    resp = client.get(f'/games/{game.id}/map')
    assert resp.status_code == 200
    data = resp.json()
    assert data['name'] == gm.name
    assert len(data['stops']) == 1
    assert data['stops'][0]['name'] == 'Oxford Circus'
    assert len(data['routes']) == 1
    assert data['routes'][0]['stop_ids'] == [str(stop.id)]
