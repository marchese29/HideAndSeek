"""Game-timer pause primitive — ref-counted acquire/release for the seeking clock.

`pause_game(game, reason)` and `resume_game(game, reason)` are the only public
entry points. Both are idempotent on `reason`; multiple concurrent reasons
extend the pause until every reason is released. The empty ↔ non-empty
transitions of `Game.active_pause_reasons` drive the freeze/thaw of the clock.

Resume order is load-bearing: deadlines shift first, the accumulator updates
next, `paused_at` clears last. The reconciler reads its overdue queries with
`paused_at IS NULL` in a separate transaction, so it sees either "still paused,
skip" or "unpaused with already-shifted deadlines" — never an inconsistent
middle state.

See design/2026-04-25-game-timer-pause.md.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog

from hideandseek_core.broadcast.events import (
    GameplayEvent,
    GameTimerPausedEvent,
    GameTimerResumedEvent,
)
from hideandseek_core.queries.questions import get_open_questions_with_deadlines
from hideandseek_models.game import Game
from hideandseek_models.types import PauseReason

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def pause_game(game: Game, reason: PauseReason) -> GameplayEvent | None:
    """Add `reason` to the active pause set; stamp `paused_at` if newly paused.

    Idempotent — re-entering with an already-active reason is a no-op and
    returns None. Otherwise returns a `GameTimerPausedEvent` so the caller
    (router or worker task) can emit it from the boundary that owns the
    transaction. Logic functions don't reach into the broadcast layer.
    """
    if reason in game.active_pause_reasons:
        return None
    if game.active_pause_reasons:
        # Invariant: paused_at is set whenever active_pause_reasons is non-empty.
        assert game.paused_at is not None
        paused_at = game.paused_at
    else:
        paused_at = datetime.now(UTC)
        game.paused_at = paused_at
    game.active_pause_reasons = [*game.active_pause_reasons, reason]
    logger.info(
        'game_timer_paused',
        game_id=str(game.id),
        reason=reason.value,
        active_pause_reasons=list(game.active_pause_reasons),
    )
    return GameTimerPausedEvent(
        game_id=game.id,
        paused_at=paused_at,
        active_pause_reasons=list(game.active_pause_reasons),
    )


def resume_game(game: Game, reason: PauseReason) -> GameplayEvent | None:
    """Remove `reason` from the active pause set; if empty, shift deadlines and clear `paused_at`.

    Idempotent — releasing a reason that isn't active is a no-op and returns
    None. If the set is non-empty after removal, returns a `GameTimerPausedEvent`
    with the reduced list (clock stays paused). If the set becomes empty,
    shifts every live deadline forward by the pause duration and returns a
    `GameTimerResumedEvent` carrying every shifted deadline. The caller emits
    the returned event.
    """
    if reason not in game.active_pause_reasons:
        return None
    # Invariant: paused_at is set whenever active_pause_reasons is non-empty.
    assert game.paused_at is not None
    paused_at = game.paused_at

    remaining = [r for r in game.active_pause_reasons if r != reason]
    game.active_pause_reasons = remaining

    if remaining:
        logger.info(
            'game_timer_pause_reason_released',
            game_id=str(game.id),
            reason=reason.value,
            active_pause_reasons=list(remaining),
        )
        return GameTimerPausedEvent(
            game_id=game.id,
            paused_at=paused_at,
            active_pause_reasons=list(remaining),
        )

    now = datetime.now(UTC)
    delta = now - paused_at

    if game.hiding_ends_at is not None:
        game.hiding_ends_at = game.hiding_ends_at + delta
    if game.found_claim_expires_at is not None:
        game.found_claim_expires_at = game.found_claim_expires_at + delta

    question_deadlines: dict[uuid.UUID, datetime] = {}
    for q in get_open_questions_with_deadlines(game):
        # Query filters deadline_at IS NOT NULL; column type is datetime | None.
        assert q.deadline_at is not None
        new_deadline = q.deadline_at + delta
        q.deadline_at = new_deadline
        question_deadlines[q.id] = new_deadline

    # m8r.nah will extend this to also shift PhotoQuestionParams.submit_deadline_at
    # and review_deadline_at once those columns exist.

    # The seeking accumulator is a UI carve-out for the count-up belt timer
    # (`elapsed = now - seeking_started_at - seeking_pause_accumulated_sec - …`).
    # Pre-seeking pauses already shift hiding_ends_at; double-counting them here
    # would make the seeking timer start negative and clamp at 00:00:00 forever.
    # The reconciler can't transition phase mid-pause (it filters paused_at IS NULL),
    # so the entire pause is always in one phase — the simple None check suffices.
    if game.seeking_started_at is not None:
        game.seeking_pause_accumulated_sec += int(delta.total_seconds())
    game.paused_at = None  # MUST be last — reconciler's atomicity hinges on this.

    logger.info(
        'game_timer_resumed',
        game_id=str(game.id),
        reason=reason.value,
        delta_sec=delta.total_seconds(),
        shifted_questions=len(question_deadlines),
    )
    return GameTimerResumedEvent(
        game_id=game.id,
        resumed_at=now,
        seeking_pause_accumulated_sec=game.seeking_pause_accumulated_sec,
        hiding_ends_at=game.hiding_ends_at,
        found_claim_expires_at=game.found_claim_expires_at,
        question_deadlines=question_deadlines,
    )
