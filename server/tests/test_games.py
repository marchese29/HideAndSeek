from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point
from sqlalchemy import select
from sqlalchemy.orm import Session

from hideandseek_core.queries.games import set_hider_station
from hideandseek_models.game import Game, Player
from hideandseek_models.game_map import GameMap
from hideandseek_models.location import LocationUpdate
from hideandseek_models.transit import Route, RouteStop, Stop
from hideandseek_models.types import (
    GameStatus,
    PlayerColor,
    PlayerRole,
    RouteType,
    StationElectionStatus,
)
from tests.conftest import (
    TEST_SECRET,
    create_game,
    create_game_map,
    create_location_update,
    create_player,
)


def _headers(player_id: uuid.UUID) -> dict[str, str]:
    return {'X-Player-Id': str(player_id), 'X-Player-Secret': TEST_SECRET}


def _get_host(session: Session, game: Game) -> Player:
    """Get the auto-created host player."""
    return session.scalars(
        select(Player).where(Player.game_id == game.id, Player.id == game.host_player_id)
    ).one()


# ── POST /games ──────────────────────────────────────────────────────────────


def test_create_game(client: TestClient, session: Session):
    gm = create_game_map(session)
    resp = client.post(
        '/games',
        json={'map_id': str(gm.id), 'name': 'Host'},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert 'game' in data
    assert 'player_id' in data
    assert 'player_secret' in data
    game = data['game']
    assert game['status'] == 'lobby'
    assert game['map_id'] == str(gm.id)
    assert len(game['join_code']) == 4
    assert len(game['players']) == 1
    assert game['players'][0]['name'] == 'Host'
    assert game['players'][0]['color'] == 'red'


def test_create_game_includes_size(client: TestClient, session: Session):
    """POST /games returns the game's effective size."""
    gm = create_game_map(session)
    resp = client.post('/games', json={'map_id': str(gm.id), 'name': 'Host'})
    assert resp.status_code == 201
    assert resp.json()['game']['size'] == 'medium'


def test_create_game_size_override(client: TestClient, session: Session):
    """POST /games with size override stores the chosen size on the game."""
    gm = create_game_map(session)  # default size=medium
    resp = client.post(
        '/games',
        json={'map_id': str(gm.id), 'name': 'Host', 'size': 'large'},
    )
    assert resp.status_code == 201
    game = resp.json()['game']
    assert game['size'] == 'large'
    assert game['hiding_time_min'] == 180  # large default


def test_create_game_size_special_rejected(client: TestClient, session: Session):
    """POST /games rejects 'special' as a user-selected size."""
    gm = create_game_map(session)
    resp = client.post(
        '/games',
        json={'map_id': str(gm.id), 'name': 'Host', 'size': 'special'},
    )
    assert resp.status_code == 422


def test_create_game_map_not_found(client: TestClient):
    resp = client.post(
        '/games',
        json={'map_id': str(uuid.uuid4()), 'name': 'Host'},
    )
    assert resp.status_code == 404


# ── POST /games/join ─────────────────────────────────────────────────────────


def test_join_game(client: TestClient, session: Session):
    create_game(session, join_code='ABCD')
    resp = client.post(
        '/games/join',
        json={
            'join_code': 'ABCD',
            'name': 'Alice',
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data['player_id'] is not None
    assert 'player_secret' in data
    assert len(data['game']['players']) == 2
    joiner = next(p for p in data['game']['players'] if p['name'] == 'Alice')
    assert joiner['role'] is None
    assert joiner['color'] in [c.value for c in PlayerColor]


def test_join_game_invalid_code(client: TestClient):
    resp = client.post(
        '/games/join',
        json={
            'join_code': 'ZZZZ',
            'name': 'Bob',
        },
    )
    assert resp.status_code == 404


def test_join_game_not_in_lobby(client: TestClient, session: Session):
    create_game(session, join_code='WXYZ', status=GameStatus.hiding)
    resp = client.post(
        '/games/join',
        json={
            'join_code': 'WXYZ',
            'name': 'Charlie',
        },
    )
    assert resp.status_code == 409


# ── GET /games/{game_id} ────────────────────────────────────────────────────


def test_get_game_state(client: TestClient, session: Session):
    game = create_game(session)
    resp = client.get(f'/games/{game.id}')
    assert resp.status_code == 200
    data = resp.json()
    assert data['id'] == str(game.id)
    assert len(data['players']) == 1
    assert data['players'][0]['name'] == 'Host'
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


# ── Hider station helpers ────────────────────────────────────────────────


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


# ── PATCH /games/{game_id}/players/{player_id} ──────────────────────────────


def test_update_player_role(client: TestClient, session: Session):
    game = create_game(session)
    player = create_player(session, game.id)
    resp = client.patch(
        f'/games/{game.id}/players/{player.id}',
        json={'role': 'seeker'},
        headers=_headers(player.id),
    )
    assert resp.status_code == 200
    assert resp.json()['role'] == 'seeker'


def test_update_player_name_and_color(client: TestClient, session: Session):
    game = create_game(session)
    player = create_player(session, game.id, name='Old', color=PlayerColor.blue)
    resp = client.patch(
        f'/games/{game.id}/players/{player.id}',
        json={'name': 'New', 'color': 'green'},
        headers=_headers(player.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['name'] == 'New'
    assert data['color'] == 'green'


def test_update_player_not_found(client: TestClient, session: Session):
    game = create_game(session)
    host = _get_host(session, game)
    resp = client.patch(
        f'/games/{game.id}/players/{uuid.uuid4()}',
        json={'role': 'hider'},
        headers=_headers(host.id),
    )
    assert resp.status_code == 404


# ── POST /games/{game_id}/start ─────────────────────────────────────────────


def test_start_game(client: TestClient, session: Session):
    game = create_game(session)
    # Assign role to auto-created host player
    host = _get_host(session, game)
    host.role = PlayerRole.hider
    session.flush()
    create_player(session, game.id, role=PlayerRole.seeker)
    resp = client.post(
        f'/games/{game.id}/start',
        headers=_headers(game.host_player_id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'hiding'
    assert data['join_code'] is None
    assert data['hiding_started_at'] is not None
    assert data['seeking_started_at'] is None


def test_start_game_unassigned_roles(client: TestClient, session: Session):
    """Host has no role (auto-created) → 409 unassigned roles."""
    game = create_game(session)
    resp = client.post(
        f'/games/{game.id}/start',
        headers=_headers(game.host_player_id),
    )
    assert resp.status_code == 409
    assert 'assigned roles' in resp.json()['detail']


def test_start_game_missing_hider(client: TestClient, session: Session):
    game = create_game(session)
    # Assign host as seeker, add another seeker — no hider
    host = _get_host(session, game)
    host.role = PlayerRole.seeker
    session.flush()
    create_player(session, game.id, role=PlayerRole.seeker)
    resp = client.post(
        f'/games/{game.id}/start',
        headers=_headers(game.host_player_id),
    )
    assert resp.status_code == 409
    assert 'hider' in resp.json()['detail']


def test_start_game_missing_seeker(client: TestClient, session: Session):
    game = create_game(session)
    # Assign host as hider — no seeker
    host = _get_host(session, game)
    host.role = PlayerRole.hider
    session.flush()
    resp = client.post(
        f'/games/{game.id}/start',
        headers=_headers(game.host_player_id),
    )
    assert resp.status_code == 409
    assert 'seeker' in resp.json()['detail']


def test_start_game_not_in_lobby(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking)
    resp = client.post(
        f'/games/{game.id}/start',
        headers=_headers(game.host_player_id),
    )
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
        headers=_headers(seeker.id),
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
        headers=_headers(hider.id),
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
        headers=_headers(hider.id),
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
        headers=_headers(hider.id),
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
        headers=_headers(player.id),
    )
    assert resp.status_code == 404


# ── Lobby: host-as-player, player cap, color assignment, auth guards ────


def test_create_game_host_is_player(client: TestClient, session: Session):
    """POST /games returns JoinGameResponse with host as first player."""
    gm = create_game_map(session)
    resp = client.post(
        '/games',
        json={'map_id': str(gm.id), 'name': 'HostPlayer'},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data['player_id'] is not None
    players = data['game']['players']
    assert len(players) == 1
    assert players[0]['name'] == 'HostPlayer'
    assert players[0]['color'] == 'red'


def test_join_full_game_409(client: TestClient, session: Session):
    """Joining a game with 12 players returns 409."""
    game = create_game(session, join_code='FULL')
    # Host already exists as player 0 (red). Add 11 more to reach cap of 12.
    for i in range(11):
        create_player(session, game.id, name=f'P{i}', color=list(PlayerColor)[i + 1])
    resp = client.post(
        '/games/join',
        json={'join_code': 'FULL', 'name': 'Extra'},
    )
    assert resp.status_code == 409
    assert '12 players' in resp.json()['detail']


def test_join_assigns_unique_colors(client: TestClient, session: Session):
    """Two players joining get different auto-assigned colors (host already has red)."""
    create_game(session, join_code='CLRS')
    r1 = client.post(
        '/games/join',
        json={'join_code': 'CLRS', 'name': 'A'},
    )
    r2 = client.post(
        '/games/join',
        json={'join_code': 'CLRS', 'name': 'B'},
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    # r2 has all 3 players (host + 2 joiners)
    players = r2.json()['game']['players']
    colors = {p['color'] for p in players}
    assert len(colors) == 3  # host(red) + 2 unique joiner colors


def test_patch_player_self_only_403(client: TestClient, session: Session):
    """PATCH another player returns 403."""
    game = create_game(session)
    player = create_player(session, game.id)
    other = create_player(session, game.id)
    resp = client.patch(
        f'/games/{game.id}/players/{player.id}',
        json={'name': 'Hacked'},
        headers=_headers(other.id),
    )
    assert resp.status_code == 403


def test_patch_color_swap_409(client: TestClient, session: Session):
    """PATCH color to a taken color returns 409."""
    game = create_game(session)
    # Host already has red. Try to swap p1 to red.
    p1 = create_player(session, game.id, color=PlayerColor.blue)
    resp = client.patch(
        f'/games/{game.id}/players/{p1.id}',
        json={'color': 'red'},
        headers=_headers(p1.id),
    )
    assert resp.status_code == 409
    assert 'already taken' in resp.json()['detail']


def test_patch_color_swap_success(client: TestClient, session: Session):
    """PATCH color to an available color succeeds."""
    game = create_game(session)
    p1 = create_player(session, game.id, color=PlayerColor.blue)
    resp = client.patch(
        f'/games/{game.id}/players/{p1.id}',
        json={'color': 'green'},
        headers=_headers(p1.id),
    )
    assert resp.status_code == 200
    assert resp.json()['color'] == 'green'


def test_start_game_host_only_403(client: TestClient, session: Session):
    """Non-host starting the game returns 403."""
    game = create_game(session)
    non_host = create_player(session, game.id)
    resp = client.post(
        f'/games/{game.id}/start',
        headers=_headers(non_host.id),
    )
    assert resp.status_code == 403
    assert 'host' in resp.json()['detail']


def test_patch_device_token(client: TestClient, session: Session):
    """PATCH device_token upserts via the device token table."""
    game = create_game(session)
    player = create_player(session, game.id)
    resp = client.patch(
        f'/games/{game.id}/players/{player.id}',
        json={'device_token': 'new-token-hex'},
        headers=_headers(player.id),
    )
    assert resp.status_code == 200


# ── DELETE /games/{game_id}/players/{player_id} ─────────────────────────────


def test_remove_player_self_leave(client: TestClient, session: Session):
    """Non-host player leaves → 204, player gone from game."""
    game = create_game(session)
    host = _get_host(session, game)
    player = create_player(session, game.id)
    resp = client.delete(
        f'/games/{game.id}/players/{player.id}',
        headers=_headers(player.id),
    )
    assert resp.status_code == 204
    # Verify player is gone
    game_resp = client.get(f'/games/{game.id}')
    assert len(game_resp.json()['players']) == 1
    assert game_resp.json()['players'][0]['name'] == host.name


def test_remove_player_host_kick(client: TestClient, session: Session):
    """Host removes another player → 204, player gone."""
    game = create_game(session)
    target = create_player(session, game.id, name='Kicked')
    resp = client.delete(
        f'/games/{game.id}/players/{target.id}',
        headers=_headers(game.host_player_id),
    )
    assert resp.status_code == 204
    game_resp = client.get(f'/games/{game.id}')
    names = [p['name'] for p in game_resp.json()['players']]
    assert 'Kicked' not in names


def test_remove_player_unauthorized_403(client: TestClient, session: Session):
    """Non-self, non-host removal → 403."""
    game = create_game(session)
    target = create_player(session, game.id)
    bystander = create_player(session, game.id)
    resp = client.delete(
        f'/games/{game.id}/players/{target.id}',
        headers=_headers(bystander.id),
    )
    assert resp.status_code == 403


def test_remove_player_not_in_game_404(client: TestClient, session: Session):
    """Player from different game → 404."""
    game = create_game(session)
    resp = client.delete(
        f'/games/{game.id}/players/{uuid.uuid4()}',
        headers=_headers(game.host_player_id),
    )
    assert resp.status_code == 404


def test_remove_player_finished_game_422(client: TestClient, session: Session):
    """Game already finished → 422."""
    game = create_game(session, status=GameStatus.finished)
    player = create_player(session, game.id)
    resp = client.delete(
        f'/games/{game.id}/players/{player.id}',
        headers=_headers(player.id),
    )
    assert resp.status_code == 422
    assert 'lobby or active' in resp.json()['detail']


def test_remove_host_only_player_dissolves(client: TestClient, session: Session):
    """Host is only player, leaves → 204, game status becomes dissolved."""
    game = create_game(session)
    host = _get_host(session, game)
    resp = client.delete(
        f'/games/{game.id}/players/{host.id}',
        headers=_headers(game.host_player_id),
    )
    assert resp.status_code == 204
    session.expire(game)
    assert game.status == GameStatus.dissolved


def test_remove_host_requires_new_host_422(client: TestClient, session: Session):
    """Host leaves with others but no new_host_id → 422."""
    game = create_game(session)
    host = _get_host(session, game)
    create_player(session, game.id)
    resp = client.delete(
        f'/games/{game.id}/players/{host.id}',
        headers=_headers(game.host_player_id),
    )
    assert resp.status_code == 422
    assert 'new_host_id' in resp.json()['detail']


def test_remove_host_invalid_new_host_422(client: TestClient, session: Session):
    """new_host_id is the leaving host → 422."""
    game = create_game(session)
    host = _get_host(session, game)
    create_player(session, game.id)
    resp = client.request(
        'DELETE',
        f'/games/{game.id}/players/{host.id}',
        json={'new_host_id': str(host.id)},
        headers=_headers(game.host_player_id),
    )
    assert resp.status_code == 422
    assert 'another player' in resp.json()['detail']


def test_remove_host_transfers_and_leaves(client: TestClient, session: Session):
    """Host leaves with valid new_host_id → 204, host_player_id updated."""
    game = create_game(session)
    host = _get_host(session, game)
    successor = create_player(session, game.id, name='Successor')
    resp = client.request(
        'DELETE',
        f'/games/{game.id}/players/{host.id}',
        json={'new_host_id': str(successor.id)},
        headers=_headers(game.host_player_id),
    )
    assert resp.status_code == 204
    game_resp = client.get(f'/games/{game.id}')
    assert game_resp.json()['status'] == 'lobby'
    assert len(game_resp.json()['players']) == 1
    assert game_resp.json()['players'][0]['name'] == 'Successor'


def test_remove_player_frees_color(client: TestClient, session: Session):
    """After removal, the freed color is assigned to the next joiner."""
    game = create_game(session, join_code='FREE')
    # Host already has red. Add a player with blue.
    p2 = create_player(session, game.id, color=PlayerColor.blue)
    # Remove p2 (blue)
    client.delete(
        f'/games/{game.id}/players/{p2.id}',
        headers=_headers(game.host_player_id),
    )
    # Join a new player — should get red's next unused, which is blue (freed)
    join_resp = client.post(
        '/games/join',
        json={'join_code': 'FREE', 'name': 'NewPlayer'},
    )
    assert join_resp.status_code == 201
    new_color = join_resp.json()['game']['players'][-1]['color']
    assert new_color == 'blue'


# ── DELETE /players (mid-game) ───────────────────────────────────────────────


def test_remove_player_active_game_succeeds(client: TestClient, session: Session):
    """Non-host seeker leaves during seeking → 204."""
    game = create_game(session, status=GameStatus.seeking)
    host = _get_host(session, game)
    host.role = PlayerRole.hider
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    seeker2 = create_player(session, game.id, name='Seeker2', role=PlayerRole.seeker)
    session.flush()

    resp = client.delete(
        f'/games/{game.id}/players/{seeker.id}',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204
    session.expire(game)
    assert game.status == GameStatus.seeking
    remaining_ids = {p.id for p in game.players}
    assert seeker.id not in remaining_ids
    assert seeker2.id in remaining_ids


def test_remove_player_active_last_hider_dissolves(client: TestClient, session: Session):
    """Last hider leaves during seeking → game dissolved."""
    game = create_game(session, status=GameStatus.seeking)
    host = _get_host(session, game)
    host.role = PlayerRole.hider
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    session.flush()

    resp = client.request(
        'DELETE',
        f'/games/{game.id}/players/{host.id}',
        json={'new_host_id': str(seeker.id)},
        headers=_headers(host.id),
    )
    assert resp.status_code == 204
    session.expire(game)
    assert game.status == GameStatus.dissolved


def test_remove_player_active_last_seeker_dissolves(client: TestClient, session: Session):
    """Last seeker leaves during seeking → game dissolved."""
    game = create_game(session, status=GameStatus.seeking)
    host = _get_host(session, game)
    host.role = PlayerRole.hider
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    session.flush()

    resp = client.delete(
        f'/games/{game.id}/players/{seeker.id}',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204
    session.expire(game)
    assert game.status == GameStatus.dissolved


def test_remove_player_active_host_transfers(client: TestClient, session: Session):
    """Host leaves during active play with new_host_id → 204, host transferred."""
    game = create_game(session, status=GameStatus.seeking)
    host = _get_host(session, game)
    host.role = PlayerRole.seeker
    seeker2 = create_player(session, game.id, name='Seeker2', role=PlayerRole.seeker)
    create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    session.flush()

    resp = client.request(
        'DELETE',
        f'/games/{game.id}/players/{host.id}',
        json={'new_host_id': str(seeker2.id)},
        headers=_headers(host.id),
    )
    assert resp.status_code == 204
    session.expire(game)
    assert game.status == GameStatus.seeking
    assert game.host_player_id == seeker2.id


def test_remove_player_active_deletes_location_history(client: TestClient, session: Session):
    """Player leaving mid-game has their location history deleted."""
    game = create_game(session, status=GameStatus.seeking)
    host = _get_host(session, game)
    host.role = PlayerRole.hider
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    seeker2 = create_player(session, game.id, name='Seeker2', role=PlayerRole.seeker)
    session.flush()

    # Create location history for the leaving player
    create_location_update(session, seeker.id, game.id, coordinates=Point(0.5, 0.5))
    create_location_update(session, seeker.id, game.id, coordinates=Point(0.6, 0.6))
    # And one for another player (should NOT be deleted)
    create_location_update(session, seeker2.id, game.id, coordinates=Point(0.7, 0.7))

    resp = client.delete(
        f'/games/{game.id}/players/{seeker.id}',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204

    # Leaving player's locations should be gone
    remaining = session.scalars(
        select(LocationUpdate).where(LocationUpdate.game_id == game.id)
    ).all()
    assert len(remaining) == 1
    assert remaining[0].player_id == seeker2.id


# ── Expand hiding zone ──────────────────────────────────────────────────


def test_expand_hiding_zone_success(client: TestClient, session: Session):
    """Hider can expand the hiding zone during seeking phase."""
    game = create_game(session, status=GameStatus.seeking)
    host = _get_host(session, game)
    host.role = PlayerRole.hider
    create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    session.flush()

    resp = client.post(
        f'/games/{game.id}/expand-hiding-zone',
        headers=_headers(host.id),
    )
    assert resp.status_code == 204
    session.refresh(game)
    assert game.hiding_zone_expanded is True


def test_expand_hiding_zone_seeker_forbidden(client: TestClient, session: Session):
    """Seekers cannot expand the hiding zone."""
    game = create_game(session, status=GameStatus.seeking)
    host = _get_host(session, game)
    host.role = PlayerRole.hider
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    session.flush()

    resp = client.post(
        f'/games/{game.id}/expand-hiding-zone',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 403


def test_expand_hiding_zone_wrong_phase(client: TestClient, session: Session):
    """Expanding is only allowed during seeking phase."""
    game = create_game(session, status=GameStatus.hiding)
    host = _get_host(session, game)
    host.role = PlayerRole.hider
    create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    session.flush()

    resp = client.post(
        f'/games/{game.id}/expand-hiding-zone',
        headers=_headers(host.id),
    )
    assert resp.status_code == 409


def test_expand_hiding_zone_already_expanded(client: TestClient, session: Session):
    """Cannot expand twice."""
    game = create_game(session, status=GameStatus.seeking)
    host = _get_host(session, game)
    host.role = PlayerRole.hider
    create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)
    session.flush()

    resp1 = client.post(
        f'/games/{game.id}/expand-hiding-zone',
        headers=_headers(host.id),
    )
    assert resp1.status_code == 204

    resp2 = client.post(
        f'/games/{game.id}/expand-hiding-zone',
        headers=_headers(host.id),
    )
    assert resp2.status_code == 409
