"""Push notification delivery task with retry."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog

from hideandseek_core.config import load_sns_config
from hideandseek_core.db import session_scope
from hideandseek_core.push import PushService
from hideandseek_core.queries.device_tokens import (
    delete_device_token_by_endpoint,
    get_device_tokens_for_game,
)
from hideandseek_models.types import PlayerRole, PushEventType
from hideandseek_worker.celery_app import app

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_push_service: PushService | None = None


def _get_push_service() -> PushService:
    """Lazy singleton for the worker-process PushService."""
    global _push_service  # noqa: PLW0603
    if _push_service is None:
        _push_service = PushService(load_sns_config())
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
    and delivers via PushService. ARNs SNS reports as disabled/invalid
    are deleted inline — next registration recreates them.
    """
    with session_scope():
        role = PlayerRole(role_filter) if role_filter is not None else None
        device_tokens = get_device_tokens_for_game(uuid.UUID(game_id), role_filter=role)
        endpoint_arns = [dt.endpoint_arn for dt in device_tokens if dt.endpoint_arn]

    if not endpoint_arns:
        logger.info('push_no_tokens', game_id=game_id, event_type=event_type)
        return

    push_service = _get_push_service()
    disabled_arns = asyncio.run(
        push_service.send_to_tokens(
            endpoint_arns,
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
        token_count=len(endpoint_arns),
        dead_count=len(disabled_arns),
    )

    if disabled_arns:
        with session_scope():
            for arn in disabled_arns:
                delete_device_token_by_endpoint(arn)
                logger.info('dead_endpoint_removed', arn=arn)
