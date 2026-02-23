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
    endgame = 'endgame'
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


class SlotType(StrEnum):
    radar = 'radar'
    thermometer = 'thermometer'


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


class PushEventType(StrEnum):
    game_started = 'game_started'
    phase_changed = 'phase_changed'
    question_asked = 'question_asked'
    question_answerable = 'question_answerable'
    question_answered = 'question_answered'
    question_auto_answered = 'question_auto_answered'


# ── Value objects (stored as JSON columns) ─────────────────────────────────────


class RestPeriod(BaseModel):
    start: str  # HH:MM time string
    end: str


class TimingRules(BaseModel):
    hiding_time_min: int
    location_question_delay_min: int
    move_hide_time_min: int
    rest_periods: list[RestPeriod] = []


class DistrictClass(BaseModel):
    district_class: int  # tier level
    label: str
