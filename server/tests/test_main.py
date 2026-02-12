from __future__ import annotations

from fastapi.testclient import TestClient


def test_root(client: TestClient):
    response = client.get('/')
    assert response.status_code == 200
    assert response.json() == {'message': 'Hello, HideAndSeek!'}


def test_health(client: TestClient):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
