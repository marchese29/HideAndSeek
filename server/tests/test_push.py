"""Tests for push notification infrastructure (SNS Mobile Push)."""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from hideandseek_core.config import SnsConfig
from hideandseek_core.logic.push_registration import register_push_endpoint
from hideandseek_core.push import PushService, SnsProvider, create_platform_endpoint
from hideandseek_core.queries.device_tokens import (
    delete_device_token,
    delete_device_token_by_endpoint,
    get_device_tokens_for_game,
    upsert_device_token,
)
from hideandseek_models.device_token import DeviceToken
from hideandseek_models.types import PlayerRole, PushEventType, TokenProvider
from hideandseek_worker.tasks import push as push_task
from tests.conftest import create_game, create_player

# ── Helpers ───────────────────────────────────────────────────────────────────


def _sns_config() -> SnsConfig:
    return SnsConfig(
        region='us-east-1',
        apns_app_arn='arn:aws:sns:us-east-1:000000000000:app/APNS_SANDBOX/hideandseek-ios-dev',
        fcm_app_arn='arn:aws:sns:us-east-1:000000000000:app/GCM/hideandseek-android-dev',
        endpoint_url='http://localstack:4566',
    )


def _client_error(code: str, message: str = '') -> ClientError:
    return ClientError(
        {'Error': {'Code': code, 'Message': message}},
        'Publish',
    )


# ── upsert_device_token ──────────────────────────────────────────────────────


def test_upsert_creates_token(session: Session):
    player_id = uuid.uuid4()
    dt = upsert_device_token(
        player_id=player_id,
        token='aabbccdd',
        endpoint_arn='arn:aws:sns:us-east-1:000000000000:endpoint/APNS_SANDBOX/x/abc',
    )
    assert dt.player_id == player_id
    assert dt.token == 'aabbccdd'
    assert dt.provider == TokenProvider.apns
    assert dt.endpoint_arn == 'arn:aws:sns:us-east-1:000000000000:endpoint/APNS_SANDBOX/x/abc'


def test_upsert_creates_fcm_token(session: Session):
    player_id = uuid.uuid4()
    dt = upsert_device_token(
        player_id=player_id,
        token='fcm-reg-token',
        provider='fcm',
        endpoint_arn='arn:aws:sns:us-east-1:000000000000:endpoint/GCM/x/abc',
    )
    assert dt.provider == TokenProvider.fcm
    assert dt.endpoint_arn == 'arn:aws:sns:us-east-1:000000000000:endpoint/GCM/x/abc'


def test_upsert_updates_existing_token(session: Session):
    player_id = uuid.uuid4()
    dt1 = upsert_device_token(player_id=player_id, token='old_token', endpoint_arn='arn:old')
    original_time = dt1.updated_at

    dt2 = upsert_device_token(
        player_id=player_id, token='new_token', provider='fcm', endpoint_arn='arn:new'
    )
    assert dt2.token == 'new_token'
    assert dt2.provider == TokenProvider.fcm
    assert dt2.endpoint_arn == 'arn:new'
    assert dt2.updated_at >= original_time

    result = session.get(DeviceToken, player_id)
    assert result is not None
    assert result.endpoint_arn == 'arn:new'


def test_upsert_allows_null_endpoint_arn(session: Session):
    """Noop-mode registration (no SNS config) persists with endpoint_arn=None."""
    player_id = uuid.uuid4()
    dt = upsert_device_token(player_id=player_id, token='tok', endpoint_arn=None)
    assert dt.endpoint_arn is None


# ── get_device_tokens_for_game ────────────────────────────────────────────────


def test_get_device_tokens_for_game(session: Session):
    game = create_game(session)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    upsert_device_token(player_id=hider.id, token='hider_token', endpoint_arn='arn:hider')
    upsert_device_token(
        player_id=seeker.id, token='seeker_token', provider='fcm', endpoint_arn='arn:seeker'
    )

    all_tokens = get_device_tokens_for_game(game.id)
    assert len(all_tokens) == 2
    arns = {dt.endpoint_arn for dt in all_tokens}
    assert arns == {'arn:hider', 'arn:seeker'}


def test_get_device_tokens_with_role_filter(session: Session):
    game = create_game(session)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)

    upsert_device_token(player_id=hider.id, token='hider_token', endpoint_arn='arn:hider')
    upsert_device_token(player_id=seeker.id, token='seeker_token', endpoint_arn='arn:seeker')

    hider_tokens = get_device_tokens_for_game(game.id, role_filter=PlayerRole.hider)
    assert len(hider_tokens) == 1
    assert hider_tokens[0].endpoint_arn == 'arn:hider'


# ── delete_device_token ──────────────────────────────────────────────────────


def test_delete_device_token(session: Session):
    player_id = uuid.uuid4()
    upsert_device_token(player_id=player_id, token='to_delete', endpoint_arn='arn:x')
    delete_device_token(player_id)
    assert session.get(DeviceToken, player_id) is None


def test_delete_device_token_by_endpoint(session: Session):
    player_id = uuid.uuid4()
    upsert_device_token(player_id=player_id, token='t', endpoint_arn='arn:dead')
    delete_device_token_by_endpoint('arn:dead')
    assert session.get(DeviceToken, player_id) is None


def test_delete_device_token_by_endpoint_noop_when_missing(session: Session):
    """Deleting a non-existent endpoint ARN is a no-op."""
    delete_device_token_by_endpoint('arn:never-seen')


# ── SnsProvider ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_sns_provider_publishes_envelope():
    """SnsProvider.publish sends a MessageStructure='json' envelope with APNS + GCM variants."""
    captured: list[dict[str, Any]] = []
    fake_client = MagicMock()
    fake_client.publish.side_effect = lambda **kw: captured.append(kw) or {'MessageId': 'x'}

    with patch('hideandseek_core.push.boto3.client', return_value=fake_client):
        provider = SnsProvider(_sns_config())

    game_id = uuid.uuid4()
    question_id = uuid.uuid4()

    dead = await provider.send(
        ['arn:device:1'],
        {
            'event_type': PushEventType.question_asked,
            'game_id': str(game_id),
            'question_id': str(question_id),
            'question_type': 'radar',
            'parameters': {'radius': 3000},
        },
        alert='A 3 km radar question has been asked.',
    )

    assert dead == []
    assert len(captured) == 1
    call = captured[0]
    assert call['TargetArn'] == 'arn:device:1'
    assert call['MessageStructure'] == 'json'
    envelope = json.loads(call['Message'])
    assert set(envelope) == {'default', 'APNS', 'APNS_SANDBOX', 'GCM'}

    apns = json.loads(envelope['APNS'])
    assert apns['aps']['alert'] == {
        'title': 'Hide & Seek',
        'body': 'A 3 km radar question has been asked.',
    }
    assert apns['aps']['sound'] == 'default'
    assert apns['aps']['content-available'] == 1
    assert apns['aps']['interruption-level'] == 'time-sensitive'
    assert apns['data']['event_type'] == 'question_asked'

    gcm = json.loads(envelope['GCM'])
    # FCM data values must be strings — dicts are json-encoded.
    assert gcm['data']['event_type'] == 'question_asked'
    assert gcm['data']['parameters'] == json.dumps({'radius': 3000})
    assert gcm['notification'] == {
        'title': 'Hide & Seek',
        'body': 'A 3 km radar question has been asked.',
    }
    assert gcm['android'] == {'priority': 'high'}


@pytest.mark.anyio
async def test_sns_provider_silent_push_has_content_available_only():
    """Silent pushes omit alert/sound and FCM notification block."""
    captured: list[dict[str, Any]] = []
    fake_client = MagicMock()
    fake_client.publish.side_effect = lambda **kw: captured.append(kw) or {'MessageId': 'x'}

    with patch('hideandseek_core.push.boto3.client', return_value=fake_client):
        provider = SnsProvider(_sns_config())

    await provider.send(
        ['arn:device:1'],
        {'event_type': PushEventType.phase_changed, 'game_id': str(uuid.uuid4())},
        silent=True,
    )

    envelope = json.loads(captured[0]['Message'])
    apns = json.loads(envelope['APNS'])
    assert apns['aps'] == {'content-available': 1}
    assert 'alert' not in apns['aps']
    assert 'sound' not in apns['aps']

    gcm = json.loads(envelope['GCM'])
    assert 'notification' not in gcm


@pytest.mark.anyio
async def test_sns_provider_endpoint_disabled_returned_as_dead_arn():
    """EndpointDisabled/NotFound/InvalidParameter are collected, not re-raised."""
    fake_client = MagicMock()
    fake_client.publish.side_effect = [
        {'MessageId': 'ok'},
        _client_error('EndpointDisabled'),
        _client_error('NotFound'),
    ]

    with patch('hideandseek_core.push.boto3.client', return_value=fake_client):
        provider = SnsProvider(_sns_config())

    dead = await provider.send(
        ['arn:ok', 'arn:disabled', 'arn:gone'],
        {'event_type': PushEventType.game_started, 'game_id': str(uuid.uuid4())},
    )

    assert dead == ['arn:disabled', 'arn:gone']


@pytest.mark.anyio
async def test_sns_provider_other_errors_reraise():
    """Throttling or service errors re-raise so Celery retries."""
    fake_client = MagicMock()
    fake_client.publish.side_effect = _client_error('Throttling')

    with patch('hideandseek_core.push.boto3.client', return_value=fake_client):
        provider = SnsProvider(_sns_config())

    with pytest.raises(ClientError):
        await provider.send(
            ['arn:x'],
            {'event_type': PushEventType.game_started, 'game_id': str(uuid.uuid4())},
        )


# ── create_platform_endpoint ─────────────────────────────────────────────────


def _make_fake_sns_client() -> MagicMock:
    """MagicMock shaped like an SNS client, with the typed exception classes we catch."""
    fake = MagicMock()
    fake.exceptions.InvalidParameterException = ClientError
    return fake


def test_create_platform_endpoint_apns():
    fake = _make_fake_sns_client()
    fake.create_platform_endpoint.return_value = {'EndpointArn': 'arn:new-endpoint'}

    with patch('hideandseek_core.push.boto3.client', return_value=fake):
        arn = create_platform_endpoint(_sns_config(), 'raw-token', TokenProvider.apns)

    assert arn == 'arn:new-endpoint'
    fake.create_platform_endpoint.assert_called_once_with(
        PlatformApplicationArn=_sns_config().apns_app_arn,
        Token='raw-token',
    )


def test_create_platform_endpoint_fcm_selects_fcm_app():
    fake = _make_fake_sns_client()
    fake.create_platform_endpoint.return_value = {'EndpointArn': 'arn:fcm-endpoint'}

    with patch('hideandseek_core.push.boto3.client', return_value=fake):
        arn = create_platform_endpoint(_sns_config(), 'fcm-token', TokenProvider.fcm)

    assert arn == 'arn:fcm-endpoint'
    call = fake.create_platform_endpoint.call_args
    assert call.kwargs['PlatformApplicationArn'] == _sns_config().fcm_app_arn


def test_create_platform_endpoint_handles_duplicate():
    """On 'already exists', parse ARN from message and re-enable."""
    existing = 'arn:aws:sns:us-east-1:000000000000:endpoint/APNS_SANDBOX/x/existing'
    fake = _make_fake_sns_client()
    fake.create_platform_endpoint.side_effect = ClientError(
        {
            'Error': {
                'Code': 'InvalidParameter',
                'Message': f'Invalid parameter: Token Reason: Endpoint {existing} already exists.',
            }
        },
        'CreatePlatformEndpoint',
    )

    with patch('hideandseek_core.push.boto3.client', return_value=fake):
        arn = create_platform_endpoint(_sns_config(), 'raw-token', TokenProvider.apns)

    assert arn == existing
    fake.set_endpoint_attributes.assert_called_once_with(
        EndpointArn=existing,
        Attributes={'Token': 'raw-token', 'Enabled': 'true'},
    )


def test_create_platform_endpoint_unparseable_error_reraises():
    """If the 'already exists' message doesn't carry an ARN, propagate."""
    fake = _make_fake_sns_client()
    fake.create_platform_endpoint.side_effect = ClientError(
        {'Error': {'Code': 'InvalidParameter', 'Message': 'Something else went wrong.'}},
        'CreatePlatformEndpoint',
    )

    with (
        patch('hideandseek_core.push.boto3.client', return_value=fake),
        pytest.raises(ClientError),
    ):
        create_platform_endpoint(_sns_config(), 'raw-token', TokenProvider.apns)


# ── register_push_endpoint ───────────────────────────────────────────────────


def test_register_push_endpoint_mints_arn(session: Session):
    player_id = uuid.uuid4()
    fake = _make_fake_sns_client()
    fake.create_platform_endpoint.return_value = {'EndpointArn': 'arn:minted'}

    with (
        patch('hideandseek_core.push.boto3.client', return_value=fake),
        patch(
            'hideandseek_core.logic.push_registration.load_sns_config',
            return_value=_sns_config(),
        ),
    ):
        dt = register_push_endpoint(player_id=player_id, token='tok', provider='apns')

    assert dt.endpoint_arn == 'arn:minted'
    assert dt.token == 'tok'
    assert dt.provider == TokenProvider.apns


def test_register_push_endpoint_uses_fcm_app(session: Session):
    fake = _make_fake_sns_client()
    fake.create_platform_endpoint.return_value = {'EndpointArn': 'arn:fcm'}

    with (
        patch('hideandseek_core.push.boto3.client', return_value=fake),
        patch(
            'hideandseek_core.logic.push_registration.load_sns_config',
            return_value=_sns_config(),
        ),
    ):
        register_push_endpoint(player_id=uuid.uuid4(), token='t', provider='fcm')

    call = fake.create_platform_endpoint.call_args
    assert call.kwargs['PlatformApplicationArn'] == _sns_config().fcm_app_arn


def test_register_push_endpoint_noop_when_sns_not_configured(session: Session):
    """Without SnsConfig, upsert the token with endpoint_arn=None and skip SNS calls."""
    player_id = uuid.uuid4()
    with patch(
        'hideandseek_core.logic.push_registration.load_sns_config',
        return_value=None,
    ):
        dt = register_push_endpoint(player_id=player_id, token='tok', provider='apns')

    assert dt.endpoint_arn is None
    assert dt.token == 'tok'


# ── PushService ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_push_service_noop_when_config_missing():
    """PushService with no config logs but doesn't raise."""
    push = PushService(sns_config=None)
    dead = await push.send_to_tokens(
        ['arn:ignored'],
        uuid.uuid4(),
        PushEventType.game_started,
        alert='Test alert',
    )
    assert dead == []


@pytest.mark.anyio
async def test_push_service_empty_endpoint_list():
    """Empty endpoint list returns immediately."""
    push = PushService(sns_config=None)
    dead = await push.send_to_tokens(
        [],
        uuid.uuid4(),
        PushEventType.game_started,
        alert='Test alert',
    )
    assert dead == []


@pytest.mark.anyio
async def test_push_service_returns_disabled_arns():
    """send_to_tokens propagates SnsProvider's dead-ARN list to the caller."""
    fake = MagicMock()
    fake.publish.side_effect = [{'MessageId': 'ok'}, _client_error('EndpointDisabled')]

    with patch('hideandseek_core.push.boto3.client', return_value=fake):
        push = PushService(sns_config=_sns_config())

    dead = await push.send_to_tokens(
        ['arn:ok', 'arn:bad'],
        uuid.uuid4(),
        PushEventType.game_started,
        alert='go',
    )

    assert dead == ['arn:bad']


# ── send_push Celery task ────────────────────────────────────────────────────


def test_send_push_task_deletes_dead_endpoints(session: Session):
    """End-to-end: when SNS reports an endpoint disabled, the task deletes the row."""
    game = create_game(session)
    hider = create_player(session, game.id, role=PlayerRole.hider)
    seeker = create_player(session, game.id, role=PlayerRole.seeker)
    upsert_device_token(player_id=hider.id, token='h', endpoint_arn='arn:hider-dead')
    upsert_device_token(player_id=seeker.id, token='s', endpoint_arn='arn:seeker-ok')

    fake = MagicMock()
    fake.publish.side_effect = [_client_error('EndpointDisabled'), {'MessageId': 'ok'}]

    @contextlib.contextmanager
    def reuse_test_session() -> Generator[Session, None, None]:
        """Route the task's session_scope() to the test-bound session so its
        writes stay inside the test transaction (and thus get rolled back)."""
        session.flush()
        yield session
        session.flush()

    with (
        patch('hideandseek_core.push.boto3.client', return_value=fake),
        patch(
            'hideandseek_worker.tasks.push.load_sns_config',
            return_value=_sns_config(),
        ),
        patch(
            'hideandseek_worker.tasks.push.session_scope',
            reuse_test_session,
        ),
    ):
        # Bypass the module-level singleton so the patched boto3.client is picked up.
        push_task._push_service = None  # noqa: SLF001
        try:
            push_task.send_push(
                str(game.id),
                PushEventType.game_started.value,
                alert='Game on',
            )
        finally:
            push_task._push_service = None  # noqa: SLF001

    assert session.get(DeviceToken, hider.id) is None
    assert session.get(DeviceToken, seeker.id) is not None
