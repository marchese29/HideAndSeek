"""Device token model for APNS push notifications."""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class DeviceToken(SQLModel, table=True):
    """Maps a client_id to its APNS device token.

    Separate from Player — a client_id can span multiple games and may register
    a token before joining any game.
    """

    __tablename__ = 'device_token'  # type: ignore[assignment]

    client_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_type=sa.Uuid,
        description='The device client_id (PK).',
    )
    token: str = Field(description='Hex-encoded APNS device token.')
    environment: str = Field(
        default='production',
        description='APNS environment: "production" or "sandbox".',
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description='Last registration time.',
    )
