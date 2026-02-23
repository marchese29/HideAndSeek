"""Request body schemas for the HideAndSeek API."""

from __future__ import annotations

import uuid
from datetime import datetime

from geojson_pydantic import Point
from pydantic import BaseModel, Field

from hideandseek.models.types import FeatureCategory, PlayerRole

# ── Games ─────────────────────────────────────────────────────────────────────


class CreateGameRequest(BaseModel):
    """Create a new game on a map."""

    map_id: uuid.UUID = Field(description='ID of the map to play on.')
    device_token: str | None = Field(
        default=None,
        description='Hex-encoded APNS device token. Optional for game creation.',
    )
    device_token_environment: str = Field(
        default='production',
        description='APNS environment: "production" or "sandbox".',
    )


class JoinGameRequest(BaseModel):
    """Join an existing game by its join code."""

    join_code: str = Field(description='4-character code shared by the host.')
    name: str = Field(description='Display name for this player.')
    color: str = Field(description='Hex color for this player, e.g. "#FF5733".')
    device_token: str = Field(
        description='Hex-encoded APNS device token. Required — push is central to gameplay.',
    )
    device_token_environment: str = Field(
        default='production',
        description='APNS environment: "production" or "sandbox".',
    )


# ── Players ───────────────────────────────────────────────────────────────────


class PlayerUpdate(BaseModel):
    """Partial update to a player. All fields are optional; only provided fields are applied."""

    name: str | None = Field(default=None, description='New display name.')
    color: str | None = Field(default=None, description='New hex color.')
    role: PlayerRole | None = Field(default=None, description='Assign hider or seeker role.')


# ── Location ──────────────────────────────────────────────────────────────────


class LocationReportRequest(BaseModel):
    """Report the caller's current position."""

    coordinates: Point = Field(description='Current position as a GeoJSON Point.')
    timestamp: datetime = Field(description='Client-side timestamp of the reading.')


# ── Questions ─────────────────────────────────────────────────────────────────


class AskRadarRequest(BaseModel):
    """Ask a radar question, spending a radar inventory slot."""

    location: Point = Field(description='Current seeker position as a GeoJSON Point.')
    slot_index: int = Field(description='0-based index into the available radar slot list.')
    custom_distance: float | None = Field(
        default=None,
        description='Required for custom slots (distance=null). In convention units.',
    )


class AskThermometerRequest(BaseModel):
    """Ask a thermometer question, spending a thermometer inventory slot."""

    location: Point = Field(description='Current seeker position as a GeoJSON Point.')
    slot_index: int = Field(description='0-based index into the available thermometer slot list.')
    custom_distance: float | None = Field(
        default=None,
        description='Required for custom slots (distance=null). In convention units.',
    )


class AskMatchingRequest(BaseModel):
    """Ask a matching question about a feature category."""

    location: Point = Field(description='Current seeker position as a GeoJSON Point.')
    category: FeatureCategory = Field(description='Feature category to match on.')
    feature_class: int | None = Field(
        default=None,
        description='Feature class tier. Required for classed categories.',
    )


class AskMeasuringRequest(BaseModel):
    """Ask a measuring question about a feature category."""

    location: Point = Field(description='Current seeker position as a GeoJSON Point.')
    category: FeatureCategory = Field(description='Feature category to measure distance to.')
    feature_class: int | None = Field(
        default=None,
        description='Feature class tier. Required for classed categories.',
    )


class PreviewQuestionRequest(BaseModel):
    """Preview the nearest feature for a matching/measuring question without consuming inventory."""

    question_type: str = Field(description='matching or measuring.')
    category: FeatureCategory = Field(description='Feature category to preview.')
    feature_class: int | None = Field(
        default=None,
        description='Feature class tier for classed categories.',
    )
    location: Point = Field(description='Current position as a GeoJSON Point.')
