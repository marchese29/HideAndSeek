"""Tests for the host pause/resume endpoints.

Covers HTTP-layer concerns: host-only auth, phase guards (active-only),
and pause-state conflicts (already-paused / not-paused). The core
primitive's deadline-shift math + SSE emission is covered in test_pause.py;
these tests just confirm the router calls into core and reports correct
HTTP status codes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hideandseek_models.types import GameStatus, PauseReason
from tests.conftest import TEST_SECRET, create_game, create_player


def _headers(player_id: uuid.UUID) -> dict[str, str]:
    return {'X-Player-Id': str(player_id), 'X-Player-Secret': TEST_SECRET}


_NOW = datetime.now(UTC)


# ── POST /games/{game_id}/pause ─────────────────────────────────────────────


def test_pause_during_seeking(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking, join_code=None)
    resp = client.post(f'/games/{game.id}/pause', headers=_headers(game.host_player_id))
    assert resp.status_code == 204
    session.expire(game)
    assert game.paused_at is not None
    assert game.active_pause_reasons == [PauseReason.host]


def test_pause_during_hiding(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.hiding)
    resp = client.post(f'/games/{game.id}/pause', headers=_headers(game.host_player_id))
    assert resp.status_code == 204
    session.expire(game)
    assert game.paused_at is not None
    assert game.active_pause_reasons == [PauseReason.host]


def test_pause_in_lobby_returns_409(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.lobby)
    resp = client.post(f'/games/{game.id}/pause', headers=_headers(game.host_player_id))
    assert resp.status_code == 409
    assert 'lobby' in resp.json()['detail']


def test_pause_when_finished_returns_409(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.finished, join_code=None)
    resp = client.post(f'/games/{game.id}/pause', headers=_headers(game.host_player_id))
    assert resp.status_code == 409


def test_pause_non_host_returns_403(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.seeking, join_code=None)
    non_host = create_player(session, game.id)
    resp = client.post(f'/games/{game.id}/pause', headers=_headers(non_host.id))
    assert resp.status_code == 403


def test_pause_already_host_paused_returns_409(client: TestClient, session: Session):
    game = create_game(
        session,
        status=GameStatus.seeking,
        join_code=None,
        active_pause_reasons=[PauseReason.host],
        paused_at=_NOW,
    )
    resp = client.post(f'/games/{game.id}/pause', headers=_headers(game.host_player_id))
    assert resp.status_code == 409
    assert 'host-paused' in resp.json()['detail']


def test_pause_stacks_on_photo_pause(client: TestClient, session: Session):
    """Host can pause a game already paused for another reason."""
    game = create_game(
        session,
        status=GameStatus.seeking,
        join_code=None,
        active_pause_reasons=[PauseReason.photo_question_open],
        paused_at=_NOW,
    )
    resp = client.post(f'/games/{game.id}/pause', headers=_headers(game.host_player_id))
    assert resp.status_code == 204
    session.expire(game)
    assert PauseReason.host in game.active_pause_reasons
    assert PauseReason.photo_question_open in game.active_pause_reasons


# ── POST /games/{game_id}/resume ────────────────────────────────────────────


def test_resume_during_seeking(client: TestClient, session: Session):
    game = create_game(
        session,
        status=GameStatus.seeking,
        join_code=None,
        active_pause_reasons=[PauseReason.host],
        paused_at=_NOW,
    )
    resp = client.post(f'/games/{game.id}/resume', headers=_headers(game.host_player_id))
    assert resp.status_code == 204
    session.expire(game)
    assert game.paused_at is None
    assert game.active_pause_reasons == []


def test_resume_during_hiding(client: TestClient, session: Session):
    game = create_game(
        session,
        status=GameStatus.hiding,
        active_pause_reasons=[PauseReason.host],
        paused_at=_NOW,
    )
    resp = client.post(f'/games/{game.id}/resume', headers=_headers(game.host_player_id))
    assert resp.status_code == 204
    session.expire(game)
    assert game.paused_at is None


def test_resume_in_lobby_returns_409(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.lobby)
    resp = client.post(f'/games/{game.id}/resume', headers=_headers(game.host_player_id))
    assert resp.status_code == 409


def test_resume_when_finished_returns_409(client: TestClient, session: Session):
    game = create_game(session, status=GameStatus.finished, join_code=None)
    resp = client.post(f'/games/{game.id}/resume', headers=_headers(game.host_player_id))
    assert resp.status_code == 409


def test_resume_non_host_returns_403(client: TestClient, session: Session):
    game = create_game(
        session,
        status=GameStatus.seeking,
        join_code=None,
        active_pause_reasons=[PauseReason.host],
        paused_at=_NOW,
    )
    non_host = create_player(session, game.id)
    resp = client.post(f'/games/{game.id}/resume', headers=_headers(non_host.id))
    assert resp.status_code == 403


def test_resume_when_not_host_paused_returns_409(client: TestClient, session: Session):
    """Host calls resume but no host pause is active."""
    game = create_game(session, status=GameStatus.seeking, join_code=None)
    resp = client.post(f'/games/{game.id}/resume', headers=_headers(game.host_player_id))
    assert resp.status_code == 409
    assert 'host-paused' in resp.json()['detail']


def test_resume_when_only_other_reason_active_returns_409(client: TestClient, session: Session):
    """Host call to resume 409s when the host reason isn't in the set, even
    if other pause reasons are active.
    """
    game = create_game(
        session,
        status=GameStatus.seeking,
        join_code=None,
        active_pause_reasons=[PauseReason.photo_question_open],
        paused_at=_NOW,
    )
    resp = client.post(f'/games/{game.id}/resume', headers=_headers(game.host_player_id))
    assert resp.status_code == 409


def test_resume_partial_keeps_other_reasons(client: TestClient, session: Session):
    """Resuming the host reason while a photo pause is active keeps the
    clock paused (still has photo_question_open in the set).
    """
    game = create_game(
        session,
        status=GameStatus.seeking,
        join_code=None,
        active_pause_reasons=[PauseReason.host, PauseReason.photo_question_open],
        paused_at=_NOW,
    )
    resp = client.post(f'/games/{game.id}/resume', headers=_headers(game.host_player_id))
    assert resp.status_code == 204
    session.expire(game)
    # Host reason removed; photo reason remains; game is still paused.
    assert game.active_pause_reasons == [PauseReason.photo_question_open]
    assert game.paused_at is not None
