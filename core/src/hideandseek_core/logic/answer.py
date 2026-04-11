from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from shapely import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from hideandseek_core.conventions import from_meters, resolve_tentacle_distance, to_meters
from hideandseek_core.exclusion import (
    exclude_matching,
    exclude_measuring,
    exclude_radar,
    exclude_tentacles,
    exclude_thermometer,
)
from hideandseek_core.geo import distance
from hideandseek_core.logic.resolution import resolve_matching_feature, resolve_measuring_feature
from hideandseek_core.queries.features import (
    get_features_by_category,
    get_features_by_stable_ids_nearest,
)
from hideandseek_core.queries.questions import get_latest_total_exclusion
from hideandseek_models.game import Game
from hideandseek_models.question import Question
from hideandseek_models.types import QuestionStatus, QuestionType


def _accumulate_exclusion(game: Game, exclusion: BaseGeometry | None) -> BaseGeometry | None:
    """Compute cumulative total_exclusion by unioning with previous."""
    prev = get_latest_total_exclusion(game)
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
        boundary, question.seeker_location_start, radius_m, hit=answer == 'yes'
    )

    question.answer = answer
    question.exclusion = exclusion
    question.total_exclusion = _accumulate_exclusion(game, exclusion)
    question.answered_at = datetime.now(UTC)
    question.status = QuestionStatus.answered


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

    question.answer = answer
    question.exclusion = exclusion
    question.total_exclusion = _accumulate_exclusion(game, exclusion)
    question.answered_at = datetime.now(UTC)
    question.status = QuestionStatus.answered


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

    hider_feature, hider_dist = resolve_matching_feature(
        category=params.category,
        location=question.hider_location,
        game_map=game.game_map,
        feature_class=params.feature_class,
    )

    if hider_feature is None:
        answer = 'null'
        exclusion = None
    else:
        params.hider_feature_id = hider_feature.stable_id
        params.hider_feature_name = hider_feature.name
        params.hider_distance = from_meters(hider_dist, convention)
        answer = 'yes' if params.seeker_feature_id == hider_feature.stable_id else 'no'

        features = get_features_by_category(
            game, category=params.category, feature_class=params.feature_class
        )
        seeker_poi = None
        other_pois: list[BaseGeometry] = []
        for f in features:
            if f.stable_id == params.seeker_feature_id:
                seeker_poi = f.shape
            else:
                other_pois.append(f.shape)

        if seeker_poi is not None and other_pois:
            exclusion = exclude_matching(boundary, seeker_poi, other_pois, same=answer == 'yes')
        else:
            exclusion = None

    question.answer = answer
    question.exclusion = exclusion
    question.total_exclusion = _accumulate_exclusion(game, exclusion)
    question.answered_at = datetime.now(UTC)
    question.status = QuestionStatus.answered


def answer_measuring(question: Question, game: Game) -> None:
    """Compute measuring answer, exclusion zone, and persist.

    Resolves hider feature distance and updates feature_params.
    Answer is 'closer' if seeker is closer, 'farther' otherwise.
    """
    params = question.feature_params
    assert params is not None
    assert question.hider_location is not None
    boundary = game.game_map.boundary
    convention = game.game_map.convention

    hider_feature, hider_dist = resolve_measuring_feature(
        category=params.category,
        location=question.hider_location,
        game_map=game.game_map,
        feature_class=params.feature_class,
    )

    hider_dist_conv = from_meters(hider_dist, convention)
    params.hider_feature_id = hider_feature.stable_id
    params.hider_feature_name = hider_feature.name
    params.hider_distance = hider_dist_conv
    answer = 'closer' if params.seeker_distance < hider_dist_conv else 'farther'

    features = get_features_by_category(
        game, category=params.category, feature_class=params.feature_class
    )
    pois = [f.shape for f in features]

    seeker_distance_m = to_meters(params.seeker_distance, convention)
    exclusion = exclude_measuring(
        boundary, seeker_distance_m, pois, hider_closer=answer == 'farther'
    )

    question.answer = answer
    question.exclusion = exclusion
    question.total_exclusion = _accumulate_exclusion(game, exclusion)
    question.answered_at = datetime.now(UTC)
    question.status = QuestionStatus.answered


def answer_tentacles(question: Question, game: Game) -> None:
    """Compute tentacles answer, exclusion zone, and persist.

    Two-phase resolution:
    1. Distance check — is hider within the tentacle distance of the seeker?
       Miss if not (or if no POIs were in circle at ask time).
    2. Nearest POI — among the in-circle POIs, which is hider nearest to?
       Hit: answer is the nearest POI's stable_id, exclusion via Voronoi.
    """
    params = question.tentacle_params
    assert params is not None
    assert question.hider_location is not None
    boundary = game.game_map.boundary
    convention = game.game_map.convention

    distance_m = to_meters(resolve_tentacle_distance(game.game_map, params.category), convention)

    # Empty POI set: guaranteed miss
    if not params.poi_ids:
        params.hit = False
        exclusion = exclude_radar(boundary, question.seeker_location_start, distance_m, hit=False)
        question.answer = 'miss'
        question.exclusion = exclusion
        question.total_exclusion = _accumulate_exclusion(game, exclusion)
        question.answered_at = datetime.now(UTC)
        question.status = QuestionStatus.answered
        return

    # Phase 1: distance check
    dist = distance(question.seeker_location_start, question.hider_location)
    if dist > distance_m:
        # Miss — hider outside the distance circle
        params.hit = False
        exclusion = exclude_radar(boundary, question.seeker_location_start, distance_m, hit=False)
        question.answer = 'miss'
        question.exclusion = exclusion
        question.total_exclusion = _accumulate_exclusion(game, exclusion)
        question.answered_at = datetime.now(UTC)
        question.status = QuestionStatus.answered
        return

    # Phase 2: hit — find nearest POI (ordered by DB)
    features = get_features_by_stable_ids_nearest(game, params.poi_ids, question.hider_location)
    nearest = features[0]

    params.hit = True
    params.hider_feature_id = nearest.stable_id

    other_pois = [cast(Point, f.shape) for f in features[1:]]
    exclusion = exclude_tentacles(
        boundary, question.seeker_location_start, distance_m, cast(Point, nearest.shape), other_pois
    )

    question.answer = nearest.stable_id
    question.exclusion = exclusion
    question.total_exclusion = _accumulate_exclusion(game, exclusion)
    question.answered_at = datetime.now(UTC)
    question.status = QuestionStatus.answered


def veto_immediate(question: Question) -> None:
    """Immediately veto a question — no answer, no exclusion zone."""
    question.status = QuestionStatus.vetoed
    question.answered_at = datetime.now(UTC)


def abandon_question(question: Question) -> None:
    """Seeker abandons a question — no answer, no exclusion zone."""
    question.status = QuestionStatus.abandoned
    question.answered_at = datetime.now(UTC)


def schedule_veto(question: Question) -> None:
    """Schedule a veto to fire when the auto-answer timer expires."""
    question.scheduled_veto = True


# ── Answer previews (read-only) ───────────────────────────────────────


def preview_radar(question: Question, hider_location: Point, game: Game) -> str:
    """Preview radar answer: 'yes' if hider within radius, 'no' otherwise."""
    assert question.radar_params is not None
    radius_m = to_meters(question.radar_params.radius, game.game_map.convention)
    dist = distance(question.seeker_location_start, hider_location)
    return 'yes' if dist <= radius_m else 'no'


def preview_thermometer(question: Question, hider_location: Point) -> str:
    """Preview thermometer answer: 'closer' if nearer to end, 'farther' otherwise."""
    assert question.seeker_location_end is not None
    dist_start = distance(question.seeker_location_start, hider_location)
    dist_end = distance(question.seeker_location_end, hider_location)
    return 'closer' if dist_end < dist_start else 'farther'


def preview_matching(question: Question, hider_location: Point, game: Game) -> str:
    """Preview matching answer: 'yes'/'no'/'null' based on feature resolution."""
    params = question.feature_params
    assert params is not None
    hider_feature, _ = resolve_matching_feature(
        category=params.category,
        location=hider_location,
        game_map=game.game_map,
        feature_class=params.feature_class,
    )
    if hider_feature is None:
        return 'null'
    return 'yes' if params.seeker_feature_id == hider_feature.stable_id else 'no'


def preview_measuring(question: Question, hider_location: Point, game: Game) -> str:
    """Preview measuring answer: 'closer'/'farther' based on distance comparison."""
    params = question.feature_params
    assert params is not None
    convention = game.game_map.convention
    _, hider_dist = resolve_measuring_feature(
        category=params.category,
        location=hider_location,
        game_map=game.game_map,
        feature_class=params.feature_class,
    )
    hider_dist_conv = from_meters(hider_dist, convention)
    return 'closer' if params.seeker_distance < hider_dist_conv else 'farther'


def preview_tentacles(question: Question, hider_location: Point, game: Game) -> str:
    """Preview tentacles answer: nearest POI stable_id on hit, 'miss' if outside."""
    params = question.tentacle_params
    assert params is not None
    convention = game.game_map.convention
    distance_m = to_meters(resolve_tentacle_distance(game.game_map, params.category), convention)

    if not params.poi_ids:
        return 'miss'

    dist = distance(question.seeker_location_start, hider_location)
    if dist > distance_m:
        return 'miss'

    features = get_features_by_stable_ids_nearest(game, params.poi_ids, hider_location)
    return features[0].stable_id


def preview_answer(question: Question, hider_location: Point, game: Game) -> str:
    """Dispatch to the appropriate preview function based on question type."""
    match question.question_type:
        case QuestionType.radar:
            return preview_radar(question, hider_location, game)
        case QuestionType.thermometer:
            return preview_thermometer(question, hider_location)
        case QuestionType.matching:
            return preview_matching(question, hider_location, game)
        case QuestionType.measuring:
            return preview_measuring(question, hider_location, game)
        case QuestionType.tentacles:
            return preview_tentacles(question, hider_location, game)
