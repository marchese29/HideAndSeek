"""Timer reconciler entrypoint.

Runs forever: every TICK_SECONDS, queries Postgres for overdue game timers and
enqueues the corresponding Celery tasks. Task bodies live in
`hideandseek_worker.tasks.game_timers` and are idempotent — a redundant enqueue
during the brief execution window is a no-op.

Deployment: one replica in docker-compose and ECS. If the process dies for N
seconds, timers fire N seconds late, never lost.

Shutdown contract: SIGTERM and SIGINT set a shared `threading.Event`. The
current tick finishes its DB read, the enqueue loops poll the flag between
iterations, and the loop exits cleanly before the next sleep. This is what
makes the ECS deployment config (`minimumHealthyPercent: 0, maximumPercent:
100`) safe — the old task drains and exits in well under the default 30s
stopTimeout before the new task starts.
"""

from __future__ import annotations

import signal
import threading
from types import FrameType

import structlog

from hideandseek_core.db import session_scope
from hideandseek_core.logic.timers import (
    find_overdue_answerable_questions,
    find_overdue_found_claims,
    find_overdue_hiding_games,
)
from hideandseek_worker.tasks.game_timers import (
    auto_answer_question,
    auto_dismiss_found_claim,
    transition_hiding_to_seeking,
)

TICK_SECONDS = 1.0

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_shutdown = threading.Event()


def _handle_shutdown(signum: int, _frame: FrameType | None) -> None:
    logger.info('reconciler_shutdown_requested', signal=signal.Signals(signum).name)
    _shutdown.set()


def tick() -> None:
    """One reconciliation pass: read overdue IDs, enqueue tasks.

    The three enqueue loops check `_shutdown` between iterations so a large
    catch-up batch can't hold the process past the shutdown grace window.
    """
    with session_scope():
        hiding_ids = find_overdue_hiding_games()
        question_ids = find_overdue_answerable_questions()
        claim_ids = find_overdue_found_claims()

    for gid in hiding_ids:
        if _shutdown.is_set():
            return
        transition_hiding_to_seeking.apply_async(  # type: ignore[attr-defined]
            args=[str(gid)],
            task_id=f'hiding_timer:{gid}',
        )
        logger.info('reconcile_enqueue_hiding_transition', game_id=str(gid))

    for qid in question_ids:
        if _shutdown.is_set():
            return
        auto_answer_question.apply_async(  # type: ignore[attr-defined]
            args=[str(qid)],
            task_id=f'answer_deadline:{qid}',
        )
        logger.info('reconcile_enqueue_auto_answer', question_id=str(qid))

    for gid in claim_ids:
        if _shutdown.is_set():
            return
        auto_dismiss_found_claim.apply_async(  # type: ignore[attr-defined]
            args=[str(gid)],
            task_id=f'found_claim:{gid}',
        )
        logger.info('reconcile_enqueue_found_claim_expiry', game_id=str(gid))


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)
    logger.info('reconciler_started', tick_seconds=TICK_SECONDS)
    while not _shutdown.is_set():
        try:
            tick()
        except Exception:
            logger.exception('reconciler_tick_failed')
        _shutdown.wait(TICK_SECONDS)
    logger.info('reconciler_stopped')


if __name__ == '__main__':
    main()
