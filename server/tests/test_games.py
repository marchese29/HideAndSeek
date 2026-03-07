from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point
from sqlalchemy.orm import Session

from hideandseek.models.game import Game
from hideandseek.models.game_map import GameMap
from hideandseek.models.transit import Route, RouteStop, Stop
from hideandseek.models.types import GameStatus, PlayerRole, RouteType, StationElectionStatus
from hideandseek.queries.games import set_hider_station
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
        json={
            'join_code': 'ABCD',
            'name': 'Alice',
            'color': '#FF0000',
            'device_token': 'abc123def456',
        },
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
        json={
            'join_code': 'ZZZZ',
            'name': 'Bob',
            'color': '#0000FF',
            'device_token': 'abc123def456',
        },
        headers=_headers(),
    )
    assert resp.status_code == 404


def test_join_game_not_in_lobby(client: TestClient, session: Session):
    create_game(session, join_code='WXYZ', status=GameStatus.hiding)
    resp = client.post(
        '/games/join',
        json={
            'join_code': 'WXYZ',
            'name': 'Charlie',
            'color': '#00FF00',
            'device_token': 'abc123def456',
        },
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
    # No hider_station_id on shared endpoint
    assert 'hider_station_id' not in data


def test_get_game_inventory(client: TestClient, session: Session):
    """GameResponse inventory includes slot_index, distance, ask_count, and category slots."""
    game = create_game(session)
    resp = client.get(f'/games/{game.id}')
    assert resp.status_code == 200
    inv = resp.json()['inventory']
    assert len(inv['radar_slots']) == 3
    assert inv['radar_slots'][0] == {
        'slot_index': 0,
        'distance': 3000.0,
        'category': None,
        'feature_class': None,
        'ask_count': 0,
    }
    assert inv['radar_slots'][2]['distance'] is None
    assert len(inv['thermometer_slots']) == 2
    # No internal IDs exposed
    assert 'id' not in inv['radar_slots'][0]
    # Matching and measuring slots (empty if no map features)
    assert isinstance(inv['matching_slots'], list)
    assert isinstance(inv['measuring_slots'], list)


def test_get_inventory_endpoint(client: TestClient, session: Session):
    """Dedicated inventory endpoint returns slots grouped by type."""
    game = create_game(session)
    resp = client.get(f'/games/{game.id}/inventory')
    assert resp.status_code == 200
    inv = resp.json()
    assert len(inv['radar_slots']) == 3
    assert inv['radar_slots'][0]['distance'] == 3000.0
    assert inv['radar_slots'][0]['ask_count'] == 0
    assert len(inv['thermometer_slots']) == 2
    assert isinstance(inv['matching_slots'], list)
    assert isinstance(inv['measuring_slots'], list)


def test_get_game_not_found(client: TestClient):
    resp = client.get(f'/games/{uuid.uuid4()}')
    assert resp.status_code == 404


def test_set_hider_station(session: Session):
    game = create_game(session, status=GameStatus.seeking)
    game_map = session.get(GameMap, game.map_id)
    assert game_map is not None

    stop = Stop(
        stable_id='stop-set-test',
        dataset_id=game_map.transit_dataset_id,
        name='Test Station',
        coordinates=Point(0.5, 0.5),
    )
    session.add(stop)
    session.commit()
    session.refresh(stop)

    set_hider_station(game, stop, StationElectionStatus.auto_assigned)
    session.refresh(game)
    assert game.hider_station_id == stop.id
    assert game.station_election_status == StationElectionStatus.auto_assigned


# ── GET /games/{game_id}/hider-station ───────────────────────────────────


def _set_hider_station(session: Session, game: Game, stop_id: uuid.UUID):
    game.hider_station_id = stop_id
    session.add(game)
    session.commit()


def _create_stop(session: Session, dataset_id: uuid.UUID) -> uuid.UUID:
    stop = Stop(
        stable_id=f'stop-{uuid.uuid4().hex[:8]}',
        dataset_id=dataset_id,
        name='Test Station',
        coordinates=Point(0.5, 0.5),
    )
    session.add(stop)
    session.commit()
    session.refresh(stop)
    return stop.id


def test_hider_station_endpoint_hider_sees_station(client: TestClient, session: Session):
    """GET /hider-station as hider returns the station UUID."""
    game = create_game(session, status=GameStatus.seeking)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    game_map = session.get(GameMap, game.map_id)
    assert game_map is not None
    stop_id = _create_stop(session, game_map.transit_dataset_id)
    _set_hider_station(session, game, stop_id)

    resp = client.get(f'/games/{game.id}/hider-station', headers=_headers(hider.client_id))
    assert resp.status_code == 200
    data = resp.json()
    assert data['hider_station_id'] == str(stop_id)
    assert data['station_election_status'] == 'pending'


def test_hider_station_endpoint_seeker_403(client: TestClient, session: Session):
    """GET /hider-station as seeker returns 403."""
    game = create_game(session, status=GameStatus.seeking)
    create_player(session, game.id, role=PlayerRole.hider)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    game_map = session.get(GameMap, game.map_id)
    assert game_map is not None
    stop_id = _create_stop(session, game_map.transit_dataset_id)
    _set_hider_station(session, game, stop_id)

    resp = client.get(f'/games/{game.id}/hider-station', headers=_headers(seeker.client_id))
    assert resp.status_code == 403


def test_hider_station_not_in_shared_game_state(client: TestClient, session: Session):
    """GET /games/{id} does not include hider_station_id."""
    game = create_game(session, status=GameStatus.seeking)
    game_map = session.get(GameMap, game.map_id)
    assert game_map is not None
    stop_id = _create_stop(session, game_map.transit_dataset_id)
    _set_hider_station(session, game, stop_id)

    resp = client.get(f'/games/{game.id}')
    assert resp.status_code == 200
    assert 'hider_station_id' not in resp.json()


def test_hider_station_pending_when_not_assigned(client: TestClient, session: Session):
    """GET /hider-station returns 200 with null station and pending status."""
    game = create_game(session, status=GameStatus.seeking)
    hider = create_player(session, game.id, role=PlayerRole.hider)

    resp = client.get(f'/games/{game.id}/hider-station', headers=_headers(hider.client_id))
    assert resp.status_code == 200
    data = resp.json()
    assert data['hider_station_id'] is None
    assert data['station_election_status'] == 'pending'


def test_hider_station_409_when_lobby(client: TestClient, session: Session):
    """GET /hider-station returns 409 when game is in lobby."""
    game = create_game(session, status=GameStatus.lobby)
    hider = create_player(session, game.id, role=PlayerRole.hider)

    resp = client.get(f'/games/{game.id}/hider-station', headers=_headers(hider.client_id))
    assert resp.status_code == 409


def test_hider_station_available_during_hiding(client: TestClient, session: Session):
    """GET /hider-station returns 200 during hiding with pending status."""
    game = create_game(session, status=GameStatus.hiding)
    hider = create_player(session, game.id, role=PlayerRole.hider)

    resp = client.get(f'/games/{game.id}/hider-station', headers=_headers(hider.client_id))
    assert resp.status_code == 200
    assert resp.json()['station_election_status'] == 'pending'
    assert resp.json()['hider_station_id'] is None


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
    data = resp.json()
    assert data['status'] == 'hiding'
    assert data['join_code'] is None
    assert data['hiding_started_at'] is not None
    assert data['seeking_started_at'] is None


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
    # In real flow, join_code is already cleared at hiding start.
    # Factory creates directly at seeking, so we set join_code=None to match.
    game = create_game(session, status=GameStatus.seeking, join_code=None)
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
    game = create_game(session)
    game_map = session.get(type(game), game.id)
    assert game_map is not None

    # Add some transit data
    gm = session.get(GameMap, game.map_id)
    assert gm is not None
    ds_id = gm.transit_dataset_id

    stop = Stop(
        stable_id='OXCIRC',
        dataset_id=ds_id,
        name='Oxford Circus',
        coordinates=Point(-0.141, 51.515),
    )
    route = Route(
        stable_id='central',
        dataset_id=ds_id,
        name='Central Line',
        color='#DC241F',
        route_type=RouteType.metro,
        shape=LineString([(-0.141, 51.515), (-0.138, 51.514)]),
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


# ── POST /games/{game_id}/hider-station (election) ─────────────────────


def test_elect_station_seeker_403(client: TestClient, session: Session):
    """POST /hider-station as seeker returns 403."""
    game = create_game(session, status=GameStatus.hiding)
    create_player(session, game.id, role=PlayerRole.hider)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    resp = client.post(
        f'/games/{game.id}/hider-station',
        json={
            'station_id': str(uuid.uuid4()),
            'location': {'type': 'Point', 'coordinates': [0.5, 0.5]},
        },
        headers=_headers(seeker.client_id),
    )
    assert resp.status_code == 403


def test_elect_station_wrong_phase_409(client: TestClient, session: Session):
    """POST /hider-station in lobby returns 409."""
    game = create_game(session, status=GameStatus.lobby)
    hider = create_player(session, game.id, role=PlayerRole.hider)

    resp = client.post(
        f'/games/{game.id}/hider-station',
        json={
            'station_id': str(uuid.uuid4()),
            'location': {'type': 'Point', 'coordinates': [0.5, 0.5]},
        },
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 409


def test_elect_station_already_elected_409(client: TestClient, session: Session):
    """POST /hider-station when already elected returns 409."""
    game = create_game(session, status=GameStatus.hiding)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    game_map = session.get(GameMap, game.map_id)
    assert game_map is not None
    stop_id = _create_stop(session, game_map.transit_dataset_id)
    _set_hider_station(session, game, stop_id)

    resp = client.post(
        f'/games/{game.id}/hider-station',
        json={
            'station_id': str(uuid.uuid4()),
            'location': {'type': 'Point', 'coordinates': [0.5, 0.5]},
        },
        headers=_headers(hider.client_id),
    )
    assert resp.status_code == 409


def test_elect_station_during_ambiguity(client: TestClient, session: Session):
    """POST /hider-station allowed when status is ambiguous (even in seeking)."""
    game = create_game(
        session,
        status=GameStatus.seeking,
        station_election_status=StationElectionStatus.ambiguous,
    )
    hider = create_player(session, game.id, role=PlayerRole.hider)
    game_map = session.get(GameMap, game.map_id)
    assert game_map is not None

    resp = client.post(
        f'/games/{game.id}/hider-station',
        json={
            'station_id': str(uuid.uuid4()),
            'location': {'type': 'Point', 'coordinates': [0.5, 0.5]},
        },
        headers=_headers(hider.client_id),
    )
    # Stop doesn't exist / isn't playable → 422
    assert resp.status_code == 422


# ── GET /games/{game_id}/hiding-zone ────────────────────────────────────


def test_hiding_zone_stop_not_found(client: TestClient, session: Session):
    """GET /hiding-zone returns 404 for unknown station_id."""
    game = create_game(session, status=GameStatus.hiding)
    player = create_player(session, game.id, role=PlayerRole.hider)

    resp = client.get(
        f'/games/{game.id}/hiding-zone?station_id={uuid.uuid4()}',
        headers=_headers(player.client_id),
    )
    assert resp.status_code == 404
