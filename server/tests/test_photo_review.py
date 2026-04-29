"""Tests for photo review endpoints (accept/reject) and reconciler auto-resolve."""

from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hideandseek_core.broadcast.emit import hider_channel, seeker_channel
from hideandseek_core.config import S3Config
from hideandseek_core.logic.timers import (
    find_overdue_answerable_questions,
    find_overdue_photo_reviews,
    find_overdue_photo_submissions,
)
from hideandseek_models.game import Game, Player
from hideandseek_models.question import Question
from hideandseek_models.types import (
    GameStatus,
    PhotoReviewDecision,
    PlayerRole,
    QuestionStatus,
)

from .conftest import TEST_SECRET, create_game, create_player


@pytest.fixture(autouse=True)
def _patch_redis() -> Generator[fakeredis.FakeRedis, None, None]:
    fake = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    with patch('hideandseek_core.broadcast.emit.get_sync_redis', return_value=fake):
        yield fake


class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def upload(self, key: str, body: Any, _ct: str) -> None:
        self.objects[key] = body.read() if hasattr(body, 'read') else body


@pytest.fixture
def fake_s3() -> Generator[_FakeS3, None, None]:
    fake = _FakeS3()
    config = S3Config(bucket_name='test-bucket', endpoint_url=None)
    with (
        patch('hideandseek.routers.questions.load_s3_config', return_value=config),
        patch(
            'hideandseek.routers.questions.upload_bytes',
            side_effect=lambda _cfg, key, body, ct: fake.upload(key, body, ct),
        ),
    ):
        yield fake


def _headers(player_id: uuid.UUID) -> dict[str, str]:
    return {'X-Player-Id': str(player_id), 'X-Player-Secret': TEST_SECRET}


_JPEG_HEADER = b'\xff\xd8\xff\xe0' + b'\x00' * 16 + b'JFIF' + b'\x00' * 100


def _setup_submitted_photo(
    client: TestClient, session: Session, fake_s3: _FakeS3
) -> tuple[Game, Player, Player, Question]:
    """Game in seeking with a photo question already in `submitted` status."""
    game = create_game(session, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='H', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='S', role=PlayerRole.seeker)

    resp = client.post(
        f'/games/{game.id}/questions/photo',
        json={'location': {'type': 'Point', 'coordinates': [-0.1, 51.5]}, 'slot_index': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204, resp.text
    question = session.query(Question).filter_by(game_id=game.id).one()

    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('photo.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'true'},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204, resp.text
    session.refresh(question)
    assert question.status == QuestionStatus.submitted
    return game, hider, seeker, question


def _drain(pubsub: Any, expected: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _ in range(expected * 2 + 5):
        msg = pubsub.get_message()
        if msg is None:
            break
        if msg['type'] == 'message':
            out.append(json.loads(msg['data']))
            if len(out) >= expected:
                break
    return out


# ── Accept ──────────────────────────────────────────────────────────────


def test_accept_photo_transitions_and_emits(
    client: TestClient,
    session: Session,
    fake_s3: _FakeS3,
    _patch_redis: fakeredis.FakeRedis,
):
    game, hider, seeker, question = _setup_submitted_photo(client, session, fake_s3)

    pubsub_hider = _patch_redis.pubsub()
    pubsub_hider.subscribe(hider_channel(game.id).pubsub)
    pubsub_seeker = _patch_redis.pubsub()
    pubsub_seeker.subscribe(seeker_channel(game.id).pubsub)

    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/accept',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204, resp.text

    session.refresh(question)
    assert question.status == QuestionStatus.answered
    assert question.exclusion is None
    assert question.answer is not None  # photo object key
    pp = question.photo_params
    assert pp is not None
    assert pp.review_decision == PhotoReviewDecision.accepted
    assert pp.reviewed_by == seeker.id

    hider_msgs = _drain(pubsub_hider, 1)
    seeker_msgs = _drain(pubsub_seeker, 1)
    assert hider_msgs[-1]['event'] == 'question_answered'
    assert seeker_msgs[-1]['event'] == 'question_answered'


def test_accept_photo_wrong_status_is_409(
    client: TestClient,
    session: Session,
    fake_s3: _FakeS3,
):
    game, _hider, seeker, question = _setup_submitted_photo(client, session, fake_s3)
    # First accept succeeds
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/accept',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204
    # Second accept should 409 — already answered
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/accept',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 409


def test_accept_blocked_for_hider(
    client: TestClient,
    session: Session,
    fake_s3: _FakeS3,
):
    game, hider, _seeker, question = _setup_submitted_photo(client, session, fake_s3)
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/accept',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 403


# ── Reject ──────────────────────────────────────────────────────────────


def test_reject_photo_bounces_to_answerable(
    client: TestClient,
    session: Session,
    fake_s3: _FakeS3,
    _patch_redis: fakeredis.FakeRedis,
):
    game, hider, seeker, question = _setup_submitted_photo(client, session, fake_s3)

    pubsub_hider = _patch_redis.pubsub()
    pubsub_hider.subscribe(hider_channel(game.id).pubsub)
    pubsub_seeker = _patch_redis.pubsub()
    pubsub_seeker.subscribe(seeker_channel(game.id).pubsub)

    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/reject',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204, resp.text

    session.refresh(question)
    assert question.status == QuestionStatus.answerable
    assert question.answerable_at is not None
    pp = question.photo_params
    assert pp is not None
    assert pp.review_decision == PhotoReviewDecision.rejected
    assert pp.photo_object_key is None
    assert pp.is_null_answer is False
    assert pp.submitted_at is None
    assert pp.submitted_by is None

    hider_msgs = _drain(pubsub_hider, 1)
    seeker_msgs = _drain(pubsub_seeker, 1)
    assert hider_msgs[-1]['event'] == 'photo_rejected'
    assert seeker_msgs[-1]['event'] == 'photo_rejected'


def test_reject_then_resubmit_round_trip(
    client: TestClient,
    session: Session,
    fake_s3: _FakeS3,
):
    game, hider, seeker, question = _setup_submitted_photo(client, session, fake_s3)

    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/reject',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204
    session.refresh(question)
    assert question.status == QuestionStatus.answerable

    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('photo.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'true'},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204
    session.refresh(question)
    assert question.status == QuestionStatus.submitted

    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/accept',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204
    session.refresh(question)
    assert question.status == QuestionStatus.answered


# ── Veto / randomize blocked on submitted ──────────────────────────────


def test_veto_blocked_in_submitted(
    client: TestClient,
    session: Session,
    fake_s3: _FakeS3,
):
    game, hider, _seeker, question = _setup_submitted_photo(client, session, fake_s3)
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/veto',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 409


def test_randomize_blocked_in_submitted(
    client: TestClient,
    session: Session,
    fake_s3: _FakeS3,
):
    game, hider, _seeker, question = _setup_submitted_photo(client, session, fake_s3)
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/randomize',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 409


# ── Reconciler exclusion ────────────────────────────────────────────────


def test_reconciler_excludes_photo_from_answerable_query(
    client: TestClient,
    session: Session,
    fake_s3: _FakeS3,
):
    game = create_game(session, status=GameStatus.seeking)
    create_player(session, game.id, name='H', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='S', role=PlayerRole.seeker)

    resp = client.post(
        f'/games/{game.id}/questions/photo',
        json={'location': {'type': 'Point', 'coordinates': [-0.1, 51.5]}, 'slot_index': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204
    question = session.query(Question).filter_by(game_id=game.id).one()
    # Force the photo's answerable_at far back so submit window has lapsed
    question.answerable_at = datetime.now(UTC) - timedelta(hours=1)
    session.flush()

    answerable_overdue = find_overdue_answerable_questions()
    assert question.id not in answerable_overdue

    photo_overdue = find_overdue_photo_submissions()
    assert question.id in photo_overdue


def test_reconciler_finds_overdue_photo_review(
    client: TestClient,
    session: Session,
    fake_s3: _FakeS3,
):
    game, _hider, _seeker, question = _setup_submitted_photo(client, session, fake_s3)
    pp = question.photo_params
    assert pp is not None
    pp.submitted_at = datetime.now(UTC) - timedelta(hours=1)
    session.flush()

    review_overdue = find_overdue_photo_reviews()
    assert question.id in review_overdue
