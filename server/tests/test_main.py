from __future__ import annotations

from fastapi.testclient import TestClient

from hideandseek.main import app

client = TestClient(app)


def test_root():
    response = client.get('/')
    assert response.status_code == 200
    assert response.json() == {'message': 'Hello, HideAndSeek!'}


def test_health():
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
