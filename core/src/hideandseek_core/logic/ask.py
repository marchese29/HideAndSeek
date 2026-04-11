from __future__ import annotations

from datetime import UTC, datetime

from shapely import Point

from hideandseek_core.conventions import from_meters, resolve_tentacle_distance, to_meters
from hideandseek_core.db import register
from hideandseek_core.logic.resolution import resolve_matching_feature, resolve_measuring_feature
from hideandseek_core.queries.features import get_features_within_distance
from hideandseek_core.queries.questions import get_question_count
from hideandseek_models.game import Game, Player
from hideandseek_models.inventory import InventorySlot
from hideandseek_models.question import Question
from hideandseek_models.question_params import (
    FeatureQuestionParams,
    RadarParams,
    TentacleQuestionParams,
    ThermometerParams,
)
from hideandseek_models.types import QuestionStatus, QuestionType


def ask_radar(
    game: Game,
    player: Player,
    seeker_location: Point,
    slot: InventorySlot,
    custom_distance: float | None,
) -> Question:
    """Create a radar question: use slot, persist. Immediately answerable."""
    slot.ask_count += 1

    question = register(
        Question(
            game=game,
            sequence=get_question_count(game) + 1,
            question_type=QuestionType.radar,
            status=QuestionStatus.answerable,
            asked_by=player.id,
            seeker_location_start=seeker_location,
            ask_count=slot.ask_count,
            slot_index=slot.slot_index,
            answerable_at=datetime.now(UTC),
            radar_params=RadarParams(radius=slot.distance or custom_distance),
        )
    )
    return question


def ask_thermometer(
    game: Game,
    player: Player,
    seeker_location: Point,
    slot: InventorySlot,
    custom_distance: float | None,
) -> Question:
    """Create a thermometer question: use slot, persist. Starts in_progress."""
    slot.ask_count += 1

    question = register(
        Question(
            game=game,
            sequence=get_question_count(game) + 1,
            question_type=QuestionType.thermometer,
            status=QuestionStatus.in_progress,
            asked_by=player.id,
            seeker_location_start=seeker_location,
            ask_count=slot.ask_count,
            slot_index=slot.slot_index,
            thermometer_params=ThermometerParams(min_travel=slot.distance or custom_distance),
        )
    )
    return question


def ask_matching(
    game: Game,
    player: Player,
    seeker_location: Point,
    slot: InventorySlot,
) -> Question:
    """Create a matching question: resolve seeker feature, use slot, persist.

    Raises ValueError if seeker feature cannot be resolved.
    """
    assert slot.category is not None

    seeker_feature, seeker_dist = resolve_matching_feature(
        category=slot.category,
        location=seeker_location,
        game_map=game.game_map,
        feature_class=slot.feature_class,
    )
    if seeker_feature is None:
        raise ValueError(f'No feature found for category {slot.category} near the seeker location.')

    slot.ask_count += 1

    question = register(
        Question(
            game=game,
            sequence=get_question_count(game) + 1,
            question_type=QuestionType.matching,
            status=QuestionStatus.answerable,
            asked_by=player.id,
            seeker_location_start=seeker_location,
            ask_count=slot.ask_count,
            slot_index=slot.slot_index,
            answerable_at=datetime.now(UTC),
            feature_params=FeatureQuestionParams(
                category=slot.category,
                feature_class=slot.feature_class,
                source='map_data',
                seeker_feature_id=seeker_feature.stable_id,
                seeker_feature_name=seeker_feature.name,
                seeker_distance=from_meters(seeker_dist, game.game_map.convention),
            ),
        )
    )
    return question


def ask_measuring(
    game: Game,
    player: Player,
    seeker_location: Point,
    slot: InventorySlot,
) -> Question:
    """Create a measuring question: resolve seeker feature distance, use slot, persist."""
    assert slot.category is not None

    seeker_feature, seeker_dist = resolve_measuring_feature(
        category=slot.category,
        location=seeker_location,
        game_map=game.game_map,
        feature_class=slot.feature_class,
    )

    slot.ask_count += 1

    question = register(
        Question(
            game=game,
            sequence=get_question_count(game) + 1,
            question_type=QuestionType.measuring,
            status=QuestionStatus.answerable,
            asked_by=player.id,
            seeker_location_start=seeker_location,
            ask_count=slot.ask_count,
            slot_index=slot.slot_index,
            answerable_at=datetime.now(UTC),
            feature_params=FeatureQuestionParams(
                category=slot.category,
                feature_class=slot.feature_class,
                source='map_data',
                seeker_feature_id=seeker_feature.stable_id,
                seeker_feature_name=seeker_feature.name,
                seeker_distance=from_meters(seeker_dist, game.game_map.convention),
            ),
        )
    )
    return question


def ask_tentacles(
    game: Game,
    player: Player,
    seeker_location: Point,
    slot: InventorySlot,
) -> Question:
    """Create a tentacles question: resolve in-circle POIs, use slot, persist.

    Raises ValueError if any feature in the category has non-Point geometry.
    """
    assert slot.category is not None

    distance_m = to_meters(
        resolve_tentacle_distance(game.game_map, slot.category),
        game.game_map.convention,
    )
    features = get_features_within_distance(game, slot.category, seeker_location, distance_m)

    for f in features:
        if not isinstance(f.shape, Point):
            raise ValueError(
                f'Feature {f.stable_id} has {f.shape.geom_type} geometry; '
                f'tentacles requires Point geometry only.'
            )

    slot.ask_count += 1

    question = register(
        Question(
            game=game,
            sequence=get_question_count(game) + 1,
            question_type=QuestionType.tentacles,
            status=QuestionStatus.answerable,
            asked_by=player.id,
            seeker_location_start=seeker_location,
            ask_count=slot.ask_count,
            slot_index=slot.slot_index,
            answerable_at=datetime.now(UTC),
            tentacle_params=TentacleQuestionParams(
                category=slot.category,
                poi_ids=[f.stable_id for f in features],
                poi_names=[f.name for f in features],
            ),
        )
    )
    return question


def lock_in_thermometer(question: Question, seeker_end: Point) -> None:
    """Lock in the seeker's end position for a thermometer question."""
    question.seeker_location_end = seeker_end
    question.status = QuestionStatus.answerable
    question.answerable_at = datetime.now(UTC)
