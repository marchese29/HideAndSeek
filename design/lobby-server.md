# Lobby Server Changes

> Status: **Draft**
> Last updated: 2026-03-07

Server-side changes to support the game creation and lobby experience. Covers host-as-player semantics, authorization guards, color assignment, player cap, player removal, host transfer, and real-time lobby updates via Server-Sent Events (SSE) over Redis pub/sub.

---

## 1. Host as Player

### Problem

`POST /games` creates a game and records `host_client_id`, but does not create a Player. The host must separately join their own game via the join code — an awkward extra step.

### Change

Add `name` and `device_token` to `CreateGameRequest`. The server auto-creates a Player for the host (with a server-assigned color and `role: null`) and returns `JoinGameResponse` instead of `GameResponse`.

**Updated `CreateGameRequest`:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `map_id` | UUID | yes | |
| `name` | str | yes | Host's player name |
| `device_token` | str \| null | no | APNS token (null if notifications not granted) |
| `device_token_environment` | str | no | Default `"production"` |
| `hiding_time_min` | int \| null | no | Override map default |
| `base_question_delay_min` | int \| null | no | Override map default |
| `excluded_stop_ids` | list[UUID] | no | Default `[]` |
| `excluded_route_ids` | list[UUID] | no | Default `[]` |

**Response** changes from `GameResponse` to `JoinGameResponse` (adds `player_id`).

---

## 2. Authorization Guards

### Self-only player updates

`PATCH /games/{id}/players/{player_id}` must verify that the calling `client_id` matches `player.client_id`. Return 403 otherwise.

Players control their own role, name, and color. Not even the host can change another player's attributes.

### Host-only game start

`POST /games/{id}/start` must verify that the calling `client_id` matches `game.host_client_id`. Return 403 otherwise.

### Known limitation: client_id spoofing

The current auth model (`X-Client-Id` header) means any player who knows another player's `client_id` can impersonate them. This applies to the entire app, not just the lobby. `client_id` values are visible to all players via `PlayerResponse`. A proper fix (server-generated player secret, returned only to the owning client, required on subsequent requests) is tracked separately as a future auth improvement.

---

## 3. Player Colors

### Enum, not free-form

Colors are a fixed palette represented by a `PlayerColor` StrEnum with 12 values. The enum uses semantic names; clients map these to platform-appropriate hex codes for rendering.

```python
class PlayerColor(StrEnum):
    red = 'red'
    blue = 'blue'
    green = 'green'
    orange = 'orange'
    purple = 'purple'
    teal = 'teal'
    pink = 'pink'
    amber = 'amber'
    cyan = 'cyan'
    lime = 'lime'
    indigo = 'indigo'
    coral = 'coral'
```

### Server-assigned on join

When a player joins (or is auto-created as host), the server assigns the first unused color from the palette in declaration order. The player can change their color in the lobby via `PATCH /players/{id}`.

- `JoinGameRequest` has no `color` field — color is always server-assigned.
- `PlayerUpdate.color` accepts a `PlayerColor` value. Returns 409 if the color is taken by another player in the game.
- `PlayerResponse.color` returns the `PlayerColor` enum value.

### DB column

The `Player.color` column changes from `str` to `PlayerColor` (stored as VARCHAR via the existing `StrEnum` type annotation mapping on `Base`). Existing hex values in test fixtures are replaced with enum values.

---

## 4. Player Cap

Games are capped at **12 players** (matching the color palette size). Enforced on `POST /games/join` — return 409 if the game already has 12 players.

---

## 5. Player Removal

### Endpoint

`DELETE /games/{game_id}/players/{player_id}` — available only during `lobby` status.

### Voluntary leave

A player removes themselves (`client_id == player.client_id`).

- If the leaving player is the host and they are the **only player**, the game is dissolved (set to `finished` status).
- If the leaving player is the host and **other players remain**, the request must include a `new_host_id` field (UUID of the player to transfer host to). Returns 422 if `new_host_id` is missing or invalid. The server updates `game.host_client_id` to the new host's `client_id` before deleting the leaving player.

### Host kick

The host removes another player (`client_id == game.host_client_id`, target is not the host). No `new_host_id` needed.

### Effects

- Deletes the Player row, freeing the color for reuse.
- Publishes a `player_left` SSE event.
- If host transferred: also publishes a `host_changed` SSE event.
- Future: persist a "banned" record keyed on `client_id` + `game_id` to prevent rejoin after kick.

---

## 6. Real-Time Lobby Updates via SSE

### Why SSE?

The real-time channel is **server→client only**. All mutations go through REST endpoints. SSE is the natural fit:

- Read-only — no client→server messages needed.
- Simpler protocol: plain HTTP streaming, auto-reconnect built into the spec.
- No upgrade handshake, no ping/pong heartbeat management.

### Why Redis pub/sub?

Multiple server instances can't share in-memory state. A REST mutation on server A must reach SSE clients on server B. Redis pub/sub fans out to all subscribers across all server instances. We already have Redis for Celery.

```
                                    Redis
                                 pub/sub channel:
                              game:{game_id}:lobby:events
                                      |
          ┌───────────subscribe───────┤────────subscribe──────────┐
          |                           |                           |
      Server A                    Server B                    Server C
    SSE → Client 1           REST mutation from            SSE → Client 3
    SSE → Client 2             Client 4 (join)
                                  │
                                  └─ publish event to Redis
```

### Endpoint

```
GET /games/{game_id}/events?client_id={client_id}
Content-Type: text/event-stream
```

**Auth:** Validates that `client_id` is a player in the game. Returns 403 otherwise. The join code exists to prevent random people from seeing games they aren't part of — the SSE endpoint enforces the same boundary.

**`client_id` in query param:** SSE uses a standard HTTP GET, and `EventSource` clients don't support custom headers. The `client_id` UUID is not easily guessable, and mobile SSE clients don't expose URLs in browser history. Acceptable for now; upgrades to a short-lived token exchange when the auth model is improved (see section 2).

**Status checks:** Returns 404 if game not found, 409 if game is not in `lobby` status.

### Connection Lifecycle

1. Client opens SSE connection.
2. Server subscribes to Redis channel `game:{game_id}:lobby:events`.
3. Server fetches current game state from DB and sends it as the initial `game_state` event.
4. Server drains Redis subscription, forwarding events as SSE.
5. On client disconnect: unsubscribe from Redis, clean up.

**Race condition handling:** Subscribe to Redis *before* fetching DB state. Any events published between "subscribe" and "DB fetch" are queued in the Redis subscription buffer. Clients may receive a duplicate (e.g., `player_joined` for someone already in the initial state) — clients must be idempotent (upsert by player ID).

### Event Types

All events use JSON payloads.

**`game_state`** — Full sync, sent on initial connection.
```
event: game_state
data: {"game": <GameResponse>}
```

**`player_joined`** — New player added.
```
event: player_joined
data: {"player": <PlayerResponse>}
```

**`player_updated`** — Player changed name, color, or role.
```
event: player_updated
data: {"player": <PlayerResponse>}
```

**`player_left`** — Player left or was kicked.
```
event: player_left
data: {"player_id": "uuid"}
```

**`host_changed`** — Host role transferred to a different player.
```
event: host_changed
data: {"new_host_player_id": "uuid"}
```

**`game_started`** — Host started the game.
```
event: game_started
data: {"game": <GameResponse>}
```

### Publishing Events

REST endpoints publish to Redis after a successful DB mutation. **Publishing is transactional** — if Redis publish fails, the REST endpoint fails and the DB transaction rolls back. This avoids split-brain states where the DB is updated but subscribers aren't notified.

| Endpoint | Event(s) Published |
|----------|--------------------|
| `POST /games/join` | `player_joined` |
| `PATCH /games/{id}/players/{id}` | `player_updated` |
| `DELETE /games/{id}/players/{id}` | `player_left` (+ `host_changed` if host transferred) |
| `POST /games/{id}/start` | `game_started` |

### Redis Channel

- Channel name: `game:{game_id}:lobby:events`
- Created implicitly on first publish (Redis pub/sub channels are ephemeral).
- No explicit cleanup — when all subscribers disconnect, the channel ceases to exist.
- No message persistence — published messages are dropped if no one is subscribed. This is fine: SSE clients get initial state on connect.

### Broadcast Module

A dedicated `broadcast.py` module owns the publish/subscribe logic. In keeping with the ORM-first convention, publish functions accept ORM model objects (not raw UUIDs) and handle serialization internally.

```python
# broadcast.py

async def publish_player_joined(game: Game, player: Player) -> None:
    """Publish player_joined event. Raises on Redis failure."""

async def publish_player_updated(game: Game, player: Player) -> None:
    """Publish player_updated event. Raises on Redis failure."""

async def publish_player_left(game: Game, player: Player) -> None:
    """Publish player_left event. Called before the Player row is deleted,
    so the ORM object is still available for serialization."""

async def publish_host_changed(game: Game, new_host: Player) -> None:
    """Publish host_changed event. Raises on Redis failure."""

async def publish_game_started(game: Game) -> None:
    """Publish game_started event. Raises on Redis failure."""

async def subscribe_lobby_events(game: Game) -> AsyncGenerator[LobbyEvent, None]:
    """Subscribe to lobby events for a game. Yields parsed events."""
```

### Reconnection

On reconnect, clients get a fresh `game_state` event with full current state. No `Last-Event-ID` support in v1.

---

## 7. Schema Changes Summary

### `CreateGameRequest` (updated)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `map_id` | UUID | yes | |
| `name` | str | yes | **New** — host's player name |
| `device_token` | str \| null | no | **Now optional** — null if notifications not granted |
| `device_token_environment` | str | no | Default `"production"` |
| `hiding_time_min` | int \| null | no | Override map default |
| `base_question_delay_min` | int \| null | no | Override map default |
| `excluded_stop_ids` | list[UUID] | no | Default `[]` |
| `excluded_route_ids` | list[UUID] | no | Default `[]` |

`POST /games` response changes from `GameResponse` to `JoinGameResponse`.

### `JoinGameRequest` (updated)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `join_code` | str | yes | |
| `name` | str | yes | |
| `role` | PlayerRole \| null | no | |
| `device_token` | str \| null | no | Null if notifications not granted |
| `device_token_environment` | str | no | Default `"production"` |

`color` removed — server-assigned from palette.

### `PlayerUpdate` (updated)

| Field | Type | Notes |
|-------|------|-------|
| `name` | str \| null | Optional |
| `color` | PlayerColor \| null | Optional, 409 if taken |
| `role` | PlayerRole \| null | Optional |
| `device_token` | str \| null | Optional — allows setting token after granting notification permissions in the lobby |

### `PlayerResponse` (updated)

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | |
| `name` | str | |
| `color` | PlayerColor | Enum value, not hex |
| `role` | PlayerRole \| null | |

### `RemovePlayerRequest` (new, request body for `DELETE`)

| Field | Type | Notes |
|-------|------|-------|
| `new_host_id` | UUID \| null | Required when host is leaving and other players remain |

### New Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/games/{game_id}/events` | `client_id` query param, must be player | SSE stream of lobby events |
| `DELETE` | `/games/{game_id}/players/{player_id}` | Self or host | Remove player from lobby |

### New Types

| Type | Kind | Values |
|------|------|--------|
| `PlayerColor` | StrEnum | `red`, `blue`, `green`, `orange`, `purple`, `teal`, `pink`, `amber`, `cyan`, `lime`, `indigo`, `coral` |

---

## 8. Dependency Changes

| Package | Purpose | Notes |
|---------|---------|-------|
| `redis` | Async Redis client for pub/sub | Already in stack for Celery; verify `redis.asyncio` is available. |
| `sse-starlette` | SSE response helper for FastAPI | Evaluate vs manual `StreamingResponse`. |

---

## 9. Interaction with Push Notifications

The push notification design (`push-notifications.md`) says "No push" for lobby events. That remains correct — SSE handles lobby updates for foreground clients.

Push remains the right tool for:
- `game_started` — players who backgrounded their phone while waiting.
- All hiding/seeking phase events.

The `game_started` event is delivered through *both* channels: SSE (for clients with the lobby screen open) and push (for backgrounded clients). The client deduplicates by game status.

---

## 10. Implementation Cycles

### Cycle 1: PlayerColor + Host-as-Player + Player Cap + Auth Guards

Sections 1–4 plus authorization guards from section 2. All straightforward REST changes with no new infrastructure.

- Add `PlayerColor` StrEnum (12 values) to types and Player model column.
- Server-assign first unused color on join; color swap via `PATCH` with 409 if taken.
- Update `POST /games` to accept `name`/`device_token`, auto-create host Player, return `JoinGameResponse`.
- Enforce 12-player cap on `POST /games/join` (409 if full).
- Authorization guards: self-only player updates (403), host-only game start (403).
- Update schemas (`CreateGameRequest`, `JoinGameRequest`, `PlayerUpdate`, `PlayerResponse`).

### Cycle 2: Player Removal

Section 5. Isolated unit of logic with several edge cases worth focused testing.

- `DELETE /games/{game_id}/players/{player_id}` endpoint.
- Self-leave: host + only player → dissolve game (set `finished`). Host + others → require `new_host_id`.
- Host kick: host removes another player.
- Frees color for reuse on removal.
- `RemovePlayerRequest` schema (`new_host_id` field).

### Cycle 3: SSE + Redis Pub/Sub

Section 6. Biggest lift, introduces new infrastructure. Depends on cycles 1–2.

- `broadcast.py` module: async publish/subscribe functions accepting ORM objects.
- Redis channel `game:{game_id}:lobby:events`.
- `GET /games/{game_id}/events?client_id=...` SSE endpoint with auth.
- Wire publish calls into join, update, remove, and start endpoints.
- New dependencies: `redis` (async pub/sub), `sse-starlette`.
- Subscribe before DB fetch to handle race conditions; no `Last-Event-ID` in v1.
