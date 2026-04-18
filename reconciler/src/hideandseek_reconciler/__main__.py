"""Timer reconciler entrypoint.

Runs forever: every TICK_SECONDS, queries Postgres for overdue game timers and
enqueues the corresponding Celery tasks. Task bodies live in
`hideandseek_worker.tasks.game_timers` and are idempotent — a redundant enqueue
during the brief execution window is a no-op.

Deployment: one replica in docker-compose. If the process dies for N seconds,
timers fire N seconds late, never lost.
"""

from __future__ import annotations

import time

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


def tick() -> None:
    """One reconciliation pass: read overdue IDs, enqueue tasks."""
    with session_scope():
        hiding_ids = find_overdue_hiding_games()
        question_ids = find_overdue_answerable_questions()
        claim_ids = find_overdue_found_claims()

    for gid in hiding_ids:
        transition_hiding_to_seeking.apply_async(  # type: ignore[attr-defined]
            args=[str(gid)],
            task_id=f'hiding_timer:{gid}',
        )
        logger.info('reconcile_enqueue_hiding_transition', game_id=str(gid))

    for qid in question_ids:
        auto_answer_question.apply_async(  # type: ignore[attr-defined]
            args=[str(qid)],
            task_id=f'answer_deadline:{qid}',
        )
        logger.info('reconcile_enqueue_auto_answer', question_id=str(qid))

    for gid in claim_ids:
        auto_dismiss_found_claim.apply_async(  # type: ignore[attr-defined]
            args=[str(gid)],
            task_id=f'found_claim:{gid}',
        )
        logger.info('reconcile_enqueue_found_claim_expiry', game_id=str(gid))


def main() -> None:
    logger.info('reconciler_started', tick_seconds=TICK_SECONDS)
    while True:
        try:
            tick()
        except Exception:
            logger.exception('reconciler_tick_failed')
        time.sleep(TICK_SECONDS)


if __name__ == '__main__':
    main()
