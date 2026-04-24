"""Question asking, answering, and listing endpoints."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from geojson_pydantic import Point as GeoJSONPoint
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import mapping
from starlette.datastructures import UploadFile

from hideandseek.dependencies import (
    get_game,
    get_hider_in_game,
    get_player_in_game,
    get_seeker_in_game,
)
from hideandseek.schemas.request import AskPhotoQuestionRequest, AskQuestionRequest
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
    PhotoQueuedEvent,
    PhotoSubmittedEvent,
    PhotoUnqueuedEvent,
    QuestionAbandonedEvent,
    QuestionAnswerableEvent,
    QuestionAskedEvent,
    QuestionVetoedEvent,
    SeekerQuestionAnsweredEvent,
)
from hideandseek_core.config import load_s3_config
from hideandseek_core.conventions import effective_photo_review_sec, format_distance_label
from hideandseek_core.db import get_session, session_dependency
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
    ask_photo,
    ask_radar,
    ask_tentacles,
    ask_thermometer,
    lock_in_thermometer,
    randomize_question,
)
from hideandseek_core.logic.photo import (
    clear_queued_photo,
    queue_photo,
    submit_photo_question,
)
from hideandseek_core.logic.preview import preview_question
from hideandseek_core.queries.location import create_location_update
from hideandseek_core.queries.questions import get_eligible_randomize_slots, has_unanswered_question
from hideandseek_core.s3 import get_object_stream, upload_bytes
from hideandseek_models.game import Game, Player
from hideandseek_models.question import Question
from hideandseek_models.types import (
    PlayerRole,
    PushEventType,
    QuestionStatus,
    QuestionType,
)
from hideandseek_worker.tasks.push import send_push

if TYPE_CHECKING:
    from hideandseek_core.config import S3Config

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


@router.post('/questions/photo', status_code=204)
def ask_photo_question(
    body: AskPhotoQuestionRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_seeker_in_game),
) -> None:
    """Ask a photo question, spending a photo inventory slot."""
    _validate_can_ask(game)
    seeker_location = _record_seeker_location(body.location, player, game)

    slot = validate_slot_request(body.slot_index, None, game, QuestionType.photo)
    question = ask_photo(game, player, seeker_location, slot)

    pp = question.photo_params
    assert pp is not None
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.question_asked,
        role_filter='hider',
        alert=(f'A photo question has been asked: {pp.subject.value}. Submit an image to answer.'),
        question_id=str(question.id),
        question_type=QuestionType.photo,
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


# ── Photo submission ────────────────────────────────────────────────────

_JPEG_MAGIC = b'\xff\xd8\xff'
_PNG_MAGIC = b'\x89PNG'
_ALLOWED_PHOTO_CONTENT_TYPES = {'image/jpeg', 'image/png'}


def _load_photo_question(question_id: uuid.UUID, game: Game) -> Question:
    """Load a photo question scoped to the given game, or raise 404/422."""
    session = get_session()
    question = session.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail='Question not found.')
    if question.game_id != game.id:
        raise HTTPException(status_code=422, detail='Question does not belong to this game.')
    if question.question_type != QuestionType.photo:
        raise HTTPException(status_code=422, detail='Question is not a photo question.')
    return question


def _check_photo_submission_open(question: Question) -> None:
    """409 if the photo question is no longer accepting submissions."""
    if question.status == QuestionStatus.submitted:
        raise HTTPException(status_code=409, detail='photo already submitted')
    if question.status != QuestionStatus.answerable:
        raise HTTPException(status_code=409, detail=f'question is {question.status.value}')


def _validate_image(upload: UploadFile) -> tuple[str, str]:
    """Validate an uploaded image. Returns (content_type, file_extension).

    415 if the declared content-type isn't JPEG/PNG or the first bytes don't
    match the claimed type (mislabeled uploads are rejected). The file handle
    is seeked back to 0 before returning.
    """
    content_type = (upload.content_type or '').lower()
    if content_type not in _ALLOWED_PHOTO_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f'unsupported image content-type: {content_type or "(unset)"}',
        )
    head = upload.file.read(4)
    upload.file.seek(0)
    if content_type == 'image/jpeg':
        if not head.startswith(_JPEG_MAGIC):
            raise HTTPException(status_code=415, detail='file is not a valid JPEG')
        return content_type, 'jpg'
    if not head.startswith(_PNG_MAGIC):
        raise HTTPException(status_code=415, detail='file is not a valid PNG')
    return content_type, 'png'


def _photo_key(game_id: uuid.UUID, ext: str) -> str:
    env = os.environ.get('HIDEANDSEEK_ENV', 'local')
    return f'{env}/{game_id}/{uuid.uuid4()}.{ext}'


def _require_s3_config() -> S3Config:
    config = load_s3_config()
    if config is None:
        raise HTTPException(status_code=503, detail='photo storage not configured')
    return config


def _send_photo_submitted_push(game: Game, question: Question) -> None:
    pp = question.photo_params
    assert pp is not None
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.photo_submitted,
        role_filter='seeker',
        alert=f'A {pp.subject.value} photo has been submitted. Tap to review.',
        question_id=str(question.id),
    )


@router.post('/questions/{question_id}/photo', status_code=204)
async def submit_photo_endpoint(
    question_id: uuid.UUID,
    request: Request,
    game: Game = Depends(get_game),
    player: Player = Depends(get_hider_in_game),
) -> None:
    """Upload + optionally submit a photo, or submit a null answer.

    JSON body ``{"null": true}`` → null-submit (no upload).
    Multipart body with ``file`` field → upload the image; pair with
    ``submit=true`` to also transition to ``submitted`` in one request.
    Omitting ``submit`` (or ``submit=false``) leaves the photo queued so the
    hider can replace it.
    """
    question = _load_photo_question(question_id, game)
    _check_photo_submission_open(question)

    content_type = request.headers.get('content-type', '').lower()

    if content_type.startswith('application/json'):
        body = await request.json()
        if not isinstance(body, dict) or not body.get('null'):
            raise HTTPException(status_code=422, detail='null submit requires {"null": true}')
        submit_photo_question(question, player, is_null_answer=True)
        review_deadline = datetime.now(UTC) + timedelta(seconds=effective_photo_review_sec(game))
        emit_gameplay(PhotoSubmittedEvent.from_question(question, review_deadline=review_deadline))
        _send_photo_submitted_push(game, question)
        return

    if content_type.startswith('multipart/form-data'):
        form = await request.form()
        upload = form.get('file')
        if not isinstance(upload, UploadFile):
            raise HTTPException(status_code=422, detail='multipart body requires a "file" field')
        submit_flag_raw = form.get('submit', 'false')
        submit_flag = (
            submit_flag_raw.lower() == 'true' if isinstance(submit_flag_raw, str) else False
        )

        photo_content_type, ext = _validate_image(upload)
        s3_config = _require_s3_config()
        key = _photo_key(game.id, ext)
        upload_bytes(s3_config, key, upload.file, photo_content_type)

        queue_photo(question, player, key)
        emit_gameplay(
            PhotoQueuedEvent(
                game_id=game.id,
                question_id=question.id,
                sequence=question.sequence,
                queued_by=player.id,
                uploaded_at=datetime.now(UTC),
            )
        )

        if submit_flag:
            submit_photo_question(question, player, is_null_answer=False)
            review_deadline = datetime.now(UTC) + timedelta(
                seconds=effective_photo_review_sec(game)
            )
            emit_gameplay(
                PhotoSubmittedEvent.from_question(question, review_deadline=review_deadline)
            )
            _send_photo_submitted_push(game, question)
        return

    raise HTTPException(status_code=415, detail=f'unsupported content-type: {content_type!r}')


@router.delete('/questions/{question_id}/photo', status_code=204)
def unqueue_photo_endpoint(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    player: Player = Depends(get_hider_in_game),  # noqa: ARG001  (auth gate)
) -> None:
    """Clear a queued photo before submission. 409 if already submitted."""
    question = _load_photo_question(question_id, game)
    if question.status != QuestionStatus.answerable:
        raise HTTPException(status_code=409, detail=f'question is {question.status.value}')
    clear_queued_photo(question)
    emit_gameplay(
        PhotoUnqueuedEvent(
            game_id=game.id,
            question_id=question.id,
            sequence=question.sequence,
        )
    )


@router.get('/questions/{question_id}/photo')
def fetch_photo_endpoint(
    question_id: uuid.UUID,
    game: Game = Depends(get_game),
    player: Player = Depends(get_player_in_game),
) -> StreamingResponse:
    """Fetch the photo bytes for a photo question.

    State-sensitive auth: pre-submit photos are hider-only; once submitted,
    either role may fetch. 404 on null-answer or missing object.
    """
    question = _load_photo_question(question_id, game)
    params = question.photo_params
    assert params is not None

    if params.is_null_answer:
        raise HTTPException(status_code=404, detail='no photo for null answer')
    if params.photo_object_key is None:
        raise HTTPException(status_code=404, detail='no photo queued')

    if question.status == QuestionStatus.answerable and player.role != PlayerRole.hider:
        raise HTTPException(status_code=403, detail='photo not yet submitted')

    s3_config = _require_s3_config()
    obj = get_object_stream(s3_config, params.photo_object_key)

    return StreamingResponse(
        obj['Body'].iter_chunks(),
        media_type=obj['ContentType'],
        headers={
            'Content-Length': str(obj['ContentLength']),
            'Cache-Control': 'private, max-age=3600',
        },
    )
