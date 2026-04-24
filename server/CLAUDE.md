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
| Timers | Real (reconciler polls every 1s) | Real (reconciler polls every 1s) |
| Reset DB | `docker compose down -v` | `docker compose down -v` |
| `ENV` | `development` | `local` (default) |

In production (`ENV=production`): INFO level, JSON renderer, stderr only.

**Schema is owned by Alembic, not the server.** The lifespan only configures logging. In docker-compose a one-shot `migrate` service runs `alembic upgrade head` before the API starts (`depends_on: service_completed_successfully`). In prod, the DataStack's CDK custom resource runs the same command in a Fargate task during `cdk deploy`. Local dev (`scripts/dev.sh`) assumes you've already brought compose up at least once so the migrate service has populated the volume — or run `uv run alembic upgrade head` yourself from the repo root.

## Logging

The generic structlog config (root level, renderer, `sqlalchemy.engine` routing, third-party noise suppression) lives in `hideandseek_core.logging.setup_logging()`, shared with the worker and reconciler. Server's `hideandseek.logging.setup_logging()` wraps that and additionally builds the `hideandseek.access` logger used by `AccessLogMiddleware` — writing to `server/logs/access.log` in `local` mode, stderr in all modes. Called once from the FastAPI lifespan in `main.py`.

`AccessLogMiddleware` (`middleware.py`) captures per-request state on a `_RequestCapture` object (no closure/`nonlocal` tricks) and emits one structured log line per request with `status`, `duration_ms`, `headers`, `query`, `request_body`, `response_body`, and `response_size`. Body capture is capped at 1KB (request) / 5KB (response); responses larger than 5KB get a `... (<N> bytes total)` suffix so you can spot oversized payloads. SSE responses (`content-type: text/event-stream`) skip response-body capture entirely — the line still fires with `response_size` but no `response_body` field, since the stream can be arbitrarily large and the application logger already narrates lobby/gameplay events. Sensitive headers (`authorization`, `cookie`, `x-player-secret`) are redacted in the `headers` field, and any JSON body value whose key contains `secret` or `token` (case-insensitive) is replaced with `"[REDACTED]"` — so `player_secret`, `device_token`, etc. stay out of the logs by default, no per-endpoint allowlist needed.

Env vars (shared across all three services):
- `ENV=local|development|production` — `local`/`development` get DEBUG + console renderer, `production` gets INFO + JSON renderer.
- `LOG_FORMAT=json` — force JSON regardless of `ENV`.
- `SQL_ECHO=1|true|yes` — force `sqlalchemy.engine` to INFO (SQL visible). On by default in `local`.

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
# → question.status flips to "answered"; the reconciler's overdue query filters it out (no revoke needed)

# If hider doesn't answer, the reconciler enqueues auto_answer_question once the deadline passes
# (check: docker logs hideandseek-reconciler-1 | grep reconcile_enqueue_auto_answer
#         docker logs hideandseek-worker-1 | grep auto_answer)

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

# Randomize (hider) — replace current question with a random slot of the same type
curl -s -X POST localhost:8000/games/<game_id>/questions/<question_id>/randomize \
  -H "X-Player-Id: $HIDER_PLAYER_ID" -H "X-Player-Secret: $HIDER_SECRET"
# → original status: "randomized", original slot's ask_count restored
# → server picks random replacement slot (same type, ask_count == 0)
# → replacement question created; emits QuestionAskedEvent (client infers randomize)
# → 409 if no eligible replacement slots available

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

### Photo question

```bash
# Ask (seeker). Photo slots come from the map's size-gated subject list.
# No custom_distance, no category — just slot_index (and seeker location).
curl -s -X POST localhost:8000/games/<game_id>/questions/photo \
  -H "Content-Type: application/json" -H "X-Player-Id: $SEEKER_PLAYER_ID" -H "X-Player-Secret: $SEEKER_SECRET" \
  -d '{"location": {"type": "Point", "coordinates": [<lon>, <lat>]}, "slot_index": <N>}'
# → 204. status: "answerable". The question asks for a photo of a specific subject
#   (e.g. tree, park, tallest_mountain_from_station — see PhotoSubject enum).
# → QuestionAskedEvent emitted with parameters {type: 'photo', subject: '<subject>'}.
# → No preview endpoint for photo — GET /questions/preview?question_type=photo... → 422.
# → Hider submit + accept/reject flow lands in cycles z32.4 and z32.5.
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

### Two-party game completion (found claim)

```bash
# Seeker must be inside the hiding zone (≤ effective_hiding_zone_radius_m from hider_station)
# and have a recent location report. No other claim may be pending.

# 1. Seeker claims found
curl -s -X POST localhost:8000/games/<game_id>/found \
  -H "X-Player-Id: $SEEKER_PLAYER_ID" -H "X-Player-Secret: $SEEKER_SECRET"
# → 204. Emits FoundClaimEvent (with deadline_utc = found_claim_at + 120s) to both SSE
#   channels; push to hiders.
# → 409 if not seeking, no station elected, seeker has no location, seeker outside zone,
#   or a claim is already pending.
# Schedules auto-dismiss at T+120s (task_id=found_claim:<game_id>).

# 2a. Hider confirms → game ends
curl -s -X POST localhost:8000/games/<game_id>/found/confirm \
  -H "X-Player-Id: $HIDER_PLAYER_ID" -H "X-Player-Secret: $HIDER_SECRET"
# → 204. game.status=finished, game.end_reason=found. Emits GameEndedEvent to both channels + push.

# 2b. OR hider rejects → claim cleared, game continues
curl -s -X POST localhost:8000/games/<game_id>/found/reject \
  -H "X-Player-Id: $HIDER_PLAYER_ID" -H "X-Player-Secret: $HIDER_SECRET"
# → 204. Emits FoundClaimRejectedEvent to seeker SSE; push to seekers.

# 2c. OR nobody acts → worker auto-dismisses at T+120s
# → Emits FoundClaimExpiredEvent to both channels + push.
#   Watch: docker logs hideandseek-worker-1 | grep found_claim
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

# Worker logs (executed tasks — transitions, auto-answer, push)
docker logs hideandseek-worker-1 2>&1 | grep -iE 'transition|auto_answer|found_claim|push'

# Reconciler logs (overdue enqueue decisions)
docker logs hideandseek-reconciler-1 2>&1 | grep -iE 'reconcile_enqueue|reconciler_tick'
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
    game_state.py                       # Builds static game info + dynamic SSE state snapshots
  routers/                              # API routes (games, maps, location, questions, endgame, events)
tests/                                  # pytest (one file per router + features, geo, resolution,
                                        #   exclusion, conventions)
scripts/generate_openapi.py             # OpenAPI spec regeneration
scripts/import_seattle_gtfs.py          # Seattle GTFS transit data import
scripts/seed_seattle_map.py            # Seattle GameMap seeding (boundary + districts + hospital POIs + tentacle categories)
```

Business logic, queries, DB infra, geo math, push, and redis live in the `hideandseek-core` package (`core/`). Celery tasks (game timers, push delivery) live in the `hideandseek-worker` package (`worker/`). See `core/CLAUDE.md` and `worker/CLAUDE.md`.

**Key callouts** (things that aren't obvious from file names):
- `queries/game_state.py` stays in server because it builds Pydantic response objects (`GameInfoResponse`, `HiderGameStateResponse`, `SeekerGameStateResponse`) — presentation-layer concern. `build_game_info()` assembles static data (map geometry, transit, timing, map features) served by `GET /games/{id}/info`. `build_hider_game_state()` and `build_seeker_game_state()` assemble dynamic-only snapshots for SSE. All other query/logic modules live in core.
- `broadcast/` in server handles lobby events only (Pydantic response serialization, SSE subscription streams). Gameplay event Pydantic models and `emit_gameplay()` live in `hideandseek_core.broadcast` — shared by routers and tasks.
- `lobby.py` (in core) returns a `RemovalResult` dataclass instead of emitting events directly. The router in `games.py` interprets the result and emits the appropriate events: lobby `PlayerLeftEvent`/`HostChangedEvent` for lobby phase, gameplay `GamePlayerLeftEvent`/`GameHostChangedEvent`/`GameDissolvedEvent` for active play.
- Models live in the top-level `models/` package (`hideandseek_models`). Core lives in `core/` (`hideandseek_core`). Import from submodules directly (e.g., `from hideandseek_core.logic.ask import ask_radar`).

## Architecture Patterns

- **Schema vs Model separation**: SQLAlchemy declarative models (`hideandseek_models`) own the DB schema. Pydantic schemas (`schemas/`) control the API surface. Response schemas have `from_model()` static methods for transformation.
- **Dependency injection**: `dependencies.py` provides reusable FastAPI `Depends()` — `get_authenticated_player_id` (validates `X-Player-Id` + `X-Player-Secret` headers), `get_game` (uses `db.get_session()`, 404 if missing), `get_player_in_game` (composes `get_game` + `get_authenticated_player_id`, 403 if not found), `get_hider_in_game` / `get_seeker_in_game` (compose `get_player_in_game` + role check, 403 if wrong role), `get_optional_player_id` (returns `None` when headers absent), `get_optional_player_in_game` (uses `get_optional_player_id`, returns `None` instead of 403). Role gating is declarative via dependency — use `get_hider_in_game` or `get_seeker_in_game` instead of manual `player.role` checks. Dependencies use `db.get_session()` directly — the router-level dependency ensures the ContextVar is already set.
- **Transactional boundaries**: `session_dependency()` is an async generator that commits once after the handler succeeds and sets a `ContextVar` so `db.get_session()` works everywhere. Must be async so the ContextVar is set in the event-loop context (sync handler threads copy that context). If the handler raises, commit is never called and `Session.__exit__` rolls back. All writes in a request succeed or fail together.
- **ContextVar session access**: A `ContextVar[Session]` (`_session_var`) is set by `session_dependency()` (for requests) or `session_scope()` (for background tasks). All query and logic functions call `db.get_session()` as their first line to get the active session. No decorators, no session parameters — functions just call `session = get_session()`.
- **Router-level session dependency**: Each router uses `dependencies=[Depends(session_dependency)]` to ensure the ContextVar is always set for every route. Handlers never declare `session` in their signatures.
- **Five-package architecture**: `hideandseek-models` (ORM) ← `hideandseek-core` (business logic, queries, DB, geo, push, redis, gameplay broadcast, overdue-timer queries) ← `hideandseek-worker` (Celery task bodies: game timers, push delivery) ← `hideandseek-reconciler` (polls Postgres, enqueues Celery tasks) / `hideandseek` (server: routers, schemas, lobby broadcast). Core owns gameplay event production and Redis publishing. Worker owns background task execution. Reconciler owns timer scheduling. Server owns lobby events (Pydantic serialization), SSE subscriptions, and HTTP routing. Server imports worker tasks for `.delay()` calls (push only — it no longer schedules game timers).
- **Query layer**: `hideandseek_core.queries` package (one module per domain) handles all DB reads and writes. Exception: `hideandseek.queries.game_state` stays in server (builds Pydantic response objects). Routers never call `session.add/commit/refresh` directly. Query functions return SQLAlchemy model objects; routers transform them via `from_model()`. Import directly from submodules (e.g., `from hideandseek_core.queries.games import create_game`), not from the package root. Query functions accept ORM objects (not raw UUIDs) — e.g., `create_game(game_map=game_map, ...)`, `get_latest_location_for_player(player, game)`. Raw IDs are only used at system boundaries (dependency injection from URL params, Celery task signatures, logging/push serialization). Write functions call `session.flush()` after mutations to make changes visible to subsequent queries in the same request.
- **Background jobs (Celery + Redis)**: Push delivery goes through the `send_push` Celery task in the `hideandseek-worker` package. Game timer task bodies also live in worker but are **not scheduled by the API** — they are enqueued by the reconciler (see below). Broker resolution: (1) `CELERY_BROKER_URL` env var if set, (2) auto-detect Redis on `localhost:6379`, (3) eager mode (tasks run synchronously in-process). Set `CELERY_BROKER_URL=''` to force eager mode when Redis is running. Routers call `.delay()` on `send_push` only — they do **not** call `.apply_async(countdown=...)` or `.revoke()` anywhere. Worker tasks use `session_scope()` to get a DB session with ContextVar — all query functions using `db.get_session()` work naturally inside the `with session_scope():` block.
- **Game timers — reconciler-driven**: The `hideandseek-reconciler` process polls Postgres every second for overdue fire-times and enqueues the corresponding worker tasks for immediate execution. Authoritative fire-times live in DB columns (`Game.hiding_started_at + hiding_time_min`, `Question.answerable_at + base_question_delay_min`, `Game.found_claim_at + 120s`). Overdue queries in `hideandseek_core.logic.timers`. Router cancellation happens implicitly: when state advances (game ends, question answered, found-claim resolved), the reconciler's query filters on `Game.status` / `Question.status` / `found_claim_at IS NOT NULL` skip those rows — no explicit `revoke()` needed. Task bodies retain their own status guards as a safety net for enqueue-during-execution races.
- **Task ID convention**: Deterministic IDs (`hiding_timer:{game_id}`, `answer_deadline:{question_id}`, `found_claim:{game_id}`) set by the reconciler on `apply_async(task_id=...)`. Purpose is log-grep observability, not revocation.
- **Push notifications — SNS Mobile Push**: `PushService` wraps a single `SnsProvider` (boto3 `sns:Publish` against per-device platform endpoint ARNs). The same envelope carries both APNs + FCM payloads (`MessageStructure='json'`) and SNS routes server-side based on the endpoint's parent platform application. No-ops silently when `SnsConfig` is missing (dev/test without LocalStack). Registration flow (`logic/push_registration.register_push_endpoint`) calls `sns:CreatePlatformEndpoint` inline and stores the returned `endpoint_arn` on `DeviceToken`. Duplicate tokens are re-enabled via the parsed-ARN + `SetEndpointAttributes` idiom. Dead-token cleanup is synchronous: `SnsProvider.send()` collects any ARNs SNS reports as `EndpointDisabled`/`NotFound`/`InvalidParameter` on publish, and the `send_push` worker task deletes those rows inline via `delete_device_token_by_endpoint`. `TokenProvider` enum (`apns`/`fcm`) on `DeviceToken` selects the correct platform app during registration. Locally, LocalStack (`docker-compose.yml → localstack` service) emulates SNS; `infra/localstack/init-aws.sh` bootstraps the two platform apps on container ready. See `design/2026-04-19-aws-deployment.md` § Service Changes 1.
- **Broadcast — two layers**: Event broadcast is split between core (domain) and server (presentation):
  - **Core** (`hideandseek_core.broadcast`): Gameplay event Pydantic models (`events.py`) + `emit_gameplay()` (`emit.py`). Events auto-register via `GameplayEventSchema` base class for OpenAPI injection. Also provides `publish_sse()` (low-level Redis publish) and channel name helpers (`lobby_channel`, `hider_channel`, `seeker_channel`). Both routers and tasks import `emit_gameplay` from here.
  - **Server** (`hideandseek.broadcast`): Lobby event dataclasses (`events.py`) + `emit()` (`emit.py`) — uses Pydantic response schemas (`GameResponse`, `PlayerResponse`). SSE subscription streams (`subscribe.py`) — uses game state builders and `sse-starlette`.
  - **Lobby SSE** (Redis pub/sub): real-time data for connected clients. Channel: `game:{id}:lobby:events`. Lobby-only events (`player_joined`, `player_updated`, `player_left`, `host_changed`) are SSE-only — Redis failure propagates (no fallback). `game_started` is dual-channel — SSE failure is logged and swallowed, push still delivers independently.
  - **SSE endpoint** (`GET /games/{id}/lobby/events`): separate router (`routers/events.py`), no `session_dependency` (SSE outlives the request). Auth via `X-Player-Id` + `X-Player-Secret` headers, validated in a short-lived `session_scope()`. Returns `EventSourceResponse` from `sse-starlette`. Initial `game_state` event sent on connect, then real-time events via Redis subscription. Reconnecting clients get fresh state (no gap recovery needed).
  - **Redis client** (`hideandseek_core.redis_client`): `get_redis_url()` resolves URL (env var → auto-detect → None). `get_sync_redis()` for publish, `get_async_redis()` for subscribe. Returns None when unavailable.
  - **`LobbyEventType` enum** (`hideandseek_models.types`): `game_state`, `player_joined`, `player_updated`, `player_left`, `host_changed`, `game_started`.
  - **Emit call sites**: `routers/games.py` (join → `PlayerJoinedEvent`, remove → lobby `PlayerLeftEvent`/`HostChangedEvent` or gameplay `GamePlayerLeftEvent`/`GameHostChangedEvent`/`GameDissolvedEvent` via `RemovalResult`, patch → `PlayerUpdatedEvent` if lobby, start → `GameStartedEvent` + push, elect station → `StationElectionEvent`, expand hiding zone → `HidingZoneExpandedEvent` + push, end game → `GameEndedEvent` + push), `routers/location.py` (location report → `PlayerLocationEvent`, seeker location during seeking → `ProximityEscalatedEvent`/`ProximityDeescalatedEvent` + push to hiders), `routers/questions.py` (ask/lock-in/answer/veto/abandon/randomize → corresponding gameplay events), `routers/endgame.py` (found claim → `FoundClaimEvent` on both channels with `deadline_utc` + hider push, reject → `FoundClaimRejectedEvent` + seeker push, confirm → `GameEndedEvent` + push; schedules/revokes `found_claim:{game_id}` timer), `hideandseek_worker.tasks.game_timers` (phase transition → `PhaseChangedEvent` + `StationElectionEvent`, auto-answer → `HiderQuestionAnsweredEvent` + `SeekerQuestionAnsweredEvent` or `QuestionVetoedEvent`, auto-dismiss found claim → `FoundClaimExpiredEvent` + push). `create_game_with_host()` does NOT emit (no SSE subscribers yet).
  - **Static game info** (`GET /games/{id}/info`): returns `GameInfoResponse` — map boundary, districts, playable stops, transit routes (clipped shapes), map features (POIs with centroid locations), distance convention, hiding time, question delay. Fetched once on game entry and cached by the client. Auth via `get_player_in_game` (role-agnostic, no phase guard). `MapFeatureResponse` includes `stable_id`, `name`, `category`, `feature_class`, and `location` (GeoJSON Point centroid of the feature shape).
  - **Gameplay SSE endpoints** (`GET /games/{id}/hider-state`, `GET /games/{id}/seeker-state`): role-specific SSE streams in `routers/events.py`. Auth inline in `session_scope()` — same pattern as lobby. Phase guard: 409 if game not `is_active`. Role guard: 403 if wrong role. Two Redis channels: `game:{id}:hider-events`, `game:{id}:seeker-events`. Initial `game_state` event delivers a **dynamic-only** snapshot (`HiderGameStateResponse` or `SeekerGameStateResponse` — no map geometry, stops, routes, or timing config), then forwards Redis messages. Static data is served separately by `GET /info`. Stream generators: `hider_state_stream` / `seeker_state_stream` in `broadcast/subscribe.py`. Snapshot assembly: `queries/game_state.py` has `build_hider_game_state(game, player)` and `build_seeker_game_state(game, player)`. Both snapshots include `host_player_id` (for client-side host transfer UI).
  - **`GameplayEventType` enum** (`hideandseek_models.types`): `game_state` (initial snapshot), `player_location`, `question_asked`, `question_answerable`, `question_answered`, `question_vetoed`, `question_abandoned`, `phase_changed`, `station_election`, `player_left`, `host_changed`, `game_dissolved`, `game_ended`, `hiding_zone_expanded`, `proximity_escalated`, `proximity_deescalated`, `found_claim`, `found_claim_rejected`, `found_claim_expired`.
  - **`emit_gameplay(event)`** (`hideandseek_core.broadcast.emit`): routes gameplay events to role-specific Redis channels. All gameplay events are `required=True` (SSE is primary, no push fallback). Helper `_both_channels()` publishes identical data to hider + seeker channels. Channel routing: most events → both channels; `StationElectionEvent` → hider only; `HiderQuestionAnsweredEvent` → hider only; `SeekerQuestionAnsweredEvent` → seeker only; `PlayerLocationEvent` hider loc → hider only, seeker loc → both; `FoundClaimEvent` → both (carries `deadline_utc`); `FoundClaimRejectedEvent` → seeker only; `FoundClaimExpiredEvent` → both.
  - **Gameplay event models** (`hideandseek_core.broadcast.events`): frozen Pydantic `BaseModel` subclasses extending `GameplayEventSchema` (auto-registered for OpenAPI schema injection). `game_id = Field(exclude=True)` on the base — present for construction/routing, excluded from `.model_dump()` and JSON schema. Question events have `from_question(question)` static constructors that extract fields from the ORM model. `QuestionAnswered` uses **two separate classes** — `HiderQuestionAnsweredEvent` (hider-privileged delta: `answered_at`, `hider_location`, flat hider resolution fields) and `SeekerQuestionAnsweredEvent` (exclusion geometry + `answered_at`, no hider data) — so the type system prevents accidental data leakage.
  - **SSE type auto-sync**: Gameplay event schemas and game state snapshot schemas are injected into the OpenAPI spec by `scripts/generate_openapi.py` via `GameplayEventSchema.registered_schemas()` and `SSEExposed.registered_schemas()`. The existing `openapi-typescript` pipeline (`openapi.yaml → schema.d.ts`) then generates TypeScript types. `mobile/src/types/gameplay.ts` provides short aliases (e.g. `PlayerLocationDelta` → `S[‘PlayerLocationEvent’]`). Adding a new event class is sufficient — it auto-registers and appears in the spec on next regen.
  - **`SSEExposed` mixin** (`hideandseek.schemas.response`): marks `HiderGameStateResponse` and `SeekerGameStateResponse` for OpenAPI injection (they aren’t on REST routes). Sub-types (`GamePlayer`, `HiderActiveQuestion`, etc.) are pulled in automatically via `$defs` hoisting.
  - **Enriched question events**: Fields are placed on the event where they become *known*. `QuestionAskedEvent` carries ask-time fields: `parameters` (typed `QuestionEventParams` discriminated union), `seeker_location_start`, `asked_at`, `ask_count`, `sequence`. `QuestionAnswerableEvent` carries `seeker_location_end` (thermometer lock-in). Answered events carry only the answer-time delta. History entries in game state snapshots carry **both** ask-time and answer-time fields (enriched to replace the removed question GET endpoints). `HiderQuestionHistoryEntry` includes `parameters`, `seeker_location_start/end`, `sequence`, `ask_count`, `asked_at` plus answer-time hider data. `SeekerQuestionHistoryEntry` includes `sequence`, `ask_count`, `asked_by`, `asked_at` plus exclusion geometry.
  - **Question parameter models** (`hideandseek_core.broadcast.events`): `RadarEventParams`, `ThermometerEventParams`, `FeatureEventParams`, `TentacleEventParams` — standalone frozen Pydantic `BaseModel` subclasses with `Literal` type discriminators (`type: Literal[‘radar’] = ‘radar’`). `build_event_params(question)` factory constructs the appropriate variant from the Question ORM model’s param relationships. `TentacleEventParams` reads `poi_names` from the model (denormalized at ask time — no DB queries in event builders). Serialized automatically via `.model_dump(mode=’json’)` in `emit_gameplay()`.
  - **Mutation endpoints return 204**: `POST /questions/*` (ask, lock-in, answer, veto, abandon, randomize), `POST /hider-station`, `POST /expand-hiding-zone`, `POST /end`, and `POST /found` + `POST /found/confirm` + `POST /found/reject` all return 204 with no body. State updates flow to clients exclusively through SSE events. Push notifications remain as supplementary wake-up alerts.
  - **Two-party game completion** (`POST /found`, `/found/confirm`, `/found/reject` on `routers/endgame.py`): seeker claims found when inside the hiding zone → server records `found_claim_at`/`found_claim_player_id`, schedules `auto_dismiss_found_claim` at T+120s (`task_id=found_claim:<game_id>`), emits `FoundClaimEvent` (with `deadline_utc = found_claim_at + FOUND_CLAIM_TIMEOUT_SECONDS`) to **both** SSE channels so the claiming seeker can present a blocking waiting modal with the same authoritative countdown the hider uses. Hider push still fires. Any hider confirms → clears claim, sets `end_reason = EndReason.found`, transitions to `finished`, emits `GameEndedEvent` (both channels) + push. Any hider rejects → clears claim, emits `FoundClaimRejectedEvent` (seeker channel) + seeker push. If no hider acts in 2 min → worker fires `FoundClaimExpiredEvent` (both channels) + push. Claim validators live in `validators.py` (`validate_found_claim`, `validate_found_decision`); zone check uses `seeker_inside_hiding_zone()` from `hideandseek_core.logic.endgame`.
  - **`publish_sse(channel: SseChannel, ...)`** (`hideandseek_core.broadcast.emit`): low-level Redis publish shared by both `emit_gameplay` (core) and `emit` (server lobby). `SseChannel` is a NamedTuple of `(pubsub, seq)` keys — the publish is a single Lua `INCR` + `PUBLISH` so each message's sequence matches its delivery order. Channel helpers: `lobby_channel()`, `hider_channel()`, `seeker_channel()` — all return `SseChannel`.
  - **SSE sequence numbering & gap detection**: Every published event carries a per-channel monotonic sequence in its envelope; `subscribe.py` strips it out and sets the SSE `id:` field on each frame. The initial `game_state` frame's `id:` is the channel counter's value at subscribe time (`GET <seq_key>`); the forwarding loop drops any subsequent event with `seq <= snap_seq` so the client sees a clean monotonic stream from snapshot onwards. Mobile clients track the last-seen id per connection and reconnect when they see a gap (`got > expected+1`) — the reconnect yields a fresh snapshot and resets the baseline. No replay endpoint or event log; the snapshot is the recovery path. Lobby, hider, and seeker channels each have independent counters (`game:{id}:lobby:seq`, `game:{id}:hider:seq`, `game:{id}:seeker:seq`).
  - **`Question.slot_index`** — stored at ask time from `InventorySlot.slot_index`. Used in gameplay state question schemas.
  - **Configurable game parameters**: `POST /games` accepts optional `size` (small/medium/large — not special), `hiding_time_min`, and `base_question_delay_min` overrides. Three-level fallback: request → map → code default (by size). `Game.size` is stored on the game (can differ from `GameMap.size`), used by `effective_hiding_zone_radius_m()`. `MapSummary` exposes nullable `default_hiding_time_min` and `default_base_question_delay_min` for client-side default computation. Inventory stays map-based (not affected by game size override).
  - **Inventory slots**: `InventoryResponse` groups slots by question type: `radar_slots`, `thermometer_slots`, `matching_slots`, `measuring_slots`, `tentacles_slots`, `photo_slots`. Tentacles slots come from `GameMap.tentacle_categories` (list of `{category, distance}` dicts). Each entry creates one `InventorySlot` with `question_type=tentacles`. Photo slots come from `get_default_inventory(size)['photos']`; each entry creates one `InventorySlot` with `question_type=photo` and a `photo_subject` drawn from the size-gated `PhotoSubject` enum. `SlotResponse` carries a nullable `photo_subject` for photo slots (null on all other types).
  - **Location update processing**: `POST /location` delegates all business logic to `process_location_update()` in `core/logic/location.py`, which returns a `LocationEnrichment` dataclass. The router dispatches SSE events and push notifications based on the result. This keeps the router thin (HTTP validation + event dispatch) while core owns the decision logic.
  - **Enriched hider location events**: `PlayerLocationEvent` carries optional fields (`candidate_stations`, `not_in_zone`, `computed_answer`, `freeze_departed`) for hider events only — all `None` for seeker events. Computed by `process_location_update()` in core. `candidate_stations` populated when election is `pending` or `ambiguous`, `not_in_zone` after election, `computed_answer` when an answerable question exists, `freeze_departed` when `proximity_tier == entered`. Same fields on `HiderGameStateResponse` for SSE reconnection. Computation functions live in core: `compute_candidate_station_ids()`, `compute_not_in_zone()`, `compute_freeze_departed()` in `logic/station.py`; `preview_answer()` in `logic/answer.py`.
  - **Proximity tier tracking**: On every seeker location update during seeking (after station election), `process_location_update()` calls `evaluate_proximity()` from core. If the tier changes, the router emits `ProximityEscalatedEvent` or `ProximityDeescalatedEvent` to the hider SSE channel and dispatches a hider-only push notification. `HiderGameStateResponse` includes `proximity_tier` for SSE reconnection hydration. Seekers receive no proximity information. See `core/logic/proximity.py` for the two-phase escalation/de-escalation algorithm.
  - **Hider freeze mechanic**: When `proximity_tier` escalates to `entered`, `process_location_update()` captures each hider's position in `Player.freeze_location`. On de-escalation from `entered`, freeze locations are cleared. During `entered` tier, hider location updates compute `freeze_departed` (hiders >50m from freeze position). Edge-triggered push notification fires when a hider transitions from not-departed to departed, targeting all hiders. `freeze_departed` is on both `PlayerLocationEvent` and `HiderGameStateResponse`.
