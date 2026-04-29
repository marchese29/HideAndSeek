# Worker — Celery Background Tasks

Celery worker for the HideAndSeek game. Handles game timers (hiding-to-seeking phase transitions, auto-answer deadlines) and push notification delivery. Deployed independently from the API server.

## Commands

```bash
uv run ruff check .        # Lint
uv run ruff format .       # Format
uv run pyright             # Type check
```

No tests — worker tasks are exercised by the server test suite (`cd server && uv run pytest`), which imports worker tasks directly with Celery in eager mode.

## Package Structure

```
src/hideandseek_worker/
  celery_app.py        # Celery application instance + task autodiscovery
  celery_config.py     # Broker/result backend config (env var → auto-detect → eager)
  tasks/
    game_timers.py     # Phase transition (hiding→seeking), auto-answer deadline,
                       # auto-dismiss found claim
    push.py            # Push notification delivery (SNS Mobile Push) with retry.
                       #   After publish, deletes DeviceToken rows whose endpoint ARNs
                       #   SNS reported as disabled/invalid (inline dead-token cleanup).
```

## Game Timer Tasks

| Task | Task ID | Purpose |
|------|---------|---------|
| `transition_hiding_to_seeking` | `hiding_timer:{game_id}` | Flip game to seeking after hiding timer |
| `auto_answer_question` | `answer_deadline:{question_id}` | Auto-answer after question deadline |
| `auto_dismiss_found_claim` | `found_claim:{game_id}` | Clear a pending found claim after 2 min |
| `auto_resolve_photo_submit` | `photo_submit:{question_id}` | After photo submit window: auto-submit if a photo is queued, else abandon |
| `auto_accept_photo` | `photo_review:{question_id}` | After photo review window: auto-accept a submitted photo |

All tasks are idempotent: they re-check preconditions inside `session_scope()` and no-op if the state has already moved on.

**Scheduling**: these tasks are **not** scheduled with `apply_async(countdown=...)`. They are enqueued for immediate execution by the `hideandseek-reconciler` process, which polls Postgres every second for overdue fire-times. The three non-photo deadlines live on dedicated future-deadline columns (`Game.hiding_ends_at`, `Question.deadline_at`, `Game.found_claim_expires_at`); the reconciler filters `Game.paused_at IS NULL` so paused games are skipped naturally. The two photo deadlines still resolve from start anchors (`Question.answerable_at` for submit, `PhotoQuestionParams.submitted_at` for review) plus per-game settings until z32.5/m8r.nah introduces dedicated columns. Celery's role is strictly worker pool — the scheduler lives in its own process. See `reconciler/CLAUDE.md`.

**Deterministic task IDs** still used (for log-grep observability), but no longer for revocation: the reconciler's query filters naturally skip rows whose state has advanced, so cancellation falls out of state transitions instead of explicit `revoke()` calls.

## Architecture Rules

- **Dependency direction**: `hideandseek-models` ← `hideandseek-core` ← `hideandseek-worker` ← `hideandseek` (server). Worker imports from core and models, never from server.
- **No HTTP**: Worker never imports from `hideandseek.schemas`, `hideandseek.routers`, or any FastAPI code.
- **ContextVar session access**: Tasks use `session_scope()` from core to get a DB session. All query functions using `db.get_session()` work naturally inside the `with session_scope():` block.
- **Task ID convention**: Deterministic IDs (`hiding_timer:{game_id}`, `answer_deadline:{question_id}`, `found_claim:{game_id}`) for log-grep observability. No longer used for revocation.
- **Celery config resolution**: (1) `CELERY_BROKER_URL` env var if set, (2) auto-detect Redis on `localhost:6379`, (3) eager mode (tasks run synchronously in-process). Set `CELERY_BROKER_URL=''` to force eager mode.

## Running the Worker

```bash
# Docker (from repo root — preferred)
docker compose up --build    # Worker runs alongside API, PostGIS, Redis

# Local dev (requires: docker compose up -d postgres redis)
cd server && uv run celery -A hideandseek_worker.celery_app worker
```

## Logging

`celery_app.py` connects Celery's `setup_logging` signal to `hideandseek_core.logging.setup_logging()`, and `celery_config.py` sets `worker_hijack_root_logger = False` so Celery leaves our config alone. Level/format are driven by `ENV` (not `--loglevel`) — identical behavior to server and reconciler.

## Conventions

- Same style as server/core: single quotes, `from __future__ import annotations`, ruff + pyright.
- Import from core submodules directly (e.g., `from hideandseek_core.logic.answer import answer_radar`).
