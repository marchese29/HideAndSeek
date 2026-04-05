"""Tests for push notification infrastructure."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from hideandseek_core.push import ApnsProvider, FcmProvider, PushService
from hideandseek_core.queries.device_tokens import (
    delete_device_token,
    get_device_tokens_for_game,
    upsert_device_token,
)
from hideandseek_models.device_token import DeviceToken
from hideandseek_models.types import PlayerRole, PushEventType, TokenProvider
from tests.conftest import create_game, create_player

# ── upsert_device_token ──────────────────────────────────────────────────────


def test_upsert_creates_token(session: Session):
    player_id = uuid.uuid4()
    dt = upsert_device_token(player_id=player_id, token='aabbccdd')
    assert dt.player_id == player_id
    assert dt.token == 'aabbccdd'
    assert dt.provider == TokenProvider.apns
    assert dt.updated_at is not None


def test_upsert_creates_fcm_token(session: Session):
    player_id = uuid.uuid4()
    dt = upsert_device_token(player_id=player_id, token='fcm-reg-token', provider='fcm')
    assert dt.player_id == player_id
    assert dt.token == 'fcm-reg-token'
    assert dt.provider == TokenProvider.fcm


def test_upsert_updates_existing_token(session: Session):
    player_id = uuid.uuid4()
    dt1 = upsert_device_token(player_id=player_id, token='old_token')
    original_time = dt1.updated_at

    dt2 = upsert_device_token(player_id=player_id, token='new_token', provider='fcm')
    assert dt2.player_id == player_id
    assert dt2.token == 'new_token'
    assert dt2.provider == TokenProvider.fcm
    assert dt2.updated_at >= original_time

    # Only one record in DB
    result = session.get(DeviceToken, player_id)
    assert result is not None
    assert result.token == 'new_token'
    assert result.provider == TokenProvider.fcm


# ── get_device_tokens_for_game ────────────────────────────────────────────────


def test_get_device_tokens_for_game(session: Session):
    game = create_game(session)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    upsert_device_token(player_id=hider.id, token='hider_token')
    upsert_device_token(player_id=seeker.id, token='seeker_token', provider='fcm')

    all_tokens = get_device_tokens_for_game(game.id)
    assert len(all_tokens) == 2
    token_values = {dt.token for dt in all_tokens}
    assert token_values == {'hider_token', 'seeker_token'}


def test_get_device_tokens_with_role_filter(session: Session):
    game = create_game(session)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    upsert_device_token(player_id=hider.id, token='hider_token')
    upsert_device_token(player_id=seeker.id, token='seeker_token')

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

    upsert_device_token(player_id=hider.id, token='hider_token')

    tokens = get_device_tokens_for_game(game.id)
    assert len(tokens) == 1
    assert tokens[0].token == 'hider_token'


# ── delete_device_token ──────────────────────────────────────────────────────


def test_delete_device_token(session: Session):
    player_id = uuid.uuid4()
    upsert_device_token(player_id=player_id, token='to_delete')
    delete_device_token(player_id)
    assert session.get(DeviceToken, player_id) is None


def test_delete_nonexistent_token(session: Session):
    """Deleting a token that doesn't exist is a no-op."""
    delete_device_token(uuid.uuid4())  # should not raise


# ── PushService ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_push_service_noop_mode():
    """PushService with no config logs but doesn't error."""
    push = PushService(apns_config=None, fcm_config=None)
    await push.send_to_tokens(
        [('aabbccdd', 'apns')],
        uuid.uuid4(),
        PushEventType.game_started,
        alert='Test alert',
    )


@pytest.mark.anyio
async def test_push_service_empty_tokens():
    """PushService returns immediately for empty token list."""
    push = PushService(apns_config=None, fcm_config=None)
    await push.send_to_tokens(
        [],
        uuid.uuid4(),
        PushEventType.game_started,
        alert='Test alert',
    )


@pytest.mark.anyio
async def test_push_service_builds_apns_standard_payload():
    """Verify the APNs payload structure for a standard (non-silent) push."""
    sent_requests: list[dict] = []

    class FakeAPNs:
        async def send_notification(self, request):  # noqa: ANN001, ANN201, ANN202
            sent_requests.append(request.message)

            class FakeResponse:
                is_successful = True

            return FakeResponse()

    push = PushService(apns_config=None, fcm_config=None)
    apns_provider = ApnsProvider.__new__(ApnsProvider)
    apns_provider._client = FakeAPNs()  # type: ignore[assignment]
    push._apns = apns_provider

    game_id = uuid.uuid4()
    question_id = uuid.uuid4()

    await push.send_to_tokens(
        [('aabbccdd', 'apns')],
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
async def test_push_service_builds_apns_silent_payload():
    """Verify silent APNs push omits alert and sound."""
    sent_requests: list[dict] = []

    class FakeAPNs:
        async def send_notification(self, request):  # noqa: ANN001, ANN201, ANN202
            sent_requests.append(request.message)

            class FakeResponse:
                is_successful = True

            return FakeResponse()

    push = PushService(apns_config=None, fcm_config=None)
    apns_provider = ApnsProvider.__new__(ApnsProvider)
    apns_provider._client = FakeAPNs()  # type: ignore[assignment]
    push._apns = apns_provider

    await push.send_to_tokens(
        [('aabbccdd', 'apns')],
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


@pytest.mark.anyio
async def test_push_service_dispatches_fcm():
    """Verify FCM tokens are dispatched to the FCM provider."""
    sent_messages: list[dict] = []

    push = PushService(apns_config=None, fcm_config=None)
    fcm_provider = FcmProvider.__new__(FcmProvider)
    fcm_provider.send = AsyncMock(
        side_effect=lambda tokens, data, **kw: sent_messages.append(  # type: ignore[method-assign]
            {'tokens': tokens, 'data': data, **kw}
        )
    )
    push._fcm = fcm_provider

    game_id = uuid.uuid4()
    await push.send_to_tokens(
        [('fcm-token-123', 'fcm')],
        game_id,
        PushEventType.game_started,
        alert='Game on!',
    )

    fcm_provider.send.assert_called_once()  # type: ignore[union-attr]
    call_args = fcm_provider.send.call_args  # type: ignore[union-attr]
    assert call_args[0][0] == ['fcm-token-123']
    assert call_args[0][1]['event_type'] == 'game_started'
    assert call_args[1]['alert'] == 'Game on!'


@pytest.mark.anyio
async def test_push_service_mixed_providers():
    """Verify mixed APNs + FCM tokens are dispatched to their respective providers."""
    apns_calls: list[dict] = []
    fcm_calls: list[dict] = []

    push = PushService(apns_config=None, fcm_config=None)

    apns_provider = ApnsProvider.__new__(ApnsProvider)
    apns_provider.send = AsyncMock(
        side_effect=lambda tokens, data, **kw: apns_calls.append(  # type: ignore[method-assign]
            {'tokens': tokens}
        )
    )
    push._apns = apns_provider

    fcm_provider = FcmProvider.__new__(FcmProvider)
    fcm_provider.send = AsyncMock(
        side_effect=lambda tokens, data, **kw: fcm_calls.append(  # type: ignore[method-assign]
            {'tokens': tokens}
        )
    )
    push._fcm = fcm_provider

    await push.send_to_tokens(
        [('apns-token', 'apns'), ('fcm-token', 'fcm'), ('apns-token-2', 'apns')],
        uuid.uuid4(),
        PushEventType.game_started,
        alert='Game on!',
    )

    assert len(apns_calls) == 1
    assert apns_calls[0]['tokens'] == ['apns-token', 'apns-token-2']
    assert len(fcm_calls) == 1
    assert fcm_calls[0]['tokens'] == ['fcm-token']


@pytest.mark.anyio
async def test_fcm_provider_builds_payload():
    """Verify FcmProvider builds correct firebase messaging.Message."""
    sent_messages = []

    with patch('hideandseek_core.push.messaging') as mock_messaging:
        mock_messaging.Message = lambda **kw: kw
        mock_messaging.Notification = lambda **kw: kw
        mock_messaging.AndroidConfig = lambda **kw: kw

        async def fake_to_thread(fn, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            sent_messages.append(args[0])

        with patch('hideandseek_core.push.asyncio.to_thread', side_effect=fake_to_thread):
            provider = FcmProvider.__new__(FcmProvider)
            provider._app = None  # type: ignore[assignment]

            await provider.send(
                ['fcm-token-abc'],
                {'event_type': 'game_started', 'game_id': 'some-uuid'},
                alert='Game on!',
            )

    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert msg['token'] == 'fcm-token-abc'
    assert msg['data'] == {'event_type': 'game_started', 'game_id': 'some-uuid'}
    assert msg['notification'] == {'title': 'Hide & Seek', 'body': 'Game on!'}
    assert msg['android'] == {'priority': 'high'}


@pytest.mark.anyio
async def test_fcm_provider_silent_payload():
    """Verify FcmProvider omits notification for silent pushes."""
    sent_messages = []

    with patch('hideandseek_core.push.messaging') as mock_messaging:
        mock_messaging.Message = lambda **kw: kw
        mock_messaging.AndroidConfig = lambda **kw: kw

        async def fake_to_thread(fn, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            sent_messages.append(args[0])

        with patch('hideandseek_core.push.asyncio.to_thread', side_effect=fake_to_thread):
            provider = FcmProvider.__new__(FcmProvider)
            provider._app = None  # type: ignore[assignment]

            await provider.send(
                ['fcm-token-abc'],
                {'event_type': 'phase_changed', 'game_id': 'some-uuid'},
                silent=True,
            )

    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert msg['token'] == 'fcm-token-abc'
    assert msg['notification'] is None
    assert msg['android'] == {'priority': 'high'}
