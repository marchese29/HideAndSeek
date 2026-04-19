from __future__ import annotations

from fastapi.testclient import TestClient


def test_root(client: TestClient):
    response = client.get('/')
    assert response.status_code == 200
    assert response.json() == {'message': 'Hello, HideAndSeek!'}


def test_healthz(client: TestClient):
    response = client.get('/healthz')
    assert response.status_code == 200
    assert response.content == b''
