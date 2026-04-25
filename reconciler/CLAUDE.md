# Reconciler — Timer Scheduler

Polls Postgres for overdue game timers and enqueues Celery tasks. Replaces Celery ETA (`apply_async(countdown=...)`) for phase transitions and answer deadlines. Deployed as a single replica alongside the API and worker.

## Why a separate process

Celery's Redis broker hands ETA tasks to a worker immediately; the worker holds the timer in memory until fire-time. A worker crash loses the timer. Authoritative fire-times already live in Postgres:
- `game.hiding_started_at + hiding_time_min` → hiding→seeking transition
- `question.answerable_at + base_question_delay_min` → auto-answer deadline
- `game.found_claim_at + 120s` → found-claim expiry
- `question.answerable_at + effective_photo_submit_min` → photo submit window (task `photo_submit:{qid}`)
- `photo_params.submitted_at + effective_photo_review_sec` → photo review window (task `photo_review:{qid}`)

A tiny poller that checks these columns every second and enqueues the existing Celery tasks is resilient: a restart means timers fire N seconds late, never lost. Celery stays as a worker pool — it just stops being the scheduler.

## Commands

```bash
uv run ruff check .        # Lint
uv run ruff format .       # Format
uv run pyright             # Type check
```

No tests — reconciler logic (overdue queries) lives in `hideandseek_core.logic.timers` and is exercised by the server test suite.

## Package Structure

```
src/hideandseek_reconciler/
  __init__.py              # Module docstring
  __main__.py              # Tick loop + entrypoint
```

## Architecture Rules

- **Scheduler only**: The reconciler's job is `query overdue → enqueue task`. It never executes transition logic in-process. All state mutations happen inside the Celery task bodies in `hideandseek_worker.tasks.game_timers`.
- **Dependency direction**: `hideandseek-models` ← `hideandseek-core` ← `hideandseek-worker` ← `hideandseek-reconciler`. Reconciler imports from core (queries + session) and worker (task references for `.apply_async`). Never imports from server.
- **No HTTP**: Reconciler never imports from `hideandseek.routers`, FastAPI, or HTTP infrastructure.
- **Deterministic task IDs**: Preserves the existing `hiding_timer:{game_id}` / `answer_deadline:{question_id}` / `found_claim:{game_id}` IDs for observability (log grep by ID still works).
- **Idempotency is in the tasks, not here**: The reconciler does not guard against double-enqueue; the task bodies check status on entry and no-op if state has advanced. A redundant enqueue during the brief task-execution window is harmless.
- **Single replica**: Docker-compose runs one instance. Multiple replicas would duplicate enqueues (safe but wasteful). If we ever want redundancy, wrap each `tick()` in `pg_try_advisory_xact_lock`.

## Shutdown

SIGTERM and SIGINT are trapped in `__main__.py` and set a module-level `threading.Event` (`_shutdown`). The main loop checks the flag each iteration and `event.wait(TICK_SECONDS)` replaces `time.sleep`, so a signal wakes the sleep immediately. The three enqueue for-loops in `tick()` also poll the flag between iterations, bounding catch-up work after a long downtime.

This is what makes the ECS deployment config (`minimumHealthyPercent: 0, maximumPercent: 100`, per `design/2026-04-19-aws-deployment.md` § Service Changes 3) safe: the old task drains within the default 30s stopTimeout before the new task starts, and the next poll picks up anything missed during the 30–60s deploy gap (overdue queries use `deadline <= now()` with no lower bound, so nothing is lost).

## Running

```bash
# Docker (from repo root — preferred)
docker compose up --build          # reconciler runs alongside api, worker, postgres, redis

# Local dev (requires: docker compose up -d postgres redis)
uv run python -m hideandseek_reconciler
```

## Logging

`main()` calls `hideandseek_core.logging.setup_logging()` before entering the poll loop. Level/format follow `ENV` (shared with server + worker).

## Conventions

- Same style as server/core/worker: single quotes, `from __future__ import annotations`, ruff + pyright.
- Import from core submodules directly (e.g., `from hideandseek_core.logic.timers import find_overdue_hiding_games`).
