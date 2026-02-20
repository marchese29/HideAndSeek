"""Response schemas for the HideAndSeek API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from geojson_pydantic import LineString as GeoJSONLineString
from geojson_pydantic import Point as GeoJSONPoint
from geojson_pydantic import Polygon as GeoJSONPolygon
from pydantic import BaseModel, Field
from shapely.geometry import mapping

from hideandseek.models.types import (
    GameStatus,
    MapSize,
    PlayerRole,
    QuestionStatus,
    QuestionType,
    SlotType,
)

if TYPE_CHECKING:
    from hideandseek.models.game import Game as GameModel
    from hideandseek.models.game import Player as PlayerModel
    from hideandseek.models.game_map import GameMap as GameMapModel
    from hideandseek.models.location import LocationUpdate as LocationUpdateModel
    from hideandseek.models.question import Question as QuestionModel
    from hideandseek.models.transit import Route as RouteModel
    from hideandseek.models.transit import Stop as StopModel
    from hideandseek.queries.effective_map import EffectiveMapData


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
    boundary: GeoJSONPolygon = Field(description='GeoJSON Polygon defining the playable area.')
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
            boundary=GeoJSONPolygon(**mapping(gm.boundary)),
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


# ── Inventory ─────────────────────────────────────────────────────────────────


class SlotResponse(BaseModel):
    """A single inventory slot (radar or thermometer)."""

    id: uuid.UUID
    slot_index: int = Field(description='Original ordering index.')
    distance_m: int | None = Field(description='Preset distance, or null for custom.')
    consumed: bool = Field(description='Whether this slot has been used.')


class CategoryUsageResponse(BaseModel):
    """A used matching or measuring category."""

    category: str
    feature_class: int | None = None
    consumed_at: datetime


class InventoryResponse(BaseModel):
    """Structured question inventory for a game."""

    radar_slots: list[SlotResponse] = Field(description='Radar question slots.')
    thermometer_slots: list[SlotResponse] = Field(description='Thermometer question slots.')
    matching_used: list[CategoryUsageResponse] = Field(
        description='Matching categories already used.'
    )
    measuring_used: list[CategoryUsageResponse] = Field(
        description='Measuring categories already used.'
    )


# ── Games ─────────────────────────────────────────────────────────────────────


class GameResponse(BaseModel):
    """Full game state, including players and inventory."""

    id: uuid.UUID
    map_id: uuid.UUID
    status: GameStatus
    join_code: str | None = Field(description='4-character code for joining. Null after game ends.')
    timing: dict = Field(description='TimingRules: hiding_time_min, rest_periods, etc.')
    inventory: InventoryResponse = Field(description='Question inventory (slots + category usage).')
    players: list[PlayerResponse]
    created_at: datetime
    hiding_started_at: datetime | None = Field(
        default=None, description='When the hiding phase began. Clients compute countdown.'
    )
    seeking_started_at: datetime | None = Field(
        default=None, description='When the seeking phase began.'
    )

    @staticmethod
    def from_model(game: GameModel) -> GameResponse:
        radar_slots = [
            SlotResponse(
                id=s.id,
                slot_index=s.slot_index,
                distance_m=s.distance_m,
                consumed=s.consumed_at is not None,
            )
            for s in game.inventory_slots
            if s.slot_type == SlotType.radar
        ]
        thermometer_slots = [
            SlotResponse(
                id=s.id,
                slot_index=s.slot_index,
                distance_m=s.distance_m,
                consumed=s.consumed_at is not None,
            )
            for s in game.inventory_slots
            if s.slot_type == SlotType.thermometer
        ]
        matching_used = [
            CategoryUsageResponse(
                category=str(u.category),
                feature_class=u.feature_class,
                consumed_at=u.consumed_at,
            )
            for u in game.category_usages
            if u.question_type == QuestionType.matching
        ]
        measuring_used = [
            CategoryUsageResponse(
                category=str(u.category),
                feature_class=u.feature_class,
                consumed_at=u.consumed_at,
            )
            for u in game.category_usages
            if u.question_type == QuestionType.measuring
        ]

        return GameResponse(
            id=game.id,
            map_id=game.map_id,
            status=game.status,
            join_code=game.join_code,
            timing=game.timing,
            inventory=InventoryResponse(
                radar_slots=radar_slots,
                thermometer_slots=thermometer_slots,
                matching_used=matching_used,
                measuring_used=measuring_used,
            ),
            players=[PlayerResponse.from_model(p) for p in game.players],
            created_at=game.created_at,
            hiding_started_at=game.hiding_started_at,
            seeking_started_at=game.seeking_started_at,
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
    coordinates: GeoJSONPoint = Field(description='GeoJSON Point.')

    @staticmethod
    def from_model(stop: StopModel) -> StopResponse:
        return StopResponse(
            id=stop.id,
            stable_id=stop.stable_id,
            name=stop.name,
            coordinates=GeoJSONPoint(**mapping(stop.coordinates)),
        )


class RouteResponse(BaseModel):
    """A transit route on the effective game map, with ordered stop IDs."""

    id: uuid.UUID
    stable_id: str = Field(description='Stable identifier from the transit dataset.')
    name: str
    color: str = Field(description='Hex color for rendering.')
    route_type: str = Field(description='metro, bus, tram, rail, or ferry.')
    shape: GeoJSONLineString = Field(description='GeoJSON LineString.')
    stop_ids: list[uuid.UUID] = Field(description='Ordered stop IDs along this route.')

    @staticmethod
    def from_model(route: RouteModel, stop_ids: list[uuid.UUID]) -> RouteResponse:
        return RouteResponse(
            id=route.id,
            stable_id=route.stable_id,
            name=route.name,
            color=route.color,
            route_type=route.route_type,
            shape=GeoJSONLineString(**mapping(route.shape)),
            stop_ids=stop_ids,
        )


class EffectiveMapResponse(BaseModel):
    """The game map with transit data and exclusions applied.

    Single source of truth for what the client should render.
    """

    name: str
    size: MapSize
    boundary: GeoJSONPolygon = Field(description='GeoJSON Polygon.')
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
            boundary=GeoJSONPolygon(**mapping(gm.boundary)),
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
    coordinates: GeoJSONPoint = Field(description='GeoJSON Point — latest reported position.')
    timestamp: datetime


class LocationReportResponse(BaseModel):
    """Returned after reporting location — includes positions of all visible players."""

    players: list[VisiblePlayer]


class LocationHistoryEntry(BaseModel):
    """A single location update in the post-game replay log."""

    player_id: uuid.UUID
    coordinates: GeoJSONPoint = Field(description='GeoJSON Point.')
    timestamp: datetime

    @staticmethod
    def from_model(lu: LocationUpdateModel) -> LocationHistoryEntry:
        return LocationHistoryEntry(
            player_id=lu.player_id,
            coordinates=GeoJSONPoint(**mapping(lu.coordinates)),
            timestamp=lu.timestamp,
        )


# ── Feature Preview ──────────────────────────────────────────────────────


class FeaturePreviewResponse(BaseModel):
    """Preview of the nearest/containing feature for a matching or measuring question."""

    feature_id: str = Field(description='Stable identifier of the resolved feature.')
    name: str = Field(description='Human-readable name of the feature.')
    distance_m: float = Field(description='Distance in meters from the query location.')


# ── Question Parameters (typed responses) ────────────────────────────────


class RadarParamsResponse(BaseModel):
    """Parameters for a radar question."""

    type: Literal['radar'] = 'radar'
    radius_m: int = Field(description='Radar radius in meters.')


class ThermometerParamsResponse(BaseModel):
    """Parameters for a thermometer question."""

    type: Literal['thermometer'] = 'thermometer'
    min_travel_m: int = Field(description='Minimum travel distance in meters.')


class FeatureResolution(BaseModel):
    """Resolution result for one player's feature lookup."""

    feature_id: str = Field(description='Stable identifier of the resolved feature.')
    name: str = Field(description='Human-readable name.')
    distance_m: float = Field(description='Distance in meters.')


class FeatureParamsResponse(BaseModel):
    """Parameters for a matching or measuring question."""

    type: Literal['matching', 'measuring']
    category: str = Field(description='Feature category.')
    feature_class: int | None = Field(
        default=None, description='Feature class tier, if applicable.'
    )
    source: str = Field(description='Data source (e.g. map_data).')
    seeker_resolution: FeatureResolution = Field(description='Seeker feature resolution.')
    hider_resolution: FeatureResolution | None = Field(
        default=None, description='Hider feature resolution (populated at answer time).'
    )


QuestionParamsResponse = RadarParamsResponse | ThermometerParamsResponse | FeatureParamsResponse


# ── Questions ─────────────────────────────────────────────────────────────────


class QuestionResponse(BaseModel):
    """A question in the game — state machine: asked -> in_progress -> answerable -> answered."""

    id: uuid.UUID
    game_id: uuid.UUID
    sequence: int = Field(description='1-based chronological order within the game.')
    question_type: QuestionType
    status: QuestionStatus
    parameters: QuestionParamsResponse = Field(description='Type-specific question parameters.')
    asked_by: uuid.UUID = Field(description='Player ID of the seeker who asked.')
    asked_at: datetime
    seeker_location_start: GeoJSONPoint = Field(
        description='GeoJSON Point — seeker position when asked.'
    )
    seeker_location_end: GeoJSONPoint | None = Field(
        description='GeoJSON Point — seeker position at lock-in (thermometer only).'
    )
    answerable_at: datetime | None = Field(
        default=None, description='When the question became answerable. Clients compute deadline.'
    )
    answered_at: datetime | None
    hider_location: GeoJSONPoint | None = Field(
        description='GeoJSON Point — hider position at answer time. Hidden from seekers.'
    )
    answer: str | None = Field(description='yes/no for radar, closer/farther for thermometer.')
    exclusion: dict | None = Field(description='GeoJSON geometry — the exclusion zone.')

    @staticmethod
    def from_model(
        question: QuestionModel, *, hide_hider_location: bool = False
    ) -> QuestionResponse:
        def _point_or_none(val: object) -> GeoJSONPoint | None:
            if val is None:
                return None
            return GeoJSONPoint(**mapping(val))  # type: ignore[arg-type]

        # Build typed parameters from the relationship
        params: QuestionParamsResponse
        if question.question_type == QuestionType.radar:
            rp = question.radar_params
            assert rp is not None
            params = RadarParamsResponse(radius_m=rp.radius_m)
        elif question.question_type == QuestionType.thermometer:
            tp = question.thermometer_params
            assert tp is not None
            params = ThermometerParamsResponse(min_travel_m=tp.min_travel_m)
        else:
            fp = question.feature_params
            assert fp is not None
            seeker_res = FeatureResolution(
                feature_id=fp.seeker_feature_id,
                name=fp.seeker_feature_name,
                distance_m=fp.seeker_distance_m,
            )
            hider_res = None
            if fp.hider_feature_id is not None:
                hider_res = FeatureResolution(
                    feature_id=fp.hider_feature_id,
                    name=fp.hider_feature_name or '',
                    distance_m=fp.hider_distance_m or 0.0,
                )
            params = FeatureParamsResponse(
                type=question.question_type,  # type: ignore[arg-type]
                category=str(fp.category),
                feature_class=fp.feature_class,
                source=fp.source,
                seeker_resolution=seeker_res,
                hider_resolution=hider_res,
            )

        return QuestionResponse(
            id=question.id,
            game_id=question.game_id,
            sequence=question.sequence,
            question_type=question.question_type,
            status=question.status,
            parameters=params,
            asked_by=question.asked_by,
            asked_at=question.asked_at,
            seeker_location_start=GeoJSONPoint(**mapping(question.seeker_location_start)),
            seeker_location_end=_point_or_none(question.seeker_location_end),
            answerable_at=question.answerable_at,
            answered_at=question.answered_at,
            hider_location=None if hide_hider_location else _point_or_none(question.hider_location),
            answer=question.answer,
            exclusion=dict(mapping(question.exclusion)) if question.exclusion else None,
        )
