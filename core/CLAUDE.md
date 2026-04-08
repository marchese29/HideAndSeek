# Core — Shared Business Logic

Shared business logic for the HideAndSeek game. Sits between `hideandseek-models` (ORM) and both `hideandseek-worker` (Celery tasks) and `hideandseek` (server/presentation). Contains no HTTP code, no response schemas, and no Celery tasks. Owns gameplay event production and Redis publishing; lobby presentation (Pydantic schemas, SSE subscriptions) stays in server.

## Commands

```bash
uv run ruff check .        # Lint
uv run ruff format .       # Format
uv run pyright             # Type check
```

No tests — core is exercised by the server test suite (`cd server && uv run pytest`).

## Package Structure

```
src/hideandseek_core/
  db.py                # Engine factory, session ContextVar, register(), session_scope()
  config.py            # Push config (APNs + FCM), env-var loading
  push.py              # PushService, ApnsProvider, FcmProvider
  redis_client.py      # Redis client factory (sync + async)
  geo.py               # Pure geodesic distance functions (pyproj)
  geo_helpers.py       # Shapely-to-GeoJSON conversion helpers
  conventions.py       # Metric/imperial conversion, default inventory
  exclusion.py         # Exclusion zone geometry, boundary computation
  broadcast/           # Gameplay event production + Redis publishing
    events.py          # Typed gameplay event dataclasses (frozen, slots)
    emit.py            # publish_sse(), channel helpers, emit_gameplay()
  queries/             # DB query functions by domain
  logic/               # Business logic (session-free, side-effect-free beyond DB)
```

## Architecture Rules

- **Gameplay events live here, lobby events live in server**: Core defines gameplay event dataclasses and publishes them to Redis SSE channels via `emit_gameplay()`. Server defines lobby event dataclasses and publishes them via its own `emit()`, which imports `publish_sse` from core. SSE subscription streams and Pydantic game-state snapshots stay in server.
- **No HTTP, no Celery**: Core never imports from `hideandseek.schemas`, `hideandseek.routers`, `hideandseek_worker`, or Celery. It does not use Pydantic response schemas.
- **Dependency direction**: `hideandseek-models` ← `hideandseek-core` ← `hideandseek-worker` / `hideandseek` (server). Core never imports from worker or server.
- **Logic layer is the conversion boundary**: `to_meters()` before geo math, `from_meters()` after. Logic functions use `db.register()` for new objects and mutate tracked ORM objects directly.
- **ContextVar session access**: Query functions call `db.get_session()` — no session parameters, no decorators.

## Broadcast

`broadcast/events.py` defines frozen dataclasses for all gameplay events (question asked/answered/vetoed/abandoned, phase changes, station elections, player locations, player left, host changed, game dissolved). Each question event has a `from_question()` static constructor. `QuestionAskedEvent.from_question()` and `QuestionAnswerableEvent.from_question()` require `base_question_delay_min` kwarg to compute `question_deadline`. Parameter dataclasses (`RadarEventParams`, `ThermometerEventParams`, `FeatureEventParams`) carry type-specific question parameters.

`broadcast/emit.py` provides:
- `publish_sse(channel, event_type, data, *, required)` — low-level Redis publish (used by both core's `emit_gameplay` and server's lobby `emit`)
- `lobby_channel(game_id)`, `hider_channel(game_id)`, `seeker_channel(game_id)` — channel name helpers (used by server's subscribe module)
- `emit_gameplay(event)` — pattern-matches on gameplay event type, serializes to dicts, publishes to the appropriate Redis channels

## Conventions

- Same style as server: single quotes, `from __future__ import annotations`, ruff + pyright.
- Import from submodules directly (e.g., `from hideandseek_core.queries.games import ...`).
