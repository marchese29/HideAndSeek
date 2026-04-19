"""SNS Mobile Push notification service."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import boto3
import structlog
from botocore.exceptions import ClientError

from hideandseek_core.config import SnsConfig
from hideandseek_models.types import PushEventType, TokenProvider

if TYPE_CHECKING:
    from mypy_boto3_sns import SNSClient

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _build_data(
    game_id: uuid.UUID,
    event_type: PushEventType,
    *,
    question_id: uuid.UUID | None = None,
    question_type: str | None = None,
    question_status: str | None = None,
    parameters: dict[str, Any] | None = None,
    answer: str | None = None,
) -> dict[str, Any]:
    """Build the provider-agnostic data payload for a push notification."""
    data: dict[str, Any] = {
        'event_type': event_type,
        'game_id': str(game_id),
    }
    if question_id is not None:
        data['question_id'] = str(question_id)
    if question_type is not None:
        data['question_type'] = question_type
    if question_status is not None:
        data['question_status'] = question_status
    if parameters is not None:
        data['parameters'] = parameters
    if answer is not None:
        data['answer'] = answer
    return data


def _build_envelope(data: dict[str, Any], *, alert: str | None, silent: bool) -> str:
    """Build the SNS MessageStructure='json' envelope carrying both APNS + FCM payloads.

    SNS selects the APNs or GCM variant based on the target endpoint's parent
    platform application, so we build both every time.
    """
    if silent:
        apns_payload: dict[str, Any] = {
            'aps': {'content-available': 1},
            'data': data,
        }
    else:
        aps: dict[str, Any] = {
            'content-available': 1,
            'interruption-level': 'time-sensitive',
        }
        if alert:
            aps['alert'] = {'title': 'Hide & Seek', 'body': alert}
            aps['sound'] = 'default'
        apns_payload = {'aps': aps, 'data': data}

    # FCM requires all data values to be strings.
    fcm_data: dict[str, str] = {}
    for k, v in data.items():
        fcm_data[k] = v if isinstance(v, str) else json.dumps(v)

    fcm_payload: dict[str, Any] = {'data': fcm_data, 'android': {'priority': 'high'}}
    if not silent and alert:
        fcm_payload['notification'] = {'title': 'Hide & Seek', 'body': alert}

    envelope = {
        'default': alert or '',
        'APNS': json.dumps(apns_payload),
        'APNS_SANDBOX': json.dumps(apns_payload),
        'GCM': json.dumps(fcm_payload),
    }
    return json.dumps(envelope)


def _make_client(config: SnsConfig) -> SNSClient:
    return boto3.client(
        'sns',
        region_name=config.region,
        endpoint_url=config.endpoint_url,
    )


# SNS reports "Endpoint arn:aws:sns:... already exists" when CreatePlatformEndpoint
# sees the token already registered; we parse the ARN out to re-enable it.
_EXISTING_ARN_RE = re.compile(r'arn:aws:sns:\S+')


def create_platform_endpoint(
    config: SnsConfig,
    token: str,
    provider: TokenProvider,
) -> str:
    """Create or re-enable an SNS platform endpoint for a device token.

    Returns the endpoint ARN. When SNS reports the token already has an
    endpoint, parse the existing ARN out of the error and re-enable it.
    """
    client = _make_client(config)
    app_arn = config.apns_app_arn if provider == TokenProvider.apns else config.fcm_app_arn

    try:
        resp = client.create_platform_endpoint(
            PlatformApplicationArn=app_arn,
            Token=token,
        )
        return resp['EndpointArn']
    except client.exceptions.InvalidParameterException as e:
        message = e.response.get('Error', {}).get('Message', '')
        match = _EXISTING_ARN_RE.search(message)
        if not match:
            raise
        existing_arn = match.group(0).rstrip('.,')
        logger.info('sns_endpoint_reenable', arn=existing_arn, provider=provider.value)
        client.set_endpoint_attributes(
            EndpointArn=existing_arn,
            Attributes={'Token': token, 'Enabled': 'true'},
        )
        return existing_arn


_DEAD_ENDPOINT_CODES = frozenset({'EndpointDisabled', 'NotFound', 'InvalidParameter'})


class SnsProvider:
    """Publishes push notifications via AWS SNS Mobile Push."""

    def __init__(self, config: SnsConfig) -> None:
        self._client: SNSClient = _make_client(config)

    async def send(
        self,
        endpoint_arns: list[str],
        data: dict[str, Any],
        *,
        alert: str | None = None,
        silent: bool = False,
    ) -> list[str]:
        """Publish to each endpoint; return ARNs SNS reported as disabled/invalid.

        Re-raises non-dead-endpoint ClientErrors so Celery can retry.
        """
        envelope = _build_envelope(data, alert=alert, silent=silent)
        dead: list[str] = []

        for arn in endpoint_arns:
            try:
                await asyncio.to_thread(
                    self._client.publish,
                    TargetArn=arn,
                    MessageStructure='json',
                    Message=envelope,
                )
            except ClientError as e:
                code = e.response.get('Error', {}).get('Code', '')
                if code in _DEAD_ENDPOINT_CODES:
                    logger.warning('sns_endpoint_dead', arn=arn, code=code)
                    dead.append(arn)
                else:
                    raise

        return dead


class PushService:
    """Orchestrates push delivery.

    No-op when SnsConfig is missing (dev/test without LocalStack).
    """

    def __init__(self, sns_config: SnsConfig | None) -> None:
        self._provider: SnsProvider | None = None
        if sns_config is not None:
            self._provider = SnsProvider(sns_config)
            logger.info('push_provider_initialized', provider='sns')
        else:
            logger.info('push_service_initialized', mode='noop')

    async def send_to_tokens(
        self,
        endpoint_arns: Sequence[str],
        game_id: uuid.UUID,
        event_type: PushEventType,
        *,
        alert: str | None = None,
        silent: bool = False,
        question_id: uuid.UUID | None = None,
        question_type: str | None = None,
        question_status: str | None = None,
        parameters: dict[str, Any] | None = None,
        answer: str | None = None,
    ) -> list[str]:
        """Publish to the given endpoint ARNs; return disabled ARNs for caller cleanup."""
        if not endpoint_arns:
            return []

        data = _build_data(
            game_id,
            event_type,
            question_id=question_id,
            question_type=question_type,
            question_status=question_status,
            parameters=parameters,
            answer=answer,
        )

        if self._provider is None:
            for arn in endpoint_arns:
                logger.info(
                    'push_noop',
                    event_type=event_type,
                    game_id=str(game_id),
                    arn=arn,
                )
            return []

        return await self._provider.send(
            list(endpoint_arns),
            data,
            alert=alert,
            silent=silent,
        )
