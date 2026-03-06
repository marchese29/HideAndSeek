from __future__ import annotations

from datetime import UTC, datetime

from shapely import Point

from hideandseek.conventions import from_meters
from hideandseek.db import register
from hideandseek.logic.resolution import resolve_matching_feature, resolve_measuring_feature
from hideandseek.models.game import Game, Player
from hideandseek.models.inventory import InventorySlot
from hideandseek.models.question import Question
from hideandseek.models.question_params import FeatureQuestionParams, RadarParams, ThermometerParams
from hideandseek.models.types import QuestionStatus, QuestionType
from hideandseek.queries.questions import get_question_count


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


def lock_in_thermometer(question: Question, seeker_end: Point) -> None:
    """Lock in the seeker's end position for a thermometer question."""
    question.seeker_location_end = seeker_end
    question.status = QuestionStatus.answerable
    question.answerable_at = datetime.now(UTC)
