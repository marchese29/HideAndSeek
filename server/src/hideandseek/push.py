"""Push notification service supporting APNs and FCM providers."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from typing import Any

import structlog
from aioapns import APNs, NotificationRequest
from firebase_admin import credentials, initialize_app, messaging
from firebase_admin.exceptions import FirebaseError

from hideandseek.config import FcmConfig, PushConfig
from hideandseek_models.types import PushEventType, TokenProvider

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


class ApnsProvider:
    """Sends push notifications via Apple Push Notification service."""

    def __init__(self, config: PushConfig) -> None:
        self._client = APNs(
            key=config.key_path,
            key_id=config.key_id,
            team_id=config.team_id,
            topic=config.topic,
            use_sandbox=config.use_sandbox,
        )

    async def send(
        self,
        tokens: list[str],
        data: dict[str, Any],
        *,
        alert: str | None = None,
        silent: bool = False,
    ) -> None:
        """Send an APNs notification to the given tokens."""
        if silent:
            message: dict[str, Any] = {
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
            message = {'aps': aps, 'data': data}

        for token in tokens:
            request = NotificationRequest(device_token=token, message=message)
            try:
                response = await self._client.send_notification(request)
                if not response.is_successful:
                    logger.warning(
                        'apns_error',
                        token=f'{token[:8]}...{token[-4:]}',
                        status=response.status,
                        description=response.description,
                    )
            except Exception:
                logger.exception(
                    'push_send_failed',
                    provider='apns',
                    token=f'{token[:8]}...{token[-4:]}',
                )


class FcmProvider:
    """Sends push notifications via Firebase Cloud Messaging."""

    def __init__(self, config: FcmConfig) -> None:
        cred = credentials.Certificate(config.credentials_path)
        self._app = initialize_app(cred, name='hideandseek-fcm')

    async def send(
        self,
        tokens: list[str],
        data: dict[str, Any],
        *,
        alert: str | None = None,
        silent: bool = False,
    ) -> None:
        """Send an FCM notification to the given tokens."""
        # FCM data values must be strings
        str_data = {k: str(v) for k, v in data.items()}

        notification = None
        if not silent and alert:
            notification = messaging.Notification(title='Hide & Seek', body=alert)

        for token in tokens:
            message = messaging.Message(
                token=token,
                data=str_data,
                notification=notification,
                android=messaging.AndroidConfig(priority='high'),
            )
            try:
                await asyncio.to_thread(messaging.send, message, app=self._app)
            except FirebaseError:
                logger.exception(
                    'push_send_failed',
                    provider='fcm',
                    token=f'{token[:8]}...{token[-4:]}',
                )


class PushService:
    """Orchestrates push delivery across APNs and FCM providers.

    No-ops when neither provider is configured (dev/test).
    """

    def __init__(
        self,
        apns_config: PushConfig | None,
        fcm_config: FcmConfig | None,
    ) -> None:
        self._apns: ApnsProvider | None = None
        self._fcm: FcmProvider | None = None

        if apns_config:
            self._apns = ApnsProvider(apns_config)
            logger.info('push_provider_initialized', provider='apns')
        if fcm_config:
            self._fcm = FcmProvider(fcm_config)
            logger.info('push_provider_initialized', provider='fcm')
        if not apns_config and not fcm_config:
            logger.info('push_service_initialized', mode='noop')

    async def send_to_tokens(
        self,
        token_pairs: Sequence[tuple[str, str | TokenProvider]],
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
    ) -> None:
        """Send push notifications to device tokens, dispatching by provider.

        Args:
            token_pairs: List of (token, provider) tuples extracted from DB.
            game_id: The game this notification is about.
            event_type: Event identifier (e.g. "game_started", "question_asked").
            alert: Human-readable alert body. Omitted for silent pushes.
            silent: If True, sends data-only (no alert/sound).
            question_id: Optional question UUID for question events.
            question_type: Optional question type (radar/thermometer).
            question_status: Optional question status.
            parameters: Optional question parameters dict.
            answer: Optional question answer value.
        """
        if not token_pairs:
            return

        data = _build_data(
            game_id,
            event_type,
            question_id=question_id,
            question_type=question_type,
            question_status=question_status,
            parameters=parameters,
            answer=answer,
        )

        # Group tokens by provider
        apns_tokens: list[str] = []
        fcm_tokens: list[str] = []
        for token, provider in token_pairs:
            if provider == TokenProvider.fcm:
                fcm_tokens.append(token)
            else:
                apns_tokens.append(token)

        # Dispatch to available providers
        if apns_tokens:
            if self._apns:
                await self._apns.send(apns_tokens, data, alert=alert, silent=silent)
            else:
                for token in apns_tokens:
                    logger.info(
                        'push_noop',
                        provider='apns',
                        event_type=event_type,
                        game_id=str(game_id),
                        token=f'{token[:8]}...{token[-4:]}',
                    )

        if fcm_tokens:
            if self._fcm:
                await self._fcm.send(fcm_tokens, data, alert=alert, silent=silent)
            else:
                for token in fcm_tokens:
                    logger.info(
                        'push_noop',
                        provider='fcm',
                        event_type=event_type,
                        game_id=str(game_id),
                        token=f'{token[:8]}...{token[-4:]}',
                    )

    async def close(self) -> None:
        """Clean up provider connections."""
        self._apns = None
        self._fcm = None
