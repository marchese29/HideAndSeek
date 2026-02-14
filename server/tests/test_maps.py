from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.conftest import create_game_map, create_transit_dataset


def test_list_maps_empty(client: TestClient):
    response = client.get('/maps')
    assert response.status_code == 200
    assert response.json() == []


def test_list_maps(client: TestClient, session: Session):
    ds = create_transit_dataset(session, region='London')
    create_game_map(session, name='Zone 1-3', transit_dataset_id=ds.id)
    create_game_map(session, name='Zone 1-6', transit_dataset_id=ds.id)

    response = client.get('/maps')
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]['name'] == 'Zone 1-3'
    assert data[0]['region'] == 'London'
    assert data[1]['name'] == 'Zone 1-6'


def test_list_maps_pagination(client: TestClient, session: Session):
    ds = create_transit_dataset(session)
    for i in range(5):
        create_game_map(session, name=f'Map {i}', transit_dataset_id=ds.id)

    response = client.get('/maps', params={'offset': 2, 'limit': 2})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]['name'] == 'Map 2'


def test_get_map(client: TestClient, session: Session):
    gm = create_game_map(session, name='London Z1-3', notes='Classic map.')

    response = client.get(f'/maps/{gm.id}')
    assert response.status_code == 200
    data = response.json()
    assert data['name'] == 'London Z1-3'
    assert data['notes'] == 'Classic map.'
    assert data['boundary']['type'] == 'Polygon'
    assert 'default_inventory' in data


def test_get_map_not_found(client: TestClient):
    response = client.get(f'/maps/{uuid.uuid4()}')
    assert response.status_code == 404
