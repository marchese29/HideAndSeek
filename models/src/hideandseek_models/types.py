from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel

# ── Enums ──────────────────────────────────────────────────────────────────────


class PlayerColor(StrEnum):
    red = 'red'
    blue = 'blue'
    green = 'green'
    orange = 'orange'
    purple = 'purple'
    teal = 'teal'
    pink = 'pink'
    amber = 'amber'
    cyan = 'cyan'
    lime = 'lime'
    indigo = 'indigo'
    coral = 'coral'


MAX_PLAYERS = 12


class RouteType(StrEnum):
    metro = 'metro'
    bus = 'bus'
    tram = 'tram'
    rail = 'rail'
    ferry = 'ferry'


class DistanceConvention(StrEnum):
    metric = 'metric'
    imperial = 'imperial'


class MapSize(StrEnum):
    small = 'small'
    medium = 'medium'
    large = 'large'
    special = 'special'


class GameStatus(StrEnum):
    lobby = 'lobby'
    hiding = 'hiding'
    seeking = 'seeking'
    finished = 'finished'
    dissolved = 'dissolved'

    @property
    def is_lobby(self) -> bool:
        """Game is waiting for players to join."""
        return self == GameStatus.lobby

    @property
    def is_hiding(self) -> bool:
        """Hider is traveling to their hiding spot."""
        return self == GameStatus.hiding

    @property
    def is_seeking(self) -> bool:
        """Seekers are actively searching for the hider."""
        return self == GameStatus.seeking

    @property
    def is_finished(self) -> bool:
        """Game ran to completion."""
        return self == GameStatus.finished

    @property
    def is_active(self) -> bool:
        """Game is in an active play phase (hiding or seeking)."""
        return self.is_hiding or self.is_seeking


class PlayerRole(StrEnum):
    hider = 'hider'
    seeker = 'seeker'


class FeatureCategory(StrEnum):
    # Matching-only
    transit_line = 'transit_line'
    administrative_area = 'administrative_area'
    landmass = 'landmass'

    # Measuring-only
    high_speed_train_line = 'high_speed_train_line'
    rail_station = 'rail_station'
    international_border = 'international_border'
    admin_division_border = 'admin_division_border'
    coastline = 'coastline'

    # Both matching and measuring
    commercial_airport = 'commercial_airport'
    mountain = 'mountain'
    park = 'park'
    amusement_park = 'amusement_park'
    zoo = 'zoo'
    aquarium = 'aquarium'
    golf_course = 'golf_course'
    museum = 'museum'
    movie_theater = 'movie_theater'
    hospital = 'hospital'
    library = 'library'
    foreign_consulate = 'foreign_consulate'


# ── Feature category classification ───────────────────────────────────────────

MATCHING_CATEGORIES: set[FeatureCategory] = {
    FeatureCategory.transit_line,
    FeatureCategory.administrative_area,
    FeatureCategory.landmass,
    FeatureCategory.commercial_airport,
    FeatureCategory.mountain,
    FeatureCategory.park,
    FeatureCategory.amusement_park,
    FeatureCategory.zoo,
    FeatureCategory.aquarium,
    FeatureCategory.golf_course,
    FeatureCategory.museum,
    FeatureCategory.movie_theater,
    FeatureCategory.hospital,
    FeatureCategory.library,
    FeatureCategory.foreign_consulate,
}

MEASURING_CATEGORIES: set[FeatureCategory] = {
    FeatureCategory.high_speed_train_line,
    FeatureCategory.rail_station,
    FeatureCategory.international_border,
    FeatureCategory.admin_division_border,
    FeatureCategory.coastline,
    FeatureCategory.commercial_airport,
    FeatureCategory.mountain,
    FeatureCategory.park,
    FeatureCategory.amusement_park,
    FeatureCategory.zoo,
    FeatureCategory.aquarium,
    FeatureCategory.golf_course,
    FeatureCategory.museum,
    FeatureCategory.movie_theater,
    FeatureCategory.hospital,
    FeatureCategory.library,
    FeatureCategory.foreign_consulate,
}

# Matching uses ST_Contains for these polygon categories (non-tiling — may return None)
CONTAINMENT_CATEGORIES: set[FeatureCategory] = {
    FeatureCategory.administrative_area,
    FeatureCategory.landmass,
}

# Categories that require a feature_class to disambiguate tiers
CLASSED_CATEGORIES: set[FeatureCategory] = {
    FeatureCategory.administrative_area,
}


def category_key(category: FeatureCategory, feature_class: int | None) -> str:
    """Build inventory key like 'hospital' or 'administrative_area:1'."""
    if feature_class is not None:
        return f'{category}:{feature_class}'
    return str(category)


# ── Question types ────────────────────────────────────────────────────────────


class QuestionType(StrEnum):
    radar = 'radar'
    thermometer = 'thermometer'
    matching = 'matching'
    measuring = 'measuring'
    tentacles = 'tentacles'
    photo = 'photo'


class QuestionStatus(StrEnum):
    asked = 'asked'
    in_progress = 'in_progress'
    answerable = 'answerable'
    submitted = 'submitted'
    answered = 'answered'
    vetoed = 'vetoed'
    abandoned = 'abandoned'
    randomized = 'randomized'


# ── Photo questions ───────────────────────────────────────────────────────────


class PhotoSubject(StrEnum):
    # small-gated
    tree = 'tree'
    sky = 'sky'
    selfie = 'selfie'
    widest_street = 'widest_street'
    tallest_structure_in_sightline = 'tallest_structure_in_sightline'
    any_building_from_station = 'any_building_from_station'

    # medium-gated
    tallest_building_from_station = 'tallest_building_from_station'
    nearest_street_trace = 'nearest_street_trace'
    two_buildings = 'two_buildings'
    restaurant_interior = 'restaurant_interior'
    train_platform = 'train_platform'
    park = 'park'
    grocery_aisle = 'grocery_aisle'
    place_of_worship = 'place_of_worship'

    # large-gated
    half_mile_streets_traced = 'half_mile_streets_traced'
    tallest_mountain_from_station = 'tallest_mountain_from_station'
    biggest_body_of_water = 'biggest_body_of_water'
    five_buildings = 'five_buildings'


class PhotoReviewDecision(StrEnum):
    accepted = 'accepted'
    rejected = 'rejected'
    auto_accepted = 'auto_accepted'


@dataclass(frozen=True)
class PhotoSubjectMeta:
    label: str
    min_size: MapSize


PHOTO_SUBJECT_META: dict[PhotoSubject, PhotoSubjectMeta] = {
    # small
    PhotoSubject.tree: PhotoSubjectMeta(label='A Tree', min_size=MapSize.small),
    PhotoSubject.sky: PhotoSubjectMeta(label='The Sky', min_size=MapSize.small),
    PhotoSubject.selfie: PhotoSubjectMeta(label='A Selfie', min_size=MapSize.small),
    PhotoSubject.widest_street: PhotoSubjectMeta(label='The Widest Street', min_size=MapSize.small),
    PhotoSubject.tallest_structure_in_sightline: PhotoSubjectMeta(
        label='The Tallest Structure in Your Sightline', min_size=MapSize.small
    ),
    PhotoSubject.any_building_from_station: PhotoSubjectMeta(
        label='Any Building From Your Station', min_size=MapSize.small
    ),
    # medium
    PhotoSubject.tallest_building_from_station: PhotoSubjectMeta(
        label='The Tallest Building From Your Station', min_size=MapSize.medium
    ),
    PhotoSubject.nearest_street_trace: PhotoSubjectMeta(
        label='A Trace of the Nearest Street', min_size=MapSize.medium
    ),
    PhotoSubject.two_buildings: PhotoSubjectMeta(label='Two Buildings', min_size=MapSize.medium),
    PhotoSubject.restaurant_interior: PhotoSubjectMeta(
        label='A Restaurant Interior', min_size=MapSize.medium
    ),
    PhotoSubject.train_platform: PhotoSubjectMeta(
        label='A Train Platform', min_size=MapSize.medium
    ),
    PhotoSubject.park: PhotoSubjectMeta(label='A Park', min_size=MapSize.medium),
    PhotoSubject.grocery_aisle: PhotoSubjectMeta(
        label='A Grocery Store Aisle', min_size=MapSize.medium
    ),
    PhotoSubject.place_of_worship: PhotoSubjectMeta(
        label='A Place of Worship', min_size=MapSize.medium
    ),
    # large
    PhotoSubject.half_mile_streets_traced: PhotoSubjectMeta(
        label='A Half-Mile of Streets Traced', min_size=MapSize.large
    ),
    PhotoSubject.tallest_mountain_from_station: PhotoSubjectMeta(
        label='The Tallest Mountain From Your Station', min_size=MapSize.large
    ),
    PhotoSubject.biggest_body_of_water: PhotoSubjectMeta(
        label='The Biggest Body of Water', min_size=MapSize.large
    ),
    PhotoSubject.five_buildings: PhotoSubjectMeta(label='Five Buildings', min_size=MapSize.large),
}

_SIZE_ORDER: dict[MapSize, int] = {
    MapSize.small: 0,
    MapSize.medium: 1,
    MapSize.large: 2,
}


def subjects_for_size(size: MapSize) -> list[PhotoSubject]:
    """Return photo subjects available at the given map size.

    Subjects unlock as map size grows: small → 6, medium → 14, large → 18.
    `MapSize.special` returns [] (never user-selectable for gameplay).
    """
    if size == MapSize.special:
        return []
    target = _SIZE_ORDER[size]
    return [s for s, meta in PHOTO_SUBJECT_META.items() if _SIZE_ORDER[meta.min_size] <= target]


class StationElectionStatus(StrEnum):
    pending = 'pending'
    elected = 'elected'
    auto_assigned = 'auto_assigned'
    ambiguous = 'ambiguous'


class ProximityTier(StrEnum):
    none = 'none'
    approaching = 'approaching'
    near = 'near'
    entered = 'entered'


class EndReason(StrEnum):
    found = 'found'
    host_ended = 'host_ended'
    dissolved = 'dissolved'


class PauseReason(StrEnum):
    photo_question_open = 'photo_question_open'
    host = 'host'
    rest_period = 'rest_period'


class LobbyEventType(StrEnum):
    game_state = 'game_state'
    player_joined = 'player_joined'
    player_updated = 'player_updated'
    player_left = 'player_left'
    host_changed = 'host_changed'
    game_started = 'game_started'


class GameplayEventType(StrEnum):
    game_state = 'game_state'
    player_location = 'player_location'
    question_asked = 'question_asked'
    question_answerable = 'question_answerable'
    question_answered = 'question_answered'
    question_vetoed = 'question_vetoed'
    question_abandoned = 'question_abandoned'
    phase_changed = 'phase_changed'
    station_election = 'station_election'
    player_left = 'player_left'
    host_changed = 'host_changed'
    game_dissolved = 'game_dissolved'
    game_ended = 'game_ended'
    hiding_zone_expanded = 'hiding_zone_expanded'
    proximity_escalated = 'proximity_escalated'
    proximity_deescalated = 'proximity_deescalated'
    found_claim = 'found_claim'
    found_claim_rejected = 'found_claim_rejected'
    found_claim_expired = 'found_claim_expired'
    photo_queued = 'photo_queued'
    photo_submitted = 'photo_submitted'
    photo_rejected = 'photo_rejected'
    photo_unqueued = 'photo_unqueued'
    game_timer_paused = 'game_timer_paused'
    game_timer_resumed = 'game_timer_resumed'


class TokenProvider(StrEnum):
    apns = 'apns'
    fcm = 'fcm'


class PushEventType(StrEnum):
    game_started = 'game_started'
    phase_changed = 'phase_changed'
    question_asked = 'question_asked'
    question_answerable = 'question_answerable'
    question_answered = 'question_answered'
    question_auto_answered = 'question_auto_answered'
    station_auto_assigned = 'station_auto_assigned'
    station_ambiguous = 'station_ambiguous'
    station_elected = 'station_elected'
    question_vetoed = 'question_vetoed'
    question_abandoned = 'question_abandoned'
    question_randomized = 'question_randomized'
    station_auto_resolved = 'station_auto_resolved'
    hiding_zone_expanded = 'hiding_zone_expanded'
    game_ended = 'game_ended'
    proximity_escalated = 'proximity_escalated'
    proximity_deescalated = 'proximity_deescalated'
    freeze_departed = 'freeze_departed'
    found_claim = 'found_claim'
    found_claim_rejected = 'found_claim_rejected'
    found_claim_expired = 'found_claim_expired'
    photo_submitted = 'photo_submitted'
    photo_rejected = 'photo_rejected'
    game_timer_paused = 'game_timer_paused'
    game_timer_resumed = 'game_timer_resumed'


# ── Value objects (stored as JSON columns) ─────────────────────────────────────


class DistrictClass(BaseModel):
    district_class: int  # tier level
    label: str
