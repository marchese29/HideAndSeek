"""Question asking, answering, and listing endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from geojson_pydantic import Point as GeoJSONPoint
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import mapping

from hideandseek.dependencies import (
    get_game,
    get_player_in_game,
    get_seeker_in_game,
)
from hideandseek.schemas.request import AskQuestionRequest
from hideandseek.schemas.response import (
    FeaturePreviewResponse,
    PreviewQuestionResponse,
    TentaclePOIPreviewResponse,
)
from hideandseek.validators import (
    validate_abandon_request,
    validate_answer_request,
    validate_lock_in_request,
    validate_randomize_request,
    validate_slot_request,
)
from hideandseek_core.broadcast.emit import emit_gameplay
from hideandseek_core.broadcast.events import (
    HiderQuestionAnsweredEvent,
    QuestionAbandonedEvent,
    QuestionAnswerableEvent,
    QuestionAskedEvent,
    QuestionVetoedEvent,
    SeekerQuestionAnsweredEvent,
)
from hideandseek_core.conventions import format_distance_label
from hideandseek_core.db import session_dependency
from hideandseek_core.geo_helpers import geom_or_none
from hideandseek_core.logic.answer import (
    abandon_question,
    answer_matching,
    answer_measuring,
    answer_radar,
    answer_tentacles,
    answer_thermometer,
    schedule_veto,
    veto_immediate,
)
from hideandseek_core.logic.ask import (
    ask_matching,
    ask_measuring,
    ask_radar,
    ask_tentacles,
    ask_thermometer,
    lock_in_thermometer,
    randomize_question,
)
from hideandseek_core.logic.preview import preview_question
from hideandseek_core.queries.location import create_location_update
from hideandseek_core.queries.questions import get_eligible_randomize_slots, has_unanswered_question
from hideandseek_models.game import Game, Player
from hideandseek_models.types import (
    PushEventType,
    QuestionStatus,
    QuestionType,
)
from hideandseek_worker.tasks.push import send_push

router = APIRouter(
    prefix='/games/{game_id}', tags=['questions'], dependencies=[Depends(session_dependency)]
)


def _validate_can_ask(game: Game) -> None:
    """Common pre-ask validation: game must be seeking, no unanswered question."""
    if not game.status.is_seeking:
        raise HTTPException(status_code=409, detail='Questions can only be asked during seeking.')
    if has_unanswered_question(game):
        raise HTTPException(status_code=409, detail='There is already an unanswered question.')


def _record_seeker_location(location: GeoJSONPoint, player: Player, game: Game) -> ShapelyPoint:
    """Record the seeker's location from the request body and return as shapely Point."""
    seeker_location = ShapelyPoint(location.coordinates[0], location.coordinates[1])
    create_location_update(
        player=player,
        game=game,
        coordinates=seeker_location,
        timestamp=datetime.now(UTC),
    )
    return seeker_location


# ── Ask endpoints (per-type) ─────────────────────────────────────────────


@router.post('/questions/radar', status_code=204)
def ask_radar_question(
    body: AskQuestionRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_seeker_in_game),
) -> None:
    """Ask a radar question, spending a radar inventory slot."""
    _validate_can_ask(game)
    seeker_location = _record_seeker_location(body.location, player, game)

    slot = validate_slot_request(body.slot_index, body.custom_distance, game, QuestionType.radar)
    question = ask_radar(game, player, seeker_location, slot, body.custom_distance)

    rp = question.radar_params
    assert rp is not None
    distance_label = format_distance_label(rp.radius, game.game_map.convention)
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_asked,
        role_filter='hider',
        alert=f'A {distance_label} radar question has been asked. Your answer timer is running.',
        question_id=str(question.id),
        question_type=QuestionType.radar,
        question_status=QuestionStatus.answerable,
    )

    emit_gameplay(
        QuestionAskedEvent.from_question(
            question, base_question_delay_min=game.base_question_delay_min
        )
    )


@router.post('/questions/thermometer', status_code=204)
def ask_thermometer_question(
    body: AskQuestionRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_seeker_in_game),
) -> None:
    """Ask a thermometer question, spending a thermometer inventory slot."""
    _validate_can_ask(game)
    seeker_location = _record_seeker_location(body.location, player, game)

    slot = validate_slot_request(
        body.slot_index, body.custom_distance, game, QuestionType.thermometer
    )
    question = ask_thermometer(game, player, seeker_location, slot, body.custom_distance)

    tp = question.thermometer_params
    assert tp is not None
    distance_label = format_distance_label(tp.min_travel, game.game_map.convention)
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_asked,
        role_filter='hider',
        alert=f'A {distance_label} thermometer question has started. The seeker is traveling.',
        question_id=str(question.id),
        question_type=QuestionType.thermometer,
        question_status=QuestionStatus.in_progress,
    )

    emit_gameplay(
        QuestionAskedEvent.from_question(
            question, base_question_delay_min=game.base_question_delay_min
        )
    )


@router.post('/questions/matching', status_code=204)
def ask_matching_question(
    body: AskQuestionRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_seeker_in_game),
) -> None:
    """Ask a matching question about a feature category."""
    _validate_can_ask(game)
    seeker_location = _record_seeker_location(body.location, player, game)

    slot = validate_slot_request(body.slot_index, body.custom_distance, game, QuestionType.matching)

    try:
        question = ask_matching(game, player, seeker_location, slot)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    fp = question.feature_params
    assert fp is not None
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_asked,
        role_filter='hider',
        alert=(
            f'A matching question about {fp.category} has been asked. Your answer timer is running.'
        ),
        question_id=str(question.id),
        question_type=QuestionType.matching,
        question_status=QuestionStatus.answerable,
    )

    emit_gameplay(
        QuestionAskedEvent.from_question(
            question, base_question_delay_min=game.base_question_delay_min
        )
    )


@router.post('/questions/measuring', status_code=204)
def ask_measuring_question(
    body: AskQuestionRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_seeker_in_game),
) -> None:
    """Ask a measuring question about a feature category."""
    _validate_can_ask(game)
    seeker_location = _record_seeker_location(body.location, player, game)

    slot = validate_slot_request(
        body.slot_index, body.custom_distance, game, QuestionType.measuring
    )

    try:
        question = ask_measuring(game, player, seeker_location, slot)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    fp = question.feature_params
    assert fp is not None
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_asked,
        role_filter='hider',
        alert=(
            f'A measuring question about {fp.category} has been asked. '
            f'Your answer timer is running.'
        ),
        question_id=str(question.id),
        question_type=QuestionType.measuring,
        question_status=QuestionStatus.answerable,
    )

    emit_gameplay(
        QuestionAskedEvent.from_question(
            question, base_question_delay_min=game.base_question_delay_min
        )
    )


@router.post('/questions/tentacles', status_code=204)
def ask_tentacles_question(
    body: AskQuestionRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_seeker_in_game),
) -> None:
    """Ask a tentacles question about a POI category."""
    _validate_can_ask(game)
    seeker_location = _record_seeker_location(body.location, player, game)

    slot = validate_slot_request(
        body.slot_index, body.custom_distance, game, QuestionType.tentacles
    )

    try:
        question = ask_tentacles(game, player, seeker_location, slot)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    tp = question.tentacle_params
    assert tp is not None
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_asked,
        role_filter='hider',
        alert=(
            f'A tentacles question about {tp.category} has been asked. '
            f'Your answer timer is running.'
        ),
        question_id=str(question.id),
        question_type=QuestionType.tentacles,
        question_status=QuestionStatus.answerable,
    )

    emit_gameplay(
        QuestionAskedEvent.from_question(
            question, base_question_delay_min=game.base_question_delay_min
        )
    )


# ── Preview ─────────────────────────────────────────────────────────────


@router.get('/questions/preview')
def preview_question_endpoint(
    question_type: QuestionType = Query(description='Question type to preview.'),
    slot_index: int = Query(description='0-based inventory slot index.'),
    lat: float = Query(description='Seeker latitude.'),
    lng: float = Query(description='Seeker longitude.'),
    custom_distance: float | None = Query(
        default=None, description='Required for custom slots (distance=null).'
    ),
    end_lat: float | None = Query(default=None, description='Thermometer end latitude.'),
    end_lng: float | None = Query(default=None, description='Thermometer end longitude.'),
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> PreviewQuestionResponse:
    """Preview the dividing boundary for a question configuration.

    Read-only — does not create a question or consume inventory. Returns the
    geometry that separates the two possible answer outcomes (e.g. the radar
    circle, thermometer bisector, or Voronoi cell edge).
    """
    location = ShapelyPoint(lng, lat)

    seeker_location_end: ShapelyPoint | None = None
    if question_type == QuestionType.thermometer:
        if end_lat is None or end_lng is None:
            raise HTTPException(
                status_code=422,
                detail='end_lat and end_lng are required for thermometer preview.',
            )
        seeker_location_end = ShapelyPoint(end_lng, end_lat)

    slot = validate_slot_request(slot_index, custom_distance, game, question_type)

    try:
        result = preview_question(
            question_type=question_type,
            game=game,
            slot=slot,
            location=location,
            custom_distance=custom_distance,
            seeker_location_end=seeker_location_end,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    boundary_geojson = geom_or_none(result.boundary)
    assert boundary_geojson is not None

    feature_preview = None
    if result.feature_id is not None:
        feature_preview = FeaturePreviewResponse(
            feature_id=result.feature_id,
            name=result.feature_name or '',
            distance=result.feature_distance or 0.0,
        )

    tentacle_pois = None
    if result.tentacle_pois is not None:
        tentacle_pois = [
            TentaclePOIPreviewResponse(
                feature_id=p.feature_id,
                name=p.name,
                location=GeoJSONPoint(**mapping(p.location)),
            )
            for p in result.tentacle_pois
        ]

    return PreviewQuestionResponse(
        boundary=boundary_geojson,
        feature_preview=feature_preview,
        tentacle_pois=tentacle_pois,
    )


# ── Lock-in and answer ───────────────────────────────────────────────────


@router.post(
    '/questions/thermometer/{question_id}/lock-in',
    status_code=204,
)
def lock_in_question(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> None:
    """Lock in the seeker's end position for a thermometer question."""
    question, seeker_end = validate_lock_in_request(question_id, game, player)

    lock_in_thermometer(question, seeker_end)

    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_answerable,
        role_filter='hider',
        alert='A thermometer question is ready for your answer.',
        question_id=str(question.id),
    )

    emit_gameplay(
        QuestionAnswerableEvent.from_question(
            question, base_question_delay_min=game.base_question_delay_min
        )
    )


@router.post(
    '/questions/{question_id}/answer',
    status_code=204,
)
def answer_question(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> None:
    """Hider answers a question — snapshot location, compute answer and exclusion."""
    question, hider_location = validate_answer_request(question_id, game, player)

    # Set hider location, compute answer + exclusion, persist
    question.hider_location = hider_location

    if question.question_type == QuestionType.radar:
        answer_radar(question, game)
    elif question.question_type == QuestionType.thermometer:
        answer_thermometer(question, game)
    elif question.question_type == QuestionType.matching:
        answer_matching(question, game)
    elif question.question_type == QuestionType.measuring:
        answer_measuring(question, game)
    elif question.question_type == QuestionType.tentacles:
        answer_tentacles(question, game)
    else:
        raise HTTPException(
            status_code=422, detail=f'Unsupported question type: {question.question_type}'
        )

    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_answered,
        role_filter='seeker',
        alert=f'Question answered: {question.answer}!',
        question_id=str(question.id),
        question_type=question.question_type,
        answer=question.answer,
    )

    emit_gameplay(HiderQuestionAnsweredEvent.from_question(question))
    emit_gameplay(SeekerQuestionAnsweredEvent.from_question(question))


# ── Veto ─────────────────────────────────────────────────────────────────


@router.post(
    '/questions/{question_id}/veto',
    status_code=204,
)
def veto_question(
    question_id: uuid.UUID,
    scheduled: bool = False,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> None:
    """Hider vetoes a question — no answer, no exclusion zone.

    With scheduled=true, the veto is deferred: it fires when the auto-answer
    timer expires instead of immediately. The hider can still answer normally
    before the timer to cancel the scheduled veto implicitly.
    """
    question, _hider_location = validate_answer_request(question_id, game, player)

    if scheduled:
        schedule_veto(question)
        return

    veto_immediate(question)

    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_vetoed,
        role_filter='seeker',
        alert='The hider used a veto!',
        question_id=str(question.id),
        question_type=question.question_type,
    )

    emit_gameplay(QuestionVetoedEvent.from_question(question))


# ── Abandon ───────────────────────────────────────────────────────────


@router.post(
    '/questions/{question_id}/abandon',
    status_code=204,
)
def abandon_question_endpoint(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> None:
    """Seeker abandons a question — no answer, no exclusion zone."""
    question = validate_abandon_request(question_id, game, player)

    abandon_question(question)

    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_abandoned,
        role_filter='hider',
        alert='The seeker abandoned a question!',
        question_id=str(question.id),
        question_type=question.question_type,
    )

    emit_gameplay(QuestionAbandonedEvent.from_question(question))


# ── Randomize ──────────────────────────────────────────────────────────


@router.post(
    '/questions/{question_id}/randomize',
    status_code=204,
)
def randomize_question_endpoint(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> None:
    """Hider randomizes a question — terminates the original and creates a replacement.

    The server picks a random slot of the same question type with ask_count == 0.
    The original question is marked as randomized and its slot's ask_count is restored.
    A standard QuestionAskedEvent is emitted for the replacement.
    """
    question = validate_randomize_request(question_id, game, player)

    eligible = get_eligible_randomize_slots(game, question.question_type)
    if not eligible:
        raise HTTPException(status_code=409, detail='No eligible replacement slots available.')

    replacement = randomize_question(question, game)

    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_randomized,
        role_filter='seeker',
        alert='The hider used a randomize!',
        question_id=str(replacement.id),
        question_type=replacement.question_type,
    )

    emit_gameplay(
        QuestionAskedEvent.from_question(
            replacement, base_question_delay_min=game.base_question_delay_min
        )
    )
