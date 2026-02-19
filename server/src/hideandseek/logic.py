"""Question lifecycle logic — ask and answer orchestration.

Called by routers after validation. Handles inventory mutation, question creation,
feature resolution, and answer computation. No HTTP concerns (no HTTPException, no push).
"""

from __future__ import annotations

import uuid

from shapely.geometry import Point

from hideandseek.geo import distance
from hideandseek.models.game import Game
from hideandseek.models.map_feature import MapFeature
from hideandseek.models.question import Question
from hideandseek.models.types import (
    FeatureCategory,
    QuestionInventory,
    QuestionStatus,
    QuestionType,
)
from hideandseek.queries.questions import (
    create_question,
    get_question_count,
    update_game_inventory,
)
from hideandseek.resolution import category_key, resolve_feature_for_player


def _resolution_dict(feature: MapFeature, dist: float) -> dict:
    return {
        'feature_id': feature.stable_id,
        'name': feature.name,
        'distance_m': dist,
    }


# ── Ask ──────────────────────────────────────────────────────────────────


def ask_radar(
    game: Game,
    player_id: uuid.UUID,
    seeker_location: Point,
    slot_index: int,
    custom_distance_m: int | None,
) -> Question:
    """Create a radar question: consume slot, persist. Immediately answerable."""
    inventory = QuestionInventory(**game.inventory)
    distance_m = inventory.radars[slot_index].distance_m or custom_distance_m
    assert distance_m is not None  # guaranteed by validator

    inventory.radars.pop(slot_index)
    update_game_inventory(game, inventory.model_dump())

    return create_question(
        game_id=game.id,
        sequence=get_question_count(game.id) + 1,
        question_type=QuestionType.radar,
        status=QuestionStatus.answerable,
        parameters={'radius_m': distance_m},
        asked_by=player_id,
        seeker_location_start=seeker_location,
    )


def ask_thermometer(
    game: Game,
    player_id: uuid.UUID,
    seeker_location: Point,
    slot_index: int,
    custom_distance_m: int | None,
) -> Question:
    """Create a thermometer question: consume slot, persist. Starts in_progress."""
    inventory = QuestionInventory(**game.inventory)
    distance_m = inventory.thermometers[slot_index].distance_m or custom_distance_m
    assert distance_m is not None  # guaranteed by validator

    inventory.thermometers.pop(slot_index)
    update_game_inventory(game, inventory.model_dump())

    return create_question(
        game_id=game.id,
        sequence=get_question_count(game.id) + 1,
        question_type=QuestionType.thermometer,
        status=QuestionStatus.in_progress,
        parameters={'min_travel_m': distance_m},
        asked_by=player_id,
        seeker_location_start=seeker_location,
    )


def ask_matching(
    game: Game,
    player_id: uuid.UUID,
    seeker_location: Point,
    category: FeatureCategory,
    feature_class: int | None,
) -> Question:
    """Create a matching question: resolve seeker feature, consume category, persist."""
    seeker_feature, seeker_dist = resolve_feature_for_player(
        category=category,
        location=seeker_location,
        game_map_id=game.map_id,
        feature_class=feature_class,
        for_matching=True,
    )

    parameters: dict = {
        'category': str(category),
        'source': 'map_data',
        'seeker_resolution': (
            _resolution_dict(seeker_feature, seeker_dist) if seeker_feature else None
        ),
    }
    if feature_class is not None:
        parameters['feature_class'] = feature_class

    # Consume category in inventory
    inventory = QuestionInventory(**game.inventory)
    inventory.matching_used.append(category_key(category, feature_class))
    update_game_inventory(game, inventory.model_dump())

    return create_question(
        game_id=game.id,
        sequence=get_question_count(game.id) + 1,
        question_type=QuestionType.matching,
        status=QuestionStatus.answerable,
        parameters=parameters,
        asked_by=player_id,
        seeker_location_start=seeker_location,
    )


# ── Answer ───────────────────────────────────────────────────────────────


def answer_radar(
    question: Question,
    hider_location: Point,
) -> tuple[str, dict]:
    """Compute radar answer. Returns (answer, parameters).

    Answer is 'yes' if hider is within the radius, 'no' otherwise.
    """
    dist = distance(question.seeker_location_start, hider_location)
    answer = 'yes' if dist <= question.parameters['radius_m'] else 'no'
    return answer, question.parameters


def answer_thermometer(
    question: Question,
    hider_location: Point,
) -> tuple[str, dict]:
    """Compute thermometer answer. Returns (answer, parameters).

    Answer is 'closer' if seeker moved closer, 'farther' otherwise.
    """
    dist_start = distance(question.seeker_location_start, hider_location)
    dist_end = distance(question.seeker_location_end, hider_location)  # type: ignore[arg-type]
    answer = 'closer' if dist_end < dist_start else 'farther'
    return answer, question.parameters


def answer_matching(
    question: Question,
    game: Game,
    hider_location: Point,
) -> tuple[str, dict]:
    """Compute matching answer. Returns (answer, updated_parameters).

    Answer is 'yes' if same feature, 'no' if different, 'null' if either player
    is not inside any feature (containment categories only).
    """
    category = FeatureCategory(question.parameters['category'])
    feature_class = question.parameters.get('feature_class')

    hider_feature, hider_dist = resolve_feature_for_player(
        category=category,
        location=hider_location,
        game_map_id=game.map_id,
        feature_class=feature_class,
        for_matching=True,
    )

    params = dict(question.parameters)
    params['hider_resolution'] = (
        _resolution_dict(hider_feature, hider_dist) if hider_feature else None
    )

    seeker_resolution = question.parameters.get('seeker_resolution')
    if seeker_resolution is None or hider_feature is None:
        return 'null', params

    answer = 'yes' if seeker_resolution['feature_id'] == hider_feature.stable_id else 'no'
    return answer, params


def ask_measuring(
    game: Game,
    player_id: uuid.UUID,
    seeker_location: Point,
    category: FeatureCategory,
    feature_class: int | None,
) -> Question:
    """Create a measuring question: resolve seeker feature distance, consume category, persist."""
    seeker_feature, seeker_dist = resolve_feature_for_player(
        category=category,
        location=seeker_location,
        game_map_id=game.map_id,
        feature_class=feature_class,
        for_matching=False,
    )

    parameters: dict = {
        'category': str(category),
        'source': 'map_data',
        'seeker_resolution': (
            _resolution_dict(seeker_feature, seeker_dist) if seeker_feature else None
        ),
    }
    if feature_class is not None:
        parameters['feature_class'] = feature_class

    # Consume category in inventory
    inventory = QuestionInventory(**game.inventory)
    inventory.measuring_used.append(category_key(category, feature_class))
    update_game_inventory(game, inventory.model_dump())

    return create_question(
        game_id=game.id,
        sequence=get_question_count(game.id) + 1,
        question_type=QuestionType.measuring,
        status=QuestionStatus.answerable,
        parameters=parameters,
        asked_by=player_id,
        seeker_location_start=seeker_location,
    )


def answer_measuring(
    question: Question,
    game: Game,
    hider_location: Point,
) -> tuple[str, dict]:
    """Compute measuring answer. Returns (answer, updated_parameters).

    Answer is 'closer' if seeker is closer to the feature, 'farther' if not,
    'null' if either player's feature could not be resolved.
    """
    category = FeatureCategory(question.parameters['category'])
    feature_class = question.parameters.get('feature_class')

    hider_feature, hider_dist = resolve_feature_for_player(
        category=category,
        location=hider_location,
        game_map_id=game.map_id,
        feature_class=feature_class,
        for_matching=False,
    )

    params = dict(question.parameters)
    params['hider_resolution'] = (
        _resolution_dict(hider_feature, hider_dist) if hider_feature else None
    )

    seeker_resolution = question.parameters.get('seeker_resolution')
    if seeker_resolution is None or hider_feature is None:
        return 'null', params

    answer = 'closer' if seeker_resolution['distance_m'] < hider_dist else 'farther'
    return answer, params
