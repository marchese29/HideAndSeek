# Server — FastAPI + UV

Python FastAPI backend for the HideAndSeek game.

## Commands

```bash
uv sync                    # Install/update dependencies
uv run uvicorn hideandseek.main:app --reload  # Run dev server (localhost:8000, SQLite)
uv run pytest              # Run tests (in-memory SQLite)
uv run ruff check .        # Lint
uv run ruff format .       # Format
uv run pyright             # Type check
uv run python scripts/generate_openapi.py     # Regenerate OpenAPI spec

# Docker (from repo root)
docker compose up --build  # Start PostgreSQL + API + Redis + Celery worker (localhost:8000)
docker compose down        # Stop services (data preserved in pgdata volume)
docker compose down -v     # Stop services and wipe database

# Full-fidelity local dev (requires local Redis: brew services start redis)
scripts/dev.sh             # Launches uvicorn + Celery worker together
```

## Running the Server

Three modes — all serve on `localhost:8000`:

| | **Docker (preferred)** | **Local + worker** | **Local bare** |
|---|---|---|---|
| Start | `docker compose up --build` | `scripts/dev.sh` | `uv run uvicorn hideandseek.main:app --reload` |
| Database | PostGIS (PostgreSQL 16) | SQLite + SpatiaLite | SQLite + SpatiaLite |
| Celery | Redis + worker container | Redis + worker process | Auto-detects Redis; eager fallback |
| Timers | Real (countdown delays) | Real (countdown delays) | Real if Redis running; immediate if eager |
| Reset DB | `docker compose down -v` | Delete `server/data/` | Delete `server/data/` |
| `ENV` | `development` | `local` (default) | `local` (default) |

**Local Redis recommended**: `brew install redis && brew services start redis`. Without Redis, the local server falls back to eager mode (tasks fire synchronously, countdown delays are ignored).

In production (`ENV=production`): INFO level, JSON renderer, stderr only.

## Verification

Always verify server changes with **both** automated checks and manual API calls before committing.

1. **Automated**: `uv run pytest && uv run ruff check . && uv run pyright`
2. **Manual**: Prefer Docker (`docker compose up --build`) — it runs PostGIS, Redis, and the Celery worker, matching the eventual production stack. Run `scripts/manual-test.sh` for a full end-to-end game flow (seeds data, exercises all endpoints). For ad-hoc testing, seed test data if the DB is empty, and `curl` new/changed endpoints. Verify happy paths, error responses, and side effects (e.g., push no-op logs, DB records created, timer tasks in worker logs). To reset: `docker compose down -v` (Docker) or delete `server/data/` (local).

Manual testing catches wiring and serialization issues that unit tests miss.

## Project Structure

```
src/hideandseek/
  main.py, db.py, dependencies.py       # App entrypoint, DB engine + session, FastAPI deps
  logging.py, middleware.py              # structlog config, ASGI access log middleware
  validators.py, logic.py, resolution.py # Question lifecycle: validate → orchestrate → resolve
  geo.py, conventions.py, exclusion.py   # Distance math, metric/imperial, exclusion zones
  config.py, push.py, utils.py          # Push config, APNS service, shared utils
  celery_app.py, celery_config.py       # Celery instance + broker config
  models/                               # SQLModel table models (types, geo_types, transit,
                                        #   game_map, map_feature, game, inventory, location,
                                        #   question, question_params, device_token)
  schemas/                              # Pydantic request/response schemas + common utils
  queries/                              # DB query functions by domain (games, maps, questions,
                                        #   location, features, stops, effective_map, device_tokens)
  routers/                              # API routes (games, maps, location, questions, endgame)
  tasks/                                # Celery tasks (game_timers, push)
tests/                                  # pytest (one file per router + features, geo, resolution,
                                        #   exclusion, conventions)
scripts/generate_openapi.py             # OpenAPI spec regeneration
data/                                   # SQLite DB file (gitignored)
```

**Key callouts** (things that aren't obvious from file names):
- `logic.py` is the **conversion boundary** — `to_meters()` before geo math, `from_meters()` after. Also owns endgame functions (`get_endgame_exclusions`, `get_candidate_stations`, `compute_hider_centroid`).
- `exclusion.py` is called from `logic.py`, not from routers. Also has `compute_endgame_exclusions` for hiding zone intersection.
- `resolution.py` owns category classification sets and feature resolution strategy (containment vs nearest).
- `models/__init__.py` re-exports all models — import it to register tables on metadata.
- `celery_app.py` uses an explicit `include` list for task modules (not autodiscover — new task modules must be added manually).
- `queries/stops.py` has PostGIS-only functions (`get_candidate_stations`, `get_nearest_playable_stop`) that don't work with SQLite.

## Architecture Patterns

- **Schema vs Model separation**: SQLModel table models (`models/`) own the DB schema. Pydantic schemas (`schemas/`) control the API surface. Response schemas have `from_model()` static methods for transformation.
- **Dependency injection**: `dependencies.py` provides reusable FastAPI `Depends()` — `get_client_id` (from `X-Client-Id` header), `get_game` (uses `current_session()`, 404 if missing), `get_player_in_game` (composes `get_game` + `get_client_id`, 403 if not found), `get_optional_client_id` (returns `None` when header absent), `get_optional_player_in_game` (returns `None` instead of 403). Dependencies use `current_session()` instead of `Depends(get_session)` — the router-level dependency ensures the ContextVar is already set.
- **Transactional boundaries**: `get_session()` is an async generator that commits once after the handler succeeds and sets a `ContextVar` so query-layer decorators can access the session. Must be async so the ContextVar is set in the event-loop context (sync handler threads copy that context). If the handler raises, commit is never called and `Session.__exit__` rolls back. All writes in a request succeed or fail together.
- **ContextVar session injection**: A `ContextVar[Session]` (`_session_var`) is set by `get_session()` and read by `current_session()`. Query functions declare `session: Session` as their first parameter for explicitness and testability, but callers never pass it — decorators inject it automatically.
- **`@db_read` / `@db_write` decorators**: Applied to all query functions. Both inject session from the ContextVar and strip `Session` from the external signature. `@db_write` additionally flushes the session after the function (making writes visible to subsequent queries in the same request). Typed with PEP 695 generics (`[T, **P]`) via `Concatenate[Session, P]`.
- **Router-level session dependency**: Each router uses `dependencies=[Depends(get_session)]` to ensure the ContextVar is always set for every route. Handlers never declare `session` in their signatures.
- **Query layer**: `queries/` package (one module per domain) handles all DB reads and writes. Routers never call `session.add/commit/refresh` directly. Query functions return SQLModel objects; routers transform them via `from_model()`. Import directly from submodules (e.g., `from hideandseek.queries.games import create_game`), not from the package root. Callers invoke query functions without passing session (e.g., `create_game(map_id=..., ...)`).
- **Background jobs (Celery + Redis)**: All push delivery and game timers go through Celery tasks. Broker resolution: (1) `CELERY_BROKER_URL` env var if set, (2) auto-detect Redis on `localhost:6379`, (3) eager mode (tasks run synchronously in-process). Set `CELERY_BROKER_URL=''` to force eager mode when Redis is running. Routers call `.delay()` or `.apply_async()` instead of `BackgroundTasks`. Worker tasks use `session_scope()` to get a DB session with ContextVar — all `@db_read`/`@db_write` query functions work naturally inside the `with session_scope():` block.
- **Task ID convention**: Deterministic IDs (`hiding_timer:{game_id}`, `answer_deadline:{question_id}`) so the API can revoke tasks without storing IDs in the DB.
- **Push notifications**: `PushService` wraps `aioapns` for APNS delivery. No-ops silently when env vars are missing (dev/test). All push delivery goes through the `send_push` Celery task (with retry). Event types are defined by `PushEventType` enum. See `design/push-notifications.md` for payload specs.
- **Test fixtures**: The `session` fixture sets `_session_var` so direct query calls in tests work without passing session. The `client` fixture's `_override_get_session` also sets the ContextVar so TestClient requests work. Factory functions (`create_transit_dataset`, `create_game_map`, `create_game`, `create_player`, `create_inventory_slot`, `create_map_feature`, `create_game_map_feature`) create test data with sensible defaults and accept `**overrides`. `create_game` automatically creates `InventorySlot` rows from the default template.
- **Structured logging**: All logging uses `structlog`. `setup_logging()` is called in the app lifespan. Two logger namespaces: `hideandseek.access` (request/response, does not propagate to root) and `hideandseek.*` (general app logs, written to stderr). Use `structlog.get_logger(__name__)` to get a logger. Log events use snake_case event names with keyword args for context (e.g., `logger.info('push_noop', event_type=..., game_id=...)`). `AccessLogMiddleware` handles all request/response logging — routers don't need to log requests. Three-tier `ENV`: `local` (default) = DEBUG + console + access file, `development` = DEBUG + console + stderr only, `production` = INFO + JSON + stderr only. `LOG_FORMAT=json` forces JSON in any tier.
- **Geometry — three layers**: Geometry flows through three representations:
  - **API boundary** — GeoJSON via `geojson-pydantic` types (`Point`, `Polygon`, `LineString`). Requests accept GeoJSON; responses return GeoJSON.
  - **Python** — shapely objects (`Point`, `Polygon`, `LineString`). All model attributes, query params, and business logic use shapely. Convert with `shapely.geometry.mapping()` (shapely→GeoJSON) and `shapely.geometry.shape()` (GeoJSON→shapely).
  - **Database** — native spatial columns (PostGIS for Docker/production, SpatiaLite for local/tests). The `ShapelyGeometry(Geometry)` column type in `models/geo_types.py` transparently converts between shapely and WKB — model code never touches WKB directly.

  Routers bridge API↔Python (extract coords from geojson-pydantic, construct shapely). Response schemas bridge Python↔API (`mapping()` in `from_model()` methods). The column type bridges Python↔DB automatically.
- **Question lifecycle layers**: Questions follow a layered pattern: `validators.py` (pure HTTP validation — raises or returns) → `logic.py` (business orchestration — inventory mutation, question creation, answer computation; no HTTP concerns) → `routers/questions.py` (thin HTTP glue — validate, call logic, schedule auto-answer, push, return response). `resolution.py` provides feature resolution strategy (containment vs nearest) used by `logic.py`.
- **Per-type ask endpoints**: Each question type has its own `POST` endpoint (`/questions/radar`, `/questions/thermometer`, `/questions/matching`, `/questions/measuring`). All accept seeker `location` in the request body, which is recorded as a `LocationUpdate` and used directly as the seeker's position. Answer and list endpoints remain unified.
- **Role-gated endpoint split**: Endpoints are split by role (see `design/game-state-split.md`). Principles: role = access control only (determines *whether* you can call an endpoint, never *what* you get back), fixed response shapes (no conditional field nulling), default-deny on shared endpoints. The split:
  - **Shared** (any player): `GET /games/{id}` (slim game state with static inventory template — no IDs, no consumed flags, no `hider_station_id`), `GET /games/{id}/questions` (whitelist summary — no parameters, locations, or geometry).
  - **Hider-only** (403 for seekers): `GET /games/{id}/hider-station` (assigned station UUID), `GET /games/{id}/questions/{qid}` (full question detail minus exclusion geometry).
  - **Seeker-only** (403 for hiders): `GET /games/{id}/exclusions` (per-question exclusion geometry + cumulative total), `GET /games/{id}/endgame-exclusions`, `GET /games/{id}/candidate-stations`.
  - **Write endpoints** (ask/answer/lock-in): return `QuestionDetailResponse` (full detail minus exclusions).
  - Response schemas: `QuestionSummaryResponse` (shared list), `QuestionDetailResponse` (hider detail + write endpoints), `HiderStationResponse`, `ExclusionsResponse`, `StaticInventoryResponse` (replaces old `InventoryResponse`).
- **Relational inventory model**: Game inventory uses proper relational tables instead of JSON:
  - **`InventorySlot`** table: pre-populated from the map's `default_inventory` template at game creation. Slots are consumed by setting `consumed_at` (soft-delete). `Game.inventory_slots` relationship (ordered by `slot_index`).
  - **`CategoryUsage`** table: created when a matching/measuring question is asked. Unique constraint on `(game_id, question_type, category, feature_class)`. `Game.category_usages` relationship.
- **Per-type question parameters**: Question parameters use one-to-one relational tables instead of a JSON column:
  - `RadarParams` (`radius: float`) — one-to-one via `Question.radar_params`
  - `ThermometerParams` (`min_travel: float`) — one-to-one via `Question.thermometer_params`
  - `FeatureQuestionParams` (category, source, `seeker_distance`/`hider_distance`, seeker/hider resolution) — one-to-one via `Question.feature_params`, shared by matching and measuring
  - All distance values are stored in **convention units** (meters for metric maps, miles for imperial). Conversion to meters for geo math happens in `logic.py` via `to_meters()`/`from_meters()`.
  - Seeker resolution fields are **non-optional** — if the seeker's feature can't be resolved, the ask endpoint returns 422. Hider resolution fields are populated at answer time.
- **Question types**: Four types with two inventory models:
  - **Slot-based** (radar, thermometer): consume an `InventorySlot` row. Radar → `answerable` immediately; thermometer → `in_progress` until seeker locks in.
  - **Category-based** (matching, measuring): create a `CategoryUsage` row. Both → `answerable` immediately. Available categories are inclusion-based: derived from map features (via `GameMapFeature`) minus existing `CategoryUsage` rows.
  - **Matching**: resolves each player's nearest feature (or containing feature for `CONTAINMENT_CATEGORIES`); answer is `"yes"` (same `stable_id`), `"no"` (different), or `"null"` (hider unresolvable).
  - **Measuring**: resolves each player's distance to nearest feature; answer is `"closer"` (seeker closer), `"farther"`, or `"null"` (hider unresolvable).
- **Geo math**: `geo.py` provides pure distance functions: `distance(point_a, point_b)` for shapely Points (geodesic via pyproj) and `distance_to_feature(player, geometry)` for distance to any geometry. Answer computation and exclusion zone generation live in `logic.py`, which delegates to `exclusion.py` for the geometry. Each answered question has an `exclusion` (this question's zone) and `total_exclusion` (cumulative union across all answered questions in the game).

## Game States

```
lobby → hiding → seeking → finished
```

The `GameStatus` enum reflects this. The endgame is a client-side lens over the `seeking` phase (see `design/endgame.md`). Games can be ended from any active state (hiding/seeking). Ending a game nulls out the `join_code` to reclaim the namespace.

## Data Model Conventions

- SQLModel for all table models (wraps SQLAlchemy + Pydantic).
- **Do NOT use `from __future__ import annotations` in model files or `db.py`** — it breaks SQLModel relationship resolution and PEP 695 generics. Use quoted string forward references instead (e.g., `game_map: 'GameMap' = Relationship(...)`).
- Geometry uses the three-layer pattern (see Architecture Patterns): GeoJSON at API, shapely in Python, native spatial in DB. System dep: `brew install libspatialite` (auto-detected; `SPATIALITE_LIBRARY_PATH` override if non-standard).
- Value objects (TimingRules, etc.) stored as JSON columns on their parent table. Game inventory and question parameters use proper relational tables (see Architecture Patterns).
- UUIDs for all PKs except `LocationUpdate` (auto-increment int).
- Relationships use bottom-of-file imports and quoted forward references to avoid circular dependencies.
- Enums are `StrEnum` — stored as VARCHAR, human-readable in DB.
- **Active development — no migration or backwards-compatibility concerns.** There is no production data. Schema changes go directly in the models and `create_all` recreates tables on startup. To reset: delete `server/data/` (local SQLite) or `docker compose down -v` (Docker PostgreSQL). Alembic will be added when the schema stabilizes and real data exists.
- Tests use in-memory SQLite + SpatiaLite with `StaticPool` via the `session` and `client` fixtures in `conftest.py`. Requires `SPATIALITE_LIBRARY_PATH` env var.

## Conventions

- Manage dependencies with `uv add <package>` and `uv remove <package>`. Never edit the dependency lists in `pyproject.toml` by hand.
- All routes go in `routers/` and are included via `app.include_router()`.
- Tests use `fastapi.testclient.TestClient` via the `client` fixture from `conftest.py`.
- OpenAPI spec is auto-generated — add routes to FastAPI, not the YAML file.
- Client identity is via `X-Client-Id` header (UUID). No authentication.
- Only one unanswered question allowed at a time per game.
- `join_code` is nullable — nulled out when the game ends to prevent namespace exhaustion.
- Pagination uses offset/limit query params (`schemas/common.py`).
- `device_token` is required on `POST /games/join`, optional on `POST /games`. Device tokens are upserted by `client_id` (separate `DeviceToken` table).
- Push notification env vars: `APNS_KEY_PATH`, `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_TOPIC`, `APNS_USE_SANDBOX`. All optional — when missing, PushService runs in no-op mode.
- Database env vars: `DATABASE_URL` (default: SQLite at `server/data/hideandseek.db`). Docker Compose sets `postgresql+psycopg://...`.
- Celery env vars: `CELERY_BROKER_URL` (auto-detects `redis://localhost:6379/0` when unset; set to empty string to force eager mode). Docker Compose sets `redis://redis:6379/0`. `CELERY_RESULT_BACKEND` (default: same as broker URL).
- Logging env vars: `ENV` (`local`/`development`/`production`, default `local`), `LOG_FORMAT` (`json` to force JSON output). Use `structlog.get_logger(__name__)` for all new loggers — never use stdlib `logging.getLogger()` directly.

## Style

Enforced by ruff (lint + format) and pyright (type checking). The pre-commit hook runs all checks automatically.

- Single quotes for strings.
- `from __future__ import annotations` at the top of every module **except** SQLModel table model files and `db.py` (which use PEP 695 generics).
- All imports at the top of the file, never inline.
- Type annotations required on all function arguments and return types (except `-> None`).
- Max line length: 100 characters.
- Lint rules: pyflakes, pycodestyle, isort, pyupgrade, flake8-bugbear, flake8-simplify, flake8-future-annotations, flake8-annotations, flake8-datetimez.
- B008 exemption for FastAPI's `Depends`, `Header`, `Path`, `Query`, `Body` (configured in `pyproject.toml`).
- SQLModel/pyright `type: ignore` comments on `.join()`, `.order_by()`, `.group_by()` clauses (known SQLAlchemy typing gaps).
- Celery `type: ignore[attr-defined]` on `.delay()` and `.apply_async()` calls (Celery task decorator adds these dynamically).
- pyright in `standard` mode.
