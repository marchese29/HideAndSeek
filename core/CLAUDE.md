# Core — Shared Business Logic

Shared business logic for the HideAndSeek game. Sits between `hideandseek-models` (ORM) and `hideandseek` (server/presentation). Contains no HTTP code, no event emission, no response schemas.

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
  celery_app.py        # Celery application instance
  celery_config.py     # Celery broker/result backend config
  redis_client.py      # Redis client factory (sync + async)
  geo.py               # Pure geodesic distance functions (pyproj)
  geo_helpers.py       # Shapely-to-GeoJSON conversion helpers
  conventions.py       # Metric/imperial conversion, default inventory
  exclusion.py         # Exclusion zone geometry, boundary computation
  queries/             # DB query functions by domain
  logic/               # Business logic (session-free, side-effect-free beyond DB)
```

## Architecture Rules

- **No events, no HTTP**: Core never imports from `hideandseek.broadcast`, `hideandseek.schemas`, `hideandseek.routers`, or `hideandseek.tasks`. It returns results; the caller decides what events to emit.
- **Dependency direction**: `hideandseek-models` ← `hideandseek-core` ← `hideandseek` (server). Core never imports from server.
- **Logic layer is the conversion boundary**: `to_meters()` before geo math, `from_meters()` after. Logic functions use `db.register()` for new objects and mutate tracked ORM objects directly.
- **ContextVar session access**: Query functions call `db.get_session()` — no session parameters, no decorators.

## Conventions

- Same style as server: single quotes, `from __future__ import annotations`, ruff + pyright.
- Import from submodules directly (e.g., `from hideandseek_core.queries.games import ...`).
