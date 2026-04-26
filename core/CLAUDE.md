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
  db.py                # Engine factory (pool_pre_ping), session ContextVar, register(), session_scope()
  logging.py           # Shared setup_logging() for server / worker / reconciler
  config.py            # SnsConfig (region + APNs/FCM platform app ARNs + endpoint_url)
                       #   + S3Config (photo bucket name + endpoint_url)
  push.py              # SnsProvider (boto3 sns:Publish), create_platform_endpoint(),
                       #   PushService (no-ops when SnsConfig is None)
  s3.py                # get_s3_client() (@cache'd), upload_bytes(),
                       #   get_object_stream(), delete_object() — typed boto3 S3 wrapper
  redis_client.py      # Redis client factory (sync + async)
  geo.py               # Pure geodesic distance functions (pyproj)
  geo_helpers.py       # Shapely-to-GeoJSON conversion helpers
  conventions.py       # Metric/imperial conversion, default inventory (now incl. 'photos' key
                       #   keyed by subjects_for_size), resolve_tentacle_distance(),
                       #   photo timer resolvers (resolve_photo_submit_min / _review_sec and
                       #   their effective_* game-level wrappers), and
                       #   effective_question_deadline(question, game) — photo-aware
                       #   submit window for photo+answerable, base_question_delay_min otherwise
  exclusion.py         # Exclusion zone geometry, boundary computation (incl. tentacles Voronoi), endgame safe_zone
  broadcast/           # Gameplay event production + Redis publishing
    events.py          # Typed gameplay event Pydantic models (frozen, auto-registered for OpenAPI)
    emit.py            # publish_sse(), channel helpers, emit_gameplay()
  queries/             # DB query functions by domain
  logic/               # Business logic (session-free, side-effect-free beyond DB)
    location.py        # process_location_update() — enrichment, proximity, freeze orchestration
    photo.py           # queue/clear/submit transitions for photo-question submission
    push_registration.py  # register_push_endpoint() — inline CreatePlatformEndpoint + upsert
```

## Architecture Rules

- **Gameplay events live here, lobby events live in server**: Core defines gameplay event Pydantic models and publishes them to Redis SSE channels via `emit_gameplay()`. Server defines lobby event dataclasses and publishes them via its own `emit()`, which imports `publish_sse` from core. SSE subscription streams and Pydantic game-state snapshots stay in server.
- **No HTTP, no Celery**: Core never imports from `hideandseek.schemas`, `hideandseek.routers`, `hideandseek_worker`, or Celery. It uses Pydantic for gameplay event schemas (auto-injected into OpenAPI) but not for HTTP response schemas.
- **Dependency direction**: `hideandseek-models` ← `hideandseek-core` ← `hideandseek-worker` / `hideandseek` (server). Core never imports from worker or server.
- **Logic layer is the conversion boundary**: `to_meters()` before geo math, `from_meters()` after. Logic functions use `db.register()` for new objects and mutate tracked ORM objects directly.
- **ContextVar session access**: Query functions call `db.get_session()` — no session parameters, no decorators.

## Broadcast

`broadcast/events.py` defines frozen Pydantic models for all gameplay events (question asked/answered/vetoed/abandoned, phase changes, station elections, player locations, player left, host changed, game dissolved, game ended, hiding zone expanded, proximity escalated/deescalated, found claim/rejected/expired, photo queued/unqueued/submitted). `FoundClaimEvent` carries `deadline_utc` (server-computed `found_claim_at + FOUND_CLAIM_TIMEOUT_SECONDS`) so both roles share one authoritative countdown, and publishes to both channels. All gameplay events extend `GameplayEventSchema` which auto-registers them for OpenAPI schema injection via `__init_subclass__`. `game_id = Field(exclude=True)` is on the base — present for construction/routing but excluded from `.model_dump()` and JSON schema. Each question event has a `from_question()` static constructor. `QuestionAskedEvent.from_question()` and `QuestionAnswerableEvent.from_question()` take `game: Game` and resolve `question_deadline` via `effective_question_deadline(question, game)` — photo-aware (submit window for photo+answerable, `base_question_delay_min` otherwise). Parameter models (`RadarEventParams`, `ThermometerEventParams`, `FeatureEventParams`, `TentacleEventParams`, `PhotoEventParams`) are standalone `BaseModel` subclasses with `Literal` type discriminators (`type: Literal['radar'] = 'radar'`), pulled into the OpenAPI spec automatically via `$defs` hoisting. `TentacleEventParams` includes `poi_names` denormalized from the model (no DB queries in event builders). `PhotoEventParams` carries only the subject enum — human-readable labels resolve client-side.

`broadcast/emit.py` provides:
- `SseChannel` — NamedTuple pairing a Redis pub/sub channel name with its per-channel sequence-counter key (e.g. `pubsub='game:{id}:lobby:events'`, `seq='game:{id}:lobby:seq'`).
- `lobby_channel(game_id)`, `hider_channel(game_id)`, `seeker_channel(game_id)` — return `SseChannel`. Used by both emit sites and server's `subscribe.py`.
- `publish_sse(channel: SseChannel, event_type, data, *, required)` — low-level Redis publish. Runs a Lua script that atomically `INCR`s `channel.seq` and `PUBLISH`es an envelope `{"sequence": N, "event": ..., "data": ...}` in one round-trip. The Lua-atomic path guarantees the sequence embedded in the message matches its pub/sub delivery order even under contention. `event_type` must match `^[a-z][a-z0-9_]*$` (enum values only) since it's spliced into the envelope string.
- `emit_gameplay(event)` — pattern-matches on gameplay event type, calls `.model_dump(mode='json')` for serialization, publishes to the appropriate `SseChannel`(s).

**Per-channel sequencing**: Each of the three channels (lobby, hider, seeker) has its own monotonic counter so clients can detect dropped Redis pub/sub messages. Counters live only in Redis (`INCR` — no DB column); if Redis is flushed, the next reconnect delivers a fresh snapshot. Channel independence is required because the hider and seeker channels carry disjoint event sets (e.g. `StationElectionEvent` hider-only, `FoundClaimRejectedEvent` seeker-only) — a single game-wide counter would appear as permanent gaps on each side.

**Enriched `PlayerLocationEvent`**: Hider location events carry three optional enrichment fields (`candidate_stations`, `not_in_zone`, `computed_answer`), all `None` for seeker events. Populated by the server's location handler and game state builder using core computation functions.

## Logic — Station Enrichment

`logic/station.py` provides station-related computation for both election mechanics and location event enrichment:
- `compute_candidate_station_ids(game)` — stop IDs where ALL hiders are within hiding zone radius. Pre-election only. Reuses `get_stops_within_radius_of_all()`.
- `compute_not_in_zone(game)` — player IDs of hiders outside the hiding zone. Post-election only. Uses geodesic distance (pure math via `geo.distance()`).
- `representative_hider_location(game)` — coordinates of the hider with the most recently updated location (used as the "where the hiders are" stand-in for answer previews). No freshness filter: hiders are expected to stick together, and a stale fix is still the last-known position of the group. Returns `None` only when no hider has any location.

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

`logic/ask.py` provides `randomize_question(question, game)` — hider terminates an answerable question and the server picks a random replacement slot (same question type, `ask_count == 0`). Restores the original slot's `ask_count`, dispatches to the appropriate `ask_<type>()` function for the replacement. Thermometer replacements start in `in_progress` (seeker must travel + lock in again); all others — including photo — start `answerable`. The caller (router) handles timer revocation/scheduling and event emission. No new event type — emits a standard `QuestionAskedEvent` for the replacement.

`ask_photo(game, player, seeker_location, slot)` creates a photo question in `answerable` status immediately — the hider satisfies it by uploading an image (z32.4 cycle). `answerable_at` doubles as the submit-window anchor read by the reconciler. Photo questions expose no preview — `preview_question()` raises `ValueError` for `QuestionType.photo`, which the router surfaces as 422.

## Logic — Photo Submission

`logic/photo.py` owns photo-question state transitions for both hider submission and seeker review (kept out of the already-busy `logic/answer.py`):
- `queue_photo(question, player, object_key)` — persist a queued (not yet submitted) photo. Caller has already uploaded bytes to S3; overwriting an existing key is intentional (the previous S3 object is retained — photos kept forever per design §10).
- `clear_queued_photo(question)` — zero out the queued key and `is_null_answer` flag (DELETE endpoint).
- `submit_photo_question(question, player, *, is_null_answer)` — flip status to `submitted`, stamp `submitted_at` / `submitted_by`. For `is_null_answer=True` also clears any queued key; otherwise the caller must have queued a photo first.
- `auto_submit_photo(question)` — reconciler-driven variant when the submit window expires with content queued; `submitted_by` stays NULL so audit trails distinguish auto from manual.
- `accept_photo(question, game, *, reviewer_id)` — flips `submitted` → `answered`, sets `review_decision = accepted` (manual) or `auto_accepted` (when `reviewer_id is None`), records the photo object key (or `'null'`) as `answer`, no exclusion (`total_exclusion` carries forward via `accumulate_exclusion(game, None)`).
- `reject_photo(question, *, reviewer_id)` — flips `submitted` back to `answerable`; nulls submission state and resets `answerable_at` so the reconciler's submit-window timer restarts.

Reconciler queries in `logic/timers.py`: `find_overdue_answerable_questions` excludes `QuestionType.photo` (those are auto-answered through the dispatcher and would otherwise misfire); `find_overdue_photo_submissions` and `find_overdue_photo_reviews` cover the two photo-specific deadlines (Python-side filter using `effective_photo_submit_min` / `effective_photo_review_sec`). Reused helpers in `logic/answer.py` were renamed from underscore-prefixed (`accumulate_exclusion`, `log_question_answered`) so cross-module callers don't reach for private API.

`conventions.effective_photo_review_sec(game)` and `effective_photo_submit_min(game)` wrap the lower-level `resolve_photo_*` helpers with the standard three-level fallback (request override → map default → code default). Callers on the game critical path should use the `effective_*` wrappers.

## Logic — Answer Previews

`logic/answer.py` provides both mutating answer functions (`answer_radar`, `answer_thermometer`, etc.) and read-only preview variants (`preview_radar`, `preview_thermometer`, `preview_matching`, `preview_measuring`, `preview_tentacles`). Preview functions compute the same answer string without persisting exclusion zones or mutating the question. `preview_answer(question, hider_location, game)` dispatches to the appropriate preview function by question type.

## Logic — Two-Party Game Completion

`logic/endgame.py` also owns the found-claim lifecycle (seeker-in-zone claim → hider confirm/reject, with auto-dismiss as a backstop):
- `seeker_inside_hiding_zone(game, seeker)` — true if the seeker's latest location is within `effective_hiding_zone_radius_m` of `game.hider_station`. Gate for `POST /found`.
- `record_found_claim(game, seeker)` — sets `found_claim_at` + `found_claim_player_id`.
- `confirm_found_claim(game)` — clears claim state, sets `end_reason = EndReason.found`, transitions the game to `finished`.
- `reject_found_claim(game)` — clears claim state; game keeps seeking.
- `expire_found_claim(game) -> bool` — called by the worker's `auto_dismiss_found_claim` task; returns True if a live claim was cleared (no-op if already resolved or game not active).

**`end_reason` is set at every terminal transition.** `confirm_found_claim()` sets `found`; `end_game()` in `routers/games.py` sets `host_ended`; `remove_player()` in `logic/lobby.py` sets `dissolved` at each dissolution site. `GameEndedEvent.reason: EndReason` carries the value on the wire (values: `found`, `host_ended`) so clients can distinguish completion reasons without a follow-up GET. `GameDissolvedEvent.reason: str` stays granular (`last_player` / `no_hiders_remaining` / `no_seekers_remaining`) — orthogonal to the coarse-grained `EndReason.dissolved` stored on the game.

## Logging

`logging.py` provides `setup_logging()` — the single structlog/stdlib config used by all three services (server's lifespan, worker's `setup_logging` Celery signal, reconciler's `main()`). Handles root level, renderer (console vs JSON), `sqlalchemy.engine` routing, and third-party noise suppression. Server wraps this with its own `hideandseek.logging.setup_logging()` to additionally configure the `hideandseek.access` logger for request/response lines. Env vars: `ENV` (`local` / `development` / `production`), `LOG_FORMAT=json`, `SQL_ECHO=1|true|yes`.

**Log level policy** (`logic/` owns the event vocabulary; `queries/` stays silent):
- `logger.info(...)` — business state transitions rendered in every env. Audit-trail granularity: game lifecycle (`game_created`, `game_dissolved`, `game_ended`), player transitions (`player_joined`, `player_removed`, `host_transferred`, `color_swapped`), station election (`station_elected`, `station_fallback_used`), question lifecycle (`question_asked`, `question_answered`, `question_vetoed`, `question_abandoned`, `question_randomized`, `thermometer_locked_in`), proximity/claim changes (`proximity_changed`, `found_claim_recorded|confirmed|rejected|expired`, `hiding_zone_expanded`), push (`push_endpoint_registered`, `push_registration_noop`).
- `logger.warning(...)` — recoverable anomalies. Right now: `station_ambiguous` (logic) and `sse_publish_skipped` / `sse_publish_failed` (broadcast). Don't add new try/except in logic purely to log — exceptions propagate to task/router boundaries where they're already captured.
- `logger.debug(...)` — dev-only internal decision trace. Rendered in `local`/`development` (root DEBUG), elided in production. Used for high-frequency paths that would flood prod: `location_update_processed` (every 10s per player), `proximity_skipped`, `hider_centroid_unavailable`, `freeze_locations_set|cleared`, `question_veto_scheduled`. If a candidate log would fire >once/min per game in steady state, it belongs here.

**Convention** (matches `worker/` and `reconciler/`):
- `logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)` at module top.
- Positional snake_case event name, context as kwargs: `logger.info('station_elected', game_id=str(game.id), stop_id=str(stop.id))`.
- UUIDs stringified; enums passed as `.value`; branching outcomes carry a `reason=` kwarg with a short code.
- Log at the decision site (logic layer), not the mutation site (queries layer) — the "why" lives one layer above persistence. `push_registration.py` is the single exception since it owns both validation and an external side-effect.
- One log per business event, not per mutation. `remove_player()` emits one `player_removed` per branch with `reason=last_player|no_{role}s_remaining|host_transfer|self_leave|host_kick` rather than layering logs at each inner `update_game_status` / `delete_player`.
- Don't duplicate broadcast: `emit.py` already logs Redis degradation; `push.py` already logs dead endpoints / no-tokens.

## Push Notifications — SNS Mobile Push

Single-provider architecture on top of AWS SNS Mobile Push. `SnsProvider` calls `sns:Publish` against a per-device platform endpoint ARN; SNS routes to APNs or FCM based on the endpoint's parent platform application.

- **`SnsConfig`** (`config.py`) — loaded from env vars: `AWS_REGION`, `SNS_APNS_APP_ARN`, `SNS_FCM_APP_ARN`, optional `AWS_ENDPOINT_URL` (LocalStack in dev). `load_sns_config()` returns `None` when any required var is missing — `PushService(None)` then no-ops. Dev without LocalStack works; tests don't need mocks for the config path.
- **Typed client**: boto3 usage goes through `mypy_boto3_sns.SNSClient` (dev dep `boto3-stubs[sns]`). Typed exceptions (`client.exceptions.InvalidParameterException`) are used instead of string-matching on `Error.Code` — the one exception is parsing an existing-endpoint ARN out of the duplicate-registration error message, which AWS only exposes as free text.
- **Envelope**: `_build_envelope()` assembles `{"default", "APNS", "APNS_SANDBOX", "GCM"}` every call and passes `MessageStructure='json'`. APNs payload carries `aps` (alert/sound on standard pushes, `content-available=1` for silent) + `data`. FCM payload carries stringified `data` (FCM requires string values) and optional `notification`.
- **Registration** (`logic/push_registration.py → register_push_endpoint`): routers call this on device-token registration. Calls `sns:CreatePlatformEndpoint` inline, persists the ARN on `DeviceToken`. On the duplicate-endpoint error, parses the existing ARN out of the message and calls `set_endpoint_attributes(Enabled=true, Token=...)`.
- **Dead-token cleanup** — synchronous, not async. When SNS flips an endpoint to disabled (APNs/FCM feedback), the next `sns:Publish` to that ARN raises `EndpointDisabled` (or `NotFound` / `InvalidParameter`). `SnsProvider.send()` collects those ARNs and returns them; the `send_push` worker task calls `delete_device_token_by_endpoint(arn)` inline. Lossy by one delivery — acceptable at hobby scale. A follow-up issue proposes EventBridge/Lambda for eager feedback.

## Photo Storage — S3

Photo questions (HideAndSeek-z32.*) store hider-captured images in a single S3 bucket. No CloudFront, no lifecycle rules yet (cleanup deferred to HideAndSeek-81h).

- **`S3Config`** (`config.py`) — loaded from env vars: `S3_BUCKET_NAME` (required), optional `AWS_ENDPOINT_URL` (LocalStack in dev, shared with SNS). `load_s3_config()` returns `None` when the bucket var is missing. Unlike `SnsConfig`, there is no useful no-op — photo endpoints surface a clean 500/503 when config is absent rather than silently dropping writes.
- **`s3.py`** — module-level functions over a `@cache`-d `get_s3_client(config)`. `upload_bytes()` puts an object with explicit `content_type`; `get_object_stream()` returns the raw `GetObjectOutputTypeDef` TypedDict so callers see typed `Body` / `ContentType` / `ContentLength`; `delete_object()` is idempotent (S3 returns 204 even if the key is absent). No `SnsProvider`-style class — S3 has no stateful registration flow, so plain functions are simpler.
- **Typed client**: `mypy_boto3_s3.S3Client` via `boto3-stubs[s3]` (folded into the existing `boto3-stubs[sns,s3]` dev dep). No `Any` escape hatches.
- **LocalStack** emulates S3 in dev; `infra/localstack/init-aws.sh` creates `hideandseek-photos-local` on first boot. Prod bucket is provisioned by `DataStack` and its name flows into containers as `S3_BUCKET_NAME`.

## Database & Migrations

- **Engine**: `db.get_engine()` (cached, lazy) passes `pool_pre_ping=True` so idle pooled connections survive Aurora Serverless v2 auto-pause in prod. Harmless in dev.
- **Schema ownership**: Alembic owns the production/compose schema. Migration files live at the repo root (`alembic.ini`, `alembic/`); Alembic's `env.py` imports `hideandseek_models` to populate `Base.metadata`. In dev/compose, the `migrate` one-shot service runs `alembic upgrade head` before `api`/`worker`/`reconciler` start. **No DDL at server startup** — the lifespan does not create tables. Tests still use `Base.metadata.create_all()` (`server/tests/conftest.py`) for speed; see the comment there.
- **Adding a migration**: edit models, then from the repo root:
  ```bash
  uv run alembic revision --autogenerate -m "add <thing>"
  # Review the generated file — check for spurious spatial_ref_sys / idx_* ops,
  # spurious PostGIS Tiger geocoder table drops (addr, featnames, county, etc. —
  # installed by CREATE EXTENSION postgis but not in our models), and that
  # ShapelyGeography / ShapelyGeometry columns imported correctly.
  uv run alembic upgrade head
  ```
- **Extending an existing native enum**: adding a value to `questiontype`, `questionstatus`, etc. requires `ALTER TYPE ... ADD VALUE` — autogenerate does not emit this. Wrap in `with op.get_context().autocommit_block():` (the statement can't run inside the outer transaction). Precedent: `alembic/versions/022e24f069e7_add_photo_question_type.py`. Downgrade cannot remove enum values (Postgres limitation) — left values are harmless if unused.
- **PostGIS + custom spatial types**: `env.py` wires two geoalchemy2 integration hooks. `_render_item` emits `from hideandseek_models.geo_types import ShapelyGeography` (or `...ShapelyGeometry`) for autogenerated migrations — geoalchemy2's stock renderer assumes the type class lives in `geoalchemy2`, which breaks for our subclasses. `_compare_type` silences false `modify_type` diffs when DB reflection returns a base `Geography`/`Geometry` against a model-side `ShapelyGeography`/`ShapelyGeometry` (identical DDL). Both hooks are wired into **both** `run_migrations_offline` and `run_migrations_online`.
- **CREATE EXTENSION**: the initial migration (`alembic/versions/c8f7386a37e9_*`) starts with `op.execute('CREATE EXTENSION IF NOT EXISTS postgis')` before any `CREATE TABLE`. Future migrations don't need this.

## Conventions

- Same style as server: single quotes, `from __future__ import annotations`, ruff + pyright.
- Import from submodules directly (e.g., `from hideandseek_core.queries.games import ...`).
