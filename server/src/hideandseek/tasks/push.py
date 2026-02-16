"""Push notification delivery task with retry."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from sqlmodel import Session, select

from hideandseek.celery_app import app
from hideandseek.config import load_push_config
from hideandseek.db import engine
from hideandseek.models.device_token import DeviceToken
from hideandseek.models.game import Player
from hideandseek.models.types import PlayerRole, PushEventType
from hideandseek.push import PushService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_push_service: PushService | None = None


def _get_push_service() -> PushService:
    """Lazy singleton for the worker-process PushService."""
    global _push_service  # noqa: PLW0603
    if _push_service is None:
        config = load_push_config()
        _push_service = PushService(config)
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
    with Session(engine) as session:
        stmt = (
            select(DeviceToken)
            .join(Player, DeviceToken.client_id == Player.client_id)  # type: ignore[arg-type]
            .where(Player.game_id == uuid.UUID(game_id))
        )
        if role_filter is not None:
            stmt = stmt.where(Player.role == PlayerRole(role_filter))
        tokens = list(session.exec(stmt).all())

    if not tokens:
        logger.info('push_no_tokens', game_id=game_id, event_type=event_type)
        return

    push_service = _get_push_service()
    asyncio.run(
        push_service.send_to_tokens(
            tokens,
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
    logger.info('push_sent', game_id=game_id, event_type=event_type, token_count=len(tokens))
