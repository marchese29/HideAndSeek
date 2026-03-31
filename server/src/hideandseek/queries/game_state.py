"""Build gameplay state snapshots for SSE endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta

from geojson_pydantic import Point as GeoJSONPoint
from geojson_pydantic import Polygon as GeoJSONPolygon
from shapely.geometry import mapping

from hideandseek.models.game import Game, Player
from hideandseek.models.types import PlayerRole, QuestionStatus
from hideandseek.queries.location import get_all_player_locations
from hideandseek.queries.questions import (
    get_active_question,
    get_inventory_slots,
    get_latest_total_exclusion,
    list_questions,
)
from hideandseek.queries.stops import get_playable_stops
from hideandseek.schemas.params import build_question_params
from hideandseek.schemas.response import (
    GamePlayer,
    HiderActiveQuestion,
    HiderGameStateResponse,
    HiderQuestionHistoryEntry,
    InventorySlotResponse,
    RosterPlayer,
    SeekerActiveQuestion,
    SeekerGameStateResponse,
    SeekerQuestionHistoryEntry,
    StopResponse,
    geom_or_none,
    point_or_none,
)

_TERMINAL_STATUSES = {QuestionStatus.answered, QuestionStatus.vetoed, QuestionStatus.abandoned}


def _compute_deadline(answerable_at: datetime | None, delay_min: int) -> datetime | None:
    """Compute auto-answer deadline from answerable_at + base delay."""
    if answerable_at is None:
        return None
    return answerable_at + timedelta(minutes=delay_min)


def build_hider_game_state(game: Game, player: Player) -> HiderGameStateResponse:
    """Assemble the full hider state snapshot from DB."""
    game_map = game.game_map
    locations = get_all_player_locations(game)
    stops = get_playable_stops(game)
    active_q = get_active_question(game)
    all_questions = list_questions(game)

    hiders: list[GamePlayer] = []
    seekers: list[GamePlayer] = []

    for p in game.players:
        loc = locations.get(p.id)
        gp = GamePlayer(
            id=p.id,
            name=p.name,
            color=p.color,
            role=p.role,
            coordinates=GeoJSONPoint(**mapping(loc.coordinates)) if loc else None,
            timestamp=loc.timestamp if loc else None,
        )
        if p.role == PlayerRole.hider:
            hiders.append(gp)
        else:
            seekers.append(gp)

    hider_active: HiderActiveQuestion | None = None
    if active_q is not None:
        hider_active = HiderActiveQuestion(
            question_id=active_q.id,
            question_type=active_q.question_type,
            status=active_q.status,
            asked_by=active_q.asked_by,
            slot_index=active_q.slot_index,
            question_deadline=_compute_deadline(
                active_q.answerable_at, game.base_question_delay_min
            ),
        )

    history = [
        HiderQuestionHistoryEntry(
            question_id=q.id,
            sequence=q.sequence,
            question_type=q.question_type,
            status=q.status,
            ask_count=q.ask_count,
            asked_by=q.asked_by,
            asked_at=q.asked_at,
            slot_index=q.slot_index,
            parameters=build_question_params(q),
            seeker_location_start=GeoJSONPoint(**mapping(q.seeker_location_start)),
            seeker_location_end=point_or_none(q.seeker_location_end),
            answer=q.answer,
            answered_at=q.answered_at,
            hider_location=point_or_none(q.hider_location),
            hider_feature_id=q.feature_params.hider_feature_id if q.feature_params else None,
            hider_feature_name=q.feature_params.hider_feature_name if q.feature_params else None,
            hider_distance=q.feature_params.hider_distance if q.feature_params else None,
        )
        for q in all_questions
        if q.status in _TERMINAL_STATUSES
    ]

    return HiderGameStateResponse(
        game_id=game.id,
        phase=game.status,
        hiding_time_min=game.hiding_time_min,
        hiding_started_at=game.hiding_started_at,
        seeking_started_at=game.seeking_started_at,
        base_question_delay_min=game.base_question_delay_min,
        distance_convention=game_map.convention,
        boundary=GeoJSONPolygon(**mapping(game_map.boundary)),
        districts=game_map.districts,
        stops=[StopResponse.from_model(s) for s in stops],
        self_player_id=player.id,
        hiders=hiders,
        seekers=seekers,
        station_election_status=game.station_election_status,
        hider_station_id=game.hider_station_id,
        active_question=hider_active,
        question_history=history,
    )


def build_seeker_game_state(game: Game, player: Player) -> SeekerGameStateResponse:
    """Assemble the full seeker state snapshot from DB."""
    game_map = game.game_map
    locations = get_all_player_locations(game)
    stops = get_playable_stops(game)
    active_q = get_active_question(game)
    all_questions = list_questions(game)
    total_exclusion = get_latest_total_exclusion(game)
    slots = get_inventory_slots(game)

    hiders: list[RosterPlayer] = []
    seekers: list[GamePlayer] = []

    for p in game.players:
        if p.role == PlayerRole.hider:
            hiders.append(
                RosterPlayer(
                    id=p.id,
                    name=p.name,
                    color=p.color,
                    role=p.role,
                )
            )
        else:
            loc = locations.get(p.id)
            seekers.append(
                GamePlayer(
                    id=p.id,
                    name=p.name,
                    color=p.color,
                    role=p.role,
                    coordinates=GeoJSONPoint(**mapping(loc.coordinates)) if loc else None,
                    timestamp=loc.timestamp if loc else None,
                )
            )

    seeker_active: SeekerActiveQuestion | None = None
    if active_q is not None:
        seeker_active = SeekerActiveQuestion(
            question_id=active_q.id,
            question_type=active_q.question_type,
            status=active_q.status,
            slot_index=active_q.slot_index,
            question_deadline=_compute_deadline(
                active_q.answerable_at, game.base_question_delay_min
            ),
        )

    history = [
        SeekerQuestionHistoryEntry(
            question_id=q.id,
            sequence=q.sequence,
            question_type=q.question_type,
            status=q.status,
            ask_count=q.ask_count,
            asked_by=q.asked_by,
            asked_at=q.asked_at,
            slot_index=q.slot_index,
            answer=q.answer,
            exclusion=geom_or_none(q.exclusion),
            total_exclusion=geom_or_none(q.total_exclusion),
            answered_at=q.answered_at,
        )
        for q in all_questions
        if q.status in _TERMINAL_STATUSES
    ]

    inventory = [
        InventorySlotResponse(
            question_type=s.question_type,
            slot_index=s.slot_index,
            distance=s.distance,
            category=str(s.category) if s.category else None,
            feature_class=s.feature_class,
            ask_count=s.ask_count,
        )
        for s in slots
    ]

    return SeekerGameStateResponse(
        game_id=game.id,
        phase=game.status,
        hiding_time_min=game.hiding_time_min,
        hiding_started_at=game.hiding_started_at,
        seeking_started_at=game.seeking_started_at,
        base_question_delay_min=game.base_question_delay_min,
        distance_convention=game_map.convention,
        boundary=GeoJSONPolygon(**mapping(game_map.boundary)),
        districts=game_map.districts,
        stops=[StopResponse.from_model(s) for s in stops],
        self_player_id=player.id,
        hiders=hiders,
        seekers=seekers,
        active_question=seeker_active,
        question_history=history,
        total_exclusion=geom_or_none(total_exclusion),
        inventory=inventory,
    )
