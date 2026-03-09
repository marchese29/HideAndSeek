# Server — FastAPI + UV

Python FastAPI backend for the HideAndSeek game.

## Commands

```bash
uv sync                    # Install/update dependencies
uv run pytest              # Run tests (requires Docker — testcontainers spins up PostGIS)
uv run ruff check .        # Lint
uv run ruff format .       # Format
uv run pyright             # Type check
uv run python scripts/generate_openapi.py     # Regenerate OpenAPI spec
uv run python scripts/import_seattle_gtfs.py  # Import Seattle transit data from GTFS
uv run python scripts/seed_seattle_map.py    # Seed Seattle GameMap (requires GTFS import first)

# Docker (from repo root)
docker compose up --build  # Start PostgreSQL + API + Redis + Celery worker (localhost:8000)
docker compose down        # Stop services (data preserved in pgdata volume)
docker compose down -v     # Stop services and wipe database

# Local dev (requires: docker compose up -d postgres redis)
scripts/dev.sh             # Launches uvicorn + Celery worker together
```

## Running the Server

Two modes — both serve on `localhost:8000`, both use PostgreSQL:

| | **Docker (preferred)** | **Local + worker** |
|---|---|---|
| Start | `docker compose up --build` | `docker compose up -d postgres redis` then `scripts/dev.sh` |
| Database | PostGIS (PostgreSQL 16) | PostGIS via docker-compose |
| Celery | Redis + worker container | Redis via docker-compose + worker process |
| Timers | Real (countdown delays) | Real (countdown delays) |
| Reset DB | `docker compose down -v` | `docker compose down -v` |
| `ENV` | `development` | `local` (default) |

In production (`ENV=production`): INFO level, JSON renderer, stderr only.

## Verification

Always verify server changes with **both** automated checks and manual API calls before committing.

1. **Automated**: `uv run pytest && uv run ruff check . && uv run pyright`
2. **Manual**: Prefer Docker (`docker compose up --build`) — it runs PostGIS, Redis, and the Celery worker, matching production. Run `scripts/manual-test.sh` for a full end-to-end game flow (seeds data, exercises all endpoints). For ad-hoc testing, seed test data if the DB is empty, and `curl` new/changed endpoints. Verify happy paths, error responses, and side effects (e.g., push no-op logs, DB records created, timer tasks in worker logs). To reset: `docker compose down -v`.

Manual testing catches wiring and serialization issues that unit tests miss.

## Simulating a Game (curl)

Use Docker for game simulation — it runs real Celery timers (hiding→seeking transitions, auto-answer deadlines). Seed data first:

```bash
docker compose down -v && docker compose up --build -d
DATABASE_URL="postgresql+psycopg://hideandseek:hideandseek@localhost:5432/hideandseek" \
  uv run python scripts/import_seattle_gtfs.py
DATABASE_URL="postgresql+psycopg://hideandseek:hideandseek@localhost:5432/hideandseek" \
  uv run python scripts/seed_seattle_map.py
```

After seeding, restart the API so it picks up the new data: `docker compose restart api`.

### Game lifecycle

```bash
MAP_ID="<from GET /maps>"
HOST="aaaaaaaa-0000-0000-0000-000000000001"
HIDER="aaaaaaaa-0000-0000-0000-000000000002"
SEEKER="aaaaaaaa-0000-0000-0000-000000000003"

# 1. Create game (host is automatically the first player)
curl -s -X POST localhost:8000/games \
  -H "Content-Type: application/json" -H "X-Client-Id: $HOST" \
  -d "{\"map_id\": \"$MAP_ID\", \"name\": \"HostName\"}"
# → returns JoinGameResponse: game state under ['game'], host player_id at ['player_id']
# → host gets server-assigned color (red, blue, green, ...)

# 2. Join as hider and seeker (no color field — server assigns unique colors)
curl -s -X POST localhost:8000/games/join \
  -H "Content-Type: application/json" -H "X-Client-Id: $HIDER" \
  -d '{"join_code": "XXXX", "role": "hider", "name": "Alice", "device_token": "fake-hider"}'
curl -s -X POST localhost:8000/games/join \
  -H "Content-Type: application/json" -H "X-Client-Id: $SEEKER" \
  -d '{"join_code": "XXXX", "role": "seeker", "name": "Bob", "device_token": "fake-seeker"}'

# 3. Remove a player (self-leave or host-kick — lobby only)
curl -s -X DELETE localhost:8000/games/<game_id>/players/<player_id> \
  -H "X-Client-Id: $HOST"
# → 204 (player removed). Non-host can only remove themselves.
# Host leaving with others: include body {"new_host_id": "<player_uuid>"}
# Host leaving as sole player: game status → "dissolved"

# 4. Optionally tweak timing for fast testing
docker exec hideandseek-postgres-1 psql -U hideandseek -c \
  "UPDATE game SET hiding_time_min = 1, base_question_delay_min = 1
   WHERE id = '<game_id>';"

# 4. Start game (host-only — transitions to "hiding", schedules hiding→seeking timer)
curl -s -X POST localhost:8000/games/<game_id>/start \
  -H "X-Client-Id: $HOST"

# 5. Report hider locations during hiding phase
curl -s -X POST localhost:8000/games/<game_id>/location \
  -H "Content-Type: application/json" -H "X-Client-Id: $HIDER" \
  -d '{"coordinates": {"type": "Point", "coordinates": [<lon>, <lat>]}, "timestamp": "<ISO8601>"}'
# The hider's last location when hiding ends determines their assigned station.

# 5b. (Optional) Elect station during hiding — locks in the hider's station early
curl -s -X POST localhost:8000/games/<game_id>/hider-station \
  -H "Content-Type: application/json" -H "X-Client-Id: $HIDER" \
  -d '{"station_id": "<stop_uuid>", "location": {"type": "Point", "coordinates": [<lon>, <lat>]}}'
# → Returns hiding zone polygon. Station is now locked in.

# 5c. Query nearby stations to find candidates for election
curl -s "localhost:8000/games/<game_id>/nearby-stations?lat=<lat>&lng=<lon>" \
  -H "X-Client-Id: $HIDER"

# 6. Wait for hiding timer (check: docker logs hideandseek-worker-1 | grep transition)
#    Game auto-transitions to "seeking". If no election:
#    - 1 valid candidate → auto_assigned
#    - 0 or 2+ candidates → ambiguous (hider must elect via POST /hider-station)

# 7. Report seeker location (required before asking questions)
curl -s -X POST localhost:8000/games/<game_id>/location \
  -H "Content-Type: application/json" -H "X-Client-Id: $SEEKER" \
  -d '{"coordinates": {"type": "Point", "coordinates": [<lon>, <lat>]}, "timestamp": "<ISO8601>"}'
```

### Radar question

```bash
# Ask (seeker). Slots are re-askable (ask_count increments each time).
# Inventory: [0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0, custom] (imperial/medium)
# For the custom slot (distance=null), pass custom_distance in the request.
curl -s -X POST localhost:8000/games/<game_id>/questions/radar \
  -H "Content-Type: application/json" -H "X-Client-Id: $SEEKER" \
  -d '{"location": {"type": "Point", "coordinates": [<lon>, <lat>]}, "slot_index": <N>}'
# For custom slot: "slot_index": 9, "custom_distance": 3.0
# → status: "answerable", schedules auto-answer timer (location_question_delay_min)

# Answer (hider) — uses hider's latest reported location
curl -s -X POST localhost:8000/games/<game_id>/questions/<question_id>/answer \
  -H "X-Client-Id: $HIDER"
# → answer: "yes" (hider inside radius) or "no" (outside)
# → auto-answer timer is revoked (check: docker logs hideandseek-worker-1 | grep revoke)

# If hider doesn't answer, auto-answer fires after the timer expires
# (check: docker logs hideandseek-worker-1 | grep auto_answer)

# Veto (hider) — refuse to answer, no exclusion zone generated
curl -s -X POST localhost:8000/games/<game_id>/questions/<question_id>/veto \
  -H "X-Client-Id: $HIDER"
# → status: "vetoed", answer: null, no exclusion
# → seekers can re-ask the same slot (ask_count increments)

# Scheduled veto (hider) — veto fires when auto-answer timer expires
curl -s -X POST "localhost:8000/games/<game_id>/questions/<question_id>/veto?scheduled=true" \
  -H "X-Client-Id: $HIDER"
# → question stays answerable, veto triggers at timer expiry
# → hider can still answer normally before the timer to override

# Abandon (seeker) — drop an unwanted question, no answer or exclusion
curl -s -X POST localhost:8000/games/<game_id>/questions/<question_id>/abandon \
  -H "X-Client-Id: $SEEKER"
# → status: "abandoned", answer: null, no exclusion
# → ask is consumed (ask_count stays incremented), seeker can ask a new question
```

### Thermometer question

```bash
# Ask from starting position (seeker). Status starts as "in_progress" (not answerable yet).
# Inventory: [0.5, 1.0, 5.0, 10.0, custom] (imperial/medium)
# For the custom slot (distance=null), pass custom_distance in the request.
curl -s -X POST localhost:8000/games/<game_id>/questions/thermometer \
  -H "Content-Type: application/json" -H "X-Client-Id: $SEEKER" \
  -d '{"location": {"type": "Point", "coordinates": [<start_lon>, <start_lat>]}, "slot_index": <N>}'

# Travel, then report new location
curl -s -X POST localhost:8000/games/<game_id>/location \
  -H "Content-Type: application/json" -H "X-Client-Id: $SEEKER" \
  -d '{"coordinates": {"type": "Point", "coordinates": [<end_lon>, <end_lat>]}, "timestamp": "<ISO8601>"}'

# Lock in end position (seeker) — transitions to "answerable", starts auto-answer timer
curl -s -X POST localhost:8000/games/<game_id>/questions/thermometer/<question_id>/lock-in \
  -H "X-Client-Id: $SEEKER"

# Answer (hider)
curl -s -X POST localhost:8000/games/<game_id>/questions/<question_id>/answer \
  -H "X-Client-Id: $HIDER"
# → answer: "closer" (hider nearer to end) or "farther" (hider nearer to start)
```

### Checking results

```bash
# Question list (any player)
curl -s localhost:8000/games/<game_id>/questions -H "X-Client-Id: $SEEKER"

# Question detail (hider only — includes hider_location, parameters)
curl -s localhost:8000/games/<game_id>/questions/<question_id> -H "X-Client-Id: $HIDER"

# Exclusion zones (seeker only — per-question + cumulative total)
curl -s localhost:8000/games/<game_id>/exclusions -H "X-Client-Id: $SEEKER"

# Candidate stations (seeker only — stops not eliminated by exclusions)
curl -s localhost:8000/games/<game_id>/candidate-stations -H "X-Client-Id: $SEEKER"
```

### Useful DB queries

```bash
# Check game status and timestamps
docker exec hideandseek-postgres-1 psql -U hideandseek -c \
  "SELECT status, hiding_started_at, seeking_started_at FROM game WHERE id = '<game_id>';"

# Check hider station assignment
docker exec hideandseek-postgres-1 psql -U hideandseek -c \
  "SELECT g.hider_station_id, s.name FROM game g JOIN stop s ON s.id = g.hider_station_id WHERE g.id = '<game_id>';"

# Check location updates
docker exec hideandseek-postgres-1 psql -U hideandseek -c \
  "SELECT p.name, p.role, ST_X(lu.coordinates) AS lon, ST_Y(lu.coordinates) AS lat, lu.timestamp
   FROM location_update lu JOIN player p ON p.id = lu.player_id
   WHERE p.game_id = '<game_id>' ORDER BY lu.id;"

# Worker logs (timers, auto-answer, push)
docker logs hideandseek-worker-1 2>&1 | grep -iE 'transition|auto_answer|revoke|push'
```

## Project Structure

```
src/hideandseek/
  main.py, db.py, dependencies.py       # App entrypoint, DB engine + session, FastAPI deps
  logging.py, middleware.py              # structlog config, ASGI access log middleware
  validators.py                          # Request validation (raises HTTPException)
  geo.py, conventions.py, exclusion.py   # Distance math, metric/imperial, exclusion zones
  gtfs.py                                # Reusable GTFS feed parser (pure data, no DB deps)
  config.py, push.py, utils.py          # Push config, APNS service, shared utils
  celery_app.py, celery_config.py       # Celery instance + broker config
  logic/                                # Business logic (session-free)
    ask.py                              # Question creation (radar, thermometer, matching, measuring)
    answer.py                           # Answer computation, exclusion accumulation, veto, abandon
    resolution.py                       # Feature resolution strategy, answer computation helpers
    endgame.py                          # Hiding zone radius, endgame exclusions, candidate stations
    lobby.py                            # Game creation with host-as-player, join with color assignment
    station.py                          # Station election, transition, fallback, hider centroid
  models/                               # SQLAlchemy declarative models (base, types, geo_types,
                                        #   transit, game_map, map_feature, game, inventory,
                                        #   location, question, question_params, device_token)
  schemas/                              # Pydantic request/response schemas + common utils
  queries/                              # DB query functions by domain (games, maps, questions,
                                        #   location, features, stops, effective_map, device_tokens)
  routers/                              # API routes (games, maps, location, questions, endgame)
  tasks/                                # Celery tasks (game_timers, push)
tests/                                  # pytest (one file per router + features, geo, resolution,
                                        #   exclusion, conventions)
scripts/generate_openapi.py             # OpenAPI spec regeneration
scripts/import_seattle_gtfs.py          # Seattle GTFS transit data import
scripts/seed_seattle_map.py            # Seattle GameMap seeding (boundary + districts)
```

**Key callouts** (things that aren't obvious from file names):
- `logic/` is the **conversion boundary** — `to_meters()` before geo math, `from_meters()` after. Session-free: uses `db.register()` to persist new objects, mutates already-tracked ORM objects directly (autoflush handles persistence). Submodules: `ask.py` (question creation), `answer.py` (answer computation + exclusion), `endgame.py` (hiding zone + endgame exclusions), `lobby.py` (game creation + join + color assignment + player removal), `station.py` (election + transition + fallback + centroid).
- `db.register(*objects)` — adds objects to session, flushes, returns last object. Enables `question = register(Question(...))` in logic code without importing `get_session`.
- `exclusion.py` is called from `logic/answer.py` and `logic/endgame.py`, not from routers.
- `logic/resolution.py` owns feature resolution strategy (containment vs nearest) and answer computation helpers. Category classification constants (`MATCHING_CATEGORIES`, `MEASURING_CATEGORIES`, `CONTAINMENT_CATEGORIES`, `CLASSED_CATEGORIES`, `category_key`) live in `models/types.py` alongside `FeatureCategory` — both `logic/` and `queries/` can import them without layer violations.
- `models/__init__.py` re-exports all models — import it to register tables on metadata.
- `celery_app.py` uses an explicit `include` list for task modules (not autodiscover — new task modules must be added manually).
- `queries/stops.py` has spatial query functions (`get_candidate_stations`, `get_nearest_playable_stop`) using PostGIS.

## Architecture Patterns

- **Schema vs Model separation**: SQLAlchemy declarative models (`models/`) own the DB schema. Pydantic schemas (`schemas/`) control the API surface. Response schemas have `from_model()` static methods for transformation.
- **Dependency injection**: `dependencies.py` provides reusable FastAPI `Depends()` — `get_client_id` (from `X-Client-Id` header), `get_game` (uses `db.get_session()`, 404 if missing), `get_player_in_game` (composes `get_game` + `get_client_id`, 403 if not found), `get_hider_in_game` / `get_seeker_in_game` (compose `get_player_in_game` + role check, 403 if wrong role), `get_optional_client_id` (returns `None` when header absent), `get_optional_player_in_game` (returns `None` instead of 403). Role gating is declarative via dependency — use `get_hider_in_game` or `get_seeker_in_game` instead of manual `player.role` checks. Dependencies use `db.get_session()` directly — the router-level dependency ensures the ContextVar is already set.
- **Transactional boundaries**: `session_dependency()` is an async generator that commits once after the handler succeeds and sets a `ContextVar` so `db.get_session()` works everywhere. Must be async so the ContextVar is set in the event-loop context (sync handler threads copy that context). If the handler raises, commit is never called and `Session.__exit__` rolls back. All writes in a request succeed or fail together.
- **ContextVar session access**: A `ContextVar[Session]` (`_session_var`) is set by `session_dependency()` (for requests) or `session_scope()` (for background tasks). All query and logic functions call `db.get_session()` as their first line to get the active session. No decorators, no session parameters — functions just call `session = get_session()`.
- **Router-level session dependency**: Each router uses `dependencies=[Depends(session_dependency)]` to ensure the ContextVar is always set for every route. Handlers never declare `session` in their signatures.
- **Query layer**: `queries/` package (one module per domain) handles all DB reads and writes. Routers never call `session.add/commit/refresh` directly. Query functions return SQLAlchemy model objects; routers transform them via `from_model()`. Import directly from submodules (e.g., `from hideandseek.queries.games import create_game`), not from the package root. Query functions accept ORM objects (not raw UUIDs) — e.g., `create_game(game_map=game_map, ...)`, `get_latest_location_for_player(player, game)`. Raw IDs are only used at system boundaries (dependency injection from URL params, Celery task signatures, logging/push serialization). Write functions call `session.flush()` after mutations to make changes visible to subsequent queries in the same request.
- **Background jobs (Celery + Redis)**: All push delivery and game timers go through Celery tasks. Broker resolution: (1) `CELERY_BROKER_URL` env var if set, (2) auto-detect Redis on `localhost:6379`, (3) eager mode (tasks run synchronously in-process). Set `CELERY_BROKER_URL=''` to force eager mode when Redis is running. Routers call `.delay()` or `.apply_async()` instead of `BackgroundTasks`. Worker tasks use `session_scope()` to get a DB session with ContextVar — all query functions using `db.get_session()` work naturally inside the `with session_scope():` block.
- **Task ID convention**: Deterministic IDs (`hiding_timer:{game_id}`, `answer_deadline:{question_id}`) so the API can revoke tasks without storing IDs in the DB.
- **Push notifications**: `PushService` wraps `aioapns` for APNS delivery. No-ops silently when env vars are missing (dev/test). All push delivery goes through the `send_push` Celery task (with retry). Event types are defined by `PushEventType` enum. See `design/push-notifications.md` for payload specs.
- **Test fixtures**: The `session` fixture sets `_session_var` so `db.get_session()` works in tests. The `client` fixture's `_override_get_session` also sets the ContextVar so TestClient requests work. Factory functions (`create_transit_dataset`, `create_game_map`, `create_game`, `create_player`, `create_inventory_slot`, `create_map_feature`, `create_game_map_feature`) create test data with sensible defaults and accept `**overrides`. `create_game` automatically creates all `InventorySlot` rows — radar/thermometer from the default template, plus matching/measuring from map feature categories.
- **Structured logging**: All logging uses `structlog`. `setup_logging()` is called in the app lifespan. Two logger namespaces: `hideandseek.access` (request/response, does not propagate to root) and `hideandseek.*` (general app logs, written to stderr). Use `structlog.get_logger(__name__)` to get a logger. Log events use snake_case event names with keyword args for context (e.g., `logger.info('push_noop', event_type=..., game_id=...)`). `AccessLogMiddleware` handles all request/response logging — routers don't need to log requests. Three-tier `ENV`: `local` (default) = DEBUG + console + access file, `development` = DEBUG + console + stderr only, `production` = INFO + JSON + stderr only. `LOG_FORMAT=json` forces JSON in any tier.
- **Geometry — three layers**: Geometry flows through three representations:
  - **API boundary** — GeoJSON via `geojson-pydantic` types (`Point`, `Polygon`, `LineString`). Requests accept GeoJSON; responses return GeoJSON.
  - **Python** — shapely objects (`Point`, `Polygon`, `LineString`). All model attributes, query params, and business logic use shapely. Convert with `shapely.geometry.mapping()` (shapely→GeoJSON) and `shapely.geometry.shape()` (GeoJSON→shapely).
  - **Database** — PostGIS spatial columns with two column types in `models/geo_types.py`:
    - `ShapelyGeography(Geography)` — for distance/proximity columns (stops, locations, player positions). `ST_Distance`, `ST_DWithin`, `ST_Buffer` return meters natively — no explicit Geography casts needed in queries.
    - `ShapelyGeometry(Geometry)` — for topological columns (game map boundary, exclusion zones). Used with `ST_Contains`, `ST_Covers`, and set operations.
    - Both transparently convert between shapely and WKB — model code never touches WKB directly. A `_ShapelyProcessors` mixin shares the conversion logic.

  Routers bridge API↔Python (extract coords from geojson-pydantic, construct shapely). Response schemas bridge Python↔API (`mapping()` in `from_model()` methods). The column types bridge Python↔DB automatically. When mixing Geography and Geometry columns in a query (e.g., `ST_Contains` on a Geography column), cast to Geometry explicitly.
- **Question lifecycle layers**: Questions follow a layered pattern: `validators.py` (pure HTTP validation — raises or returns) → `logic/` (business orchestration — inventory mutation, question creation, answer computation; no HTTP concerns, no session access) → `routers/questions.py` (thin HTTP glue — validate, call logic, schedule auto-answer, push, return response). `resolution.py` provides feature resolution strategy (containment vs nearest) used by `logic/`. Logic submodules: `logic/ask.py` (question creation + `lock_in_thermometer`), `logic/answer.py` (answer computation + `veto_immediate` + `schedule_veto` + `abandon_question`). Question status: `asked` → `in_progress` (thermometer only) → `answerable` → `answered`, `vetoed`, or `abandoned`. Veto is a hider action (`POST /questions/{qid}/veto`) that skips answer computation — no exclusion zone, no hider location snapshot. Vetoed questions don't block new questions. Scheduled veto (`?scheduled=true`) sets a flag instead of vetoing immediately — the auto-answer task checks `scheduled_veto` and vetoes at timer expiry. The hider can still answer normally before the timer to override. The `scheduled_veto` field is server-only (not in any response schema) so seekers never see it. Abandon is a seeker action (`POST /questions/{qid}/abandon`) — the seeker drops an unwanted question immediately. No answer, no exclusion zone, no hider location needed. Can abandon `answerable` or `in_progress` questions. The ask is consumed (ask_count stays incremented).
- **Per-type ask endpoints**: Each question type has its own `POST` endpoint (`/questions/radar`, `/questions/thermometer`, `/questions/matching`, `/questions/measuring`). All use a unified `AskQuestionRequest` body (`slot_index`, `location`, optional `custom_distance`). The URL path determines `question_type`; `slot_index` identifies the inventory slot. Seeker `location` is recorded as a `LocationUpdate` and used directly as the seeker's position. Answer and list endpoints remain unified.
- **Role-gated endpoint split**: Endpoints are split by role (see `design/game-state-split.md`). Principles: role = access control only (determines *whether* you can call an endpoint, never *what* you get back), fixed response shapes (no conditional field nulling), default-deny on shared endpoints. The split:
  - **Shared** (any player): `GET /games/{id}` (slim game state with inventory — slots grouped by type with ask counts, no `hider_station_id`), `GET /games/{id}/questions` (whitelist summary — no parameters, locations, or geometry).
  - **Hider-only** (403 for seekers): `GET /games/{id}/hider-station` (assigned station UUID), `GET /games/{id}/questions/{qid}` (full question detail minus exclusion geometry).
  - **Seeker-only** (403 for hiders): `GET /games/{id}/exclusions` (per-question exclusion geometry + cumulative total), `GET /games/{id}/endgame-exclusions`, `GET /games/{id}/candidate-stations`.
  - **Ask endpoints** (radar/thermometer/matching/measuring): return `AskQuestionResponse` (slim — only fields meaningful at ask time, no answer-time fields).
  - **Answer/lock-in endpoints**: return `QuestionDetailResponse` (full detail minus exclusions).
  - Response schemas: `QuestionSummaryResponse` (shared list), `AskQuestionResponse` (ask endpoints), `QuestionDetailResponse` (hider detail + answer/lock-in), `HiderStationResponse`, `ExclusionsResponse`, `InventoryResponse` (slots grouped by type with ask counts).
  - `GET /games/{id}/inventory`: lightweight inventory check — returns `InventoryResponse` without loading the full game map. Slots grouped by type (radar, thermometer, matching, measuring), each with `slot_index`, `distance`, `ask_count`, and optional `category`/`feature_class`.
- **Unified inventory model**: All question types share a single `InventorySlot` table, pre-populated at game creation:
  - Radar/thermometer slots: created from the map's `default_inventory` template. Have `distance` (or `None` for custom).
  - Matching/measuring slots: created from map feature categories (`get_map_feature_categories`). Have `category` and optional `feature_class`. Categories valid for both types get a slot under each.
  - Slots are **re-askable** — `ask_count` increments on each use instead of consuming the slot. The server never gates on usage count.
  - `Game.inventory_slots` relationship. Ordered by `(question_type, slot_index)`.
- **Per-type question parameters**: Question parameters use one-to-one relational tables instead of a JSON column:
  - `RadarParams` (`radius: float`) — one-to-one via `Question.radar_params`
  - `ThermometerParams` (`min_travel: float`) — one-to-one via `Question.thermometer_params`
  - `FeatureQuestionParams` (category, source, `seeker_distance`/`hider_distance`, seeker/hider resolution) — one-to-one via `Question.feature_params`, shared by matching and measuring
  - All distance values are stored in **convention units** (meters for metric maps, miles for imperial). Conversion to meters for geo math happens in `logic/` via `to_meters()`/`from_meters()`.
  - Seeker resolution fields are **non-optional** — if the seeker's feature can't be resolved, the ask endpoint returns 422. Hider resolution fields are populated at answer time.
- **Question types**: Four types, all using `InventorySlot`:
  - **Radar**: uses slot with `distance`. Radar → `answerable` immediately.
  - **Thermometer**: uses slot with `distance`. Thermometer → `in_progress` until seeker locks in.
  - **Matching**: uses slot with `category` (and optional `feature_class`). Resolves each player's nearest feature (or containing feature for `CONTAINMENT_CATEGORIES`); answer is `"yes"` (same `stable_id`), `"no"` (different), or `"null"` (hider unresolvable). → `answerable` immediately.
  - **Measuring**: uses slot with `category`. Resolves each player's distance to nearest feature; answer is `"closer"` (seeker closer), `"farther"`, or `"null"` (hider unresolvable). → `answerable` immediately.
  - All types are re-askable — `ask_count` tracks usage for client display (e.g., multiplier indicators).
- **Geo math**: `geo.py` provides pure distance functions: `distance(point_a, point_b)` for shapely Points (geodesic via pyproj) and `distance_to_feature(player, geometry)` for distance to any geometry. Answer computation and exclusion zone generation live in `logic/answer.py`, which delegates to `exclusion.py` for the geometry. Each answered question has an `exclusion` (this question's zone) and `total_exclusion` (cumulative union across all answered questions in the game).

## Game States

```
lobby → hiding → seeking → finished
lobby → dissolved  (all players left before start)
```

The `GameStatus` enum reflects this. `dissolved` means the game was abandoned in the lobby before it ever started (distinct from `finished` which means a game ran to completion). The endgame is a client-side lens over the `seeking` phase (see `design/endgame.md`). Games can be ended from any active state (hiding/seeking). `join_code` is cleared when hiding starts (no longer usable after lobby). `GameStatus` has instance properties for status checks — use them instead of bare enum comparisons: `is_lobby`, `is_hiding`, `is_seeking`, `is_finished`, `is_active` (hiding or seeking). Direct `GameStatus.X` references are only for setting values (e.g., `update_game_status(game, GameStatus.hiding)`).

### Station Election

Hiders can voluntarily elect their station during hiding, or the system assigns it at the hiding→seeking transition. Tracked by `StationElectionStatus` enum on `Game`:

- **`pending`** — hiding phase, no election yet (default).
- **`elected`** — hider locked in via `POST /hider-station`.
- **`auto_assigned`** — system found exactly one valid candidate at transition.
- **`ambiguous`** — 0 or 2+ valid candidates at transition; hider must resolve via `POST /hider-station`.

Questions cannot be answered while status is `ambiguous`. The auto-answer timer resolves ambiguity via a 3-tier fallback cascade (all-in-radius → any-in-radius → closest pair) before computing the answer. See `design/hider-station-election.md` for full design.

**Endpoints**: `GET /nearby-stations` (query nearby playable stops), `POST /hider-station` (elect), `GET /hiding-zone` (preview zone polygon), `GET /hider-station` (check status — available during hiding + seeking).

**Key files**: `logic/station.py` (election validation, transition resolution, fallback cascade, centroid), `logic/endgame.py` (hiding zone radius + computation), `queries/stops.py` (PostGIS spatial queries), `exclusion.py` (`compute_hiding_zone`), `tasks/game_timers.py` (transition + auto-answer ambiguity handling), `validators.py` (ambiguity check on answer requests).

## Data Model Conventions

- SQLAlchemy 2.0 declarative ORM (`Mapped[]` + `mapped_column()`) for all table models. All models inherit from `Base` in `models/base.py`.
- `from __future__ import annotations` in all model files. Cross-model references use `TYPE_CHECKING` imports — SQLAlchemy resolves relationship targets from its class registry at mapper configuration time.
- Geometry uses the three-layer pattern (see Architecture Patterns): GeoJSON at API, shapely in Python, PostGIS in DB.
- Game timing uses two int columns on `Game`: `hiding_time_min` and `base_question_delay_min`. Resolved at game creation with a three-level fallback: request override → map default → code default. Code defaults: `get_default_hiding_time_min(size)` (small=30, medium=60, large=180) and 5 min for question delay. `GameMap` has optional `default_hiding_time_min` and `default_base_question_delay_min` columns for per-map overrides. Game inventory and question parameters use proper relational tables (see Architecture Patterns). `DistrictClass` is stored as a JSON column value object.
- UUIDs for all PKs except `LocationUpdate` (auto-increment int).
- Enums are `StrEnum` — stored as VARCHAR via `type_annotation_map` on `Base` (not native ENUM).
- Query layer uses `session.scalars()` for single-entity selects, `session.execute()` for multi-entity/column selects.
- **Active development — no migration or backwards-compatibility concerns.** There is no production data. Schema changes go directly in the models and `create_all` recreates tables on startup. To reset: `docker compose down -v`. Alembic will be added when the schema stabilizes and real data exists.
- Tests use `testcontainers` to spin up a disposable PostGIS container (session-scoped). Per-test isolation via transaction rollback — no table recreation between tests. Requires Docker.

## Conventions

- Manage dependencies with `uv add <package>` and `uv remove <package>`. Never edit the dependency lists in `pyproject.toml` by hand.
- All routes go in `routers/` and are included via `app.include_router()`.
- Tests use `fastapi.testclient.TestClient` via the `client` fixture from `conftest.py`.
- OpenAPI spec is auto-generated — add routes to FastAPI, not the YAML file.
- Client identity is via `X-Client-Id` header (UUID). No authentication.
- Only one unanswered question allowed at a time per game.
- `join_code` is nullable — cleared when hiding starts (reclaims the code for new games).
- Pagination uses offset/limit query params (`schemas/common.py`).
- **Host-as-player**: `POST /games` creates the game and adds the host as the first player. Returns `JoinGameResponse` (game + player_id). The `name` field is required in `CreateGameRequest`.
- **Server-assigned colors**: `PlayerColor` enum (12 values: red, blue, green, orange, purple, teal, pink, amber, cyan, lime, indigo, coral). Colors are auto-assigned on create/join. Players can swap colors via `PATCH` if the target color is available (409 if taken).
- **Player cap**: `MAX_PLAYERS = 12`. Join returns 409 when full.
- **Auth guards**: `PATCH /players/{id}` requires matching `X-Client-Id` (self-only, 403 otherwise). `POST /games/{id}/start` is host-only (403 if `client_id != game.host_client_id`). `DELETE /players/{id}` allows self-leave or host-kick (403 otherwise).
- **Player removal** (`DELETE /games/{id}/players/{pid}`): lobby-only (422 if not in lobby). Self-leave or host-kick. When the host leaves: if sole player → game dissolves (`dissolved` status); if others remain → must provide `new_host_id` in `RemovePlayerRequest` body to transfer host. Freed colors are re-assignable to new joiners.
- `device_token` is optional on both `POST /games` and `POST /games/join`. Can also be set via `PATCH /players/{id}`. Device tokens are upserted by `client_id` (separate `DeviceToken` table).
- Push notification env vars: `APNS_KEY_PATH`, `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_TOPIC`, `APNS_USE_SANDBOX`. All optional — when missing, PushService runs in no-op mode.
- Database env vars: `DATABASE_URL` (required — no default). Docker Compose sets `postgresql+psycopg://...`. `scripts/dev.sh` defaults to the docker-compose PostgreSQL.
- Celery env vars: `CELERY_BROKER_URL` (auto-detects `redis://localhost:6379/0` when unset; set to empty string to force eager mode). Docker Compose sets `redis://redis:6379/0`. `CELERY_RESULT_BACKEND` (default: same as broker URL).
- Logging env vars: `ENV` (`local`/`development`/`production`, default `local`), `LOG_FORMAT` (`json` to force JSON output). Use `structlog.get_logger(__name__)` for all new loggers — never use stdlib `logging.getLogger()` directly.

## Style

Enforced by ruff (lint + format) and pyright (type checking). The pre-commit hook runs all checks automatically.

- Single quotes for strings.
- `from __future__ import annotations` at the top of every module (**except** `db.py` which uses PEP 695 generics).
- All imports at the top of the file, never inline — enforced by `PLC0415`. Use `# noqa: PLC0415` only for circular-import avoidance (`db.py`) or conditional imports (`celery_config.py`).
- Type annotations required on all function arguments and return types (except `-> None`).
- Max line length: 100 characters.
- Lint rules: pyflakes, pycodestyle, isort, pyupgrade, flake8-bugbear, flake8-simplify, flake8-future-annotations, flake8-annotations, flake8-datetimez, pylint `import-outside-top-level`.
- B008 exemption for FastAPI's `Depends`, `Header`, `Path`, `Query`, `Body` (configured in `pyproject.toml`).
- SQLAlchemy's `Mapped[]` annotations provide full type coverage — no `type: ignore` needed on `.join()`, `.order_by()`, `.group_by()`.
- Celery `type: ignore[attr-defined]` on `.delay()` and `.apply_async()` calls (Celery task decorator adds these dynamically).
- pyright in `standard` mode.
