from __future__ import annotations

import random
from datetime import UTC, datetime

import structlog
from shapely import Point

from hideandseek_core.conventions import from_meters, resolve_tentacle_distance, to_meters
from hideandseek_core.db import register
from hideandseek_core.logic.resolution import resolve_matching_feature, resolve_measuring_feature
from hideandseek_core.queries.features import get_features_within_distance
from hideandseek_core.queries.location import get_latest_location_for_player
from hideandseek_core.queries.questions import (
    get_eligible_randomize_slots,
    get_question_count,
    get_slot_by_index,
)
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

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _log_question_asked(game: Game, player: Player, question: Question) -> None:
    logger.info(
        'question_asked',
        game_id=str(game.id),
        question_id=str(question.id),
        question_type=question.question_type.value,
        player_id=str(player.id),
    )


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
    _log_question_asked(game, player, question)
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
    _log_question_asked(game, player, question)
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
    _log_question_asked(game, player, question)
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
    _log_question_asked(game, player, question)
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
    _log_question_asked(game, player, question)
    return question


def lock_in_thermometer(question: Question, seeker_end: Point) -> None:
    """Lock in the seeker's end position for a thermometer question."""
    question.seeker_location_end = seeker_end
    question.status = QuestionStatus.answerable
    question.answerable_at = datetime.now(UTC)
    logger.info(
        'thermometer_locked_in',
        game_id=str(question.game_id),
        question_id=str(question.id),
    )


# ── Ask function dispatch ──────────────────────────────────────────────

_ASK_DISPATCH: dict[QuestionType, str] = {
    QuestionType.radar: 'ask_radar',
    QuestionType.thermometer: 'ask_thermometer',
    QuestionType.matching: 'ask_matching',
    QuestionType.measuring: 'ask_measuring',
    QuestionType.tentacles: 'ask_tentacles',
}


def randomize_question(question: Question, game: Game) -> Question:
    """Terminate the original question and create a replacement from a random eligible slot.

    Restores the original slot's ask_count, picks a random slot of the same type
    with ask_count == 0, and calls the appropriate ask function.

    The caller is responsible for revoking the original auto-answer timer
    and scheduling a new one for the replacement.
    """
    # Terminate the original question
    question.status = QuestionStatus.randomized
    question.answered_at = datetime.now(UTC)

    # Restore the original slot
    original_slot = get_slot_by_index(game, question.question_type, question.slot_index)
    assert original_slot is not None
    original_slot.ask_count -= 1

    # Pick a random replacement slot
    eligible = get_eligible_randomize_slots(game, question.question_type)
    replacement_slot = random.choice(eligible)  # noqa: S311

    # Determine seeker location
    seeker = question.asked_by_player
    if question.question_type == QuestionType.thermometer:
        latest = get_latest_location_for_player(seeker, game)
        assert latest is not None
        seeker_location = latest.coordinates
    else:
        seeker_location = question.seeker_location_start

    # Determine custom_distance for radar/thermometer custom slots
    custom_distance: float | None = None
    if replacement_slot.distance is None:
        if question.question_type == QuestionType.radar and question.radar_params:
            custom_distance = question.radar_params.radius
        elif question.question_type == QuestionType.thermometer and question.thermometer_params:
            custom_distance = question.thermometer_params.min_travel

    # Dispatch to the appropriate ask function
    qt = question.question_type
    if qt in (QuestionType.radar, QuestionType.thermometer):
        ask_fn = ask_radar if qt == QuestionType.radar else ask_thermometer
        replacement = ask_fn(game, seeker, seeker_location, replacement_slot, custom_distance)
    elif qt == QuestionType.matching:
        replacement = ask_matching(game, seeker, seeker_location, replacement_slot)
    elif qt == QuestionType.measuring:
        replacement = ask_measuring(game, seeker, seeker_location, replacement_slot)
    else:
        replacement = ask_tentacles(game, seeker, seeker_location, replacement_slot)

    logger.info(
        'question_randomized',
        game_id=str(game.id),
        original_question_id=str(question.id),
        new_question_id=str(replacement.id),
        question_type=qt.value,
    )
    return replacement
