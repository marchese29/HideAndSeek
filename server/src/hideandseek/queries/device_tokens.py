"""Device token queries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from hideandseek.db import get_session
from hideandseek.models.device_token import DeviceToken
from hideandseek.models.game import Player
from hideandseek.models.types import PlayerRole


def upsert_device_token(
    *,
    client_id: uuid.UUID,
    token: str,
    environment: str = 'production',
) -> DeviceToken:
    """Insert or update a device token for a client_id."""
    session = get_session()
    existing = session.get(DeviceToken, client_id)
    if existing:
        existing.token = token
        existing.environment = environment
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        session.flush()
        return existing

    dt = DeviceToken(
        client_id=client_id,
        token=token,
        environment=environment,
    )
    session.add(dt)
    session.flush()
    return dt


def get_device_tokens_for_game(
    game_id: uuid.UUID,
    *,
    role_filter: PlayerRole | None = None,
) -> list[DeviceToken]:
    """Look up device tokens for players in a game, optionally filtered by role."""
    session = get_session()
    stmt = (
        select(DeviceToken)
        .join(Player, DeviceToken.client_id == Player.client_id)
        .where(Player.game_id == game_id)
    )
    if role_filter is not None:
        stmt = stmt.where(Player.role == role_filter)
    return list(session.scalars(stmt).all())


def delete_device_token(client_id: uuid.UUID) -> None:
    """Delete a device token by client_id (for stale token cleanup)."""
    session = get_session()
    dt = session.get(DeviceToken, client_id)
    if dt:
        session.delete(dt)
        session.flush()
