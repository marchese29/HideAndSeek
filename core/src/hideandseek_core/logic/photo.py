"""Photo question submission logic — queue / clear / submit transitions.

Cycle z32.4 covers the pre-review half of the photo flow: hiders upload an
image (optionally keeping it queued), replace it, clear it, or submit. Cycle
z32.5 will add accept/reject and auto-resolve.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from hideandseek_models.game import Player
from hideandseek_models.question import Question
from hideandseek_models.types import QuestionStatus, QuestionType

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def queue_photo(question: Question, player: Player, object_key: str) -> None:
    """Persist a queued (non-submitted) photo upload.

    Caller is responsible for having already uploaded the bytes to S3 under
    `object_key`. Overwrites any previously-queued key — the old S3 object is
    retained (photos kept forever per design §10).
    """
    assert question.question_type == QuestionType.photo
    assert question.status == QuestionStatus.answerable
    params = question.photo_params
    assert params is not None
    params.photo_object_key = object_key
    params.is_null_answer = False
    logger.info(
        'photo_queued',
        game_id=str(question.game_id),
        question_id=str(question.id),
        queued_by=str(player.id),
    )


def clear_queued_photo(question: Question) -> None:
    """Clear queued photo state (DELETE endpoint)."""
    assert question.question_type == QuestionType.photo
    assert question.status == QuestionStatus.answerable
    params = question.photo_params
    assert params is not None
    params.photo_object_key = None
    params.is_null_answer = False
    logger.info(
        'photo_unqueued',
        game_id=str(question.game_id),
        question_id=str(question.id),
    )


def submit_photo_question(question: Question, player: Player, *, is_null_answer: bool) -> None:
    """Transition a photo question from answerable → submitted.

    For null submits, also clears any queued photo state. For photo submits,
    the caller must have already called `queue_photo()` so that
    `photo_object_key` is set.
    """
    assert question.question_type == QuestionType.photo
    assert question.status == QuestionStatus.answerable
    params = question.photo_params
    assert params is not None

    if is_null_answer:
        params.photo_object_key = None
        params.is_null_answer = True
    else:
        assert params.photo_object_key is not None

    params.submitted_at = datetime.now(UTC)
    params.submitted_by = player.id
    question.status = QuestionStatus.submitted

    logger.info(
        'photo_submitted',
        game_id=str(question.game_id),
        question_id=str(question.id),
        submitted_by=str(player.id),
        is_null_answer=params.is_null_answer,
    )
