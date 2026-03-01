"""Push notification service wrapping aioapns."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from aioapns import APNs, NotificationRequest

from hideandseek.config import PushConfig
from hideandseek.models.types import PushEventType

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class PushService:
    """Sends APNS push notifications. No-ops when config is None (dev/test)."""

    def __init__(self, config: PushConfig | None) -> None:
        self._config = config
        self._client: APNs | None = None
        if config:
            self._client = APNs(
                key=config.key_path,
                key_id=config.key_id,
                team_id=config.team_id,
                topic=config.topic,
                use_sandbox=config.use_sandbox,
            )
            logger.info('push_service_initialized', mode='apns')
        else:
            logger.info('push_service_initialized', mode='noop')

    async def send_to_tokens(
        self,
        tokens: list[str],
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
        """Send push notifications to device tokens.

        Args:
            tokens: Plain device token strings (extracted from DB before session close).
            game_id: The game this notification is about.
            event_type: Event identifier (e.g. "game_started", "question_asked").
            alert: Human-readable alert body. Omitted for silent pushes.
            silent: If True, sends content-available only (no alert/sound).
            question_id: Optional question UUID for question events.
            question_type: Optional question type (radar/thermometer).
            question_status: Optional question status.
            parameters: Optional question parameters dict.
            answer: Optional question answer value.
        """
        if not tokens:
            return

        # Build the data payload
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

        # Build the APS payload
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
            if not self._client:
                logger.info(
                    'push_noop',
                    event_type=event_type,
                    game_id=str(game_id),
                    token=f'{token[:8]}...{token[-4:]}',
                )
                continue

            request = NotificationRequest(
                device_token=token,
                message=message,
            )
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
                    token=f'{token[:8]}...{token[-4:]}',
                )

    async def close(self) -> None:
        """Clean up the APNS connection."""
        # aioapns doesn't expose an explicit close, but if it did we'd call it here.
        self._client = None
