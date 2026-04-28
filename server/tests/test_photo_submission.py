"""Tests for photo submission endpoints (queue/submit/null/unqueue/fetch)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from datetime import datetime
from typing import Any
from unittest.mock import patch

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hideandseek_core.broadcast.emit import hider_channel, seeker_channel
from hideandseek_core.config import S3Config
from hideandseek_core.db import get_session
from hideandseek_models.game import Game, Player
from hideandseek_models.question import Question
from hideandseek_models.types import (
    GameplayEventType,
    GameStatus,
    PlayerRole,
    QuestionStatus,
    QuestionType,
)

from .conftest import TEST_SECRET, create_game, create_player

# ── Fixtures: redis + S3 mocks ──────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patch_redis() -> Generator[fakeredis.FakeRedis, None, None]:
    fake = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    with patch('hideandseek_core.broadcast.emit.get_sync_redis', return_value=fake):
        yield fake


class FakeS3:
    """In-memory S3 stand-in keyed by object key."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def upload(self, key: str, body: Any, content_type: str) -> None:
        data = body.read() if hasattr(body, 'read') else body
        self.objects[key] = (data, content_type)

    def get(self, key: str) -> dict[str, Any]:
        body_bytes, content_type = self.objects[key]

        class _Stream:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def iter_chunks(self) -> Generator[bytes, None, None]:
                yield self._data

        return {
            'Body': _Stream(body_bytes),
            'ContentType': content_type,
            'ContentLength': len(body_bytes),
        }


@pytest.fixture
def fake_s3() -> Generator[FakeS3, None, None]:
    fake = FakeS3()
    config = S3Config(bucket_name='test-bucket', endpoint_url=None)
    with (
        patch('hideandseek.routers.questions.load_s3_config', return_value=config),
        patch(
            'hideandseek.routers.questions.upload_bytes',
            side_effect=lambda _cfg, key, body, ct: fake.upload(key, body, ct),
        ),
        patch(
            'hideandseek.routers.questions.get_object_stream',
            side_effect=lambda _cfg, key: fake.get(key),
        ),
    ):
        yield fake


# ── Helpers ─────────────────────────────────────────────────────────────


def _headers(player_id: uuid.UUID) -> dict[str, str]:
    return {'X-Player-Id': str(player_id), 'X-Player-Secret': TEST_SECRET}


_JPEG_HEADER = b'\xff\xd8\xff\xe0' + b'\x00' * 16 + b'JFIF' + b'\x00' * 100
_PNG_HEADER = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100


def _setup_photo_question(
    client: TestClient, session: Session, game_status: GameStatus = GameStatus.seeking
) -> tuple[Game, Player, Player, Question]:
    """Seeking game with a photo question already in 'answerable' status."""
    game = create_game(session, status=game_status)
    hider = create_player(session, game.id, name='H', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='S', role=PlayerRole.seeker)

    resp = client.post(
        f'/games/{game.id}/questions/photo',
        json={'location': {'type': 'Point', 'coordinates': [-0.1, 51.5]}, 'slot_index': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204, resp.text
    question = session.query(Question).filter_by(game_id=game.id).one()
    session.refresh(question)
    return game, hider, seeker, question


def _drain(pubsub: Any, expected: int) -> list[dict[str, Any]]:
    """Collect `expected` published messages (ignoring subscribe confirmations)."""
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


# ── 1. Upload + queue (no submit) ──────────────────────────────────────


def test_upload_queue_only(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
    _patch_redis: fakeredis.FakeRedis,
):
    game, hider, seeker, question = _setup_photo_question(client, session)

    pubsub_hider = _patch_redis.pubsub()
    pubsub_hider.subscribe(hider_channel(game.id).pubsub)
    pubsub_seeker = _patch_redis.pubsub()
    pubsub_seeker.subscribe(seeker_channel(game.id).pubsub)

    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('photo.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'false'},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204, resp.text

    session.refresh(question)
    assert question.status == QuestionStatus.answerable
    assert question.photo_params is not None
    assert question.photo_params.photo_object_key is not None
    assert question.photo_params.submitted_at is None
    assert not question.photo_params.is_null_answer

    stored_key = question.photo_params.photo_object_key
    assert stored_key in fake_s3.objects
    assert fake_s3.objects[stored_key][0] == _JPEG_HEADER
    assert fake_s3.objects[stored_key][1] == 'image/jpeg'

    hider_msgs = _drain(pubsub_hider, 1)
    seeker_msgs = _drain(pubsub_seeker, 0)
    assert len(hider_msgs) == 1
    assert hider_msgs[0]['event'] == GameplayEventType.photo_queued.value
    assert hider_msgs[0]['data']['question_id'] == str(question.id)
    assert len(seeker_msgs) == 0


# ── 2. Upload + submit (one-shot) ──────────────────────────────────────


def test_upload_and_submit(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
    _patch_redis: fakeredis.FakeRedis,
):
    game, hider, seeker, question = _setup_photo_question(client, session)

    pubsub_hider = _patch_redis.pubsub()
    pubsub_hider.subscribe(hider_channel(game.id).pubsub)
    pubsub_seeker = _patch_redis.pubsub()
    pubsub_seeker.subscribe(seeker_channel(game.id).pubsub)

    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('photo.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'true'},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    session.refresh(question)
    assert question.status == QuestionStatus.submitted
    assert question.photo_params is not None
    assert question.photo_params.submitted_at is not None
    assert question.photo_params.submitted_by == hider.id

    hider_msgs = _drain(pubsub_hider, 2)
    seeker_msgs = _drain(pubsub_seeker, 1)
    hider_events = {m['event'] for m in hider_msgs}
    assert GameplayEventType.photo_queued.value in hider_events
    assert GameplayEventType.photo_submitted.value in hider_events
    assert len(seeker_msgs) == 1
    assert seeker_msgs[0]['event'] == GameplayEventType.photo_submitted.value
    submitted_data = seeker_msgs[0]['data']
    assert submitted_data['is_null_answer'] is False
    assert submitted_data['review_deadline'] is not None


# ── 3. Null submit ──────────────────────────────────────────────────────


def test_null_submit(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
    _patch_redis: fakeredis.FakeRedis,
):
    game, hider, seeker, question = _setup_photo_question(client, session)

    pubsub_hider = _patch_redis.pubsub()
    pubsub_hider.subscribe(hider_channel(game.id).pubsub)
    pubsub_seeker = _patch_redis.pubsub()
    pubsub_seeker.subscribe(seeker_channel(game.id).pubsub)

    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        json={'null': True},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    session.refresh(question)
    assert question.status == QuestionStatus.submitted
    assert question.photo_params is not None
    assert question.photo_params.is_null_answer is True
    assert question.photo_params.photo_object_key is None
    assert fake_s3.objects == {}

    hider_msgs = _drain(pubsub_hider, 1)
    seeker_msgs = _drain(pubsub_seeker, 1)
    # No photo_queued event on null-submit
    assert all(m['event'] != GameplayEventType.photo_queued.value for m in hider_msgs)
    assert hider_msgs[-1]['event'] == GameplayEventType.photo_submitted.value
    assert hider_msgs[-1]['data']['is_null_answer'] is True
    assert seeker_msgs[0]['event'] == GameplayEventType.photo_submitted.value


def test_null_submit_requires_flag(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game, hider, seeker, question = _setup_photo_question(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        json={},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 422


# ── 4. Replace queued photo ────────────────────────────────────────────


def test_replace_queued_photo(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game, hider, seeker, question = _setup_photo_question(client, session)

    first_bytes = _JPEG_HEADER + b'first'
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.jpg', first_bytes, 'image/jpeg')},
        data={'submit': 'false'},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204
    session.refresh(question)
    assert question.photo_params is not None
    first_key = question.photo_params.photo_object_key
    assert first_key is not None

    second_bytes = _PNG_HEADER + b'second'
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('b.png', second_bytes, 'image/png')},
        data={'submit': 'false'},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204
    session.refresh(question)
    assert question.photo_params is not None
    second_key = question.photo_params.photo_object_key
    assert second_key is not None
    assert second_key != first_key

    # Old key still present in S3 (photos kept forever per design §10)
    assert first_key in fake_s3.objects
    assert second_key in fake_s3.objects


# ── 5. Unqueue ─────────────────────────────────────────────────────────


def test_unqueue_clears_state(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
    _patch_redis: fakeredis.FakeRedis,
):
    game, hider, seeker, question = _setup_photo_question(client, session)

    client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'false'},
        headers=_headers(hider.id),
    )
    session.refresh(question)
    assert question.photo_params is not None
    assert question.photo_params.photo_object_key is not None

    pubsub_hider = _patch_redis.pubsub()
    pubsub_hider.subscribe(hider_channel(game.id).pubsub)
    pubsub_seeker = _patch_redis.pubsub()
    pubsub_seeker.subscribe(seeker_channel(game.id).pubsub)

    resp = client.delete(
        f'/games/{game.id}/questions/{question.id}/photo',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204
    session.refresh(question)
    assert question.status == QuestionStatus.answerable
    assert question.photo_params is not None
    assert question.photo_params.photo_object_key is None
    assert question.photo_params.is_null_answer is False

    hider_msgs = _drain(pubsub_hider, 1)
    seeker_msgs = _drain(pubsub_seeker, 0)
    assert len(hider_msgs) == 1
    assert hider_msgs[0]['event'] == GameplayEventType.photo_unqueued.value
    assert len(seeker_msgs) == 0


def test_unqueue_after_submit_is_409(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game, hider, seeker, question = _setup_photo_question(client, session)
    client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'true'},
        headers=_headers(hider.id),
    )
    resp = client.delete(
        f'/games/{game.id}/questions/{question.id}/photo',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 409


# ── 6. State-sensitive fetch ───────────────────────────────────────────


def test_fetch_hider_before_submit(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game, hider, seeker, question = _setup_photo_question(client, session)
    client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'false'},
        headers=_headers(hider.id),
    )
    resp = client.get(
        f'/games/{game.id}/questions/{question.id}/photo',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 200
    assert resp.content == _JPEG_HEADER
    assert resp.headers['content-type'] == 'image/jpeg'


def test_fetch_seeker_before_submit_is_403(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game, hider, seeker, question = _setup_photo_question(client, session)
    client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'false'},
        headers=_headers(hider.id),
    )
    resp = client.get(
        f'/games/{game.id}/questions/{question.id}/photo',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 403


def test_fetch_seeker_after_submit(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game, hider, seeker, question = _setup_photo_question(client, session)
    client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'true'},
        headers=_headers(hider.id),
    )
    resp = client.get(
        f'/games/{game.id}/questions/{question.id}/photo',
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 200
    assert resp.content == _JPEG_HEADER


def test_fetch_hider_after_submit(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game, hider, seeker, question = _setup_photo_question(client, session)
    client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'true'},
        headers=_headers(hider.id),
    )
    resp = client.get(
        f'/games/{game.id}/questions/{question.id}/photo',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 200


def test_fetch_null_answer_is_404(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game, hider, seeker, question = _setup_photo_question(client, session)
    client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        json={'null': True},
        headers=_headers(hider.id),
    )
    resp = client.get(
        f'/games/{game.id}/questions/{question.id}/photo',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 404


def test_fetch_no_photo_queued_is_404(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game, hider, seeker, question = _setup_photo_question(client, session)
    resp = client.get(
        f'/games/{game.id}/questions/{question.id}/photo',
        headers=_headers(hider.id),
    )
    assert resp.status_code == 404


# ── 7. Submission lock ─────────────────────────────────────────────────


def test_second_upload_after_submit_is_409(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game, hider, seeker, question = _setup_photo_question(client, session)
    client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'true'},
        headers=_headers(hider.id),
    )
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('b.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'true'},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 409
    assert 'already submitted' in resp.json()['detail'].lower()


# ── 8. Content-type validation ─────────────────────────────────────────


def test_plain_text_content_type_rejected(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game, hider, seeker, question = _setup_photo_question(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.txt', b'hello', 'text/plain')},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 415


def test_mislabeled_image_rejected(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    """Bytes starting with JPEG magic but claimed as PNG → 415."""
    game, hider, seeker, question = _setup_photo_question(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.png', _JPEG_HEADER, 'image/png')},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 415


# ── 9. Wrong question type ─────────────────────────────────────────────


def test_submit_photo_to_radar_question_is_422(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game = create_game(session, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='H', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='S', role=PlayerRole.seeker)

    # Report seeker location and ask a radar question
    client.post(
        f'/games/{game.id}/location',
        json={
            'coordinates': {'type': 'Point', 'coordinates': [-0.1, 51.5]},
            'timestamp': '2026-02-11T10:00:00Z',
        },
        headers=_headers(seeker.id),
    )
    resp = client.post(
        f'/games/{game.id}/questions/radar',
        json={'location': {'type': 'Point', 'coordinates': [-0.1, 51.5]}, 'slot_index': 0},
        headers=_headers(seeker.id),
    )
    assert resp.status_code == 204
    sess = get_session()
    radar_q = (
        sess.query(Question).filter_by(game_id=game.id, question_type=QuestionType.radar).one()
    )

    resp = client.post(
        f'/games/{game.id}/questions/{radar_q.id}/photo',
        files={'file': ('a.jpg', _JPEG_HEADER, 'image/jpeg')},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 422


# ── 10. Wrong game_id ──────────────────────────────────────────────────


def test_question_from_different_game_is_422(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    game_a, hider_a, _seeker_a, question_a = _setup_photo_question(client, session)

    game_b = create_game(session, status=GameStatus.seeking)
    hider_b = create_player(session, game_b.id, name='Hb', role=PlayerRole.hider)

    resp = client.post(
        f'/games/{game_b.id}/questions/{question_a.id}/photo',
        files={'file': ('a.jpg', _JPEG_HEADER, 'image/jpeg')},
        headers=_headers(hider_b.id),
    )
    assert resp.status_code == 422


# ── 11. Review deadline math ──────────────────────────────────────────


def test_submit_sets_review_deadline(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
    _patch_redis: fakeredis.FakeRedis,
):
    """review_deadline ≈ submitted_at + effective_photo_review_sec(game)."""
    game, hider, seeker, question = _setup_photo_question(client, session)

    pubsub = _patch_redis.pubsub()
    pubsub.subscribe(seeker_channel(game.id).pubsub)

    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'true'},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 204

    msgs = _drain(pubsub, 1)
    assert len(msgs) == 1
    data = msgs[0]['data']
    # Code default: 30s for a game without overrides
    submitted = datetime.fromisoformat(data['submitted_at'].replace('Z', '+00:00'))
    deadline = datetime.fromisoformat(data['review_deadline'].replace('Z', '+00:00'))
    delta = (deadline - submitted).total_seconds()
    assert 29 <= delta <= 31


# ── Submit-already-queued (multipart, no file) ─────────────────────────


def test_submit_queued_via_multipart_no_file(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
    _patch_redis: fakeredis.FakeRedis,
):
    """Hider A queues; hider B submits via multipart submit=true with no file."""
    game, hider_a, seeker, question = _setup_photo_question(client, session)
    hider_b = create_player(session, game.id, name='B', role=PlayerRole.hider)

    # A queues
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'false'},
        headers=_headers(hider_a.id),
    )
    assert resp.status_code == 204
    session.refresh(question)
    assert question.photo_params is not None
    queued_key = question.photo_params.photo_object_key
    assert queued_key is not None

    # B submits without re-uploading — files= forces multipart encoding
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'submit': (None, 'true')},
        headers=_headers(hider_b.id),
    )
    assert resp.status_code == 204, resp.text
    session.refresh(question)
    assert question.status == QuestionStatus.submitted
    assert question.photo_params is not None
    assert question.photo_params.submitted_by == hider_b.id
    # S3 object key unchanged — bytes were not re-uploaded
    assert question.photo_params.photo_object_key == queued_key


def test_submit_queued_no_file_no_queued_is_422(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    """submit=true with no file and nothing queued → 422."""
    game, hider, seeker, question = _setup_photo_question(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'submit': (None, 'true')},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 422


def test_submit_queued_no_file_no_submit_is_422(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    """multipart with no file and submit=false → 422."""
    game, hider, seeker, question = _setup_photo_question(client, session)
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'submit': (None, 'false')},
        headers=_headers(hider.id),
    )
    assert resp.status_code == 422


def test_submit_queued_409_after_submitted(
    client: TestClient,
    session: Session,
    fake_s3: FakeS3,
):
    """Once submitted, second hider's no-file submit → 409."""
    game, hider_a, seeker, question = _setup_photo_question(client, session)
    hider_b = create_player(session, game.id, name='B', role=PlayerRole.hider)

    # A queues + submits
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'file': ('a.jpg', _JPEG_HEADER, 'image/jpeg')},
        data={'submit': 'true'},
        headers=_headers(hider_a.id),
    )
    assert resp.status_code == 204

    # B tries to submit-the-already-queued — but it's already submitted
    resp = client.post(
        f'/games/{game.id}/questions/{question.id}/photo',
        files={'submit': (None, 'true')},
        headers=_headers(hider_b.id),
    )
    assert resp.status_code == 409
