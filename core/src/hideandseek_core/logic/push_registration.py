"""Device-token registration with inline SNS platform-endpoint minting."""

from __future__ import annotations

import uuid

import structlog

from hideandseek_core.config import load_sns_config
from hideandseek_core.push import create_platform_endpoint
from hideandseek_core.queries.device_tokens import upsert_device_token
from hideandseek_models.device_token import DeviceToken
from hideandseek_models.types import TokenProvider

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def register_push_endpoint(
    *,
    player_id: uuid.UUID,
    token: str,
    provider: str = 'apns',
) -> DeviceToken:
    """Upsert a device token and mint its SNS platform endpoint ARN.

    When `SnsConfig` is unavailable (dev/test without LocalStack), falls back
    to persisting the token without an endpoint ARN — the worker will noop
    during push, same as today.
    """
    config = load_sns_config()
    if config is None:
        logger.info('push_registration_noop', player_id=str(player_id))
        return upsert_device_token(
            player_id=player_id,
            token=token,
            provider=provider,
            endpoint_arn=None,
        )

    token_provider = TokenProvider(provider)
    endpoint_arn = create_platform_endpoint(config, token, token_provider)
    device_token = upsert_device_token(
        player_id=player_id,
        token=token,
        provider=provider,
        endpoint_arn=endpoint_arn,
    )
    logger.info(
        'push_endpoint_registered',
        player_id=str(player_id),
        provider=provider,
    )
    return device_token
