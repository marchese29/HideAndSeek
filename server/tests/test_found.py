"""Tests for the two-party found-claim flow (POST /found, /confirm, /reject, auto-dismiss)."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import patch

import fakeredis
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point
from sqlalchemy.orm import Session

from hideandseek_models.game import Game
from hideandseek_models.location import LocationUpdate
from hideandseek_models.transit import Stop
from hideandseek_models.types import EndReason, GameStatus, PlayerRole
from hideandseek_worker.tasks.game_timers import auto_dismiss_found_claim

from .conftest import TEST_SECRET, create_game, create_game_map, create_player


@pytest.fixture(autouse=True)
def _patch_redis() -> Generator[None, None, None]:
    fake = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    with patch('hideandseek_core.broadcast.emit.get_sync_redis', return_value=fake):
        yield


def _headers(player_id: uuid.UUID) -> dict[str, str]:
    return {'X-Player-Id': str(player_id), 'X-Player-Secret': TEST_SECRET}


def _seeking_game_with_station(session: Session) -> tuple[Game, Stop]:
    """Create a seeking-phase game with a hider station at the origin."""
    gm = create_game_map(session)
    stop = Stop(
        stable_id=f'stop-{uuid.uuid4().hex[:8]}',
        dataset_id=gm.transit_dataset_id,
        name='Central Station',
        coordinates=Point(0.5, 0.5),
    )
    session.add(stop)
    session.flush()
    game = create_game(
        session,
        map_id=gm.id,
        status=GameStatus.seeking,
        hider_station_id=stop.id,
    )
    session.refresh(game)
    return game, stop


def _report_seeker_at(session: Session, game: Game, seeker_id: uuid.UUID, point: Point) -> None:
    lu = LocationUpdate(
        player_id=seeker_id,
        game_id=game.id,
        coordinates=point,
        timestamp=datetime.now(UTC),
    )
    session.add(lu)
    session.flush()


# ── POST /found ───────────────────────────────────────────────────────


def test_found_claim_happy_path(session: Session, client: TestClient) -> None:
    game, stop = _seeking_game_with_station(session)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    _report_seeker_at(session, game, seeker.id, stop.coordinates)

    resp = client.post(f'/games/{game.id}/found', headers=_headers(seeker.id))
    assert resp.status_code == 204

    session.expire_all()
    session.refresh(game)
    assert game.found_claim_at is not None
    assert game.found_claim_player_id == seeker.id
    assert game.status == GameStatus.seeking  # still seeking until confirmed


def test_found_claim_seeker_outside_zone(session: Session, client: TestClient) -> None:
    game, stop = _seeking_game_with_station(session)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    # Far away — stop is at (0.5, 0.5), seeker at (1.5, 1.5) ≈ >100 km
    _report_seeker_at(session, game, seeker.id, Point(1.5, 1.5))

    resp = client.post(f'/games/{game.id}/found', headers=_headers(seeker.id))
    assert resp.status_code == 409
    assert 'inside' in resp.json()['detail'].lower()


def test_found_claim_requires_seeking_phase(session: Session, client: TestClient) -> None:
    gm = create_game_map(session)
    game = create_game(session, map_id=gm.id, status=GameStatus.hiding)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    resp = client.post(f'/games/{game.id}/found', headers=_headers(seeker.id))
    assert resp.status_code == 409


def test_found_claim_requires_elected_station(session: Session, client: TestClient) -> None:
    gm = create_game_map(session)
    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    resp = client.post(f'/games/{game.id}/found', headers=_headers(seeker.id))
    assert resp.status_code == 409
    assert 'station' in resp.json()['detail'].lower()


def test_found_claim_requires_location(session: Session, client: TestClient) -> None:
    game, _stop = _seeking_game_with_station(session)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    resp = client.post(f'/games/{game.id}/found', headers=_headers(seeker.id))
    assert resp.status_code == 409


def test_found_claim_rejects_hider(session: Session, client: TestClient) -> None:
    game, _stop = _seeking_game_with_station(session)
    hider = create_player(session, game.id, role=PlayerRole.hider)

    resp = client.post(f'/games/{game.id}/found', headers=_headers(hider.id))
    assert resp.status_code == 403


def test_found_claim_rejects_when_claim_pending(session: Session, client: TestClient) -> None:
    game, stop = _seeking_game_with_station(session)
    seeker_a = create_player(session, game.id, name='A', role=PlayerRole.seeker)
    seeker_b = create_player(session, game.id, name='B', role=PlayerRole.seeker)
    _report_seeker_at(session, game, seeker_a.id, stop.coordinates)
    _report_seeker_at(session, game, seeker_b.id, stop.coordinates)

    assert client.post(f'/games/{game.id}/found', headers=_headers(seeker_a.id)).status_code == 204
    resp = client.post(f'/games/{game.id}/found', headers=_headers(seeker_b.id))
    assert resp.status_code == 409


# ── POST /found/confirm ────────────────────────────────────────────────


def test_found_confirm_ends_game(session: Session, client: TestClient) -> None:
    game, stop = _seeking_game_with_station(session)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    _report_seeker_at(session, game, seeker.id, stop.coordinates)

    assert client.post(f'/games/{game.id}/found', headers=_headers(seeker.id)).status_code == 204
    resp = client.post(f'/games/{game.id}/found/confirm', headers=_headers(hider.id))
    assert resp.status_code == 204

    session.expire_all()
    session.refresh(game)
    assert game.status == GameStatus.finished
    assert game.end_reason == EndReason.found
    assert game.found_claim_at is None
    assert game.found_claim_player_id is None


def test_found_confirm_requires_pending_claim(session: Session, client: TestClient) -> None:
    game, _stop = _seeking_game_with_station(session)
    hider = create_player(session, game.id, role=PlayerRole.hider)

    resp = client.post(f'/games/{game.id}/found/confirm', headers=_headers(hider.id))
    assert resp.status_code == 409


def test_found_confirm_rejects_seeker(session: Session, client: TestClient) -> None:
    game, stop = _seeking_game_with_station(session)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    _report_seeker_at(session, game, seeker.id, stop.coordinates)
    assert client.post(f'/games/{game.id}/found', headers=_headers(seeker.id)).status_code == 204

    resp = client.post(f'/games/{game.id}/found/confirm', headers=_headers(seeker.id))
    assert resp.status_code == 403


# ── POST /found/reject ─────────────────────────────────────────────────


def test_found_reject_clears_claim(session: Session, client: TestClient) -> None:
    game, stop = _seeking_game_with_station(session)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    _report_seeker_at(session, game, seeker.id, stop.coordinates)
    assert client.post(f'/games/{game.id}/found', headers=_headers(seeker.id)).status_code == 204

    resp = client.post(f'/games/{game.id}/found/reject', headers=_headers(hider.id))
    assert resp.status_code == 204

    session.expire_all()
    session.refresh(game)
    assert game.status == GameStatus.seeking
    assert game.end_reason is None
    assert game.found_claim_at is None
    assert game.found_claim_player_id is None


def test_found_reject_allows_new_claim(session: Session, client: TestClient) -> None:
    game, stop = _seeking_game_with_station(session)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    _report_seeker_at(session, game, seeker.id, stop.coordinates)

    assert client.post(f'/games/{game.id}/found', headers=_headers(seeker.id)).status_code == 204
    assert (
        client.post(f'/games/{game.id}/found/reject', headers=_headers(hider.id)).status_code == 204
    )
    # Second claim should succeed now
    assert client.post(f'/games/{game.id}/found', headers=_headers(seeker.id)).status_code == 204


def test_found_reject_requires_pending_claim(session: Session, client: TestClient) -> None:
    game, _stop = _seeking_game_with_station(session)
    hider = create_player(session, game.id, role=PlayerRole.hider)

    resp = client.post(f'/games/{game.id}/found/reject', headers=_headers(hider.id))
    assert resp.status_code == 409


def test_found_reject_rejects_seeker(session: Session, client: TestClient) -> None:
    game, stop = _seeking_game_with_station(session)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    _report_seeker_at(session, game, seeker.id, stop.coordinates)
    assert client.post(f'/games/{game.id}/found', headers=_headers(seeker.id)).status_code == 204

    resp = client.post(f'/games/{game.id}/found/reject', headers=_headers(seeker.id))
    assert resp.status_code == 403


# ── auto_dismiss_found_claim task ─────────────────────────────────────


@pytest.fixture
def _patch_engine(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point session_scope at the test session's engine (same pattern as test_game_timers)."""
    monkeypatch.setattr('hideandseek_core.db.get_engine', lambda: session.get_bind())


def test_auto_dismiss_clears_pending_claim(session: Session, _patch_engine: None) -> None:
    game, stop = _seeking_game_with_station(session)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    game.found_claim_at = datetime.now(UTC)
    game.found_claim_player_id = seeker.id
    session.flush()
    session.commit()

    auto_dismiss_found_claim(str(game.id))

    session.expire_all()
    session.refresh(game)
    assert game.found_claim_at is None
    assert game.found_claim_player_id is None
    assert game.status == GameStatus.seeking


def test_auto_dismiss_noop_when_no_claim(session: Session, _patch_engine: None) -> None:
    game, _stop = _seeking_game_with_station(session)
    session.commit()

    auto_dismiss_found_claim(str(game.id))  # should not raise

    session.expire_all()
    session.refresh(game)
    assert game.found_claim_at is None


def test_auto_dismiss_noop_when_game_finished(session: Session, _patch_engine: None) -> None:
    game, stop = _seeking_game_with_station(session)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    # Claim exists, but game has already been finished out-of-band
    game.found_claim_at = datetime.now(UTC)
    game.found_claim_player_id = seeker.id
    game.status = GameStatus.finished
    session.flush()
    session.commit()

    auto_dismiss_found_claim(str(game.id))

    session.expire_all()
    session.refresh(game)
    # Fields preserved — task treats finished games as terminal
    assert game.found_claim_at is not None
    assert game.status == GameStatus.finished


def test_auto_dismiss_noop_for_missing_game(_patch_engine: None) -> None:
    auto_dismiss_found_claim(str(uuid.uuid4()))  # should not raise
