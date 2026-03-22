"""Tests for the SSE events endpoint."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hideandseek.db import _session_var
from hideandseek.models.types import GameStatus
from tests.conftest import create_game, create_player


class TestLobbySSEAuth:
    """Auth validation for GET /games/{game_id}/lobby/events."""

    def test_404_game_not_found(self, client: TestClient, session: Session) -> None:
        fake_id = uuid.uuid4()
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{fake_id}/lobby/events',
                params={'client_id': str(uuid.uuid4())},
            )
        assert resp.status_code == 404

    def test_409_game_not_in_lobby(self, client: TestClient, session: Session) -> None:
        game = create_game(session, status=GameStatus.hiding)
        player = create_player(session, game.id)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game.id}/lobby/events',
                params={'client_id': str(player.client_id)},
            )
        assert resp.status_code == 409

    def test_403_not_a_player(self, client: TestClient, session: Session) -> None:
        game = create_game(session)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game.id}/lobby/events',
                params={'client_id': str(uuid.uuid4())},
            )
        assert resp.status_code == 403


@contextmanager
def _patch_session_scope(session: Session) -> Generator[None, None, None]:
    """Patch session_scope in the events router to reuse the test session."""

    @contextmanager
    def _fake_scope() -> Generator[Session, None, None]:
        token = _session_var.set(session)
        try:
            yield session
        finally:
            _session_var.reset(token)

    with patch('hideandseek.routers.events.session_scope', _fake_scope):
        yield
