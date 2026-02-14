# Server — FastAPI + UV

Python FastAPI backend for the HideAndSeek game.

## Commands

```bash
uv sync                    # Install/update dependencies
uv run uvicorn hideandseek.main:app --reload  # Run dev server (localhost:8000)
uv run pytest              # Run tests
uv run ruff check .        # Lint
uv run ruff format .       # Format
uv run pyright             # Type check
uv run python scripts/generate_openapi.py     # Regenerate OpenAPI spec
```

## Project Structure

- `src/hideandseek/main.py` — FastAPI app entrypoint with lifespan (creates DB on startup)
- `src/hideandseek/db.py` — SQLite engine, `create_db_and_tables()`, `get_session()` dependency
- `src/hideandseek/models/` — SQLModel table models and types
  - `types.py` — StrEnums (`GameStatus`, `PlayerRole`, etc.), GeoJSON Pydantic types, value objects
  - `transit.py` — `TransitDataset`, `Stop`, `Route`, `RouteStop`
  - `game_map.py` — `GameMap`
  - `game.py` — `Game`, `Player`
  - `location.py` — `LocationUpdate`
  - `question.py` — `Question`
  - `__init__.py` — Re-exports all models (import this to register tables on metadata)
- `src/hideandseek/schemas/` — Request/response Pydantic schemas (separate from DB models)
  - `request.py` — Request body schemas (`CreateGameRequest`, `JoinGameRequest`, etc.)
  - `response.py` — Response schemas with `from_model()` static methods for DB→API transformation
  - `common.py` — Shared utilities (pagination params)
- `src/hideandseek/dependencies.py` — Shared FastAPI dependencies (`get_client_id`, `get_game`, `get_player_in_game`)
- `src/hideandseek/queries.py` — Database query/mutation functions (return SQLModel objects, handle commit/refresh)
- `src/hideandseek/routers/` — API route modules
  - `maps.py` — `GET /maps`, `GET /maps/{map_id}`
  - `games.py` — `POST /games`, `POST /games/join`, `GET /games/{game_id}`, `PATCH .../players/{player_id}`, `POST .../start`, `POST .../end`, `GET .../map`
  - `location.py` — `POST .../location`, `GET .../location-history`
  - `questions.py` — `POST .../questions`, `POST .../questions/{id}/lock-in`, `GET .../questions/{id}/preview`, `POST .../questions/{id}/answer`, `GET .../questions`
- `tests/conftest.py` — In-memory SQLite fixtures (`session`, `client`) and factory functions
- `tests/` — pytest tests (one file per router: `test_maps.py`, `test_games.py`, `test_location.py`, `test_questions.py`)
- `scripts/generate_openapi.py` — dumps `app.openapi()` to `openapi/openapi.yaml`
- `data/` — SQLite database file (gitignored)

## Architecture Patterns

- **Schema vs Model separation**: SQLModel table models (`models/`) own the DB schema. Pydantic schemas (`schemas/`) control the API surface. Response schemas have `from_model()` static methods for transformation.
- **Dependency injection**: `dependencies.py` provides reusable FastAPI `Depends()` — `get_client_id` (from `X-Client-Id` header), `get_game` (404 if missing), `get_player_in_game` (composes `get_game` + `get_client_id`, 403 if not found).
- **Query layer**: `queries.py` handles all DB reads and writes. Routers never call `session.add/commit/refresh` directly. Query functions return SQLModel objects; routers transform them via `from_model()`.
- **Test factories**: `conftest.py` has factory functions (`create_transit_dataset`, `create_game_map`, `create_game`, `create_player`) that create test data with sensible defaults and accept `**overrides`.
- **Geo math deferred**: Question answer computation and exclusion zone geometry are stubbed (`answer: "pending"`, `exclusion: null`). A future `geo.py` module will implement haversine distance, radar circles, and thermometer half-planes.

## Game States

```
lobby → hiding → seeking → endgame → finished
```

The `GameStatus` enum reflects this. Games can be ended from any active state (hiding/seeking/endgame). Ending a game nulls out the `join_code` to reclaim the namespace.

## Data Model Conventions

- SQLModel for all table models (wraps SQLAlchemy + Pydantic).
- **Do NOT use `from __future__ import annotations` in model files** — it breaks SQLModel relationship resolution. Use quoted string forward references instead (e.g., `game_map: 'GameMap' = Relationship(...)`).
- GeoJSON geometry stored as JSON columns (`sa_type=sa.JSON`). Use `GeoPoint`, `GeoLineString`, `GeoPolygon` Pydantic types for API validation.
- Value objects (TimingRules, QuestionInventory, etc.) stored as JSON columns on their parent table.
- UUIDs for all PKs except `LocationUpdate` (auto-increment int).
- Relationships use bottom-of-file imports and quoted forward references to avoid circular dependencies.
- Enums are `StrEnum` — stored as VARCHAR, human-readable in DB.
- **Active development — no migration or backwards-compatibility concerns.** There is no production data. Schema changes go directly in the models and `create_all` recreates tables on startup. Delete the local `data/` directory if the schema changes. Alembic will be added when the schema stabilizes and real data exists.
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

## Style

Enforced by ruff (lint + format) and pyright (type checking). The pre-commit hook runs all checks automatically.

- Single quotes for strings.
- `from __future__ import annotations` at the top of every module **except** SQLModel table model files.
- All imports at the top of the file, never inline.
- Type annotations required on all function arguments and return types (except `-> None`).
- Max line length: 100 characters.
- Lint rules: pyflakes, pycodestyle, isort, pyupgrade, flake8-bugbear, flake8-simplify, flake8-future-annotations, flake8-annotations, flake8-datetimez.
- B008 exemption for FastAPI's `Depends`, `Header`, `Path`, `Query`, `Body` (configured in `pyproject.toml`).
- SQLModel/pyright `type: ignore` comments on `.join()`, `.order_by()`, `.group_by()` clauses (known SQLAlchemy typing gaps).
- pyright in `standard` mode.
