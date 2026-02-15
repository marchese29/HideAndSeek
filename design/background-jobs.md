# Background Jobs & Timers Design

> Status: **Draft**
> Last updated: 2026-02-15

How the server schedules timed game-state transitions, enforces answer deadlines, and processes resilient background work. Designed around gameplay scenarios — every job exists because a player would notice if it didn't run.

---

## Core Principles

1. **Gameplay drives the job list** — every scheduled task maps to a moment a player experiences. If no player is waiting on the result, it doesn't need a background job.
2. **Timers are durable** — a server restart mid-game must not lose a hiding-phase countdown. Timers survive process crashes and deploys.
3. **At-least-once, idempotent** — jobs may execute more than once (worker crash, network partition). Every handler must be safe to re-run — check current state before acting.
4. **Dev stays simple** — `docker compose up` launches the API server, worker, broker, and database together. No external infrastructure required for local development.

---

## Gameplay Scenarios Requiring Background Jobs

### Scenario 1: Hiding Phase Timer (hiding -> seeking)

**Player experience:** The host taps "Start Game." Everyone sees a countdown: "Seeking begins in 28:42." When the timer hits zero, all phones buzz — "Seeking phase has begun!" — and the seekers can start asking questions.

**Why it's a background job:** No player triggers the transition. The server must fire it automatically after `timing.hiding_time_min` minutes. If the server restarts mid-countdown, the transition must still happen on time.

**Job:** `transition_hiding_to_seeking`

| Field | Value |
|-------|-------|
| Trigger | `POST /games/{id}/start` sets status to `hiding` |
| Delay | `game.timing['hiding_time_min']` minutes |
| Action | Set `game.status = seeking`, set `seeking_started_at = now()`, push `phase_changed` to all players |
| Idempotency | Check `game.status == hiding` before acting. If already `seeking` or later, no-op. |
| Cancellation | `POST /games/{id}/end` while in `hiding` revokes the pending task. |

**Data model impact:** The `Game` model needs a `hiding_started_at: datetime | None` field so clients can render the countdown (`hiding_started_at + hiding_time_min`). Set when the game transitions to `hiding`. Also needs `seeking_started_at: datetime | None` for the seeking phase start.

### Scenario 2: Hider Answer Deadline (question timeout)

**Player experience:** A radar question lands on the hider's screen: "A 3 km radar question has been asked. You have 5:00 to answer." A countdown ticks down. If the hider doesn't answer in time, the system auto-answers based on their current location — the hider loses control of timing but doesn't get to dodge the question.

**Why it's a background job:** The hider may close the app, lose signal, or simply stall. The game must not freeze because one player stops responding. The `timing.location_question_delay_min` rule enforces fairness.

**Job:** `auto_answer_question`

| Field | Value |
|-------|-------|
| Trigger | Question enters `answerable` status (radar: on ask; thermometer: on lock-in) |
| Delay | `game.timing['location_question_delay_min']` minutes |
| Action | Snapshot hider's latest location, compute answer + exclusion zone, set `status = answered`, push `question_answered` to seekers |
| Idempotency | Check `question.status == answerable` before acting. If already `answered`, no-op. |
| Cancellation | Hider manually answers (`POST .../answer`) before the deadline. Revoke the pending task. |

**Data model impact:** `Question` needs an `answerable_at: datetime | None` field — set when the question transitions to `answerable`. The client renders the countdown from this timestamp.

### Scenario 3: Resilient Push Delivery

**Current state:** Push notifications are fire-and-forget via `BackgroundTasks`. If the APNS call fails (network blip, token issue), the notification is lost. For most events, this is acceptable — the client polls and catches up. But for the hiding -> seeking transition, a missed push means players don't know the phase changed until their next poll.

**Approach:** Move critical pushes (phase transitions) through the task queue instead of `BackgroundTasks`. The worker retries on transient failures with exponential backoff.

| Field | Value |
|-------|-------|
| Events | `phase_changed` (hiding->seeking), `phase_changed` (seeking->endgame) |
| Retry | 3 attempts, exponential backoff (10s, 30s, 90s) |
| Non-critical events | `question_asked`, `question_answered`, etc. remain fire-and-forget via `BackgroundTasks` — the cost of a retry queue isn't justified for events the client will pick up on its next poll. |

---

## Technology Choice: Celery + Redis

### Why Celery

- **Durable delayed tasks** — `apply_async(countdown=...)` schedules a task for a specific future time, persisted in the broker. Survives worker restarts.
- **Task revocation** — `revoke(task_id)` cancels a scheduled task (e.g., when the hider answers before the deadline, or the host ends the game early).
- **Periodic tasks** — Celery Beat schedules recurring jobs without cron.
- **Retry with backoff** — built-in `autoretry_for`, `retry_backoff`, `max_retries`.

### Why Redis as Broker (not PostgreSQL)

The main database is PostgreSQL, but Redis is the better Celery broker for our use cases:

- **Task revocation** — Celery's `revoke()` stores revoked task IDs in Redis's fast key-value store. With PostgreSQL as broker, Celery uses polling (not pub/sub) and revocation is racier.
- **Delayed tasks** — `countdown`/`eta` support is Redis's primary tested path in Celery.
- **No DB contention** — keeps job-queue traffic off the application database.
- **Minimal overhead** — ~5 MB Alpine container. Deploying a managed Redis instance (e.g., ElastiCache) is straightforward.

Redis serves as both Celery broker and result backend.

### Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **APScheduler (in-process)** | No broker needed | Not durable across restarts, no task revocation |
| **Dramatiq + Redis** | Cleaner API than Celery | No built-in ETA/delayed tasks — needs a custom scheduler |
| **arq (async + Redis)** | Native async, lightweight | No task revocation, no beat scheduler |
| **PostgreSQL as Celery broker** | One fewer service | Polling-based, weaker revocation, adds load to app DB |

---

## Architecture

### Process Model

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   FastAPI App    │────▶│   Redis Broker   │◀────│  Celery Worker   │
│  (uvicorn)       │     │   (port 6379)    │     │  (1+ processes)  │
│                  │     │                  │     │                  │
│  Enqueues tasks  │     │  Stores tasks,   │     │  Executes tasks, │
│  via .delay() /  │     │  results, ETAs   │     │  accesses DB     │
│  .apply_async()  │     │                  │     │  directly         │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                                                │
         ▼                                                ▼
┌─────────────────┐                              ┌─────────────────┐
│   PostgreSQL     │◀─────────────────────────────│  Celery Beat     │
│   (port 5432)    │                              │  (scheduler)     │
│                  │                              │  embedded in     │
│  App database    │                              │  worker process  │
└─────────────────┘                              └─────────────────┘
```

- **FastAPI app** enqueues tasks but never executes them. The API response returns immediately.
- **Celery worker** runs in a separate process. It has its own DB sessions — no shared state with the API process except through the database and Redis.
- **Celery Beat** is embedded in the worker process (`--beat` flag) for development. In production, runs as a separate process for reliability.
- **Redis** acts as both broker (task queue) and result backend (task state for revocation).
- **PostgreSQL** is the shared application database, accessed by both the API and worker processes.

### Task ID Convention

Celery task IDs for game timers follow a deterministic pattern so the API can revoke them without storing task IDs in the database:

```
hiding_timer:{game_id}        — hiding -> seeking countdown
answer_deadline:{question_id} — hider answer timeout
```

The `start_game` endpoint schedules `hiding_timer:{game_id}`. The `end_game` endpoint revokes it by reconstructing the ID. No extra database column needed.

### Session Management in Workers

Workers create their own synchronous `Session` for each task — they don't use the FastAPI request-scoped async session. The task opens a session, does its work, commits, and closes. Workers import the same `engine` from `db.py` and use `Session(engine)` directly.

```python
from hideandseek.db import engine

@app.task(bind=True)
def transition_hiding_to_seeking(self, game_id: str) -> None:
    with Session(engine) as session:
        game = session.get(Game, uuid.UUID(game_id))
        if not game or game.status != GameStatus.hiding:
            return  # already transitioned or game ended

        game.status = GameStatus.seeking
        game.seeking_started_at = datetime.now(UTC)
        session.commit()

        # Push notification (sync call from worker)
        tokens = ...  # query device tokens
        push_service.send_to_tokens_sync(tokens, ...)
```

### Push from Workers

The current `PushService.send_to_tokens()` is async (uses `aioapns`). Workers run synchronously. Use `asyncio.run()` to call the async method from the sync worker context. The `aioapns` call is short-lived and doesn't benefit from async concurrency in a single-task worker context. If push delivery needs its own retry policy later, extract to a separate task.

---

## Module Layout

```
server/src/hideandseek/
├── celery_app.py          # Celery app instance, config, autodiscover
├── tasks/
│   ├── __init__.py
│   ├── game_timers.py     # transition_hiding_to_seeking, auto_answer_question
│   └── push.py            # send_critical_push (retry-resilient push delivery)
```

### `celery_app.py`

```python
from celery import Celery

app = Celery('hideandseek')
app.config_from_object('hideandseek.celery_config')
app.autodiscover_tasks(['hideandseek.tasks'])
```

### `celery_config.py`

```python
import os

broker_url = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
result_backend = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'UTC'
enable_utc = True
```

---

## Integration Points

### start_game (router) -> hiding timer

```python
# In routers/games.py, after updating status to hiding:
from hideandseek.tasks.game_timers import transition_hiding_to_seeking

hiding_minutes = game.timing.get('hiding_time_min', 30)
task_id = f'hiding_timer:{game.id}'
transition_hiding_to_seeking.apply_async(
    args=[str(game.id)],
    countdown=hiding_minutes * 60,
    task_id=task_id,
)
```

### end_game (router) -> cancel hiding timer

```python
# In routers/games.py, when ending a game:
from hideandseek.celery_app import app as celery_app

celery_app.control.revoke(f'hiding_timer:{game.id}', terminate=False)
```

### ask_question / lock_in (router) -> answer deadline

```python
# After question becomes answerable:
from hideandseek.tasks.game_timers import auto_answer_question

delay_minutes = game.timing.get('location_question_delay_min', 5)
task_id = f'answer_deadline:{question.id}'
auto_answer_question.apply_async(
    args=[str(question.id)],
    countdown=delay_minutes * 60,
    task_id=task_id,
)
```

### answer_question (router) -> cancel deadline

```python
celery_app.control.revoke(f'answer_deadline:{question.id}', terminate=False)
```

---

## Data Model Changes

### Game Model

Add phase-transition timestamps:

| Field | Type | Notes |
|-------|------|-------|
| `hiding_started_at` | `datetime \| None` | Set when game enters `hiding`. Clients compute countdown: `hiding_started_at + hiding_time_min`. |
| `seeking_started_at` | `datetime \| None` | Set when game enters `seeking`. |

### Question Model

Add answerable timestamp:

| Field | Type | Notes |
|-------|------|-------|
| `answerable_at` | `datetime \| None` | Set when question enters `answerable` status. Clients compute deadline: `answerable_at + location_question_delay_min`. |

### PushEventType Enum

Add new event type:

| Event | When |
|-------|------|
| `question_auto_answered` | Hider didn't answer in time; system answered automatically |

---

## Local Development Setup

### Docker Compose

A `docker-compose.yml` in the repo root launches the full stack:

```yaml
services:
  postgres:
    image: postgres:17-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: hideandseek
      POSTGRES_USER: hideandseek
      POSTGRES_PASSWORD: hideandseek
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  api:
    build: ./server
    command: uvicorn hideandseek.main:app --host 0.0.0.0 --reload
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://hideandseek:hideandseek@postgres:5432/hideandseek
      - CELERY_BROKER_URL=redis://redis:6379/0
    volumes:
      - ./server/src:/app/src
    depends_on:
      - postgres
      - redis

  worker:
    build: ./server
    command: celery -A hideandseek.celery_app worker --loglevel=info --beat
    environment:
      - DATABASE_URL=postgresql://hideandseek:hideandseek@postgres:5432/hideandseek
      - CELERY_BROKER_URL=redis://redis:6379/0
    volumes:
      - ./server/src:/app/src
    depends_on:
      - postgres
      - redis

volumes:
  pgdata:
```

`--beat` flag embeds the beat scheduler in the worker process (fine for single-worker dev).

### Without Docker

```bash
# Requires local PostgreSQL and Redis running

# Terminal 1: API server
DATABASE_URL=postgresql://... uv run uvicorn hideandseek.main:app --reload

# Terminal 2: Celery worker + beat
DATABASE_URL=postgresql://... CELERY_BROKER_URL=redis://localhost:6379/0 \
  uv run celery -A hideandseek.celery_app worker --loglevel=info --beat
```

---

## Testing Strategy

### Unit Tests (no broker)

Task functions are plain Python functions that happen to be decorated with `@app.task`. Test them by calling the function directly (not `.delay()`), with a test DB session:

```python
def test_hiding_to_seeking_transition(session):
    game = create_game(status=GameStatus.hiding, hiding_started_at=...)
    session.commit()

    transition_hiding_to_seeking(str(game.id))

    session.refresh(game)
    assert game.status == GameStatus.seeking
```

No Redis, no worker, no Celery machinery needed.

### Integration Tests (with broker)

For verifying the full enqueue -> execute -> result flow, use `CELERY_ALWAYS_EAGER = True` in test config. This executes tasks synchronously in the calling process.

### Manual Testing

1. `docker compose up`
2. Create a game with `hiding_time_min: 1` (1 minute).
3. Start the game via `POST /games/{id}/start`.
4. Watch the worker logs — after 60 seconds, the transition task fires.
5. `GET /games/{id}` — status should be `seeking`.
6. Verify `phase_changed` push was sent (check push no-op logs).

---

## Implementation Phases

### Phase 1: Foundation (minimum viable background jobs)

- Add `celery` and `redis` dependencies
- Create `celery_app.py`, `celery_config.py`, and `tasks/` package
- Implement `transition_hiding_to_seeking` task
- Add `hiding_started_at`, `seeking_started_at` to Game model
- Wire `start_game` to enqueue the task, `end_game` to revoke it
- Docker Compose with PostgreSQL, Redis, API, and worker
- Update CLAUDE.md

### Phase 2: Question Deadlines

- Implement `auto_answer_question` task
- Add `answerable_at` to Question model
- Wire `ask_question`/`lock_in` to enqueue, `answer_question` to revoke
- Depends on geo math being implemented (the auto-answer needs to compute the actual answer)

### Phase 3: Resilient Push

- Move critical push delivery through the task queue
- Add retry logic with exponential backoff

---

## Scope Boundaries

Explicitly **out of scope**:

- **Rest period enforcement** — pausing/resuming timers at wall-clock boundaries. A future feature once core timers are proven.
- **Stale game cleanup** — periodic housekeeping for abandoned games. Easy to add as a Celery Beat task later.
- **Seeking -> endgame transition** — triggered by proximity detection (geo math), not a timer. Will use the same task infrastructure but the trigger is a location update, not a scheduled delay.
- **Horizontal scaling** — single worker is sufficient for expected game concurrency. Celery supports multiple workers when needed.
- **Monitoring / observability** — Celery Flower or similar dashboards. Worth adding later, not blocking for v1.
