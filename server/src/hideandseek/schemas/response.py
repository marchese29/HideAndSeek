"""Response schemas for the HideAndSeek API."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from geojson_pydantic import LineString as GeoJSONLineString
from geojson_pydantic import Point as GeoJSONPoint
from geojson_pydantic import Polygon as GeoJSONPolygon
from geojson_pydantic.geometries import Geometry as GeoJSONGeometry
from pydantic import BaseModel, Field, TypeAdapter
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from hideandseek.models.types import (
    GameStatus,
    MapSize,
    PlayerColor,
    PlayerRole,
    QuestionStatus,
    QuestionType,
    StationElectionStatus,
)

if TYPE_CHECKING:
    from hideandseek.exclusion import EndgameExclusionResult
    from hideandseek.models.game import Game as GameModel
    from hideandseek.models.game import Player as PlayerModel
    from hideandseek.models.game_map import GameMap as GameMapModel
    from hideandseek.models.inventory import InventorySlot as InventorySlotModel
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
    default_hiding_time_min: int | None = Field(
        default=None, description='Map-level hiding phase duration override (minutes).'
    )
    default_base_question_delay_min: int | None = Field(
        default=None, description='Map-level auto-answer delay override (minutes).'
    )
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
            default_hiding_time_min=gm.default_hiding_time_min,
            default_base_question_delay_min=gm.default_base_question_delay_min,
            notes=gm.notes,
        )


# ── Players ───────────────────────────────────────────────────────────────────


class PlayerResponse(BaseModel):
    """A player in a game."""

    id: uuid.UUID
    name: str
    color: PlayerColor = Field(description='Server-assigned player color.')
    role: PlayerRole | None = Field(description='Null until the host assigns a role.')

    @staticmethod
    def from_model(player: PlayerModel) -> PlayerResponse:
        return PlayerResponse(id=player.id, name=player.name, color=player.color, role=player.role)


# ── Inventory ─────────────────────────────────────────────────────────────────


class SlotResponse(BaseModel):
    """A slot in the question inventory."""

    slot_index: int = Field(description='Original template position (stable across the game).')
    distance: float | None = Field(
        default=None,
        description='Preset distance or null for custom. Radar/thermometer only.',
    )
    category: str | None = Field(
        default=None, description='Feature category. Matching/measuring only.'
    )
    feature_class: int | None = Field(
        default=None, description='Feature class tier. Classed categories only.'
    )
    ask_count: int = Field(description='Number of times this slot has been used.')


class InventoryResponse(BaseModel):
    """Question inventory — all slots grouped by question type."""

    radar_slots: list[SlotResponse] = Field(description='Radar question slots.')
    thermometer_slots: list[SlotResponse] = Field(description='Thermometer question slots.')
    matching_slots: list[SlotResponse] = Field(description='Matching question slots.')
    measuring_slots: list[SlotResponse] = Field(description='Measuring question slots.')

    @staticmethod
    def from_slots(slots: Sequence[InventorySlotModel]) -> InventoryResponse:
        groups: dict[str, list[SlotResponse]] = {
            'radar': [],
            'thermometer': [],
            'matching': [],
            'measuring': [],
        }
        for s in slots:
            groups[s.question_type].append(
                SlotResponse(
                    slot_index=s.slot_index,
                    distance=s.distance,
                    category=str(s.category) if s.category else None,
                    feature_class=s.feature_class,
                    ask_count=s.ask_count,
                )
            )
        return InventoryResponse(
            radar_slots=groups['radar'],
            thermometer_slots=groups['thermometer'],
            matching_slots=groups['matching'],
            measuring_slots=groups['measuring'],
        )


# ── Games ─────────────────────────────────────────────────────────────────────


class GameResponse(BaseModel):
    """Full game state, including players and question inventory."""

    id: uuid.UUID
    map_id: uuid.UUID
    status: GameStatus
    convention: str = Field(description='Distance convention: "metric" or "imperial".')
    join_code: str | None = Field(
        description='4-character code for joining. Null once hiding starts.'
    )
    hiding_time_min: int = Field(description='Hiding phase duration in minutes.')
    base_question_delay_min: int = Field(description='Auto-answer delay in minutes.')
    inventory: InventoryResponse = Field(
        description='Question inventory — all slots grouped by type.'
    )
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
        return GameResponse(
            id=game.id,
            map_id=game.map_id,
            status=game.status,
            convention=game.game_map.convention,
            join_code=game.join_code,
            hiding_time_min=game.hiding_time_min,
            base_question_delay_min=game.base_question_delay_min,
            inventory=InventoryResponse.from_slots(game.inventory_slots),
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
    color: PlayerColor
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
    distance: float = Field(description='Distance in convention units from the query location.')


# ── Question Parameters (typed responses) ────────────────────────────────


class RadarParamsResponse(BaseModel):
    """Parameters for a radar question."""

    type: Literal['radar'] = 'radar'
    radius: float = Field(description='Radar radius in convention units.')


class ThermometerParamsResponse(BaseModel):
    """Parameters for a thermometer question."""

    type: Literal['thermometer'] = 'thermometer'
    min_travel: float = Field(description='Minimum travel distance in convention units.')


class FeatureResolution(BaseModel):
    """Resolution result for one player's feature lookup."""

    feature_id: str = Field(description='Stable identifier of the resolved feature.')
    name: str = Field(description='Human-readable name.')
    distance: float = Field(description='Distance in convention units.')


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


_geojson_adapter: TypeAdapter[GeoJSONGeometry] = TypeAdapter(GeoJSONGeometry)


def geom_or_none(geom: object) -> GeoJSONGeometry | None:
    if geom is None:
        return None
    return _geojson_adapter.validate_python(mapping(geom))  # type: ignore[arg-type]


def _build_question_params(question: QuestionModel) -> QuestionParamsResponse:
    """Build typed parameters from the question's param relationships."""
    if question.question_type == QuestionType.radar:
        rp = question.radar_params
        assert rp is not None
        return RadarParamsResponse(radius=rp.radius)
    elif question.question_type == QuestionType.thermometer:
        tp = question.thermometer_params
        assert tp is not None
        return ThermometerParamsResponse(min_travel=tp.min_travel)
    else:
        fp = question.feature_params
        assert fp is not None
        seeker_res = FeatureResolution(
            feature_id=fp.seeker_feature_id,
            name=fp.seeker_feature_name,
            distance=fp.seeker_distance,
        )
        hider_res = None
        if fp.hider_feature_id is not None:
            hider_res = FeatureResolution(
                feature_id=fp.hider_feature_id,
                name=fp.hider_feature_name or '',
                distance=fp.hider_distance or 0.0,
            )
        return FeatureParamsResponse(
            type=question.question_type,  # type: ignore[arg-type]
            category=str(fp.category),
            feature_class=fp.feature_class,
            source=fp.source,
            seeker_resolution=seeker_res,
            hider_resolution=hider_res,
        )


class QuestionSummaryResponse(BaseModel):
    """Lightweight question summary — whitelist of safe fields for shared polling.

    No parameters, no locations, no geometry. Both roles use this to detect
    new activity. New fields added to the question model do not appear here
    until consciously included.
    """

    id: uuid.UUID
    sequence: int = Field(description='1-based chronological order within the game.')
    question_type: QuestionType
    status: QuestionStatus
    ask_count: int = Field(description='Which attempt this was (1 = first ask).')
    asked_by: uuid.UUID = Field(description='Player ID of the seeker who asked.')
    asked_at: datetime
    answered_at: datetime | None
    answer: str | None = Field(description='yes/no for radar, closer/farther for thermometer, etc.')

    @staticmethod
    def from_model(question: QuestionModel) -> QuestionSummaryResponse:
        return QuestionSummaryResponse(
            id=question.id,
            sequence=question.sequence,
            question_type=question.question_type,
            status=question.status,
            ask_count=question.ask_count,
            asked_by=question.asked_by,
            asked_at=question.asked_at,
            answered_at=question.answered_at,
            answer=question.answer,
        )


class AskQuestionResponse(BaseModel):
    """Slim response for ask endpoints — only fields meaningful at ask time.

    No answer-time fields (seeker_location_end, hider_location, answered_at, answer).
    """

    id: uuid.UUID
    game_id: uuid.UUID
    sequence: int = Field(description='1-based chronological order within the game.')
    question_type: QuestionType
    status: QuestionStatus
    ask_count: int = Field(description='Which attempt this was (1 = first ask).')
    parameters: QuestionParamsResponse = Field(description='Type-specific question parameters.')
    asked_by: uuid.UUID = Field(description='Player ID of the seeker who asked.')
    asked_at: datetime
    seeker_location_start: GeoJSONPoint = Field(
        description='GeoJSON Point — seeker position when asked.'
    )

    @staticmethod
    def from_model(question: QuestionModel) -> AskQuestionResponse:
        return AskQuestionResponse(
            id=question.id,
            game_id=question.game_id,
            sequence=question.sequence,
            question_type=question.question_type,
            status=question.status,
            ask_count=question.ask_count,
            parameters=_build_question_params(question),
            asked_by=question.asked_by,
            asked_at=question.asked_at,
            seeker_location_start=GeoJSONPoint(**mapping(question.seeker_location_start)),
        )


class QuestionDetailResponse(BaseModel):
    """Full question detail for hiders — everything except exclusion geometry.

    Used by the hider detail endpoint and write endpoints (answer/lock-in).
    """

    id: uuid.UUID
    game_id: uuid.UUID
    sequence: int = Field(description='1-based chronological order within the game.')
    question_type: QuestionType
    status: QuestionStatus
    ask_count: int = Field(description='Which attempt this was (1 = first ask).')
    parameters: QuestionParamsResponse = Field(description='Type-specific question parameters.')
    asked_by: uuid.UUID = Field(description='Player ID of the seeker who asked.')
    asked_at: datetime
    seeker_location_start: GeoJSONPoint = Field(
        description='GeoJSON Point — seeker position when asked.'
    )
    seeker_location_end: GeoJSONPoint | None = Field(
        description='GeoJSON Point — seeker position at lock-in (thermometer only).'
    )
    answered_at: datetime | None
    hider_location: GeoJSONPoint | None = Field(
        description='GeoJSON Point — hider position at answer time.'
    )
    answer: str | None = Field(description='yes/no for radar, closer/farther for thermometer.')

    @staticmethod
    def from_model(question: QuestionModel) -> QuestionDetailResponse:
        def _point_or_none(val: object) -> GeoJSONPoint | None:
            if val is None:
                return None
            return GeoJSONPoint(**mapping(val))  # type: ignore[arg-type]

        return QuestionDetailResponse(
            id=question.id,
            game_id=question.game_id,
            sequence=question.sequence,
            question_type=question.question_type,
            status=question.status,
            ask_count=question.ask_count,
            parameters=_build_question_params(question),
            asked_by=question.asked_by,
            asked_at=question.asked_at,
            seeker_location_start=GeoJSONPoint(**mapping(question.seeker_location_start)),
            seeker_location_end=_point_or_none(question.seeker_location_end),
            answered_at=question.answered_at,
            hider_location=_point_or_none(question.hider_location),
            answer=question.answer,
        )


# ── Hider Station ────────────────────────────────────────────────────────


class HiderStationResponse(BaseModel):
    """The hider's assigned station — includes election status."""

    hider_station_id: uuid.UUID | None = Field(
        description='Station UUID, or null if not yet assigned (ambiguous/pending).'
    )
    station_election_status: StationElectionStatus = Field(
        description='Current station election status.'
    )


class NearbyStationResponse(BaseModel):
    """A playable stop near a given point, with its hiding zone polygon."""

    id: uuid.UUID
    stable_id: str = Field(description='Stable identifier from the transit dataset.')
    name: str
    coordinates: GeoJSONPoint = Field(description='GeoJSON Point.')
    hiding_zone: GeoJSONGeometry = Field(
        description='Hiding zone polygon (buffer clipped to game map boundary).'
    )

    @staticmethod
    def from_stop_and_zone(
        stop: StopModel,
        zone: BaseGeometry,
    ) -> NearbyStationResponse:
        return NearbyStationResponse(
            id=stop.id,
            stable_id=stop.stable_id,
            name=stop.name,
            coordinates=GeoJSONPoint(**mapping(stop.coordinates)),
            hiding_zone=_geojson_adapter.validate_python(mapping(zone)),
        )


class HidingZoneResponse(BaseModel):
    """The hiding zone polygon around a given station."""

    hiding_zone: GeoJSONGeometry = Field(
        description='Hiding zone polygon (buffer clipped to game map boundary).'
    )

    @staticmethod
    def from_geometry(zone: BaseGeometry) -> HidingZoneResponse:
        return HidingZoneResponse(
            hiding_zone=_geojson_adapter.validate_python(mapping(zone)),
        )


# ── Exclusions ───────────────────────────────────────────────────────────


class QuestionExclusionEntry(BaseModel):
    """Per-question exclusion geometry for seekers."""

    question_id: uuid.UUID
    sequence: int = Field(description='1-based chronological order within the game.')
    question_type: QuestionType
    exclusion: GeoJSONGeometry | None = Field(description='GeoJSON geometry — the exclusion zone.')


class ExclusionsResponse(BaseModel):
    """Seeker tactical view — per-question exclusion geometry and cumulative total."""

    exclusions: list[QuestionExclusionEntry]
    total_exclusion: GeoJSONGeometry | None = Field(
        description='Cumulative exclusion across all answered questions.'
    )


# ── Endgame ──────────────────────────────────────────────────────────────────


class EndgameExclusionEntryResponse(BaseModel):
    """One question's exclusion intersected with the hiding zone."""

    question_id: uuid.UUID
    sequence: int = Field(description='1-based chronological order within the game.')
    exclusion: GeoJSONGeometry | None = Field(
        description='Exclusion zone intersected with the hiding zone circle.'
    )
    total_exclusion: GeoJSONGeometry | None = Field(
        description='Cumulative exclusion across endgame-scoped questions.'
    )


class EndgameExclusionsResponse(BaseModel):
    """Endgame exclusion view — hiding zone geometry and per-question intersected exclusions."""

    hiding_zone: GeoJSONGeometry = Field(
        description='Hiding zone circle (clipped to game map boundary).'
    )
    entries: list[EndgameExclusionEntryResponse]

    @staticmethod
    def from_result(result: EndgameExclusionResult) -> EndgameExclusionsResponse:
        return EndgameExclusionsResponse(
            hiding_zone=_geojson_adapter.validate_python(mapping(result.hiding_zone)),
            entries=[
                EndgameExclusionEntryResponse(
                    question_id=e.question_id,
                    sequence=e.sequence,
                    exclusion=geom_or_none(e.exclusion),
                    total_exclusion=geom_or_none(e.total_exclusion),
                )
                for e in result.entries
            ],
        )
