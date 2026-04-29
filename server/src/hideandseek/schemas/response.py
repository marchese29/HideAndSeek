"""Response schemas for the HideAndSeek API."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from geojson_pydantic import LineString as GeoJSONLineString
from geojson_pydantic import MultiLineString as GeoJSONMultiLineString
from geojson_pydantic import MultiPolygon as GeoJSONMultiPolygon
from geojson_pydantic import Point as GeoJSONPoint
from geojson_pydantic.geometries import Geometry as GeoJSONGeometry
from pydantic import BaseModel, Field, TypeAdapter
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from hideandseek.schemas.params import QuestionParamsResponse
from hideandseek_core.geo_helpers import geom_or_none
from hideandseek_models.types import (
    GameStatus,
    MapSize,
    PauseReason,
    PhotoSubject,
    PlayerColor,
    PlayerRole,
    ProximityTier,
    QuestionStatus,
    QuestionType,
    StationElectionStatus,
)

if TYPE_CHECKING:
    from shapely.geometry import LineString as LineStringType
    from shapely.geometry import MultiLineString as MultiLineStringType

    from hideandseek_core.exclusion import EndgameExclusionResult
    from hideandseek_core.queries.effective_map import EffectiveMapData
    from hideandseek_models.game import Game as GameModel
    from hideandseek_models.game import Player as PlayerModel
    from hideandseek_models.game_map import GameMap as GameMapModel
    from hideandseek_models.inventory import InventorySlot as InventorySlotModel
    from hideandseek_models.location import LocationUpdate as LocationUpdateModel
    from hideandseek_models.map_feature import MapFeature as MapFeatureModel
    from hideandseek_models.transit import Route as RouteModel
    from hideandseek_models.transit import Stop as StopModel


# ── Maps ──────────────────────────────────────────────────────────────────────


class MapSummary(BaseModel):
    """A map in the browse list — name, size, region, and timing defaults."""

    id: uuid.UUID
    name: str
    size: MapSize
    region: str = Field(description='Geographic region from the transit dataset.')
    default_hiding_time_min: int | None = Field(
        default=None,
        description='Map-level hiding time override (minutes). Null means use size default.',
    )
    default_base_question_delay_min: int | None = Field(
        default=None,
        description='Map-level question delay override (minutes). Null means use code default.',
    )
    default_photo_submit_min: int | None = Field(
        default=None,
        description='Map-level photo submit window override (minutes). Null = code default.',
    )
    default_photo_review_sec: int | None = Field(
        default=None,
        description='Map-level photo review window override (seconds). Null = code default.',
    )

    @staticmethod
    def from_model(game_map: GameMapModel, region: str) -> MapSummary:
        return MapSummary(
            id=game_map.id,
            name=game_map.name,
            size=game_map.size,
            region=region,
            default_hiding_time_min=game_map.default_hiding_time_min,
            default_base_question_delay_min=game_map.default_base_question_delay_min,
            default_photo_submit_min=game_map.default_photo_submit_min,
            default_photo_review_sec=game_map.default_photo_review_sec,
        )


class MapDetail(BaseModel):
    """Full map detail including geometry for rendering a preview. Omits stops/routes."""

    id: uuid.UUID
    name: str
    size: MapSize
    transit_dataset_id: uuid.UUID
    boundary: GeoJSONMultiPolygon = Field(description='GeoJSON Polygon defining the playable area.')
    districts: list = Field(description='District boundaries with id, name, class, and geometry.')
    district_classes: list = Field(description='District class definitions (tier + label).')
    default_inventory: dict = Field(description='Default question inventory for games on this map.')
    default_hiding_time_min: int | None = Field(
        default=None, description='Map-level hiding phase duration override (minutes).'
    )
    default_base_question_delay_min: int | None = Field(
        default=None, description='Map-level auto-answer delay override (minutes).'
    )
    default_photo_submit_min: int | None = Field(
        default=None, description='Map-level photo submit window override (minutes).'
    )
    default_photo_review_sec: int | None = Field(
        default=None, description='Map-level photo review window override (seconds).'
    )
    notes: str | None

    @staticmethod
    def from_model(gm: GameMapModel) -> MapDetail:
        return MapDetail(
            id=gm.id,
            name=gm.name,
            size=gm.size,
            transit_dataset_id=gm.transit_dataset_id,
            boundary=GeoJSONMultiPolygon(**mapping(gm.boundary)),
            districts=gm.districts,
            district_classes=gm.district_classes,
            default_inventory=gm.default_inventory,
            default_hiding_time_min=gm.default_hiding_time_min,
            default_base_question_delay_min=gm.default_base_question_delay_min,
            default_photo_submit_min=gm.default_photo_submit_min,
            default_photo_review_sec=gm.default_photo_review_sec,
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
    photo_subject: PhotoSubject | None = Field(
        default=None, description='Photo subject. Photo slots only.'
    )
    ask_count: int = Field(description='Number of times this slot has been used.')


class InventoryResponse(BaseModel):
    """Question inventory — all slots grouped by question type."""

    radar_slots: list[SlotResponse] = Field(description='Radar question slots.')
    thermometer_slots: list[SlotResponse] = Field(description='Thermometer question slots.')
    matching_slots: list[SlotResponse] = Field(description='Matching question slots.')
    measuring_slots: list[SlotResponse] = Field(description='Measuring question slots.')
    tentacles_slots: list[SlotResponse] = Field(description='Tentacles question slots.')
    photo_slots: list[SlotResponse] = Field(description='Photo question slots.')

    @staticmethod
    def from_slots(slots: Sequence[InventorySlotModel]) -> InventoryResponse:
        groups: dict[str, list[SlotResponse]] = {
            'radar': [],
            'thermometer': [],
            'matching': [],
            'measuring': [],
            'tentacles': [],
            'photo': [],
        }
        for s in slots:
            groups[s.question_type].append(
                SlotResponse(
                    slot_index=s.slot_index,
                    distance=s.distance,
                    category=str(s.category) if s.category else None,
                    feature_class=s.feature_class,
                    photo_subject=s.photo_subject,
                    ask_count=s.ask_count,
                )
            )
        return InventoryResponse(
            radar_slots=groups['radar'],
            thermometer_slots=groups['thermometer'],
            matching_slots=groups['matching'],
            measuring_slots=groups['measuring'],
            tentacles_slots=groups['tentacles'],
            photo_slots=groups['photo'],
        )


# ── Games ─────────────────────────────────────────────────────────────────────


class GameResponse(BaseModel):
    """Full game state, including players and question inventory."""

    id: uuid.UUID
    map_id: uuid.UUID
    host_player_id: uuid.UUID = Field(description="Player ID of the game's host.")
    status: GameStatus
    size: MapSize = Field(description='Effective game size (may differ from map size).')
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
            host_player_id=game.host_player_id,
            status=game.status,
            size=game.size,
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
    """Returned when a player joins a game — includes credentials for the session."""

    game: GameResponse
    player_id: uuid.UUID = Field(description="The joining player's ID for subsequent requests.")
    player_secret: str = Field(description='Secret token. Store securely — not retrievable again.')


class SessionResponse(BaseModel):
    """Session validation — confirms the caller is a valid player in the game."""

    player: PlayerResponse
    game_status: GameStatus


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
    shape: GeoJSONLineString | GeoJSONMultiLineString = Field(
        description='GeoJSON LineString or MultiLineString (clipped to game boundary).'
    )
    stop_ids: list[uuid.UUID] = Field(description='Ordered stop IDs along this route.')

    @staticmethod
    def from_gameplay_route(
        route: RouteModel,
        clipped_shape: LineStringType | MultiLineStringType,
        stop_ids: list[uuid.UUID],
    ) -> RouteResponse:
        geojson = mapping(clipped_shape)
        if geojson['type'] == 'LineString':
            shape: GeoJSONLineString | GeoJSONMultiLineString = GeoJSONLineString(**geojson)
        else:
            shape = GeoJSONMultiLineString(**geojson)
        return RouteResponse(
            id=route.id,
            stable_id=route.stable_id,
            name=route.name,
            color=route.color,
            route_type=route.route_type,
            shape=shape,
            stop_ids=stop_ids,
        )

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
    boundary: GeoJSONMultiPolygon = Field(description='GeoJSON Polygon.')
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
            boundary=GeoJSONMultiPolygon(**mapping(gm.boundary)),
            districts=gm.districts,
            district_classes=gm.district_classes,
            stops=[StopResponse.from_model(s) for s in data.stops],
            routes=[RouteResponse.from_model(rws.route, rws.stop_ids) for rws in data.routes],
        )


# ── Location ──────────────────────────────────────────────────────────────────


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


class TentaclePOIPreviewResponse(BaseModel):
    """A POI in a tentacles question preview."""

    feature_id: str = Field(description='Stable identifier of the POI.')
    name: str = Field(description='Human-readable name.')
    location: GeoJSONPoint = Field(description='GeoJSON Point location of the POI.')


class PreviewQuestionResponse(BaseModel):
    """Boundary geometry and optional feature info for a question preview."""

    boundary: GeoJSONGeometry = Field(
        description='GeoJSON dividing line/curve between the two possible answer outcomes.'
    )
    feature_preview: FeaturePreviewResponse | None = Field(
        default=None,
        description='Resolved feature info. Present for matching and measuring question types.',
    )
    tentacle_pois: list[TentaclePOIPreviewResponse] | None = Field(
        default=None,
        description='In-circle POIs for a tentacles question preview.',
    )


# ── Questions ─────────────────────────────────────────────────────────────────


_geojson_adapter: TypeAdapter[GeoJSONGeometry] = TypeAdapter(GeoJSONGeometry)


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
    safe_zone: GeoJSONGeometry = Field(
        description='Area within the hiding zone not covered by any exclusion. '
        'Equals hiding_zone when no exclusions exist.',
    )
    entries: list[EndgameExclusionEntryResponse]

    @staticmethod
    def from_result(result: EndgameExclusionResult) -> EndgameExclusionsResponse:
        return EndgameExclusionsResponse(
            hiding_zone=_geojson_adapter.validate_python(mapping(result.hiding_zone)),
            safe_zone=_geojson_adapter.validate_python(mapping(result.safe_zone)),
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


# ── Gameplay State ──────────────────────────────────────────────────────────


class GamePlayer(BaseModel):
    """A player with optional location — visible to roles that can see this player."""

    id: uuid.UUID
    name: str
    color: PlayerColor = Field(description='Server-assigned player color.')
    role: PlayerRole | None
    coordinates: GeoJSONPoint | None = Field(
        default=None, description='Last known position (null if not yet reported).'
    )
    timestamp: datetime | None = Field(default=None, description='Time of last location report.')


class RosterPlayer(BaseModel):
    """A player in the roster — identity only, no location fields."""

    id: uuid.UUID
    name: str
    color: PlayerColor = Field(description='Server-assigned player color.')
    role: PlayerRole | None


class HiderActiveQuestion(BaseModel):
    """The active question as seen by the hider."""

    question_id: uuid.UUID
    question_type: QuestionType
    status: QuestionStatus
    asked_by: uuid.UUID = Field(description='Seeker who asked.')
    slot_index: int = Field(description='Inventory slot used.')
    question_deadline: datetime | None = Field(
        default=None, description='When auto-answer fires (null if timer not started).'
    )
    submitted_at: datetime | None = Field(
        default=None, description='Photo questions only: when the hider submitted.'
    )
    is_null_answer: bool | None = Field(
        default=None, description='Photo questions only: true for null submissions.'
    )
    review_deadline: datetime | None = Field(
        default=None,
        description='Photo questions only: when auto-accept fires for a submitted photo.',
    )
    photo_subject: PhotoSubject | None = Field(
        default=None,
        description='Photo questions only: subject the seeker requested.',
    )
    photo_queued_by: uuid.UUID | None = Field(
        default=None,
        description='Photo questions only: hider who uploaded the queued photo.',
    )
    photo_uploaded_at: datetime | None = Field(
        default=None,
        description='Photo questions only: when the queued photo was uploaded (cache-bust key).',
    )


class SeekerActiveQuestion(BaseModel):
    """The active question as seen by the seeker."""

    question_id: uuid.UUID
    question_type: QuestionType
    status: QuestionStatus
    slot_index: int = Field(description='Inventory slot used.')
    question_deadline: datetime | None = Field(
        default=None, description='When auto-answer fires (null if timer not started).'
    )
    submitted_at: datetime | None = Field(
        default=None, description='Photo questions only: when the hider submitted.'
    )
    is_null_answer: bool | None = Field(
        default=None, description='Photo questions only: true for null submissions.'
    )
    review_deadline: datetime | None = Field(
        default=None,
        description='Photo questions only: when auto-accept fires for a submitted photo.',
    )


class HiderQuestionHistoryEntry(BaseModel):
    """A resolved question from the hider's perspective.

    Full question detail for reconnecting hiders — everything except exclusion
    geometry. Supersedes the removed ``GET /questions/{id}`` detail endpoint.
    """

    question_id: uuid.UUID
    sequence: int = Field(description='1-based chronological order within the game.')
    question_type: QuestionType
    status: QuestionStatus = Field(description='Terminal status: answered, vetoed, or abandoned.')
    ask_count: int = Field(description='Which attempt this was (1 = first ask).')
    asked_by: uuid.UUID = Field(description='Seeker who asked.')
    asked_at: datetime = Field(description='When the question was asked.')
    slot_index: int = Field(description='Inventory slot used.')
    parameters: QuestionParamsResponse = Field(description='Type-specific question parameters.')
    seeker_location_start: GeoJSONPoint = Field(
        description='GeoJSON Point — seeker position when asked.'
    )
    seeker_location_end: GeoJSONPoint | None = Field(
        default=None,
        description='GeoJSON Point — seeker position at lock-in (thermometer only).',
    )
    answer: str | None = Field(
        default=None, description='yes/no/closer/farther or null if vetoed/abandoned.'
    )
    answered_at: datetime | None = Field(
        default=None, description='When the question was resolved.'
    )
    hider_location: GeoJSONPoint | None = Field(
        default=None, description='GeoJSON Point — hider position at answer time.'
    )
    hider_feature_id: str | None = Field(
        default=None, description='Hider feature ID (matching/measuring only).'
    )
    hider_feature_name: str | None = Field(
        default=None, description='Hider feature name (matching/measuring only).'
    )
    hider_distance: float | None = Field(
        default=None,
        description='Hider distance to feature in convention units (matching/measuring only).',
    )


class SeekerQuestionHistoryEntry(BaseModel):
    """A resolved question from the seeker's perspective.

    Includes answer-time delta fields plus ask-time metadata for reconnecting
    seekers. Supersedes the removed ``GET /questions`` list endpoint.
    No hider-privileged data (no hider_location, no hider feature resolution).
    """

    question_id: uuid.UUID
    sequence: int = Field(description='1-based chronological order within the game.')
    question_type: QuestionType
    status: QuestionStatus = Field(description='Terminal status: answered, vetoed, or abandoned.')
    ask_count: int = Field(description='Which attempt this was (1 = first ask).')
    asked_by: uuid.UUID = Field(description='Seeker who asked.')
    asked_at: datetime = Field(description='When the question was asked.')
    slot_index: int = Field(description='Inventory slot used.')
    parameters: QuestionParamsResponse = Field(description='Type-specific question parameters.')
    answer: str | None = Field(
        default=None, description='yes/no/closer/farther or null if vetoed/abandoned.'
    )
    exclusion: GeoJSONGeometry | None = Field(
        default=None, description="This question's exclusion zone."
    )
    total_exclusion: GeoJSONGeometry | None = Field(
        default=None, description='Cumulative exclusion after this question.'
    )
    answered_at: datetime | None = Field(
        default=None, description='When the question was resolved.'
    )


class InventorySlotResponse(BaseModel):
    """A single inventory slot in the gameplay state."""

    question_type: QuestionType
    slot_index: int = Field(description='Original template position (stable across the game).')
    distance: float | None = Field(
        default=None, description='Preset distance. Radar/thermometer only.'
    )
    category: str | None = Field(
        default=None, description='Feature category. Matching/measuring only.'
    )
    feature_class: int | None = Field(
        default=None, description='Feature class tier. Classed categories only.'
    )
    photo_subject: PhotoSubject | None = Field(
        default=None, description='Photo subject. Photo slots only.'
    )
    ask_count: int = Field(description='Number of times this slot has been used.')


class MapFeatureResponse(BaseModel):
    """A map feature (POI) on the game map."""

    stable_id: str = Field(description='Stable identifier of the feature.')
    name: str = Field(description='Human-readable name.')
    category: str = Field(description='Feature category (e.g. hospital, park, museum).')
    feature_class: int | None = Field(
        default=None, description='Feature class tier. Classed categories only.'
    )
    location: GeoJSONPoint = Field(description='GeoJSON Point — centroid of the feature shape.')

    @staticmethod
    def from_model(feature: MapFeatureModel) -> MapFeatureResponse:
        return MapFeatureResponse(
            stable_id=feature.stable_id,
            name=feature.name,
            category=feature.category,
            feature_class=feature.feature_class,
            location=GeoJSONPoint(**mapping(feature.shape.centroid)),
        )


class GameInfoResponse(BaseModel):
    """Static game info — map geometry, transit data, timing config. Never changes mid-game."""

    game_id: uuid.UUID
    distance_convention: str = Field(description='metric or imperial.')
    boundary: GeoJSONMultiPolygon = Field(description='Game map boundary.')
    districts: list = Field(description='District boundaries.')
    stops: list[StopResponse] = Field(description='All playable stops.')
    routes: list[RouteResponse] = Field(description='Transit routes with shapes and stop IDs.')
    features: list[MapFeatureResponse] = Field(
        description='All map features (POIs) on the game map.'
    )
    hiding_time_min: int = Field(description='Hiding phase duration in minutes.')
    base_question_delay_min: int = Field(description='Auto-answer timer duration in minutes.')


class SSEExposed:
    """Mixin marking a Pydantic schema for OpenAPI injection (SSE-only, not on REST routes)."""

    _registry: ClassVar[set[type[SSEExposed]]] = set()

    def __init_subclass__(cls, **kwargs):  # noqa: ANN003
        super().__init_subclass__(**kwargs)
        SSEExposed._registry.add(cls)

    @classmethod
    def registered_schemas(cls) -> Sequence[type[SSEExposed]]:
        """Return all registered SSE-exposed schemas."""
        return list(cls._registry)


class HiderGameStateResponse(SSEExposed, BaseModel):
    """Dynamic hider state snapshot — delivered as initial SSE event on connect."""

    game_id: uuid.UUID
    phase: str = Field(description='Current phase: hiding or seeking.')
    hiding_started_at: datetime | None
    seeking_started_at: datetime | None
    self_player_id: uuid.UUID = Field(description="Caller's player ID.")
    host_player_id: uuid.UUID = Field(description="Player ID of the game's host.")
    hiders: list[GamePlayer] = Field(description='All hiders with last known positions.')
    seekers: list[GamePlayer] = Field(description='All seekers with last known positions.')
    station_election_status: StationElectionStatus
    hider_station_id: uuid.UUID | None = Field(
        default=None, description='Assigned station (once elected/assigned).'
    )
    active_question: HiderActiveQuestion | None = Field(
        default=None, description='Current unanswered question.'
    )
    question_history: list[HiderQuestionHistoryEntry] = Field(description='All resolved questions.')

    # Enrichment fields — same semantics as on PlayerLocationEvent, computed at snapshot time.
    candidate_stations: list[uuid.UUID] | None = Field(
        default=None,
        description='Stop IDs where all hiders are within hiding zone radius (pre-election only).',
    )
    not_in_zone: list[uuid.UUID] | None = Field(
        default=None,
        description='Player IDs of hiders outside the hiding zone (post-election only).',
    )
    computed_answer: str | None = Field(
        default=None,
        description='Hypothetical answer if question were answered now.',
    )
    hiding_zone_expanded: bool = Field(
        default=False, description='Whether the hiding zone has been expanded.'
    )
    proximity_tier: ProximityTier = Field(
        default=ProximityTier.none,
        description='Current proximity tier based on nearest seeker distance to hiding zone.',
    )
    freeze_departed: list[uuid.UUID] | None = Field(
        default=None,
        description='Player IDs of hiders who moved >50m from freeze position during entered tier.',
    )
    paused: bool = Field(description='Whether the game clock is currently paused.')
    paused_at: datetime | None = Field(
        default=None, description='Wall-clock instant the current pause began.'
    )
    active_pause_reasons: list[PauseReason] = Field(
        default_factory=list,
        description='Reasons currently holding the pause; empty when not paused.',
    )
    seeking_pause_accumulated_sec: int = Field(
        default=0,
        description=(
            'Total seconds of pause time during the seeking phase, for client-side elapsed math.'
        ),
    )
    hiding_ends_at: datetime | None = Field(
        default=None,
        description='Wall-clock deadline for the hiding phase; shifts forward on pause/resume.',
    )
    found_claim_expires_at: datetime | None = Field(
        default=None,
        description='Wall-clock deadline at which a pending found claim auto-dismisses.',
    )


class SeekerGameStateResponse(SSEExposed, BaseModel):
    """Dynamic seeker state snapshot — delivered as initial SSE event on connect."""

    game_id: uuid.UUID
    phase: str = Field(description='Current phase: hiding or seeking.')
    hiding_started_at: datetime | None
    seeking_started_at: datetime | None
    self_player_id: uuid.UUID = Field(description="Caller's player ID.")
    host_player_id: uuid.UUID = Field(description="Player ID of the game's host.")
    hiders: list[RosterPlayer] = Field(description='Hiders — identity only, no location.')
    seekers: list[GamePlayer] = Field(description='All seekers with last known positions.')
    active_question: SeekerActiveQuestion | None = Field(
        default=None, description='Current in-flight question.'
    )
    question_history: list[SeekerQuestionHistoryEntry] = Field(
        description='Resolved questions with answers and exclusion geometry.'
    )
    total_exclusion: GeoJSONGeometry | None = Field(
        default=None, description='Cumulative exclusion zone.'
    )
    inventory: list[InventorySlotResponse] = Field(
        description='All inventory slots with current ask counts.'
    )
    hiding_zone_expanded: bool = Field(
        default=False, description='Whether the hiding zone has been expanded.'
    )
    paused: bool = Field(description='Whether the game clock is currently paused.')
    paused_at: datetime | None = Field(
        default=None, description='Wall-clock instant the current pause began.'
    )
    active_pause_reasons: list[PauseReason] = Field(
        default_factory=list,
        description='Reasons currently holding the pause; empty when not paused.',
    )
    seeking_pause_accumulated_sec: int = Field(
        default=0,
        description=(
            'Total seconds of pause time during the seeking phase, for client-side elapsed math.'
        ),
    )
    hiding_ends_at: datetime | None = Field(
        default=None,
        description='Wall-clock deadline for the hiding phase; shifts forward on pause/resume.',
    )
    found_claim_expires_at: datetime | None = Field(
        default=None,
        description='Wall-clock deadline at which a pending found claim auto-dismisses.',
    )
