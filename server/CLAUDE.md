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
docker compose up --build  # Start PostgreSQL + API server (localhost:8000)
docker compose down        # Stop services (data preserved in pgdata volume)
docker compose down -v     # Stop services and wipe database
```

## Running the Server

Two modes — both serve on `localhost:8000`:

| | **Local (SQLite)** | **Docker (PostgreSQL)** |
|---|---|---|
| Start | `uv run uvicorn hideandseek.main:app --reload` | `docker compose up --build` (from repo root) |
| Database | SQLite at `server/data/hideandseek.db` | PostgreSQL 17 in container |
| `ENV` | `local` (default) | `development` (set in compose) |
| Log level | DEBUG, console renderer | DEBUG, console renderer |
| Access logs | `server/logs/access.log` + stderr | stderr only |
| Reset DB | Delete `server/data/` directory | `docker compose down -v` |

In production (`ENV=production`): INFO level, JSON renderer, stderr only.

## Verification

Always verify server changes with **both** automated checks and manual API calls before committing.

1. **Automated**: `uv run pytest && uv run ruff check . && uv run pyright`
2. **Manual**: Start the server (either local or Docker), seed test data if the DB is empty, and `curl` new/changed endpoints. Verify happy paths, error responses, and side effects (e.g., push no-op logs, DB records created). To reset: delete `server/data/` (local) or `docker compose down -v` (Docker).

Manual testing catches wiring and serialization issues that unit tests miss.

## Project Structure

- `src/hideandseek/main.py` — FastAPI app entrypoint with lifespan (sets up logging, creates DB, initializes PushService)
- `src/hideandseek/logging.py` — Centralized structlog configuration (`setup_logging()`). Configures two logger namespaces: `hideandseek.access` (request/response) and root (general app → stderr). Three-tier `ENV`: `local` (default, file+stderr, console), `development` (stderr only, console), `production` (stderr only, JSON).
- `src/hideandseek/middleware.py` — Raw ASGI `AccessLogMiddleware` for structured request/response logging. Logs method, path, headers (sensitive values redacted), request body (truncated at 1KB), status, duration, response size. Generates `request_id` UUID per request (bound to structlog contextvars, returned in `X-Request-ID` response header). Skips `/health`.
- `src/hideandseek/db.py` — Database engine (`DATABASE_URL` env var, defaults to SQLite), `create_db_and_tables()`, `get_session()` (commit-at-boundary + ContextVar), `current_session()`, `@db_read`/`@db_write` decorators
- `Dockerfile` — Multi-stage build using `uv` image (Python 3.12, bookworm-slim)
- `src/hideandseek/utils.py` — Shared utilities (`find_server_root()` — walks up to `pyproject.toml`)
- `src/hideandseek/config.py` — `PushConfig` dataclass and `load_push_config()` from env vars
- `src/hideandseek/push.py` — `PushService` class wrapping `aioapns` (no-ops when unconfigured)
- `src/hideandseek/models/` — SQLModel table models and types
  - `types.py` — StrEnums (`GameStatus`, `PlayerRole`, `PushEventType`, etc.), GeoJSON Pydantic types, value objects
  - `transit.py` — `TransitDataset`, `Stop`, `Route`, `RouteStop`
  - `game_map.py` — `GameMap`
  - `game.py` — `Game`, `Player`
  - `location.py` — `LocationUpdate`
  - `question.py` — `Question`
  - `device_token.py` — `DeviceToken` (maps `client_id` → APNS token)
  - `__init__.py` — Re-exports all models (import this to register tables on metadata)
- `src/hideandseek/schemas/` — Request/response Pydantic schemas (separate from DB models)
  - `request.py` — Request body schemas (`CreateGameRequest`, `JoinGameRequest`, etc.)
  - `response.py` — Response schemas with `from_model()` static methods for DB→API transformation
  - `common.py` — Shared utilities (pagination params)
- `src/hideandseek/dependencies.py` — Shared FastAPI dependencies (`get_client_id`, `get_game`, `get_player_in_game`, `get_push_service`)
- `src/hideandseek/queries/` — Database query/mutation functions, split by domain
  - `device_tokens.py` — `upsert_device_token`, `get_device_tokens_for_game`, `delete_device_token`
  - `maps.py` — `list_maps`, `get_map`
  - `games.py` — `generate_join_code`, `create_game`, `find_game_by_join_code`, `add_player`, `get_player`, `update_player`, `update_game_status`
  - `effective_map.py` — `get_effective_map_data`, `RouteWithStops`, `EffectiveMapData` dataclasses
  - `location.py` — `create_location_update`, `get_visible_players`, `get_location_history`, `get_latest_location_for_player`, `get_avg_seeker_location`, `VisiblePlayerData` dataclass
  - `questions.py` — `has_unanswered_question`, `get_question_count`, `create_question`, `get_question`, `list_questions`, `update_question`, `update_game_inventory`
- `src/hideandseek/routers/` — API route modules
  - `maps.py` — `GET /maps`, `GET /maps/{map_id}`
  - `games.py` — `POST /games`, `POST /games/join`, `GET /games/{game_id}`, `PATCH .../players/{player_id}`, `POST .../start`, `POST .../end`, `GET .../map`
  - `location.py` — `POST .../location`, `GET .../location-history`
  - `questions.py` — `POST .../questions`, `POST .../questions/{id}/lock-in`, `GET .../questions/{id}/preview`, `POST .../questions/{id}/answer`, `GET .../questions`
- `tests/conftest.py` — In-memory SQLite fixtures (`session`, `client`) and factory functions
- `tests/` — pytest tests (one file per router: `test_maps.py`, `test_games.py`, `test_location.py`, `test_questions.py`, `test_push.py`)
- `scripts/generate_openapi.py` — dumps `app.openapi()` to `openapi/openapi.yaml`
- `data/` — SQLite database file (gitignored)

## Architecture Patterns

- **Schema vs Model separation**: SQLModel table models (`models/`) own the DB schema. Pydantic schemas (`schemas/`) control the API surface. Response schemas have `from_model()` static methods for transformation.
- **Dependency injection**: `dependencies.py` provides reusable FastAPI `Depends()` — `get_client_id` (from `X-Client-Id` header), `get_game` (uses `current_session()`, 404 if missing), `get_player_in_game` (composes `get_game` + `get_client_id`, 403 if not found), `get_push_service` (from `app.state`). Dependencies use `current_session()` instead of `Depends(get_session)` — the router-level dependency ensures the ContextVar is already set.
- **Transactional boundaries**: `get_session()` is an async generator that commits once after the handler succeeds and sets a `ContextVar` so query-layer decorators can access the session. Must be async so the ContextVar is set in the event-loop context (sync handler threads copy that context). If the handler raises, commit is never called and `Session.__exit__` rolls back. All writes in a request succeed or fail together.
- **ContextVar session injection**: A `ContextVar[Session]` (`_session_var`) is set by `get_session()` and read by `current_session()`. Query functions declare `session: Session` as their first parameter for explicitness and testability, but callers never pass it — decorators inject it automatically.
- **`@db_read` / `@db_write` decorators**: Applied to all query functions. Both inject session from the ContextVar and strip `Session` from the external signature. `@db_write` additionally flushes the session after the function (making writes visible to subsequent queries in the same request). Typed with PEP 695 generics (`[T, **P]`) via `Concatenate[Session, P]`.
- **Router-level session dependency**: Each router uses `dependencies=[Depends(get_session)]` to ensure the ContextVar is always set for every route. Handlers never declare `session` in their signatures.
- **Query layer**: `queries/` package (one module per domain) handles all DB reads and writes. Routers never call `session.add/commit/refresh` directly. Query functions return SQLModel objects; routers transform them via `from_model()`. Import directly from submodules (e.g., `from hideandseek.queries.games import create_game`), not from the package root. Callers invoke query functions without passing session (e.g., `create_game(map_id=..., ...)`).
- **Push notifications**: `PushService` wraps `aioapns` for APNS delivery. No-ops silently when env vars are missing (dev/test). Routers resolve device tokens while the session is alive, then dispatch `push.send_to_tokens()` via `BackgroundTasks` (fire-and-forget). Event types are defined by `PushEventType` enum. See `design/push-notifications.md` for payload specs.
- **Test fixtures**: The `session` fixture sets `_session_var` so direct query calls in tests work without passing session. The `client` fixture's `_override_get_session` also sets the ContextVar so TestClient requests work. Factory functions (`create_transit_dataset`, `create_game_map`, `create_game`, `create_player`) create test data with sensible defaults and accept `**overrides`.
- **Structured logging**: All logging uses `structlog`. `setup_logging()` is called in the app lifespan. Two logger namespaces: `hideandseek.access` (request/response, does not propagate to root) and `hideandseek.*` (general app logs, written to stderr). Use `structlog.get_logger(__name__)` to get a logger. Log events use snake_case event names with keyword args for context (e.g., `logger.info('push_noop', event_type=..., game_id=...)`). `AccessLogMiddleware` handles all request/response logging — routers don't need to log requests. Three-tier `ENV`: `local` (default) = DEBUG + console + access file, `development` = DEBUG + console + stderr only, `production` = INFO + JSON + stderr only. `LOG_FORMAT=json` forces JSON in any tier.
- **Geo math deferred**: Question answer computation and exclusion zone geometry are stubbed (`answer: "pending"`, `exclusion: null`). A future `geo.py` module will implement haversine distance, radar circles, and thermometer half-planes.

## Game States

```
lobby → hiding → seeking → endgame → finished
```

The `GameStatus` enum reflects this. Games can be ended from any active state (hiding/seeking/endgame). Ending a game nulls out the `join_code` to reclaim the namespace.

## Data Model Conventions

- SQLModel for all table models (wraps SQLAlchemy + Pydantic).
- **Do NOT use `from __future__ import annotations` in model files or `db.py`** — it breaks SQLModel relationship resolution and PEP 695 generics. Use quoted string forward references instead (e.g., `game_map: 'GameMap' = Relationship(...)`).
- GeoJSON geometry stored as JSON columns (`sa_type=sa.JSON`). Use `GeoPoint`, `GeoLineString`, `GeoPolygon` Pydantic types for API validation.
- Value objects (TimingRules, QuestionInventory, etc.) stored as JSON columns on their parent table.
- UUIDs for all PKs except `LocationUpdate` (auto-increment int).
- Relationships use bottom-of-file imports and quoted forward references to avoid circular dependencies.
- Enums are `StrEnum` — stored as VARCHAR, human-readable in DB.
- **Active development — no migration or backwards-compatibility concerns.** There is no production data. Schema changes go directly in the models and `create_all` recreates tables on startup. To reset: delete `server/data/` (local SQLite) or `docker compose down -v` (Docker PostgreSQL). Alembic will be added when the schema stabilizes and real data exists.
- Tests use in-memory SQLite with `StaticPool` via the `session` and `client` fixtures in `conftest.py`.

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
- pyright in `standard` mode.
