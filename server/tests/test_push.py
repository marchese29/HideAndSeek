"""Tests for push notification infrastructure."""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session

from hideandseek.models.device_token import DeviceToken
from hideandseek.models.types import PlayerRole, PushEventType
from hideandseek.push import PushService
from hideandseek.queries.device_tokens import (
    delete_device_token,
    get_device_tokens_for_game,
    upsert_device_token,
)
from tests.conftest import create_game, create_player

# ── upsert_device_token ──────────────────────────────────────────────────────


def test_upsert_creates_token(session: Session):
    client_id = uuid.uuid4()
    dt = upsert_device_token(client_id=client_id, token='aabbccdd', environment='sandbox')
    assert dt.client_id == client_id
    assert dt.token == 'aabbccdd'
    assert dt.environment == 'sandbox'
    assert dt.updated_at is not None


def test_upsert_updates_existing_token(session: Session):
    client_id = uuid.uuid4()
    dt1 = upsert_device_token(client_id=client_id, token='old_token')
    original_time = dt1.updated_at

    dt2 = upsert_device_token(client_id=client_id, token='new_token')
    assert dt2.client_id == client_id
    assert dt2.token == 'new_token'
    assert dt2.updated_at >= original_time

    # Only one record in DB
    result = session.get(DeviceToken, client_id)
    assert result is not None
    assert result.token == 'new_token'


# ── get_device_tokens_for_game ────────────────────────────────────────────────


def test_get_device_tokens_for_game(session: Session):
    game = create_game(session)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    upsert_device_token(client_id=hider.client_id, token='hider_token')
    upsert_device_token(client_id=seeker.client_id, token='seeker_token')

    all_tokens = get_device_tokens_for_game(game.id)
    assert len(all_tokens) == 2
    token_values = {dt.token for dt in all_tokens}
    assert token_values == {'hider_token', 'seeker_token'}


def test_get_device_tokens_with_role_filter(session: Session):
    game = create_game(session)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    upsert_device_token(client_id=hider.client_id, token='hider_token')
    upsert_device_token(client_id=seeker.client_id, token='seeker_token')

    hider_tokens = get_device_tokens_for_game(game.id, role_filter=PlayerRole.hider)
    assert len(hider_tokens) == 1
    assert hider_tokens[0].token == 'hider_token'

    seeker_tokens = get_device_tokens_for_game(game.id, role_filter=PlayerRole.seeker)
    assert len(seeker_tokens) == 1
    assert seeker_tokens[0].token == 'seeker_token'


def test_get_device_tokens_excludes_missing(session: Session):
    """Players without a registered device token are excluded."""
    game = create_game(session)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    create_player(session, game.id, role=PlayerRole.seeker)  # no token

    upsert_device_token(client_id=hider.client_id, token='hider_token')

    tokens = get_device_tokens_for_game(game.id)
    assert len(tokens) == 1
    assert tokens[0].token == 'hider_token'


# ── delete_device_token ──────────────────────────────────────────────────────


def test_delete_device_token(session: Session):
    client_id = uuid.uuid4()
    upsert_device_token(client_id=client_id, token='to_delete')
    delete_device_token(client_id)
    assert session.get(DeviceToken, client_id) is None


def test_delete_nonexistent_token(session: Session):
    """Deleting a token that doesn't exist is a no-op."""
    delete_device_token(uuid.uuid4())  # should not raise


# ── PushService ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_push_service_noop_mode():
    """PushService with no config logs but doesn't error."""
    push = PushService(config=None)
    # Should succeed silently in no-op mode
    await push.send_to_tokens(
        ['aabbccdd'],
        uuid.uuid4(),
        PushEventType.game_started,
        alert='Test alert',
    )


@pytest.mark.anyio
async def test_push_service_empty_tokens():
    """PushService returns immediately for empty token list."""
    push = PushService(config=None)
    await push.send_to_tokens(
        [],
        uuid.uuid4(),
        PushEventType.game_started,
        alert='Test alert',
    )


@pytest.mark.anyio
async def test_push_service_builds_standard_payload():
    """Verify the payload structure for a standard (non-silent) push."""
    sent_requests: list[dict] = []

    class FakeAPNs:
        async def send_notification(self, request):  # noqa: ANN001, ANN201, ANN202
            sent_requests.append(request.message)

            class FakeResponse:
                is_successful = True

            return FakeResponse()

    push = PushService(config=None)
    push._client = FakeAPNs()  # type: ignore[assignment]

    game_id = uuid.uuid4()
    question_id = uuid.uuid4()

    await push.send_to_tokens(
        ['aabbccdd'],
        game_id,
        PushEventType.question_asked,
        alert='A 3 km radar question has been asked.',
        question_id=question_id,
        question_type='radar',
        question_status='answerable',
        parameters={'radius': 3000},
    )

    assert len(sent_requests) == 1
    payload = sent_requests[0]
    assert payload['aps']['alert'] == {
        'title': 'Hide & Seek',
        'body': 'A 3 km radar question has been asked.',
    }
    assert payload['aps']['sound'] == 'default'
    assert payload['aps']['content-available'] == 1
    assert payload['aps']['interruption-level'] == 'time-sensitive'
    assert payload['data']['event_type'] == 'question_asked'
    assert payload['data']['game_id'] == str(game_id)
    assert payload['data']['question_id'] == str(question_id)
    assert payload['data']['question_type'] == 'radar'
    assert payload['data']['parameters'] == {'radius': 3000}


@pytest.mark.anyio
async def test_push_service_builds_silent_payload():
    """Verify silent push omits alert and sound."""
    sent_requests: list[dict] = []

    class FakeAPNs:
        async def send_notification(self, request):  # noqa: ANN001, ANN201, ANN202
            sent_requests.append(request.message)

            class FakeResponse:
                is_successful = True

            return FakeResponse()

    push = PushService(config=None)
    push._client = FakeAPNs()  # type: ignore[assignment]

    await push.send_to_tokens(
        ['aabbccdd'],
        uuid.uuid4(),
        PushEventType.phase_changed,
        silent=True,
    )

    assert len(sent_requests) == 1
    payload = sent_requests[0]
    assert payload['aps'] == {'content-available': 1}
    assert 'alert' not in payload['aps']
    assert 'sound' not in payload['aps']
    assert payload['data']['event_type'] == 'phase_changed'
