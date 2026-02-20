"""Question lifecycle logic — ask and answer orchestration.

Called by routers after validation. Handles inventory mutation, question creation,
feature resolution, and answer computation. No HTTP concerns (no HTTPException, no push).
"""

from __future__ import annotations

import uuid

from shapely.geometry import Point

from hideandseek.geo import distance
from hideandseek.models.game import Game
from hideandseek.models.inventory import InventorySlot
from hideandseek.models.question import Question
from hideandseek.models.question_params import FeatureQuestionParams
from hideandseek.models.types import (
    FeatureCategory,
    QuestionStatus,
    QuestionType,
)
from hideandseek.queries.questions import (
    consume_slot,
    create_feature_params,
    create_question,
    create_radar_params,
    create_thermometer_params,
    get_question_count,
    record_category_usage,
)
from hideandseek.resolution import resolve_feature_for_player

# ── Ask ──────────────────────────────────────────────────────────────────


def ask_radar(
    game: Game,
    player_id: uuid.UUID,
    seeker_location: Point,
    slot: InventorySlot,
    custom_distance_m: int | None,
) -> Question:
    """Create a radar question: consume slot, persist. Immediately answerable."""
    distance_m = slot.distance_m or custom_distance_m
    assert distance_m is not None  # guaranteed by validator

    consume_slot(slot)

    question = create_question(
        game_id=game.id,
        sequence=get_question_count(game.id) + 1,
        question_type=QuestionType.radar,
        status=QuestionStatus.answerable,
        asked_by=player_id,
        seeker_location_start=seeker_location,
    )
    create_radar_params(question.id, radius_m=distance_m)

    return question


def ask_thermometer(
    game: Game,
    player_id: uuid.UUID,
    seeker_location: Point,
    slot: InventorySlot,
    custom_distance_m: int | None,
) -> Question:
    """Create a thermometer question: consume slot, persist. Starts in_progress."""
    distance_m = slot.distance_m or custom_distance_m
    assert distance_m is not None  # guaranteed by validator

    consume_slot(slot)

    question = create_question(
        game_id=game.id,
        sequence=get_question_count(game.id) + 1,
        question_type=QuestionType.thermometer,
        status=QuestionStatus.in_progress,
        asked_by=player_id,
        seeker_location_start=seeker_location,
    )
    create_thermometer_params(question.id, min_travel_m=distance_m)

    return question


def ask_matching(
    game: Game,
    player_id: uuid.UUID,
    seeker_location: Point,
    category: FeatureCategory,
    feature_class: int | None,
) -> Question:
    """Create a matching question: resolve seeker feature, consume category, persist.

    Raises ValueError if seeker feature cannot be resolved.
    """
    seeker_feature, seeker_dist = resolve_feature_for_player(
        category=category,
        location=seeker_location,
        game_map_id=game.map_id,
        feature_class=feature_class,
        for_matching=True,
    )

    if seeker_feature is None:
        raise ValueError(f'No feature found for category {category} near the seeker location.')

    record_category_usage(game.id, QuestionType.matching, category, feature_class)

    question = create_question(
        game_id=game.id,
        sequence=get_question_count(game.id) + 1,
        question_type=QuestionType.matching,
        status=QuestionStatus.answerable,
        asked_by=player_id,
        seeker_location_start=seeker_location,
    )
    create_feature_params(
        question.id,
        category=category,
        feature_class=feature_class,
        source='map_data',
        seeker_feature_id=seeker_feature.stable_id,
        seeker_feature_name=seeker_feature.name,
        seeker_distance_m=seeker_dist,
    )

    return question


def ask_measuring(
    game: Game,
    player_id: uuid.UUID,
    seeker_location: Point,
    category: FeatureCategory,
    feature_class: int | None,
) -> Question:
    """Create a measuring question: resolve seeker feature distance, consume category, persist.

    Raises ValueError if seeker feature cannot be resolved.
    """
    seeker_feature, seeker_dist = resolve_feature_for_player(
        category=category,
        location=seeker_location,
        game_map_id=game.map_id,
        feature_class=feature_class,
        for_matching=False,
    )

    if seeker_feature is None:
        raise ValueError(f'No feature found for category {category} near the seeker location.')

    record_category_usage(game.id, QuestionType.measuring, category, feature_class)

    question = create_question(
        game_id=game.id,
        sequence=get_question_count(game.id) + 1,
        question_type=QuestionType.measuring,
        status=QuestionStatus.answerable,
        asked_by=player_id,
        seeker_location_start=seeker_location,
    )
    create_feature_params(
        question.id,
        category=category,
        feature_class=feature_class,
        source='map_data',
        seeker_feature_id=seeker_feature.stable_id,
        seeker_feature_name=seeker_feature.name,
        seeker_distance_m=seeker_dist,
    )

    return question


# ── Answer ───────────────────────────────────────────────────────────────


def answer_radar(question: Question) -> str:
    """Compute radar answer.

    Answer is 'yes' if hider is within the radius, 'no' otherwise.
    """
    assert question.radar_params is not None
    assert question.hider_location is not None
    dist = distance(question.seeker_location_start, question.hider_location)
    return 'yes' if dist <= question.radar_params.radius_m else 'no'


def answer_thermometer(question: Question) -> str:
    """Compute thermometer answer.

    Answer is 'closer' if seeker moved closer, 'farther' otherwise.
    """
    assert question.hider_location is not None
    assert question.seeker_location_end is not None
    dist_start = distance(question.seeker_location_start, question.hider_location)
    dist_end = distance(question.seeker_location_end, question.hider_location)
    return 'closer' if dist_end < dist_start else 'farther'


def answer_matching(question: Question, game: Game) -> str:
    """Compute matching answer.

    Resolves hider feature and updates feature_params.
    Answer is 'yes' if same feature, 'no' if different, 'null' if hider unresolvable.
    """
    params = question.feature_params
    assert params is not None
    assert question.hider_location is not None

    hider_feature, hider_dist = resolve_feature_for_player(
        category=params.category,
        location=question.hider_location,
        game_map_id=game.map_id,
        feature_class=params.feature_class,
        for_matching=True,
    )

    if hider_feature is None:
        return 'null'

    _update_hider_resolution(params, hider_feature.stable_id, hider_feature.name, hider_dist)
    return 'yes' if params.seeker_feature_id == hider_feature.stable_id else 'no'


def answer_measuring(question: Question, game: Game) -> str:
    """Compute measuring answer.

    Resolves hider feature distance and updates feature_params.
    Answer is 'closer' if seeker is closer, 'farther' if not, 'null' if hider unresolvable.
    """
    params = question.feature_params
    assert params is not None
    assert question.hider_location is not None

    hider_feature, hider_dist = resolve_feature_for_player(
        category=params.category,
        location=question.hider_location,
        game_map_id=game.map_id,
        feature_class=params.feature_class,
        for_matching=False,
    )

    if hider_feature is None:
        return 'null'

    _update_hider_resolution(params, hider_feature.stable_id, hider_feature.name, hider_dist)
    return 'closer' if params.seeker_distance_m < hider_dist else 'farther'


def _update_hider_resolution(
    params: FeatureQuestionParams,
    feature_id: str,
    feature_name: str,
    distance_m: float,
) -> None:
    """Populate hider resolution fields on feature params."""
    params.hider_feature_id = feature_id
    params.hider_feature_name = feature_name
    params.hider_distance_m = distance_m
