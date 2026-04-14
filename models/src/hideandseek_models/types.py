from __future__ import annotations

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


class QuestionStatus(StrEnum):
    asked = 'asked'
    in_progress = 'in_progress'
    answerable = 'answerable'
    answered = 'answered'
    vetoed = 'vetoed'
    abandoned = 'abandoned'
    randomized = 'randomized'


class StationElectionStatus(StrEnum):
    pending = 'pending'
    elected = 'elected'
    auto_assigned = 'auto_assigned'
    ambiguous = 'ambiguous'


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


# ── Value objects (stored as JSON columns) ─────────────────────────────────────


class DistrictClass(BaseModel):
    district_class: int  # tier level
    label: str
