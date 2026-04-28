# Models — hideandseek-models

SQLAlchemy declarative models for the HideAndSeek game. Standalone package with minimal dependencies — no FastAPI, Celery, or server infrastructure.

## Commands

```bash
uv run ruff check .        # Lint
uv run ruff format .       # Format
uv run pyright             # Type check
```

## Package Structure

```
src/hideandseek_models/
  __init__.py              # Re-exports all models, enums, and constants
  base.py                  # DeclarativeBase with StrEnum type annotation map
  types.py                 # Enums (GameStatus, PlayerColor, QuestionType, ProximityTier,
                           #   EndReason, PhotoSubject, PhotoReviewDecision, etc.),
                           #   constants (MAX_PLAYERS), value objects (DistrictClass,
                           #   PhotoSubjectMeta), category classification sets,
                           #   PHOTO_SUBJECT_META + subjects_for_size(size) helper
  geo_types.py             # Custom SQLAlchemy column types (ShapelyGeography, ShapelyGeometry)
  game.py                  # Game (end_reason + found_claim_* for two-party completion),
                           #   Player (Player.freeze_location for endgame freeze mechanic)
  game_map.py              # GameMap (tentacle_categories JSON column for tentacles config)
  inventory.py             # InventorySlot
  location.py              # LocationUpdate
  map_feature.py           # MapFeature, GameMapFeature
  question.py              # Question
  question_params.py       # RadarParams, ThermometerParams, FeatureQuestionParams,
                           #   TentacleQuestionParams, PhotoQuestionParams
  transit.py               # TransitDataset, Stop, Route, RouteStop
  device_token.py          # DeviceToken (token + endpoint_arn for SNS Mobile Push)
```

## Dependencies

Minimal — only what the ORM models need:
- `sqlalchemy` — ORM declarative base, column types, relationships
- `geoalchemy2` — PostGIS column types (Geography, Geometry)
- `shapely` — Python geometry objects (Point, Polygon, MultiPolygon, LineString)
- `pydantic` — `DistrictClass` value object in `types.py`

## Conventions

- Import path: `from hideandseek_models.game import Game` or `from hideandseek_models import Game`
- `from __future__ import annotations` at top of every module
- Cross-model references use `TYPE_CHECKING` imports to avoid circular dependencies
- Enums are `StrEnum` — stored as VARCHAR via `type_annotation_map` on `Base`
- UUIDs for all PKs except `LocationUpdate` (auto-increment int)
- Two spatial column types: `ShapelyGeography` (distance/proximity) and `ShapelyGeometry` (topological). See `geo_types.py`.
- `GameMap.boundary` is `MULTIPOLYGON` — always stored as `MultiPolygon` (single polygons wrapped at creation via `MultiPolygon([polygon])`).
- Enum-value extension caveat: the existing Postgres native enum types (`questiontype`, `questionstatus`, etc.) were created by the initial migration via `sa.Enum(name=...)`. Adding new values to those enums requires `ALTER TYPE ... ADD VALUE` in an `op.get_context().autocommit_block()` (see `alembic/versions/022e24f069e7_*`). New StrEnum fields added since the initial migration store as VARCHAR per `type_annotation_map={StrEnum: String}` — no new native enum types are created going forward.
- Future-deadline columns: live future events use `*_ends_at` / `*_expires_at` / `*_deadline_at` (mutate-while-future, freeze-once-elapsed). Existing `*_started_at` / `*_at` columns stay as immutable audit anchors. See `design/2026-04-25-game-timer-pause.md`.
- No business logic — models define schema only
- Style rules match the server (ruff + pyright, single quotes, 100 char line length)

## Adding a New Model

1. Create `src/hideandseek_models/<model>.py` with `from hideandseek_models.base import Base`
2. Add re-exports to `__init__.py`
3. Alembic's `env.py` imports `hideandseek_models` which registers all tables on `Base.metadata`. Run `uv run alembic revision --autogenerate -m "add <model>"` from the repo root to generate a migration, then review and commit it alongside the model.
