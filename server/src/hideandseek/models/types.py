from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

# ── Enums ──────────────────────────────────────────────────────────────────────


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


class QuestionType(StrEnum):
    radar = 'radar'
    thermometer = 'thermometer'
    matching = 'matching'
    measuring = 'measuring'


class QuestionStatus(StrEnum):
    asked = 'asked'
    in_progress = 'in_progress'
    answerable = 'answerable'
    answered = 'answered'
    vetoed = 'vetoed'


class StationElectionStatus(StrEnum):
    pending = 'pending'
    elected = 'elected'
    auto_assigned = 'auto_assigned'
    ambiguous = 'ambiguous'


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
    station_auto_resolved = 'station_auto_resolved'


# ── Value objects (stored as JSON columns) ─────────────────────────────────────


class DistrictClass(BaseModel):
    district_class: int  # tier level
    label: str
