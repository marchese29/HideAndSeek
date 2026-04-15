# Core — Shared Business Logic

Shared business logic for the HideAndSeek game. Sits between `hideandseek-models` (ORM) and both `hideandseek-worker` (Celery tasks) and `hideandseek` (server/presentation). Contains no HTTP code, no response schemas, and no Celery tasks. Owns gameplay event production and Redis publishing; lobby presentation (Pydantic schemas, SSE subscriptions) stays in server.

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
  redis_client.py      # Redis client factory (sync + async)
  geo.py               # Pure geodesic distance functions (pyproj)
  geo_helpers.py       # Shapely-to-GeoJSON conversion helpers
  conventions.py       # Metric/imperial conversion, default inventory, resolve_tentacle_distance()
  exclusion.py         # Exclusion zone geometry, boundary computation (incl. tentacles Voronoi), endgame safe_zone
  broadcast/           # Gameplay event production + Redis publishing
    events.py          # Typed gameplay event Pydantic models (frozen, auto-registered for OpenAPI)
    emit.py            # publish_sse(), channel helpers, emit_gameplay()
  queries/             # DB query functions by domain
  logic/               # Business logic (session-free, side-effect-free beyond DB)
    location.py        # process_location_update() — enrichment, proximity, freeze orchestration
```

## Architecture Rules

- **Gameplay events live here, lobby events live in server**: Core defines gameplay event Pydantic models and publishes them to Redis SSE channels via `emit_gameplay()`. Server defines lobby event dataclasses and publishes them via its own `emit()`, which imports `publish_sse` from core. SSE subscription streams and Pydantic game-state snapshots stay in server.
- **No HTTP, no Celery**: Core never imports from `hideandseek.schemas`, `hideandseek.routers`, `hideandseek_worker`, or Celery. It uses Pydantic for gameplay event schemas (auto-injected into OpenAPI) but not for HTTP response schemas.
- **Dependency direction**: `hideandseek-models` ← `hideandseek-core` ← `hideandseek-worker` / `hideandseek` (server). Core never imports from worker or server.
- **Logic layer is the conversion boundary**: `to_meters()` before geo math, `from_meters()` after. Logic functions use `db.register()` for new objects and mutate tracked ORM objects directly.
- **ContextVar session access**: Query functions call `db.get_session()` — no session parameters, no decorators.

## Broadcast

`broadcast/events.py` defines frozen Pydantic models for all gameplay events (question asked/answered/vetoed/abandoned, phase changes, station elections, player locations, player left, host changed, game dissolved, game ended, hiding zone expanded, proximity escalated/deescalated). All gameplay events extend `GameplayEventSchema` which auto-registers them for OpenAPI schema injection via `__init_subclass__`. `game_id = Field(exclude=True)` is on the base — present for construction/routing but excluded from `.model_dump()` and JSON schema. Each question event has a `from_question()` static constructor. `QuestionAskedEvent.from_question()` and `QuestionAnswerableEvent.from_question()` require `base_question_delay_min` kwarg to compute `question_deadline`. Parameter models (`RadarEventParams`, `ThermometerEventParams`, `FeatureEventParams`, `TentacleEventParams`) are standalone `BaseModel` subclasses with `Literal` type discriminators (`type: Literal['radar'] = 'radar'`), pulled into the OpenAPI spec automatically via `$defs` hoisting. `TentacleEventParams` includes `poi_names` denormalized from the model (no DB queries in event builders).

`broadcast/emit.py` provides:
- `publish_sse(channel, event_type, data, *, required)` — low-level Redis publish (used by both core's `emit_gameplay` and server's lobby `emit`)
- `lobby_channel(game_id)`, `hider_channel(game_id)`, `seeker_channel(game_id)` — channel name helpers (used by server's subscribe module)
- `emit_gameplay(event)` — pattern-matches on gameplay event type, calls `.model_dump(mode='json')` for serialization, publishes to the appropriate Redis channels

**Enriched `PlayerLocationEvent`**: Hider location events carry three optional enrichment fields (`candidate_stations`, `not_in_zone`, `computed_answer`), all `None` for seeker events. Populated by the server's location handler and game state builder using core computation functions.

## Logic — Station Enrichment

`logic/station.py` provides station-related computation for both election mechanics and location event enrichment:
- `compute_candidate_station_ids(game)` — stop IDs where ALL hiders are within hiding zone radius. Pre-election only. Reuses `get_stops_within_radius_of_all()`.
- `compute_not_in_zone(game)` — player IDs of hiders outside the hiding zone. Post-election only. Uses geodesic distance (pure math via `geo.distance()`).
- `compute_hider_centroid(game)` — centroid of hiders with recent locations (used as representative hider location for answer previews).

## Logic — Proximity Tier Tracking

`logic/proximity.py` monitors seeker distance rings around the hider's hiding zone:
- `evaluate_proximity(game, reporting_seeker)` — two-phase algorithm: (1) check only the reporting seeker's distance to hider station — if closer than current tier, escalate immediately; (2) if not escalating, query all seekers' latest positions and de-escalate to the closest remaining seeker's tier if it's farther than current. Returns `ProximityResult(old_tier, new_tier)` dataclass with `.changed`, `.escalated`, `.deescalated` properties. Mutates `game.proximity_tier` if changed.
- `_distance_to_tier(distance_m, radius_m)` — maps distance to `ProximityTier` via 1×/2×/4× threshold multipliers of the effective hiding zone radius.

Tier thresholds: `entered` ≤ 1× radius, `near` ≤ 2×, `approaching` ≤ 4×, `none` beyond 4×. Asymmetric rules: escalation on any single seeker, de-escalation requires all seekers unanimous. The router handles SSE event emission and push notification dispatch based on the result.

## Logic — Hider Freeze Mechanic

`logic/station.py` also provides freeze-related functions triggered when `proximity_tier` reaches `entered`:
- `set_freeze_locations(game)` — captures each hider's latest position into `Player.freeze_location`. Called on escalation to `entered`.
- `clear_freeze_locations(game)` — nulls out all hiders' freeze locations. Called on de-escalation from `entered`.
- `compute_freeze_departed(game)` — player IDs of hiders who moved >50m from their freeze position. Used for `freeze_departed` field on `PlayerLocationEvent` and `HiderGameStateResponse`.

## Logic — Location Update Processing

`logic/location.py` orchestrates all business logic for a location update:
- `process_location_update(game, player, coordinates, timestamp)` → `LocationEnrichment` — persists the location, evaluates proximity (seeker path), manages freeze state transitions, and computes hider enrichment fields. Returns a `LocationEnrichment` dataclass; the router dispatches events and push based on the result.
- This module owns the freeze departure edge-trigger detection (`freeze_departure_push` flag on the result).

## Logic — Randomize Powerup

`logic/ask.py` provides `randomize_question(question, game)` — hider terminates an answerable question and the server picks a random replacement slot (same question type, `ask_count == 0`). Restores the original slot's `ask_count`, dispatches to the appropriate `ask_<type>()` function for the replacement. Thermometer replacements start in `in_progress` (seeker must travel + lock in again); all others start `answerable`. The caller (router) handles timer revocation/scheduling and event emission. No new event type — emits a standard `QuestionAskedEvent` for the replacement.

## Logic — Answer Previews

`logic/answer.py` provides both mutating answer functions (`answer_radar`, `answer_thermometer`, etc.) and read-only preview variants (`preview_radar`, `preview_thermometer`, `preview_matching`, `preview_measuring`, `preview_tentacles`). Preview functions compute the same answer string without persisting exclusion zones or mutating the question. `preview_answer(question, hider_location, game)` dispatches to the appropriate preview function by question type.

## Conventions

- Same style as server: single quotes, `from __future__ import annotations`, ruff + pyright.
- Import from submodules directly (e.g., `from hideandseek_core.queries.games import ...`).
