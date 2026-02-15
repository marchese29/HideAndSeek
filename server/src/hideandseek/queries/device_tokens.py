"""Device token queries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import Session, select

from hideandseek.db import persisted
from hideandseek.models.device_token import DeviceToken
from hideandseek.models.game import Player
from hideandseek.models.types import PlayerRole


@persisted
def upsert_device_token(
    session: Session,
    *,
    client_id: uuid.UUID,
    token: str,
    environment: str = 'production',
) -> DeviceToken:
    """Insert or update a device token for a client_id."""
    existing = session.get(DeviceToken, client_id)
    if existing:
        existing.token = token
        existing.environment = environment
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        return existing

    dt = DeviceToken(
        client_id=client_id,
        token=token,
        environment=environment,
    )
    session.add(dt)
    return dt


def get_device_tokens_for_game(
    session: Session,
    game_id: uuid.UUID,
    *,
    role_filter: PlayerRole | None = None,
) -> list[DeviceToken]:
    """Look up device tokens for players in a game, optionally filtered by role."""
    stmt = (
        select(DeviceToken)
        .join(Player, DeviceToken.client_id == Player.client_id)  # type: ignore[arg-type]
        .where(Player.game_id == game_id)
    )
    if role_filter is not None:
        stmt = stmt.where(Player.role == role_filter)
    return list(session.exec(stmt).all())


@persisted
def delete_device_token(session: Session, client_id: uuid.UUID) -> None:
    """Delete a device token by client_id (for stale token cleanup)."""
    dt = session.get(DeviceToken, client_id)
    if dt:
        session.delete(dt)
