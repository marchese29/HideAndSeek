"""Question lifecycle logic — ask and answer orchestration.

Called by routers after validation. Handles inventory mutation, question creation,
feature resolution, answer computation, and exclusion zone generation.
No HTTP concerns (no HTTPException, no push).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from shapely.geometry import MultiPoint, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from hideandseek.conventions import from_meters, get_default_hiding_zone_radius, to_meters
from hideandseek.exclusion import (
    EndgameExclusionResult,
    compute_endgame_exclusions,
    compute_hiding_zone,
    exclude_matching,
    exclude_measuring,
    exclude_radar,
    exclude_thermometer,
)
from hideandseek.geo import distance
from hideandseek.models.game import Game
from hideandseek.models.inventory import InventorySlot
from hideandseek.models.question import Question
from hideandseek.models.question_params import FeatureQuestionParams
from hideandseek.models.transit import Stop
from hideandseek.models.types import (
    PlayerRole,
    QuestionStatus,
    QuestionType,
    StationElectionStatus,
)
from hideandseek.queries.features import get_features_by_category
from hideandseek.queries.location import get_latest_location_for_player
from hideandseek.queries.questions import (
    create_feature_params,
    create_question,
    create_radar_params,
    create_thermometer_params,
    get_latest_total_exclusion,
    get_question_count,
    list_answered_questions_after_sequence,
    update_question,
    use_slot,
)
from hideandseek.queries.stops import (
    all_hiders_within_radius,
    get_closest_stop_to_any,
    get_stops_within_radius_of_all,
    get_stops_within_radius_of_any,
    validate_stop_playable,
)
from hideandseek.queries.stops import (
    get_candidate_stations as query_candidate_stations,
)
from hideandseek.resolution import resolve_feature_for_player

# ── Ask ──────────────────────────────────────────────────────────────────


def ask_radar(
    game: Game,
    player_id: uuid.UUID,
    seeker_location: Point,
    slot: InventorySlot,
    custom_distance: float | None,
) -> Question:
    """Create a radar question: use slot, persist. Immediately answerable."""
    dist = slot.distance or custom_distance
    assert dist is not None  # guaranteed by validator

    use_slot(slot)

    question = create_question(
        game_id=game.id,
        sequence=get_question_count(game.id) + 1,
        question_type=QuestionType.radar,
        status=QuestionStatus.answerable,
        asked_by=player_id,
        seeker_location_start=seeker_location,
        ask_count=slot.ask_count,
    )
    create_radar_params(question.id, radius=dist)

    return question


def ask_thermometer(
    game: Game,
    player_id: uuid.UUID,
    seeker_location: Point,
    slot: InventorySlot,
    custom_distance: float | None,
) -> Question:
    """Create a thermometer question: use slot, persist. Starts in_progress."""
    dist = slot.distance or custom_distance
    assert dist is not None  # guaranteed by validator

    use_slot(slot)

    question = create_question(
        game_id=game.id,
        sequence=get_question_count(game.id) + 1,
        question_type=QuestionType.thermometer,
        status=QuestionStatus.in_progress,
        asked_by=player_id,
        seeker_location_start=seeker_location,
        ask_count=slot.ask_count,
    )
    create_thermometer_params(question.id, min_travel=dist)

    return question


def ask_matching(
    game: Game,
    player_id: uuid.UUID,
    seeker_location: Point,
    slot: InventorySlot,
) -> Question:
    """Create a matching question: resolve seeker feature, use slot, persist.

    Raises ValueError if seeker feature cannot be resolved.
    """
    assert slot.category is not None

    seeker_feature, seeker_dist = resolve_feature_for_player(
        category=slot.category,
        location=seeker_location,
        game_map_id=game.map_id,
        feature_class=slot.feature_class,
        for_matching=True,
    )

    if seeker_feature is None:
        raise ValueError(f'No feature found for category {slot.category} near the seeker location.')

    use_slot(slot)

    question = create_question(
        game_id=game.id,
        sequence=get_question_count(game.id) + 1,
        question_type=QuestionType.matching,
        status=QuestionStatus.answerable,
        asked_by=player_id,
        seeker_location_start=seeker_location,
        ask_count=slot.ask_count,
    )
    convention = game.game_map.convention
    create_feature_params(
        question.id,
        category=slot.category,
        feature_class=slot.feature_class,
        source='map_data',
        seeker_feature_id=seeker_feature.stable_id,
        seeker_feature_name=seeker_feature.name,
        seeker_distance=from_meters(seeker_dist, convention),
    )

    return question


def ask_measuring(
    game: Game,
    player_id: uuid.UUID,
    seeker_location: Point,
    slot: InventorySlot,
) -> Question:
    """Create a measuring question: resolve seeker feature distance, use slot, persist.

    Raises ValueError if seeker feature cannot be resolved.
    """
    assert slot.category is not None

    seeker_feature, seeker_dist = resolve_feature_for_player(
        category=slot.category,
        location=seeker_location,
        game_map_id=game.map_id,
        feature_class=slot.feature_class,
        for_matching=False,
    )

    if seeker_feature is None:
        raise ValueError(f'No feature found for category {slot.category} near the seeker location.')

    use_slot(slot)

    question = create_question(
        game_id=game.id,
        sequence=get_question_count(game.id) + 1,
        question_type=QuestionType.measuring,
        status=QuestionStatus.answerable,
        asked_by=player_id,
        seeker_location_start=seeker_location,
        ask_count=slot.ask_count,
    )
    convention = game.game_map.convention
    create_feature_params(
        question.id,
        category=slot.category,
        feature_class=slot.feature_class,
        source='map_data',
        seeker_feature_id=seeker_feature.stable_id,
        seeker_feature_name=seeker_feature.name,
        seeker_distance=from_meters(seeker_dist, convention),
    )

    return question


# ── Answer ───────────────────────────────────────────────────────────────


def _accumulate_exclusion(
    game_id: uuid.UUID, exclusion: BaseGeometry | None
) -> BaseGeometry | None:
    """Compute cumulative total_exclusion by unioning with previous."""
    prev = get_latest_total_exclusion(game_id)
    if exclusion is None:
        return prev
    if prev is None:
        return exclusion
    return unary_union([prev, exclusion])


def answer_radar(question: Question, game: Game) -> None:
    """Compute radar answer, exclusion zone, and persist.

    Answer is 'yes' if hider is within the radius, 'no' otherwise.
    """
    assert question.radar_params is not None
    assert question.hider_location is not None
    boundary = game.game_map.boundary
    convention = game.game_map.convention

    radius_m = to_meters(question.radar_params.radius, convention)
    dist = distance(question.seeker_location_start, question.hider_location)
    answer = 'yes' if dist <= radius_m else 'no'

    exclusion = exclude_radar(
        boundary,
        question.seeker_location_start,
        radius_m,
        hit=answer == 'yes',
    )
    total = _accumulate_exclusion(game.id, exclusion)

    update_question(
        question,
        {
            'answer': answer,
            'exclusion': exclusion,
            'total_exclusion': total,
            'answered_at': datetime.now(UTC),
            'status': QuestionStatus.answered,
        },
    )


def answer_thermometer(question: Question, game: Game) -> None:
    """Compute thermometer answer, exclusion zone, and persist.

    Answer is 'closer' if seeker moved closer, 'farther' otherwise.
    """
    assert question.hider_location is not None
    assert question.seeker_location_end is not None
    boundary = game.game_map.boundary

    dist_start = distance(question.seeker_location_start, question.hider_location)
    dist_end = distance(question.seeker_location_end, question.hider_location)
    answer = 'closer' if dist_end < dist_start else 'farther'

    exclusion = exclude_thermometer(
        boundary,
        question.seeker_location_start,
        question.seeker_location_end,
        seeker_closer=answer == 'closer',
    )
    total = _accumulate_exclusion(game.id, exclusion)

    update_question(
        question,
        {
            'answer': answer,
            'exclusion': exclusion,
            'total_exclusion': total,
            'answered_at': datetime.now(UTC),
            'status': QuestionStatus.answered,
        },
    )


def answer_matching(question: Question, game: Game) -> None:
    """Compute matching answer, exclusion zone, and persist.

    Resolves hider feature and updates feature_params.
    Answer is 'yes' if same feature, 'no' if different, 'null' if hider unresolvable.
    """
    params = question.feature_params
    assert params is not None
    assert question.hider_location is not None
    boundary = game.game_map.boundary
    convention = game.game_map.convention

    hider_feature, hider_dist = resolve_feature_for_player(
        category=params.category,
        location=question.hider_location,
        game_map_id=game.map_id,
        feature_class=params.feature_class,
        for_matching=True,
    )

    if hider_feature is None:
        answer = 'null'
        exclusion = None
    else:
        _update_hider_resolution(
            params,
            hider_feature.stable_id,
            hider_feature.name,
            from_meters(hider_dist, convention),
        )
        answer = 'yes' if params.seeker_feature_id == hider_feature.stable_id else 'no'

        features = get_features_by_category(
            game_map_id=game.map_id,
            category=params.category,
            feature_class=params.feature_class,
        )
        seeker_poi = None
        other_pois: list[BaseGeometry] = []
        for f in features:
            if f.stable_id == params.seeker_feature_id:
                seeker_poi = f.geometry
            else:
                other_pois.append(f.geometry)

        if seeker_poi is not None and other_pois:
            exclusion = exclude_matching(boundary, seeker_poi, other_pois, same=answer == 'yes')
        else:
            exclusion = None

    total = _accumulate_exclusion(game.id, exclusion)

    update_question(
        question,
        {
            'answer': answer,
            'exclusion': exclusion,
            'total_exclusion': total,
            'answered_at': datetime.now(UTC),
            'status': QuestionStatus.answered,
        },
    )


def answer_measuring(question: Question, game: Game) -> None:
    """Compute measuring answer, exclusion zone, and persist.

    Resolves hider feature distance and updates feature_params.
    Answer is 'closer' if seeker is closer, 'farther' if not, 'null' if hider unresolvable.
    """
    params = question.feature_params
    assert params is not None
    assert question.hider_location is not None
    boundary = game.game_map.boundary
    convention = game.game_map.convention

    hider_feature, hider_dist = resolve_feature_for_player(
        category=params.category,
        location=question.hider_location,
        game_map_id=game.map_id,
        feature_class=params.feature_class,
        for_matching=False,
    )

    if hider_feature is None:
        answer = 'null'
        exclusion = None
    else:
        hider_dist_conv = from_meters(hider_dist, convention)
        _update_hider_resolution(
            params,
            hider_feature.stable_id,
            hider_feature.name,
            hider_dist_conv,
        )
        answer = 'closer' if params.seeker_distance < hider_dist_conv else 'farther'

        features = get_features_by_category(
            game_map_id=game.map_id,
            category=params.category,
            feature_class=params.feature_class,
        )
        pois = [f.geometry for f in features]

        if pois:
            seeker_distance_m = to_meters(params.seeker_distance, convention)
            exclusion = exclude_measuring(
                boundary, seeker_distance_m, pois, hider_closer=answer == 'farther'
            )
        else:
            exclusion = None

    total = _accumulate_exclusion(game.id, exclusion)

    update_question(
        question,
        {
            'answer': answer,
            'exclusion': exclusion,
            'total_exclusion': total,
            'answered_at': datetime.now(UTC),
            'status': QuestionStatus.answered,
        },
    )


def _update_hider_resolution(
    params: FeatureQuestionParams,
    feature_id: str,
    feature_name: str,
    distance: float,
) -> None:
    """Populate hider resolution fields on feature params."""
    params.hider_feature_id = feature_id
    params.hider_feature_name = feature_name
    params.hider_distance = distance


# ── Endgame ─────────────────────────────────────────────────────────────


def effective_hiding_zone_radius_m(game: Game) -> float:
    """Compute effective hiding zone radius in meters for a game.

    Fallback chain: game-level override → map-level override → code-level default.
    """
    gm = game.game_map
    radius_conv = (
        game.hiding_zone_radius_override
        or gm.hiding_zone_radius
        or get_default_hiding_zone_radius(gm.convention, gm.size)
    )
    return to_meters(radius_conv, gm.convention)


def get_endgame_exclusions(
    game: Game, station: Stop, after_sequence: int
) -> EndgameExclusionResult:
    """Compute endgame exclusion view for a station.

    Returns hiding zone geometry and per-question exclusions intersected with it,
    starting from questions after the given sequence number.
    """
    radius_m = effective_hiding_zone_radius_m(game)
    questions = list_answered_questions_after_sequence(game.id, after_sequence)
    return compute_endgame_exclusions(
        game.game_map.boundary, station.coordinates, radius_m, questions
    )


def get_candidate_stations(game: Game, offset: int, limit: int) -> list[Stop]:
    """Return playable stops not fully covered by the game's total exclusion."""
    radius_m = effective_hiding_zone_radius_m(game)
    return query_candidate_stations(game, radius_m, offset, limit)


# ── Station election ──────────────────────────────────────────────────


def _get_hider_locations(game: Game) -> list[Point]:
    """Fetch latest location for each hider in the game."""
    hiders = [p for p in game.players if p.role == PlayerRole.hider]
    locations = []
    for hider in hiders:
        latest = get_latest_location_for_player(hider.id, game.id)
        if latest:
            locations.append(latest.coordinates)
    return locations


def validate_station_election(game: Game, station_id: uuid.UUID) -> Stop:
    """Validate a station election request. Returns the stop.

    Raises ValueError if the stop is not playable or any hider is outside the radius.
    """
    stop = validate_stop_playable(game, station_id)
    if not stop:
        raise ValueError('Stop is not a playable station in this game.')

    radius_m = effective_hiding_zone_radius_m(game)
    hider_locations = _get_hider_locations(game)
    if not hider_locations:
        raise ValueError('No hider locations available.')

    if not all_hiders_within_radius(stop, hider_locations, radius_m):
        raise ValueError('Not all hiders are within the hiding zone radius of this station.')

    return stop


def resolve_station_at_transition(
    game: Game,
) -> tuple[Stop | None, StationElectionStatus]:
    """Resolve hider station at the hiding→seeking transition.

    If already elected, returns (None, elected) — no work needed.
    Otherwise finds valid candidates (stops where all hiders are within radius).
    Exactly 1 → auto_assigned. 0 or 2+ → ambiguous.
    """
    if game.station_election_status == StationElectionStatus.elected:
        return None, StationElectionStatus.elected

    radius_m = effective_hiding_zone_radius_m(game)
    hider_locations = _get_hider_locations(game)
    if not hider_locations:
        return None, StationElectionStatus.ambiguous

    candidates = get_stops_within_radius_of_all(game, hider_locations, radius_m)
    if len(candidates) == 1:
        return candidates[0], StationElectionStatus.auto_assigned
    return None, StationElectionStatus.ambiguous


def resolve_station_fallback(game: Game) -> Stop:
    """Resolve station via 3-tier cascade for ambiguity fallback.

    1. All hiders within radius → pick tightest fit
    2. Any hider within radius → pick shortest min distance
    3. Closest (stop, hider) pair

    Each query returns results ordered by its selection criterion,
    so index 0 is the best pick for that tier.
    """
    radius_m = effective_hiding_zone_radius_m(game)
    hider_locations = _get_hider_locations(game)

    # Tier 1: all hiders in radius — ordered by max hider distance (tightest fit first)
    candidates = get_stops_within_radius_of_all(game, hider_locations, radius_m)
    if candidates:
        return candidates[0]

    # Tier 2: any hider in radius — ordered by min hider distance (shortest first)
    candidates = get_stops_within_radius_of_any(game, hider_locations, radius_m)
    if candidates:
        return candidates[0]

    # Tier 3: absolute closest (stop, hider) pair across all combos
    stop = get_closest_stop_to_any(game, hider_locations)
    if stop:
        return stop

    raise RuntimeError('No playable stops found for fallback resolution.')


def compute_hiding_zone_for_station(game: Game, station: Stop) -> BaseGeometry:
    """Compute the hiding zone polygon for a station in a game."""
    radius_m = effective_hiding_zone_radius_m(game)
    return compute_hiding_zone(station.coordinates, radius_m, game.game_map.boundary)


_HIDER_LOCATION_FRESHNESS = timedelta(minutes=1)


def compute_hider_centroid(game: Game) -> Point | None:
    """Compute the centroid of hiders with recent location updates.

    Finds the latest hider location update across all hiders, then averages
    the positions of all hiders whose latest update is within 1 minute of it.
    Returns None if no hider has a location update.
    """
    hiders = [p for p in game.players if p.role == PlayerRole.hider]
    if not hiders:
        return None

    locations = []
    for hider in hiders:
        latest = get_latest_location_for_player(hider.id, game.id)
        if latest:
            locations.append(latest)

    if not locations:
        return None

    newest = max(loc.timestamp for loc in locations)
    cutoff = newest - _HIDER_LOCATION_FRESHNESS

    fresh = [loc.coordinates for loc in locations if loc.timestamp >= cutoff]
    return MultiPoint(fresh).centroid
