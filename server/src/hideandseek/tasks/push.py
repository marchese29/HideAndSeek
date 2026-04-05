"""Push notification delivery task with retry."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog

from hideandseek_core.celery_app import app
from hideandseek_core.config import load_fcm_config, load_push_config
from hideandseek_core.db import session_scope
from hideandseek_core.push import PushService
from hideandseek_core.queries.device_tokens import get_device_tokens_for_game
from hideandseek_models.types import PlayerRole, PushEventType

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_push_service: PushService | None = None


def _get_push_service() -> PushService:
    """Lazy singleton for the worker-process PushService."""
    global _push_service  # noqa: PLW0603
    if _push_service is None:
        apns_config = load_push_config()
        fcm_config = load_fcm_config()
        _push_service = PushService(apns_config, fcm_config)
    return _push_service


@app.task(
    autoretry_for=(Exception,),
    retry_backoff=10,
    max_retries=3,
)
def send_push(
    game_id: str,
    event_type: str,
    *,
    role_filter: str | None = None,
    alert: str | None = None,
    **kwargs: Any,
) -> None:
    """Send push notifications for a game event.

    Fetches device tokens from the DB, optionally filtered by role,
    and delivers via PushService with retry on failure.
    """
    with session_scope():
        role = PlayerRole(role_filter) if role_filter is not None else None
        device_tokens = get_device_tokens_for_game(uuid.UUID(game_id), role_filter=role)
        # Extract (token, provider) pairs before session closes to avoid DetachedInstanceError
        token_pairs = [(dt.token, dt.provider) for dt in device_tokens]

    if not token_pairs:
        logger.info('push_no_tokens', game_id=game_id, event_type=event_type)
        return

    push_service = _get_push_service()
    asyncio.run(
        push_service.send_to_tokens(
            token_pairs,
            uuid.UUID(game_id),
            PushEventType(event_type),
            alert=alert,
            question_id=uuid.UUID(kwargs['question_id']) if 'question_id' in kwargs else None,
            question_type=kwargs.get('question_type'),
            question_status=kwargs.get('question_status'),
            parameters=kwargs.get('parameters'),
            answer=kwargs.get('answer'),
        )
    )
    logger.info(
        'push_sent',
        game_id=game_id,
        event_type=event_type,
        token_count=len(token_pairs),
    )
