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
# Credentials come from POST /games and POST /games/join responses:
# HOST_PLAYER_ID, HOST_SECRET, HIDER_PLAYER_ID, HIDER_SECRET, etc.

# 1. Create game (host is automatically the first player, no auth needed)
#    Optional: size (small/medium/large), hiding_time_min, base_question_delay_min
curl -s -X POST localhost:8000/games \
  -H "Content-Type: application/json" \
  -d "{\"map_id\": \"$MAP_ID\", \"name\": \"HostName\", \"size\": \"large\"}"
# → returns JoinGameResponse: game state under ['game'], player_id + player_secret for auth
# → host gets server-assigned color (red, blue, green, ...)
# → game.size reflects the chosen size; hiding_time_min defaults to size (30/60/180)

# 1b. Connect to lobby SSE stream (in another terminal — stays open)
curl -N localhost:8000/games/<game_id>/lobby/events \
  -H "X-Player-Id: $HOST_PLAYER_ID" -H "X-Player-Secret: $HOST_SECRET"
# → initial game_state event, then real-time player_joined/updated/left/host_changed/game_started

# 2. Join as hider and seeker (no color field — server assigns unique colors)
curl -s -X POST localhost:8000/games/join \
  -H "Content-Type: application/json" \
  -d '{"join_code": "XXXX", "role": "hider", "name": "Alice", "device_token": "fake-hider"}'
curl -s -X POST localhost:8000/games/join \
  -H "Content-Type: application/json" \
  -d '{"join_code": "XXXX", "role": "seeker", "name": "Bob", "device_token": "fake-seeker"}'

# 3. Remove a player (self-leave or host-kick — lobby or active play)
curl -s -X DELETE localhost:8000/games/<game_id>/players/<player_id> \
  -H "X-Player-Id: $HOST_PLAYER_ID" -H "X-Player-Secret: $HOST_SECRET"
# → 204 (player removed). Non-host can only remove themselves.
# Host leaving with others: include body {"new_host_id": "<player_uuid>"}
# Host leaving as sole player: game status → "dissolved"
# Mid-game: location history deleted, last hider/seeker leaving dissolves game
# Dissolution emits GameDissolvedEvent on gameplay SSE channels

# 4. Optionally tweak timing for fast testing
docker exec hideandseek-postgres-1 psql -U hideandseek -c \
  "UPDATE game SET hiding_time_min = 1, base_question_delay_min = 1
   WHERE id = '<game_id>';"

# 4. Start game (host-only — transitions to "hiding", schedules hiding→seeking timer)
curl -s -X POST localhost:8000/games/<game_id>/start \
  -H "X-Player-Id: $HOST_PLAYER_ID" -H "X-Player-Secret: $HOST_SECRET"

# 5. Report hider locations during hiding phase (returns 204, broadcasts via SSE)
curl -s -X POST localhost:8000/games/<game_id>/location \
  -H "Content-Type: application/json" -H "X-Player-Id: $HIDER_PLAYER_ID" -H "X-Player-Secret: $HIDER_SECRET" \
  -d '{"coordinates": {"type": "Point", "coordinates": [<lon>, <lat>]}, "timestamp": "<ISO8601>"}'
# → 204 No Content. Location broadcast to hider SSE channel only.
# The hider's last location when hiding ends determines their assigned station.

# 5b. (Optional) Elect station during hiding — locks in the hider's station early
curl -s -X POST localhost:8000/games/<game_id>/hider-station \
  -H "Content-Type: application/json" -H "X-Player-Id: $HIDER_PLAYER_ID" -H "X-Player-Secret: $HIDER_SECRET" \
  -d '{"station_id": "<stop_uuid>", "location": {"type": "Point", "coordinates": [<lon>, <lat>]}}'
# → Returns hiding zone polygon. Station is now locked in.

# 5c. Query nearby stations to find candidates for election
curl -s "localhost:8000/games/<game_id>/nearby-stations?lat=<lat>&lng=<lon>" \
  -H "X-Player-Id: $HIDER_PLAYER_ID" -H "X-Player-Secret: $HIDER_SECRET"

# 6. Wait for hiding timer (check: docker logs hideandseek-worker-1 | grep transition)
#    Game auto-transitions to "seeking". If no election:
#    - 1 valid candidate → auto_assigned
#    - 0 or 2+ candidates → ambiguous (hider must elect via POST /hider-station)

# 7. Report seeker location (seeking phase only — returns 409 during hiding)
curl -s -X POST localhost:8000/games/<game_id>/location \
  -H "Content-Type: application/json" -H "X-Player-Id: $SEEKER_PLAYER_ID" -H "X-Player-Secret: $SEEKER_SECRET" \
  -d '{"coordinates": {"type": "Point", "coordinates": [<lon>, <lat>]}, "timestamp": "<ISO8601>"}'
# → 204 No Content. Location broadcast to both hider + seeker SSE channels.
# → 409 if game is not active, or if seeker during hiding phase.
```

### Radar question

```bash
# Ask (seeker). Slots are re-askable (ask_count increments each time).
# Inventory: [0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0, custom] (imperial/medium)
# For the custom slot (distance=null), pass custom_distance in the request.
curl -s -X POST localhost:8000/games/<game_id>/questions/radar \
  -H "Content-Type: application/json" -H "X-Player-Id: $SEEKER_PLAYER_ID" -H "X-Player-Secret: $SEEKER_SECRET" \
  -d '{"location": {"type": "Point", "coordinates": [<lon>, <lat>]}, "slot_index": <N>}'
# For custom slot: "slot_index": 9, "custom_distance": 3.0
# → status: "answerable", schedules auto-answer timer (location_question_delay_min)

# Answer (hider) — uses hider's latest reported location
curl -s -X POST localhost:8000/games/<game_id>/questions/<question_id>/answer \
  -H "X-Player-Id: $HIDER_PLAYER_ID" -H "X-Player-Secret: $HIDER_SECRET"
# → answer: "yes" (hider inside radius) or "no" (outside)
# → auto-answer timer is revoked (check: docker logs hideandseek-worker-1 | grep revoke)

# If hider doesn't answer, auto-answer fires after the timer expires
# (check: docker logs hideandseek-worker-1 | grep auto_answer)

# Veto (hider) — refuse to answer, no exclusion zone generated
curl -s -X POST localhost:8000/games/<game_id>/questions/<question_id>/veto \
  -H "X-Player-Id: $HIDER_PLAYER_ID" -H "X-Player-Secret: $HIDER_SECRET"
# → status: "vetoed", answer: null, no exclusion
# → seekers can re-ask the same slot (ask_count increments)

# Scheduled veto (hider) — veto fires when auto-answer timer expires
curl -s -X POST "localhost:8000/games/<game_id>/questions/<question_id>/veto?scheduled=true" \
  -H "X-Player-Id: $HIDER_PLAYER_ID" -H "X-Player-Secret: $HIDER_SECRET"
# → question stays answerable, veto triggers at timer expiry
# → hider can still answer normally before the timer to override

# Abandon (seeker) — drop an unwanted question, no answer or exclusion
curl -s -X POST localhost:8000/games/<game_id>/questions/<question_id>/abandon \
  -H "X-Player-Id: $SEEKER_PLAYER_ID" -H "X-Player-Secret: $SEEKER_SECRET"
# → status: "abandoned", answer: null, no exclusion
# → ask is consumed (ask_count stays incremented), seeker can ask a new question
```

### Thermometer question

```bash
# Ask from starting position (seeker). Status starts as "in_progress" (not answerable yet).
# Inventory: [0.5, 1.0, 5.0, 10.0, custom] (imperial/medium)
# For the custom slot (distance=null), pass custom_distance in the request.
curl -s -X POST localhost:8000/games/<game_id>/questions/thermometer \
  -H "Content-Type: application/json" -H "X-Player-Id: $SEEKER_PLAYER_ID" -H "X-Player-Secret: $SEEKER_SECRET" \
  -d '{"location": {"type": "Point", "coordinates": [<start_lon>, <start_lat>]}, "slot_index": <N>}'

# Travel, then report new location
curl -s -X POST localhost:8000/games/<game_id>/location \
  -H "Content-Type: application/json" -H "X-Player-Id: $SEEKER_PLAYER_ID" -H "X-Player-Secret: $SEEKER_SECRET" \
  -d '{"coordinates": {"type": "Point", "coordinates": [<end_lon>, <end_lat>]}, "timestamp": "<ISO8601>"}'

# Lock in end position (seeker) — transitions to "answerable", starts auto-answer timer
curl -s -X POST localhost:8000/games/<game_id>/questions/thermometer/<question_id>/lock-in \
  -H "X-Player-Id: $SEEKER_PLAYER_ID" -H "X-Player-Secret: $SEEKER_SECRET"

# Answer (hider)
curl -s -X POST localhost:8000/games/<game_id>/questions/<question_id>/answer \
  -H "X-Player-Id: $HIDER_PLAYER_ID" -H "X-Player-Secret: $HIDER_SECRET"
# → answer: "closer" (hider nearer to end) or "farther" (hider nearer to start)
```

### Tentacles question

```bash
# Ask (seeker). Tentacles slots come from tentacle_categories on the map config.
# Each slot has a category (e.g. museum) — distance is resolved from map config.
curl -s -X POST localhost:8000/games/<game_id>/questions/tentacles \
  -H "Content-Type: application/json" -H "X-Player-Id: $SEEKER_PLAYER_ID" -H "X-Player-Secret: $SEEKER_SECRET" \
  -d '{"location": {"type": "Point", "coordinates": [<lon>, <lat>]}, "slot_index": <N>}'
# → status: "answerable", schedules auto-answer timer
# → Server finds POIs of the slot's category within the configured distance

# Answer (hider)
curl -s -X POST localhost:8000/games/<game_id>/questions/<question_id>/answer \
  -H "X-Player-Id: $HIDER_PLAYER_ID" -H "X-Player-Secret: $HIDER_SECRET"
# → answer: "miss" (hider outside circle or no POIs) or "<poi_stable_id>" (nearest POI on hit)
# → On hit, exclusion is Voronoi-based (excludes cells of non-answered POIs within the circle)
```

### Question preview

```bash
# Preview the boundary for a radar question (either role)
curl -s "localhost:8000/games/<game_id>/questions/preview?question_type=radar&slot_index=3&lat=47.6&lng=-122.3" \
  -H "X-Player-Id: $PLAYER_ID" -H "X-Player-Secret: $SECRET"
# → { "boundary": { "type": "LineString", ... }, "feature_preview": null }

# Preview thermometer (requires end coords)
curl -s "localhost:8000/games/<game_id>/questions/preview?question_type=thermometer&slot_index=0&lat=47.6&lng=-122.3&end_lat=47.7&end_lng=-122.2" \
  -H "X-Player-Id: $PLAYER_ID" -H "X-Player-Secret: $SECRET"

# Preview matching (returns feature_preview with resolved feature)
curl -s "localhost:8000/games/<game_id>/questions/preview?question_type=matching&slot_index=0&lat=47.6&lng=-122.3" \
  -H "X-Player-Id: $PLAYER_ID" -H "X-Player-Secret: $SECRET"
# → { "boundary": { ... }, "feature_preview": { "feature_id": "...", "name": "...", "distance": 1234.5 } }

# Preview tentacles (returns boundary circle + Voronoi edges + POI list)
curl -s "localhost:8000/games/<game_id>/questions/preview?question_type=tentacles&slot_index=0&lat=47.6&lng=-122.3" \
  -H "X-Player-Id: $PLAYER_ID" -H "X-Player-Secret: $SECRET"
# → { "boundary": { ... }, "feature_preview": null, "tentacle_pois": [{ "feature_id": "...", "name": "...", "location": { ... } }] }
```

### Checking results

```bash
# Candidate stations (seeker only — stops not eliminated by exclusions)
curl -s localhost:8000/games/<game_id>/candidate-stations \
  -H "X-Player-Id: $SEEKER_PLAYER_ID" -H "X-Player-Secret: $SEEKER_SECRET"

# Question history is delivered via SSE game state snapshot (no polling endpoints).
# Connect to hider/seeker SSE to see question_history in the initial game_state event.
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
  main.py, dependencies.py              # App entrypoint, FastAPI deps (auth, game lookup)
  logging.py, middleware.py              # structlog config, ASGI access log middleware
  validators.py                          # Request validation (raises HTTPException)
  gtfs.py, utils.py                      # GTFS parser, shared utils
  broadcast/                            # Lobby event broadcast (SSE + push routing)
    events.py                           # Typed lobby event dataclasses
    emit.py                             # Lobby emit: pattern-match → publish_sse (from core)
    subscribe.py                        # SSE streaming: Redis subscribe + initial game_state
  schemas/                              # Pydantic request/response/params schemas + common utils
  queries/
    game_state.py                       # Builds Pydantic game state responses for SSE snapshots
  routers/                              # API routes (games, maps, location, questions, endgame, events)
tests/                                  # pytest (one file per router + features, geo, resolution,
                                        #   exclusion, conventions)
scripts/generate_openapi.py             # OpenAPI spec regeneration
scripts/import_seattle_gtfs.py          # Seattle GTFS transit data import
scripts/seed_seattle_map.py            # Seattle GameMap seeding (boundary + districts + hospital POIs + tentacle categories)
```

Business logic, queries, DB infra, geo math, push, and redis live in the `hideandseek-core` package (`core/`). Celery tasks (game timers, push delivery) live in the `hideandseek-worker` package (`worker/`). See `core/CLAUDE.md` and `worker/CLAUDE.md`.

**Key callouts** (things that aren't obvious from file names):
- `queries/game_state.py` stays in server because it builds Pydantic response objects (`HiderGameStateResponse`, `SeekerGameStateResponse`) — presentation-layer concern. All other query/logic modules live in core.
- `broadcast/` in server handles lobby events only (Pydantic response serialization, SSE subscription streams). Gameplay event Pydantic models and `emit_gameplay()` live in `hideandseek_core.broadcast` — shared by routers and tasks.
- `lobby.py` (in core) returns a `RemovalResult` dataclass instead of emitting events directly. The router in `games.py` interprets the result and emits the appropriate events: lobby `PlayerLeftEvent`/`HostChangedEvent` for lobby phase, gameplay `GamePlayerLeftEvent`/`GameHostChangedEvent`/`GameDissolvedEvent` for active play.
- Models live in the top-level `models/` package (`hideandseek_models`). Core lives in `core/` (`hideandseek_core`). Import from submodules directly (e.g., `from hideandseek_core.logic.ask import ask_radar`).

## Architecture Patterns

- **Schema vs Model separation**: SQLAlchemy declarative models (`hideandseek_models`) own the DB schema. Pydantic schemas (`schemas/`) control the API surface. Response schemas have `from_model()` static methods for transformation.
- **Dependency injection**: `dependencies.py` provides reusable FastAPI `Depends()` — `get_authenticated_player_id` (validates `X-Player-Id` + `X-Player-Secret` headers), `get_game` (uses `db.get_session()`, 404 if missing), `get_player_in_game` (composes `get_game` + `get_authenticated_player_id`, 403 if not found), `get_hider_in_game` / `get_seeker_in_game` (compose `get_player_in_game` + role check, 403 if wrong role), `get_optional_player_id` (returns `None` when headers absent), `get_optional_player_in_game` (uses `get_optional_player_id`, returns `None` instead of 403). Role gating is declarative via dependency — use `get_hider_in_game` or `get_seeker_in_game` instead of manual `player.role` checks. Dependencies use `db.get_session()` directly — the router-level dependency ensures the ContextVar is already set.
- **Transactional boundaries**: `session_dependency()` is an async generator that commits once after the handler succeeds and sets a `ContextVar` so `db.get_session()` works everywhere. Must be async so the ContextVar is set in the event-loop context (sync handler threads copy that context). If the handler raises, commit is never called and `Session.__exit__` rolls back. All writes in a request succeed or fail together.
- **ContextVar session access**: A `ContextVar[Session]` (`_session_var`) is set by `session_dependency()` (for requests) or `session_scope()` (for background tasks). All query and logic functions call `db.get_session()` as their first line to get the active session. No decorators, no session parameters — functions just call `session = get_session()`.
- **Router-level session dependency**: Each router uses `dependencies=[Depends(session_dependency)]` to ensure the ContextVar is always set for every route. Handlers never declare `session` in their signatures.
- **Four-package architecture**: `hideandseek-models` (ORM) ← `hideandseek-core` (business logic, queries, DB, geo, push, redis, gameplay broadcast) ← `hideandseek-worker` (Celery tasks: game timers, push delivery) ← `hideandseek` (server: routers, schemas, lobby broadcast). Core owns gameplay event production and Redis publishing. Worker owns background task execution. Server owns lobby events (Pydantic serialization), SSE subscriptions, and HTTP routing. Server imports worker tasks for `.delay()` / `.apply_async()` calls.
- **Query layer**: `hideandseek_core.queries` package (one module per domain) handles all DB reads and writes. Exception: `hideandseek.queries.game_state` stays in server (builds Pydantic response objects). Routers never call `session.add/commit/refresh` directly. Query functions return SQLAlchemy model objects; routers transform them via `from_model()`. Import directly from submodules (e.g., `from hideandseek_core.queries.games import create_game`), not from the package root. Query functions accept ORM objects (not raw UUIDs) — e.g., `create_game(game_map=game_map, ...)`, `get_latest_location_for_player(player, game)`. Raw IDs are only used at system boundaries (dependency injection from URL params, Celery task signatures, logging/push serialization). Write functions call `session.flush()` after mutations to make changes visible to subsequent queries in the same request.
- **Background jobs (Celery + Redis)**: All push delivery and game timers go through Celery tasks in the `hideandseek-worker` package. Broker resolution: (1) `CELERY_BROKER_URL` env var if set, (2) auto-detect Redis on `localhost:6379`, (3) eager mode (tasks run synchronously in-process). Set `CELERY_BROKER_URL=''` to force eager mode when Redis is running. Routers call `.delay()` or `.apply_async()` on worker tasks instead of `BackgroundTasks`. Worker tasks use `session_scope()` to get a DB session with ContextVar — all query functions using `db.get_session()` work naturally inside the `with session_scope():` block. Import tasks from worker: `from hideandseek_worker.tasks.push import send_push`, `from hideandseek_worker.tasks.game_timers import auto_answer_question`. Celery app: `from hideandseek_worker.celery_app import app`.
- **Task ID convention**: Deterministic IDs (`hiding_timer:{game_id}`, `answer_deadline:{question_id}`) so the API can revoke tasks without storing IDs in the DB.
- **Push notifications**: `PushService` orchestrates delivery across APNs (`ApnsProvider` wrapping `aioapns`) and FCM (`FcmProvider` wrapping `firebase-admin`). Each provider constructs its own wire format from a shared data dict. No-ops silently when env vars are missing (dev/test). All push delivery goes through the `send_push` Celery task (with retry). The task extracts `(token, provider)` pairs from `DeviceToken` and dispatches by provider. Event types are defined by `PushEventType` enum. `TokenProvider` enum (`apns`/`fcm`) on `DeviceToken` determines routing. See `design/push-notifications.md` for payload specs.
- **Broadcast — two layers**: Event broadcast is split between core (domain) and server (presentation):
  - **Core** (`hideandseek_core.broadcast`): Gameplay event Pydantic models (`events.py`) + `emit_gameplay()` (`emit.py`). Events auto-register via `GameplayEventSchema` base class for OpenAPI injection. Also provides `publish_sse()` (low-level Redis publish) and channel name helpers (`lobby_channel`, `hider_channel`, `seeker_channel`). Both routers and tasks import `emit_gameplay` from here.
  - **Server** (`hideandseek.broadcast`): Lobby event dataclasses (`events.py`) + `emit()` (`emit.py`) — uses Pydantic response schemas (`GameResponse`, `PlayerResponse`). SSE subscription streams (`subscribe.py`) — uses game state builders and `sse-starlette`.
  - **Lobby SSE** (Redis pub/sub): real-time data for connected clients. Channel: `game:{id}:lobby:events`. Lobby-only events (`player_joined`, `player_updated`, `player_left`, `host_changed`) are SSE-only — Redis failure propagates (no fallback). `game_started` is dual-channel — SSE failure is logged and swallowed, push still delivers independently.
  - **SSE endpoint** (`GET /games/{id}/lobby/events`): separate router (`routers/events.py`), no `session_dependency` (SSE outlives the request). Auth via `X-Player-Id` + `X-Player-Secret` headers, validated in a short-lived `session_scope()`. Returns `EventSourceResponse` from `sse-starlette`. Initial `game_state` event sent on connect, then real-time events via Redis subscription. Reconnecting clients get fresh state (no gap recovery needed).
  - **Redis client** (`hideandseek_core.redis_client`): `get_redis_url()` resolves URL (env var → auto-detect → None). `get_sync_redis()` for publish, `get_async_redis()` for subscribe. Returns None when unavailable.
  - **`LobbyEventType` enum** (`hideandseek_models.types`): `game_state`, `player_joined`, `player_updated`, `player_left`, `host_changed`, `game_started`.
  - **Emit call sites**: `routers/games.py` (join → `PlayerJoinedEvent`, remove → lobby `PlayerLeftEvent`/`HostChangedEvent` or gameplay `GamePlayerLeftEvent`/`GameHostChangedEvent`/`GameDissolvedEvent` via `RemovalResult`, patch → `PlayerUpdatedEvent` if lobby, start → `GameStartedEvent` + push, elect station → `StationElectionEvent`), `routers/location.py` (location report → `PlayerLocationEvent`), `routers/questions.py` (ask/lock-in/answer/veto/abandon → corresponding gameplay events), `hideandseek_worker.tasks.game_timers` (phase transition → `PhaseChangedEvent` + `StationElectionEvent`, auto-answer → `HiderQuestionAnsweredEvent` + `SeekerQuestionAnsweredEvent` or `QuestionVetoedEvent`). `create_game_with_host()` does NOT emit (no SSE subscribers yet).
  - **Gameplay SSE endpoints** (`GET /games/{id}/hider-state`, `GET /games/{id}/seeker-state`): role-specific SSE streams in `routers/events.py`. Auth inline in `session_scope()` — same pattern as lobby. Phase guard: 409 if game not `is_active`. Role guard: 403 if wrong role. Two Redis channels: `game:{id}:hider-events`, `game:{id}:seeker-events`. Initial `game_state` event delivers full snapshot (`HiderGameStateResponse` or `SeekerGameStateResponse`), then forwards Redis messages. Stream generators: `hider_state_stream` / `seeker_state_stream` in `broadcast/subscribe.py`. Snapshot assembly: `queries/game_state.py` has `build_hider_game_state(game, player)` and `build_seeker_game_state(game, player)`. Both snapshots include `host_player_id` (for client-side host transfer UI) and `routes: list[RouteResponse]` (route shapes + ordered playable stop IDs) for map rendering alongside `stops`.
  - **`GameplayEventType` enum** (`hideandseek_models.types`): `game_state` (initial snapshot), `player_location`, `question_asked`, `question_answerable`, `question_answered`, `question_vetoed`, `question_abandoned`, `phase_changed`, `station_election`, `player_left`, `host_changed`, `game_dissolved`.
  - **`emit_gameplay(event)`** (`hideandseek_core.broadcast.emit`): routes gameplay events to role-specific Redis channels. All gameplay events are `required=True` (SSE is primary, no push fallback). Helper `_both_channels()` publishes identical data to hider + seeker channels. Channel routing: most events → both channels; `StationElectionEvent` → hider only; `HiderQuestionAnsweredEvent` → hider only; `SeekerQuestionAnsweredEvent` → seeker only; `PlayerLocationEvent` hider loc → hider only, seeker loc → both.
  - **Gameplay event models** (`hideandseek_core.broadcast.events`): frozen Pydantic `BaseModel` subclasses extending `GameplayEventSchema` (auto-registered for OpenAPI schema injection). `game_id = Field(exclude=True)` on the base — present for construction/routing, excluded from `.model_dump()` and JSON schema. Question events have `from_question(question)` static constructors that extract fields from the ORM model. `QuestionAnswered` uses **two separate classes** — `HiderQuestionAnsweredEvent` (hider-privileged delta: `answered_at`, `hider_location`, flat hider resolution fields) and `SeekerQuestionAnsweredEvent` (exclusion geometry + `answered_at`, no hider data) — so the type system prevents accidental data leakage.
  - **SSE type auto-sync**: Gameplay event schemas and game state snapshot schemas are injected into the OpenAPI spec by `scripts/generate_openapi.py` via `GameplayEventSchema.registered_schemas()` and `SSEExposed.registered_schemas()`. The existing `openapi-typescript` pipeline (`openapi.yaml → schema.d.ts`) then generates TypeScript types. `mobile/src/types/gameplay.ts` provides short aliases (e.g. `PlayerLocationDelta` → `S[‘PlayerLocationEvent’]`). Adding a new event class is sufficient — it auto-registers and appears in the spec on next regen.
  - **`SSEExposed` mixin** (`hideandseek.schemas.response`): marks `HiderGameStateResponse` and `SeekerGameStateResponse` for OpenAPI injection (they aren’t on REST routes). Sub-types (`GamePlayer`, `HiderActiveQuestion`, etc.) are pulled in automatically via `$defs` hoisting.
  - **Enriched question events**: Fields are placed on the event where they become *known*. `QuestionAskedEvent` carries ask-time fields: `parameters` (typed `QuestionEventParams` discriminated union), `seeker_location_start`, `asked_at`, `ask_count`, `sequence`. `QuestionAnswerableEvent` carries `seeker_location_end` (thermometer lock-in). Answered events carry only the answer-time delta. History entries in game state snapshots carry **both** ask-time and answer-time fields (enriched to replace the removed question GET endpoints). `HiderQuestionHistoryEntry` includes `parameters`, `seeker_location_start/end`, `sequence`, `ask_count`, `asked_at` plus answer-time hider data. `SeekerQuestionHistoryEntry` includes `sequence`, `ask_count`, `asked_by`, `asked_at` plus exclusion geometry.
  - **Question parameter models** (`hideandseek_core.broadcast.events`): `RadarEventParams`, `ThermometerEventParams`, `FeatureEventParams`, `TentacleEventParams` — standalone frozen Pydantic `BaseModel` subclasses with `Literal` type discriminators (`type: Literal[‘radar’] = ‘radar’`). `build_event_params(question)` factory constructs the appropriate variant from the Question ORM model’s param relationships. `TentacleEventParams` reads `poi_names` from the model (denormalized at ask time — no DB queries in event builders). Serialized automatically via `.model_dump(mode=’json’)` in `emit_gameplay()`.
  - **Mutation endpoints return 204**: `POST /questions/*` (ask, lock-in, answer, veto, abandon) and `POST /hider-station` return 204 with no body. State updates flow to clients exclusively through SSE events. Push notifications remain as supplementary wake-up alerts.
  - **`publish_sse(channel, ...)`** (`hideandseek_core.broadcast.emit`): low-level Redis publish shared by both `emit_gameplay` (core) and `emit` (server lobby). Channel helpers: `lobby_channel()`, `hider_channel()`, `seeker_channel()`.
  - **`Question.slot_index`** — stored at ask time from `InventorySlot.slot_index`. Used in gameplay state question schemas.
  - **Configurable game parameters**: `POST /games` accepts optional `size` (small/medium/large — not special), `hiding_time_min`, and `base_question_delay_min` overrides. Three-level fallback: request → map → code default (by size). `Game.size` is stored on the game (can differ from `GameMap.size`), used by `effective_hiding_zone_radius_m()`. `MapSummary` exposes nullable `default_hiding_time_min` and `default_base_question_delay_min` for client-side default computation. Inventory stays map-based (not affected by game size override).
  - **Inventory slots**: `InventoryResponse` groups slots by question type: `radar_slots`, `thermometer_slots`, `matching_slots`, `measuring_slots`, `tentacles_slots`. Tentacles slots come from `GameMap.tentacle_categories` (list of `{category, distance}` dicts). Each entry creates one `InventorySlot` with `question_type=tentacles`.
