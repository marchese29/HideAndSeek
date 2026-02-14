from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

# ── Enums ──────────────────────────────────────────────────────────────────────


class RouteType(StrEnum):
    metro = 'metro'
    bus = 'bus'
    tram = 'tram'
    rail = 'rail'
    ferry = 'ferry'


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


class QuestionType(StrEnum):
    radar = 'radar'
    thermometer = 'thermometer'


class QuestionStatus(StrEnum):
    asked = 'asked'
    in_progress = 'in_progress'
    answerable = 'answerable'
    answered = 'answered'


# ── GeoJSON value types ───────────────────────────────────────────────────────


class GeoPoint(BaseModel):
    type: Literal['Point'] = 'Point'
    coordinates: tuple[float, float]  # [lng, lat]


class GeoLineString(BaseModel):
    type: Literal['LineString'] = 'LineString'
    coordinates: list[tuple[float, float]]


class GeoPolygon(BaseModel):
    type: Literal['Polygon'] = 'Polygon'
    coordinates: list[list[tuple[float, float]]]


# ── Value objects (stored as JSON columns) ─────────────────────────────────────


class RestPeriod(BaseModel):
    start: str  # HH:MM time string
    end: str


class DistanceSlot(BaseModel):
    distance_m: int | None = None


class QuestionInventory(BaseModel):
    radars: list[DistanceSlot] = []
    thermometers: list[DistanceSlot] = []


class TimingRules(BaseModel):
    hiding_time_min: int
    location_question_delay_min: int
    move_hide_time_min: int
    rest_periods: list[RestPeriod] = []


class DistrictClass(BaseModel):
    district_class: int  # tier level
    label: str
