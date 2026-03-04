"""Device token model for APNS push notifications."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

from hideandseek.models.base import Base


class DeviceToken(Base):
    """Maps a client_id to its APNS device token.

    Separate from Player — a client_id can span multiple games and may register
    a token before joining any game.
    """

    __tablename__ = 'device_token'

    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    token: Mapped[str]
    environment: Mapped[str] = mapped_column(default='production')
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
    )
