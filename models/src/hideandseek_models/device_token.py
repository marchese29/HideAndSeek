"""Device token model for push notifications (APNs + FCM)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

from hideandseek_models.base import Base
from hideandseek_models.types import TokenProvider


class DeviceToken(Base):
    """Maps a player_id to its native push token.

    Separate from Player — a player_id can span multiple games and may register
    a token before joining any game.
    """

    __tablename__ = 'device_token'

    player_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    token: Mapped[str]
    provider: Mapped[TokenProvider] = mapped_column(default=TokenProvider.apns)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
    )
