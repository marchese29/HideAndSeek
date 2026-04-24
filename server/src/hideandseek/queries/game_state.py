"""Build static game info and dynamic gameplay state snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta

from geojson_pydantic import MultiPolygon as GeoJSONMultiPolygon
from geojson_pydantic import Point as GeoJSONPoint
from shapely.geometry import mapping

from hideandseek.schemas.params import build_question_params
from hideandseek.schemas.response import (
    GameInfoResponse,
    GamePlayer,
    HiderActiveQuestion,
    HiderGameStateResponse,
    HiderQuestionHistoryEntry,
    InventorySlotResponse,
    MapFeatureResponse,
    RosterPlayer,
    RouteResponse,
    SeekerActiveQuestion,
    SeekerGameStateResponse,
    SeekerQuestionHistoryEntry,
    StopResponse,
)
from hideandseek_core.geo_helpers import geom_or_none, point_or_none
from hideandseek_core.logic.answer import preview_answer
from hideandseek_core.logic.station import (
    compute_candidate_station_ids,
    compute_freeze_departed,
    compute_not_in_zone,
    representative_hider_location,
)
from hideandseek_core.queries.features import get_all_map_features
from hideandseek_core.queries.location import get_all_player_locations
from hideandseek_core.queries.questions import (
    get_active_question,
    get_inventory_slots,
    get_latest_total_exclusion,
    list_questions,
)
from hideandseek_core.queries.routes import get_gameplay_routes
from hideandseek_core.queries.stops import get_playable_stops
from hideandseek_models.game import Game, Player
from hideandseek_models.types import (
    PlayerRole,
    ProximityTier,
    QuestionStatus,
    QuestionType,
    StationElectionStatus,
)

_TERMINAL_STATUSES = {
    QuestionStatus.answered,
    QuestionStatus.vetoed,
    QuestionStatus.abandoned,
    QuestionStatus.randomized,
}


def _compute_deadline(answerable_at: datetime | None, delay_min: int) -> datetime | None:
    """Compute auto-answer deadline from answerable_at + base delay."""
    if answerable_at is None:
        return None
    return answerable_at + timedelta(minutes=delay_min)


def build_game_info(game: Game) -> GameInfoResponse:
    """Assemble the static game info response — map geometry, transit, timing."""
    game_map = game.game_map
    stops = get_playable_stops(game)
    routes = get_gameplay_routes(game)
    features = get_all_map_features(game)
    return GameInfoResponse(
        game_id=game.id,
        distance_convention=game_map.convention,
        boundary=GeoJSONMultiPolygon(**mapping(game_map.boundary)),
        districts=game_map.districts,
        stops=[StopResponse.from_model(s) for s in stops],
        routes=[
            RouteResponse.from_gameplay_route(r.route, r.clipped_shape, r.stop_ids) for r in routes
        ],
        features=[MapFeatureResponse.from_model(f) for f in features],
        hiding_time_min=game.hiding_time_min,
        base_question_delay_min=game.base_question_delay_min,
    )


def build_hider_game_state(game: Game, player: Player) -> HiderGameStateResponse:
    """Assemble the dynamic hider state snapshot from DB."""
    locations = get_all_player_locations(game)
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

    history = []
    for q in all_questions:
        if q.status not in _TERMINAL_STATUSES:
            continue
        fp = q.feature_params
        tp = q.tentacle_params
        if fp:
            hider_fid = fp.hider_feature_id
            hider_fname = fp.hider_feature_name
            hider_dist = fp.hider_distance
        elif tp and tp.hider_feature_id:
            hider_fid = tp.hider_feature_id
            try:
                idx = list(tp.poi_ids).index(tp.hider_feature_id)
                hider_fname = list(tp.poi_names)[idx]
            except (ValueError, IndexError):
                hider_fname = None
            hider_dist = None
        else:
            hider_fid = None
            hider_fname = None
            hider_dist = None
        history.append(
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
                hider_feature_id=hider_fid,
                hider_feature_name=hider_fname,
                hider_distance=hider_dist,
            )
        )

    # Compute enrichment fields (same logic as location handler).
    candidate_stations = None
    not_in_zone = None
    computed_answer = None

    if game.station_election_status in (
        StationElectionStatus.pending,
        StationElectionStatus.ambiguous,
    ):
        candidate_stations = compute_candidate_station_ids(game)
    elif game.hider_station_id is not None:
        not_in_zone = compute_not_in_zone(game)
        if (
            active_q is not None
            and active_q.status == QuestionStatus.answerable
            and active_q.question_type != QuestionType.photo
        ):
            hider_loc = representative_hider_location(game)
            if hider_loc is not None:
                computed_answer = preview_answer(active_q, hider_loc, game)

    freeze_departed = (
        compute_freeze_departed(game) if game.proximity_tier == ProximityTier.entered else None
    )

    return HiderGameStateResponse(
        game_id=game.id,
        phase=game.status,
        hiding_started_at=game.hiding_started_at,
        seeking_started_at=game.seeking_started_at,
        self_player_id=player.id,
        host_player_id=game.host_player_id,
        hiders=hiders,
        seekers=seekers,
        station_election_status=game.station_election_status,
        hider_station_id=game.hider_station_id,
        active_question=hider_active,
        question_history=history,
        candidate_stations=candidate_stations,
        not_in_zone=not_in_zone,
        computed_answer=computed_answer,
        hiding_zone_expanded=game.hiding_zone_expanded,
        proximity_tier=game.proximity_tier,
        freeze_departed=freeze_departed,
    )


def build_seeker_game_state(game: Game, player: Player) -> SeekerGameStateResponse:
    """Assemble the dynamic seeker state snapshot from DB."""
    locations = get_all_player_locations(game)
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
            parameters=build_question_params(q),
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
            photo_subject=s.photo_subject,
            ask_count=s.ask_count,
        )
        for s in slots
    ]

    return SeekerGameStateResponse(
        game_id=game.id,
        phase=game.status,
        hiding_started_at=game.hiding_started_at,
        seeking_started_at=game.seeking_started_at,
        self_player_id=player.id,
        host_player_id=game.host_player_id,
        hiders=hiders,
        seekers=seekers,
        active_question=seeker_active,
        question_history=history,
        total_exclusion=geom_or_none(total_exclusion),
        inventory=inventory,
        hiding_zone_expanded=game.hiding_zone_expanded,
    )
