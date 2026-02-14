"""Response schemas for the HideAndSeek API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from hideandseek.models.types import (
    GameStatus,
    GeoPolygon,
    MapSize,
    PlayerRole,
    QuestionStatus,
    QuestionType,
)

if TYPE_CHECKING:
    from hideandseek.models.game import Game as GameModel
    from hideandseek.models.game import Player as PlayerModel
    from hideandseek.models.game_map import GameMap as GameMapModel
    from hideandseek.models.location import LocationUpdate as LocationUpdateModel
    from hideandseek.models.question import Question as QuestionModel
    from hideandseek.models.transit import Route as RouteModel
    from hideandseek.models.transit import Stop as StopModel
    from hideandseek.queries import EffectiveMapData


# ── Maps ──────────────────────────────────────────────────────────────────────


class MapSummary(BaseModel):
    """A map in the browse list — name, size, and region."""

    id: uuid.UUID
    name: str
    size: MapSize
    region: str = Field(description='Geographic region from the transit dataset.')

    @staticmethod
    def from_model(game_map: GameMapModel, region: str) -> MapSummary:
        return MapSummary(id=game_map.id, name=game_map.name, size=game_map.size, region=region)


class MapDetail(BaseModel):
    """Full map detail including geometry for rendering a preview. Omits stops/routes."""

    id: uuid.UUID
    name: str
    size: MapSize
    transit_dataset_id: uuid.UUID
    boundary: dict = Field(description='GeoJSON Polygon defining the playable area.')
    districts: list = Field(description='District boundaries with id, name, class, and geometry.')
    district_classes: list = Field(description='District class definitions (tier + label).')
    default_inventory: dict = Field(description='Default question inventory for games on this map.')
    notes: str | None

    @staticmethod
    def from_model(gm: GameMapModel) -> MapDetail:
        return MapDetail(
            id=gm.id,
            name=gm.name,
            size=gm.size,
            transit_dataset_id=gm.transit_dataset_id,
            boundary=gm.boundary,
            districts=gm.districts,
            district_classes=gm.district_classes,
            default_inventory=gm.default_inventory,
            notes=gm.notes,
        )


# ── Players ───────────────────────────────────────────────────────────────────


class PlayerResponse(BaseModel):
    """A player in a game."""

    id: uuid.UUID
    name: str
    color: str = Field(description='Hex color, e.g. "#FF5733".')
    role: PlayerRole | None = Field(description='Null until the host assigns a role.')

    @staticmethod
    def from_model(player: PlayerModel) -> PlayerResponse:
        return PlayerResponse(id=player.id, name=player.name, color=player.color, role=player.role)


# ── Games ─────────────────────────────────────────────────────────────────────


class GameResponse(BaseModel):
    """Full game state, including players and inventory."""

    id: uuid.UUID
    map_id: uuid.UUID
    status: GameStatus
    join_code: str | None = Field(description='4-character code for joining. Null after game ends.')
    timing: dict = Field(description='TimingRules: hiding_time_min, rest_periods, etc.')
    inventory: dict = Field(description='Remaining question inventory (radars + thermometers).')
    players: list[PlayerResponse]
    created_at: datetime

    @staticmethod
    def from_model(game: GameModel) -> GameResponse:
        return GameResponse(
            id=game.id,
            map_id=game.map_id,
            status=game.status,
            join_code=game.join_code,
            timing=game.timing,
            inventory=game.inventory,
            players=[PlayerResponse.from_model(p) for p in game.players],
            created_at=game.created_at,
        )


class JoinGameResponse(BaseModel):
    """Returned when a player joins a game — includes the game state and the caller's player ID."""

    game: GameResponse
    player_id: uuid.UUID = Field(description="The joining player's ID for subsequent requests.")


# ── Effective map ─────────────────────────────────────────────────────────────


class StopResponse(BaseModel):
    """A transit stop on the effective game map."""

    id: uuid.UUID
    stable_id: str = Field(description='Stable identifier from the transit dataset.')
    name: str
    coordinates: dict = Field(description='GeoJSON Point.')

    @staticmethod
    def from_model(stop: StopModel) -> StopResponse:
        return StopResponse(
            id=stop.id,
            stable_id=stop.stable_id,
            name=stop.name,
            coordinates=stop.coordinates,
        )


class RouteResponse(BaseModel):
    """A transit route on the effective game map, with ordered stop IDs."""

    id: uuid.UUID
    stable_id: str = Field(description='Stable identifier from the transit dataset.')
    name: str
    color: str = Field(description='Hex color for rendering.')
    route_type: str = Field(description='metro, bus, tram, rail, or ferry.')
    shape: dict = Field(description='GeoJSON LineString.')
    stop_ids: list[uuid.UUID] = Field(description='Ordered stop IDs along this route.')

    @staticmethod
    def from_model(route: RouteModel, stop_ids: list[uuid.UUID]) -> RouteResponse:
        return RouteResponse(
            id=route.id,
            stable_id=route.stable_id,
            name=route.name,
            color=route.color,
            route_type=route.route_type,
            shape=route.shape,
            stop_ids=stop_ids,
        )


class EffectiveMapResponse(BaseModel):
    """The game map with transit data and exclusions applied.

    Single source of truth for what the client should render.
    """

    name: str
    size: MapSize
    boundary: dict = Field(description='GeoJSON Polygon.')
    districts: list
    district_classes: list
    stops: list[StopResponse]
    routes: list[RouteResponse]

    @staticmethod
    def from_effective_map_data(data: EffectiveMapData) -> EffectiveMapResponse:
        gm = data.game_map
        return EffectiveMapResponse(
            name=gm.name,
            size=gm.size,
            boundary=gm.boundary,
            districts=gm.districts,
            district_classes=gm.district_classes,
            stops=[StopResponse.from_model(s) for s in data.stops],
            routes=[RouteResponse.from_model(rws.route, rws.stop_ids) for rws in data.routes],
        )


# ── Location ──────────────────────────────────────────────────────────────────


class VisiblePlayer(BaseModel):
    """A player visible to the caller, with their latest position."""

    player_id: uuid.UUID
    name: str
    color: str
    role: PlayerRole | None
    coordinates: dict = Field(description='GeoJSON Point — latest reported position.')
    timestamp: datetime


class LocationReportResponse(BaseModel):
    """Returned after reporting location — includes positions of all visible players."""

    players: list[VisiblePlayer]


class LocationHistoryEntry(BaseModel):
    """A single location update in the post-game replay log."""

    player_id: uuid.UUID
    coordinates: dict = Field(description='GeoJSON Point.')
    timestamp: datetime

    @staticmethod
    def from_model(lu: LocationUpdateModel) -> LocationHistoryEntry:
        return LocationHistoryEntry(
            player_id=lu.player_id,
            coordinates=lu.coordinates,
            timestamp=lu.timestamp,
        )


# ── Questions ─────────────────────────────────────────────────────────────────


class QuestionResponse(BaseModel):
    """A question in the game — state machine: asked → in_progress → answerable → answered."""

    id: uuid.UUID
    game_id: uuid.UUID
    sequence: int = Field(description='1-based chronological order within the game.')
    question_type: QuestionType
    status: QuestionStatus
    parameters: dict = Field(description='radius_m for radar, min_travel_m for thermometer.')
    asked_by: uuid.UUID = Field(description='Player ID of the seeker who asked.')
    asked_at: datetime
    seeker_location_start: dict = Field(description='GeoJSON Point — seeker position when asked.')
    seeker_location_end: dict | None = Field(
        description='GeoJSON Point — seeker position at lock-in (thermometer only).'
    )
    answered_at: datetime | None
    hider_location: dict | None = Field(
        description='GeoJSON Point — hider position at answer time. Hidden from seekers.'
    )
    answer: str | None = Field(description='yes/no for radar, closer/farther for thermometer.')
    exclusion: dict | None = Field(description='GeoJSON Polygon — the exclusion zone.')

    @staticmethod
    def from_model(
        question: QuestionModel, *, hide_hider_location: bool = False
    ) -> QuestionResponse:
        return QuestionResponse(
            id=question.id,
            game_id=question.game_id,
            sequence=question.sequence,
            question_type=question.question_type,
            status=question.status,
            parameters=question.parameters,
            asked_by=question.asked_by,
            asked_at=question.asked_at,
            seeker_location_start=question.seeker_location_start,
            seeker_location_end=question.seeker_location_end,
            answered_at=question.answered_at,
            hider_location=None if hide_hider_location else question.hider_location,
            answer=question.answer,
            exclusion=question.exclusion,
        )


class QuestionPreview(BaseModel):
    """Live preview of what the answer would be if the hider committed now."""

    answer: str | None = Field(description='Computed answer based on current hider position.')
    exclusion: GeoPolygon | None = Field(description='Computed exclusion zone.')
