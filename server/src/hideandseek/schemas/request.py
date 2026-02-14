"""Request body schemas for the HideAndSeek API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from hideandseek.models.types import GeoPoint, PlayerRole, QuestionType

# ── Games ─────────────────────────────────────────────────────────────────────


class CreateGameRequest(BaseModel):
    """Create a new game on a map."""

    map_id: uuid.UUID = Field(description='ID of the map to play on.')


class JoinGameRequest(BaseModel):
    """Join an existing game by its join code."""

    join_code: str = Field(description='4-character code shared by the host.')
    name: str = Field(description='Display name for this player.')
    color: str = Field(description='Hex color for this player, e.g. "#FF5733".')


# ── Players ───────────────────────────────────────────────────────────────────


class PlayerUpdate(BaseModel):
    """Partial update to a player. All fields are optional; only provided fields are applied."""

    name: str | None = Field(default=None, description='New display name.')
    color: str | None = Field(default=None, description='New hex color.')
    role: PlayerRole | None = Field(default=None, description='Assign hider or seeker role.')


# ── Location ──────────────────────────────────────────────────────────────────


class LocationReportRequest(BaseModel):
    """Report the caller's current position."""

    coordinates: GeoPoint = Field(description='Current position as a GeoJSON Point.')
    timestamp: datetime = Field(description='Client-side timestamp of the reading.')


# ── Questions ─────────────────────────────────────────────────────────────────


class AskQuestionRequest(BaseModel):
    """Ask a radar or thermometer question, spending an inventory slot."""

    question_type: QuestionType = Field(description='Type of question: radar or thermometer.')
    slot_index: int = Field(
        description='0-based index into the inventory slot list for this question type.'
    )
    custom_distance_m: int | None = Field(
        default=None,
        description='Required when the chosen slot has distance_m=null (custom slot).',
    )
