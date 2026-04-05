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
    game_timers.py     # Phase transition (hiding→seeking) + auto-answer deadline
    push.py            # Push notification delivery (APNs + FCM) with retry
```

## Architecture Rules

- **Dependency direction**: `hideandseek-models` ← `hideandseek-core` ← `hideandseek-worker` ← `hideandseek` (server). Worker imports from core and models, never from server.
- **No HTTP**: Worker never imports from `hideandseek.schemas`, `hideandseek.routers`, or any FastAPI code.
- **ContextVar session access**: Tasks use `session_scope()` from core to get a DB session. All query functions using `db.get_session()` work naturally inside the `with session_scope():` block.
- **Task ID convention**: Deterministic IDs (`hiding_timer:{game_id}`, `answer_deadline:{question_id}`) so the API can revoke tasks without storing IDs in the DB.
- **Celery config resolution**: (1) `CELERY_BROKER_URL` env var if set, (2) auto-detect Redis on `localhost:6379`, (3) eager mode (tasks run synchronously in-process). Set `CELERY_BROKER_URL=''` to force eager mode.

## Running the Worker

```bash
# Docker (from repo root — preferred)
docker compose up --build    # Worker runs alongside API, PostGIS, Redis

# Local dev (requires: docker compose up -d postgres redis)
cd server && uv run celery -A hideandseek_worker.celery_app worker --loglevel=info --beat
```

## Conventions

- Same style as server/core: single quotes, `from __future__ import annotations`, ruff + pyright.
- Import from core submodules directly (e.g., `from hideandseek_core.logic.answer import answer_radar`).
