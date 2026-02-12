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
- `src/hideandseek/routers/` — API route modules
- `tests/conftest.py` — In-memory SQLite fixtures (`session`, `client`)
- `tests/` — pytest tests (use `httpx` / `TestClient`)
- `scripts/generate_openapi.py` — dumps `app.openapi()` to `openapi/openapi.yaml`
- `data/` — SQLite database file (gitignored)

## Data Model Conventions

- SQLModel for all table models (wraps SQLAlchemy + Pydantic).
- GeoJSON geometry stored as JSON columns (`sa_type=sa.JSON`). Use `GeoPoint`, `GeoLineString`, `GeoPolygon` Pydantic types for API validation.
- Value objects (TimingRules, QuestionInventory, etc.) stored as JSON columns on their parent table.
- UUIDs for all PKs except `LocationUpdate` (auto-increment int).
- Relationships use bottom-of-file imports to avoid circular dependencies.
- Enums are `StrEnum` — stored as VARCHAR, human-readable in DB.
- **Active development — no migration or backwards-compatibility concerns.** There is no production data. Schema changes go directly in the models and `create_all` recreates tables on startup. Delete the local `data/` directory if the schema changes. Alembic will be added when the schema stabilizes and real data exists.
- Tests use in-memory SQLite with `StaticPool` via the `session` and `client` fixtures in `conftest.py`.

## Conventions

- Manage dependencies with `uv add <package>` and `uv remove <package>`. Never edit the dependency lists in `pyproject.toml` by hand.
- All routes go in `routers/` and are included via `app.include_router()`.
- Tests use `fastapi.testclient.TestClient` via the `client` fixture from `conftest.py`.
- OpenAPI spec is auto-generated — add routes to FastAPI, not the YAML file.

## Style

Enforced by ruff (lint + format) and pyright (type checking). The pre-commit hook runs all checks automatically.

- Single quotes for strings.
- `from __future__ import annotations` at the top of every module.
- All imports at the top of the file, never inline.
- Type annotations required on all function arguments and return types (except `-> None`).
- Max line length: 100 characters.
- Lint rules: pyflakes, pycodestyle, isort, pyupgrade, flake8-bugbear, flake8-simplify, flake8-future-annotations, flake8-annotations.
- pyright in `standard` mode.
