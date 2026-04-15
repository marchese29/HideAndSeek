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
  types.py                 # Enums (GameStatus, PlayerColor, QuestionType, ProximityTier, etc.),
                           #   constants (MAX_PLAYERS), value objects (DistrictClass),
                           #   category classification sets
  geo_types.py             # Custom SQLAlchemy column types (ShapelyGeography, ShapelyGeometry)
  game.py                  # Game, Player
  game_map.py              # GameMap (tentacle_categories JSON column for tentacles config)
  inventory.py             # InventorySlot
  location.py              # LocationUpdate
  map_feature.py           # MapFeature, GameMapFeature
  question.py              # Question
  question_params.py       # RadarParams, ThermometerParams, FeatureQuestionParams, TentacleQuestionParams
  transit.py               # TransitDataset, Stop, Route, RouteStop
  device_token.py          # DeviceToken
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
- No business logic — models define schema only
- Style rules match the server (ruff + pyright, single quotes, 100 char line length)

## Adding a New Model

1. Create `src/hideandseek_models/<model>.py` with `from hideandseek_models.base import Base`
2. Add re-exports to `__init__.py`
3. The server's `db.create_db_and_tables()` imports `hideandseek_models` which registers all tables on `Base.metadata`
