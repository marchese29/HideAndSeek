"""Photo question submission logic — queue / clear / submit transitions.

Cycle z32.4 covers the pre-review half of the photo flow: hiders upload an
image (optionally keeping it queued), replace it, clear it, or submit. Cycle
z32.5 will add accept/reject and auto-resolve.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog

from hideandseek_core.logic.answer import accumulate_exclusion, log_question_answered
from hideandseek_models.game import Game, Player
from hideandseek_models.question import Question
from hideandseek_models.types import PhotoReviewDecision, QuestionStatus, QuestionType

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
    params.queued_at = datetime.now(UTC)
    params.queued_by = player.id
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
    params.queued_at = None
    params.queued_by = None
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
    params.queued_at = None
    params.queued_by = None
    question.status = QuestionStatus.submitted

    logger.info(
        'photo_submitted',
        game_id=str(question.game_id),
        question_id=str(question.id),
        submitted_by=str(player.id),
        is_null_answer=params.is_null_answer,
    )


def auto_submit_photo(question: Question) -> None:
    """Reconciler-driven auto-submit when the hider has a queued photo at deadline.

    Same shape as `submit_photo_question` but with no submitting player —
    `submitted_by` stays NULL so audit trails distinguish auto from manual.
    """
    assert question.question_type == QuestionType.photo
    assert question.status == QuestionStatus.answerable
    params = question.photo_params
    assert params is not None
    assert params.photo_object_key is not None or params.is_null_answer

    params.submitted_at = datetime.now(UTC)
    params.submitted_by = None
    params.queued_at = None
    params.queued_by = None
    question.status = QuestionStatus.submitted

    logger.info(
        'photo_auto_submitted',
        game_id=str(question.game_id),
        question_id=str(question.id),
        is_null_answer=params.is_null_answer,
    )


def accept_photo(question: Question, game: Game, *, reviewer_id: uuid.UUID | None) -> None:
    """Seeker accepts a submitted photo (or worker auto-accepts at deadline).

    Flips the question to `answered`. The "answer" string is the photo object
    key (or 'null' for null submissions). No exclusion zone — photos don't
    constrain hider position. `total_exclusion` carries forward unchanged.
    """
    assert question.question_type == QuestionType.photo
    assert question.status == QuestionStatus.submitted
    params = question.photo_params
    assert params is not None

    now = datetime.now(UTC)
    params.review_decision = (
        PhotoReviewDecision.accepted
        if reviewer_id is not None
        else PhotoReviewDecision.auto_accepted
    )
    params.reviewed_by = reviewer_id
    params.reviewed_at = now

    question.answer = 'null' if params.is_null_answer else params.photo_object_key
    question.exclusion = None
    question.total_exclusion = accumulate_exclusion(game, None)
    question.answered_at = now
    question.status = QuestionStatus.answered
    log_question_answered(question)


def reject_photo(question: Question, *, reviewer_id: uuid.UUID) -> None:
    """Seeker rejects a submitted photo — bounce back to `answerable`.

    Clears submission state so the hider can queue/submit again. Resets
    `answerable_at` to now so the reconciler's submit-window deadline
    starts over from the rejection moment.
    """
    assert question.question_type == QuestionType.photo
    assert question.status == QuestionStatus.submitted
    params = question.photo_params
    assert params is not None

    now = datetime.now(UTC)
    params.review_decision = PhotoReviewDecision.rejected
    params.reviewed_by = reviewer_id
    params.reviewed_at = now
    params.photo_object_key = None
    params.is_null_answer = False
    params.queued_at = None
    params.queued_by = None
    params.submitted_at = None
    params.submitted_by = None

    question.status = QuestionStatus.answerable
    question.answerable_at = now

    logger.info(
        'photo_rejected',
        game_id=str(question.game_id),
        question_id=str(question.id),
        reviewed_by=str(reviewer_id),
    )
