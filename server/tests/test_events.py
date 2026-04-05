"""Tests for the SSE events endpoint."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hideandseek.db import _session_var
from hideandseek_models.types import GameStatus, PlayerColor, PlayerRole
from tests.conftest import TEST_SECRET, create_game, create_player


class TestLobbySSEAuth:
    """Auth validation for GET /games/{game_id}/lobby/events."""

    def test_404_game_not_found(self, client: TestClient, session: Session) -> None:
        game = create_game(session)
        player = create_player(session, game.id)
        fake_game_id = uuid.uuid4()
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{fake_game_id}/lobby/events',
                headers={'X-Player-Id': str(player.id), 'X-Player-Secret': TEST_SECRET},
            )
        assert resp.status_code == 404

    def test_409_game_not_in_lobby(self, client: TestClient, session: Session) -> None:
        game = create_game(session, status=GameStatus.hiding)
        player = create_player(session, game.id)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game.id}/lobby/events',
                headers={'X-Player-Id': str(player.id), 'X-Player-Secret': TEST_SECRET},
            )
        assert resp.status_code == 409

    def test_401_invalid_credentials(self, client: TestClient, session: Session) -> None:
        game = create_game(session)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game.id}/lobby/events',
                headers={'X-Player-Id': str(uuid.uuid4()), 'X-Player-Secret': 'wrong'},
            )
        assert resp.status_code == 401


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


# ── Hider State SSE Auth Tests ─────────────────────────────────────────────


class TestHiderStateAuth:
    """Auth and phase validation for GET /games/{game_id}/hider-state."""

    def test_404_game_not_found(self, client: TestClient, session: Session) -> None:
        game = create_game(session, status=GameStatus.hiding)
        player = create_player(session, game.id, role=PlayerRole.hider)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{uuid.uuid4()}/hider-state',
                headers={'X-Player-Id': str(player.id), 'X-Player-Secret': TEST_SECRET},
            )
        assert resp.status_code == 404

    def test_409_game_not_active(self, client: TestClient, session: Session) -> None:
        game = create_game(session, status=GameStatus.lobby)
        player = create_player(session, game.id, role=PlayerRole.hider)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game.id}/hider-state',
                headers={'X-Player-Id': str(player.id), 'X-Player-Secret': TEST_SECRET},
            )
        assert resp.status_code == 409

    def test_401_invalid_credentials(self, client: TestClient, session: Session) -> None:
        game = create_game(session, status=GameStatus.hiding)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game.id}/hider-state',
                headers={'X-Player-Id': str(uuid.uuid4()), 'X-Player-Secret': 'wrong'},
            )
        assert resp.status_code == 401

    def test_403_not_in_game(self, client: TestClient, session: Session) -> None:
        game1 = create_game(session, status=GameStatus.hiding)
        game2 = create_game(session, status=GameStatus.hiding)
        player = create_player(session, game2.id, role=PlayerRole.hider)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game1.id}/hider-state',
                headers={'X-Player-Id': str(player.id), 'X-Player-Secret': TEST_SECRET},
            )
        assert resp.status_code == 403

    def test_403_wrong_role(self, client: TestClient, session: Session) -> None:
        game = create_game(session, status=GameStatus.hiding)
        seeker = create_player(session, game.id, role=PlayerRole.seeker, color=PlayerColor.cyan)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game.id}/hider-state',
                headers={'X-Player-Id': str(seeker.id), 'X-Player-Secret': TEST_SECRET},
            )
        assert resp.status_code == 403

    def test_409_finished_game(self, client: TestClient, session: Session) -> None:
        game = create_game(session, status=GameStatus.finished)
        player = create_player(session, game.id, role=PlayerRole.hider)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game.id}/hider-state',
                headers={'X-Player-Id': str(player.id), 'X-Player-Secret': TEST_SECRET},
            )
        assert resp.status_code == 409


# ── Seeker State SSE Auth Tests ────────────────────────────────────────────


class TestSeekerStateAuth:
    """Auth and phase validation for GET /games/{game_id}/seeker-state."""

    def test_404_game_not_found(self, client: TestClient, session: Session) -> None:
        game = create_game(session, status=GameStatus.hiding)
        player = create_player(session, game.id, role=PlayerRole.seeker)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{uuid.uuid4()}/seeker-state',
                headers={'X-Player-Id': str(player.id), 'X-Player-Secret': TEST_SECRET},
            )
        assert resp.status_code == 404

    def test_409_game_not_active(self, client: TestClient, session: Session) -> None:
        game = create_game(session, status=GameStatus.lobby)
        player = create_player(session, game.id, role=PlayerRole.seeker)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game.id}/seeker-state',
                headers={'X-Player-Id': str(player.id), 'X-Player-Secret': TEST_SECRET},
            )
        assert resp.status_code == 409

    def test_401_invalid_credentials(self, client: TestClient, session: Session) -> None:
        game = create_game(session, status=GameStatus.hiding)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game.id}/seeker-state',
                headers={'X-Player-Id': str(uuid.uuid4()), 'X-Player-Secret': 'wrong'},
            )
        assert resp.status_code == 401

    def test_403_not_in_game(self, client: TestClient, session: Session) -> None:
        game1 = create_game(session, status=GameStatus.hiding)
        game2 = create_game(session, status=GameStatus.hiding)
        player = create_player(session, game2.id, role=PlayerRole.seeker)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game1.id}/seeker-state',
                headers={'X-Player-Id': str(player.id), 'X-Player-Secret': TEST_SECRET},
            )
        assert resp.status_code == 403

    def test_403_wrong_role(self, client: TestClient, session: Session) -> None:
        game = create_game(session, status=GameStatus.hiding)
        hider = create_player(session, game.id, role=PlayerRole.hider, color=PlayerColor.cyan)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game.id}/seeker-state',
                headers={'X-Player-Id': str(hider.id), 'X-Player-Secret': TEST_SECRET},
            )
        assert resp.status_code == 403

    def test_409_finished_game(self, client: TestClient, session: Session) -> None:
        game = create_game(session, status=GameStatus.finished)
        player = create_player(session, game.id, role=PlayerRole.seeker)
        with _patch_session_scope(session):
            resp = client.get(
                f'/games/{game.id}/seeker-state',
                headers={'X-Player-Id': str(player.id), 'X-Player-Secret': TEST_SECRET},
            )
        assert resp.status_code == 409
