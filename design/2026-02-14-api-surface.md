# API Surface Design

> Status: **Implementation** (all 16 endpoints implemented; geo math stubbed)
> Last updated: 2026-02-14

REST API surface for the HideAndSeek server, organized by the player interactions that drive each endpoint.

**Push-to-device:** Several interactions require notifying players who may not have the app foregrounded (e.g., "you have a question to answer," "seeking phase has begun"). The mechanism (APNs, Live Activities, etc.) is TBD — this document notes where pushes are needed without specifying how they're delivered.

---

## Conventions

### Client Identity

No authentication. Each device generates a UUID on first launch (`client_id`) and sends it as a header on every request:

```
X-Client-Id: 550e8400-e29b-41d4-a716-446655440000
```

The server resolves the calling player by matching `client_id` + `game_id` to a `Player` record. Endpoints outside a game context (browsing maps, creating a game) use `client_id` only for tracking the creator.

### Response Shape

All responses return JSON. Successful responses return the resource directly (no wrapper). Errors return:

```json
{ "detail": "Human-readable error message" }
```

Standard HTTP status codes: 200 OK, 201 Created, 404 Not Found, 409 Conflict, 422 Unprocessable Entity.

### URL Design

- Resource IDs in URL path segments
- All game-scoped resources nest under `/games/{game_id}/`
- No query parameters for filtering in v1 — lists are small and bounded

### Game States

```
lobby → hiding → seeking → endgame → finished
```

| State | What's happening | Who can act |
|-------|-----------------|-------------|
| `lobby` | Players joining, roles assigned | Host assigns roles, starts game |
| `hiding` | Hiders travel to their hiding spot | No questions allowed; seekers wait |
| `seeking` | Seekers ask questions, narrow the search | Core gameplay loop |
| `endgame` | Seekers at the hider's station; hider must stay put | Location rules change (details TBD) |
| `finished` | Game over, all information revealed | Post-game review and replay |

The `hiding → seeking` transition is time-based (`timing.hiding_time_min`). The server triggers this transition and pushes it to all players. The timer/scheduler design is TBD.

The `seeking → endgame` transition has open questions — it's technically possible the seekers don't know they're in endgame, but the hider must know since their rules change. Details TBD.

The game always ends manually — the official rule is "when the seekers physically spot the hider," which only the players can determine.

---

## Use Case 1: Browse and Select a Map

**Player experience:** The host opens the app and sees a list of available maps — name, size, region. They tap one to see the full detail (boundary on a map, district info) before deciding to create a game on it.

### `GET /maps`

List available maps.

```
Response 200:
[
  {
    "id": "uuid",
    "name": "London Zone 1-3",
    "size": "medium",
    "region": "London"
  }
]
```

### `GET /maps/{map_id}`

Full map detail including geometry for rendering a preview.

```
Response 200:
{
  "id": "uuid",
  "name": "London Zone 1-3",
  "size": "medium",
  "transit_dataset_id": "uuid",
  "boundary": { "type": "Polygon", "coordinates": [...] },
  "districts": [
    { "id": "z1", "name": "Zone 1", "class": 1, "boundary": { "type": "Polygon", ... } }
  ],
  "district_classes": [
    { "district_class": 1, "label": "Zone" }
  ],
  "default_inventory": {
    "radars": [{ "distance_m": 3000 }, { "distance_m": 5000 }, { "distance_m": null }],
    "thermometers": [{ "distance_m": 500 }, { "distance_m": null }]
  },
  "notes": "Classic London underground map."
}
```

This endpoint omits stop/route data. For the full transit overlay, see `GET /games/{game_id}/map`.

---

## Use Case 2: Create a Game

**Player experience:** After picking a map, the host taps "Create Game." They see a join code (e.g., `ABCD`) to share with friends. They can tweak timing rules and the question inventory before anyone joins.

### `POST /games`

Create a new game on a map. Inventory and timing are copied from the map's defaults and can be customized before the game starts.

```
Request body:
{
  "map_id": "uuid"
}

Response 201:
{
  "id": "uuid",
  "map_id": "uuid",
  "status": "lobby",
  "join_code": "ABCD",
  "timing": {
    "hiding_time_min": 30,
    "location_question_delay_min": 5,
    "move_hide_time_min": 15,
    "rest_periods": [{ "start": "22:00", "end": "07:00" }]
  },
  "inventory": {
    "radars": [{ "distance_m": 3000 }, { "distance_m": 5000 }, { "distance_m": null }],
    "thermometers": [{ "distance_m": 500 }, { "distance_m": null }]
  },
  "players": [],
  "created_at": "2026-02-11T10:00:00Z"
}
```

The server generates the `join_code` — a short, unique, human-friendly code (4-6 alphanumeric characters).

---

## Use Case 3: Join a Game

**Player experience:** A player opens the app and enters the join code shared by the host. They pick a display name and color, then land in the lobby.

### `POST /games/join`

Join a game by its join code. The server resolves the code, creates a `Player` record, and returns the game state. Fails if the code is invalid or the game isn't in `lobby`.

```
Request body:
{
  "join_code": "ABCD",
  "name": "Alice",
  "color": "#FF5733"
}

Response 201:
{
  "game": {
    "id": "uuid",
    "status": "lobby",
    "join_code": "ABCD",
    "timing": { ... },
    "inventory": { ... },
    "players": [
      { "id": "uuid", "name": "Alice", "color": "#FF5733", "role": null },
      { "id": "uuid", "name": "Bob", "color": "#3357FF", "role": null }
    ],
    "created_at": "2026-02-11T10:00:00Z"
  },
  "player_id": "uuid"
}
```

The response includes the caller's `player_id` so the client knows its own identity in subsequent requests. The `role` is null until assigned by the host.

**Why `POST /games/join` instead of `POST /games/{game_id}/players`?** The joining player only knows the join code, not the game ID. A dedicated join endpoint avoids a two-step lookup.

---

## Use Case 4: Lobby — Assign Roles and Start

**Player experience:** Everyone is in the lobby. The host sees all players and assigns each one as a hider or seeker. Players poll for updates. When ready, the host starts the game — the hiding phase begins.

### `GET /games/{game_id}`

Fetch current game state. Used for lobby polling, reconnecting, or catching up on any missed changes.

```
Response 200:
{
  "id": "uuid",
  "map_id": "uuid",
  "status": "lobby",
  "join_code": "ABCD",
  "timing": { ... },
  "inventory": { ... },
  "players": [
    { "id": "uuid", "name": "Alice", "color": "#FF5733", "role": "hider" },
    { "id": "uuid", "name": "Bob", "color": "#3357FF", "role": "seeker" }
  ],
  "created_at": "2026-02-11T10:00:00Z"
}
```

### `PATCH /games/{game_id}/players/{player_id}`

Update a player's role, name, or color. In the lobby, the host uses this to assign roles.

```
Request body (all fields optional):
{
  "role": "hider"
}

Response 200:
{
  "id": "uuid",
  "name": "Alice",
  "color": "#FF5733",
  "role": "hider"
}
```

### `POST /games/{game_id}/start`

Transition the game from `lobby` to `hiding`. Hiders have `timing.hiding_time_min` minutes to reach a station before the seeking phase begins.

```
Request body: none

Response 200:
{
  "id": "uuid",
  "status": "hiding",
  ...
}
```

Fails with 409 if not all players have assigned roles, or if the game isn't in `lobby` status.

**Push to all players:** Game has started — hiding phase begins.

The `hiding → seeking` transition happens automatically after `hiding_time_min` elapses. The server is responsible for this transition and pushing it to all players (timer/scheduler design TBD).

---

## Use Case 5: Active Gameplay — Location Reporting

**Player experience:** The map shows positions of visible players. Hiders see all seekers. Seekers see only other seekers. Each player's device reports its own location at a regular interval.

### `POST /games/{game_id}/location`

Report the caller's location and receive the current positions of all visible players. The client calls this at a device-configured interval (with a server-enforced minimum to prevent abuse).

```
Request body:
{
  "coordinates": { "type": "Point", "coordinates": [lng, lat] },
  "timestamp": "2026-02-11T10:05:00Z"
}

Response 200:
{
  "players": [
    {
      "player_id": "uuid",
      "name": "Bob",
      "color": "#3357FF",
      "role": "seeker",
      "coordinates": { "type": "Point", "coordinates": [lng, lat] },
      "timestamp": "2026-02-11T10:05:01Z"
    }
  ]
}
```

The `players` array only includes players visible to the caller based on role visibility rules. Hiders see all seekers; seekers see only other seekers.

The server stores each report as a `LocationUpdate` (append-only log) for post-game replay.

---

## Use Case 6: Load the Game Map

**Player experience:** When the game starts (or when the client initializes), the player sees the full transit map — stations, routes, the game boundary, districts. If the host excluded certain stops or routes for this particular game, those are already filtered out.

### `GET /games/{game_id}/map`

Returns the effective map for this game: the underlying `GameMap` data with stops, routes, and any game-level overrides applied (e.g., additional stop exclusions). This is the single source of truth for what the client should render.

```
Response 200:
{
  "name": "London Zone 1-3",
  "size": "medium",
  "boundary": { "type": "Polygon", "coordinates": [...] },
  "districts": [
    { "id": "z1", "name": "Zone 1", "class": 1, "boundary": { "type": "Polygon", ... } }
  ],
  "district_classes": [
    { "district_class": 1, "label": "Zone" }
  ],
  "stops": [
    {
      "id": "uuid",
      "stable_id": "940GZZLUOXC",
      "name": "Oxford Circus",
      "coordinates": { "type": "Point", "coordinates": [-0.1410, 51.5152] }
    }
  ],
  "routes": [
    {
      "id": "uuid",
      "stable_id": "central",
      "name": "Central Line",
      "color": "#DC241F",
      "route_type": "metro",
      "shape": { "type": "LineString", "coordinates": [...] },
      "stop_ids": ["uuid", "uuid", "uuid"]
    }
  ]
}
```

Excluded stops and routes are omitted from the response — the client renders exactly what it receives. This endpoint can be cached aggressively since the effective map doesn't change during a game.

---

## Use Case 7: Seeker Asks a Radar Question

**Player experience:** The seeker opens their question inventory (part of the game state from `GET /games/{game_id}`) and sees available radar slots: "3 km (×1), 5 km (×1), Custom (×1)." They tap the 3 km radar. A circle appears on the map centered on the seeker team's position. The hider is notified — they see the circle and a live "Yes / No" indicator that updates as they move. The hider taps "Answer Now" to lock in the result. The exclusion zone appears for everyone.

### `POST /games/{game_id}/questions` — Seeker asks

```
Request body:
{
  "question_type": "radar",
  "slot_index": 0
}

Response 201:
{
  "id": "uuid",
  "game_id": "uuid",
  "sequence": 1,
  "question_type": "radar",
  "status": "answerable",
  "parameters": { "radius_m": 3000 },
  "asked_by": "player-uuid",
  "asked_at": "2026-02-11T11:00:00Z",
  "seeker_location_start": { "type": "Point", "coordinates": [lng, lat] },
  "seeker_location_end": null,
  "answered_at": null,
  "hider_location": null,
  "answer": null,
  "exclusion": null
}
```

`slot_index` identifies which inventory slot to spend (0-indexed within the question type's slot list). The server reads the distance from the slot and populates `parameters`. For a custom slot (`distance_m: null`), the client must also provide the distance:

```json
{ "question_type": "radar", "slot_index": 2, "custom_distance_m": 4000 }
```

The `seeker_location_start` is the average position of all seekers at the moment the question is asked. For radar, status goes directly to `answerable` — no seeker travel required.

The server removes the spent slot from the game's inventory.

**Push to hider:** A question has been asked — your answer timer is starting.

### `GET /games/{game_id}/questions/{question_id}/preview` — Hider previews

The hider sees a live preview of what the answer would be if they committed right now. The client polls this while the hider is deciding.

```
Response 200:
{
  "answer": "yes",
  "exclusion": { "type": "Polygon", "coordinates": [...] }
}
```

Computed from the hider's most recent reported location — nothing is stored. Only available when question status is `answerable`.

### `POST /games/{game_id}/questions/{question_id}/answer` — Hider answers

The hider taps "Answer Now." The server snapshots the hider's current location, computes the definitive answer, and locks in the exclusion zone. Irreversible.

```
Request body: none

Response 200:
{
  "id": "uuid",
  "status": "answered",
  "answer": "yes",
  "hider_location": { "type": "Point", "coordinates": [lng, lat] },
  "exclusion": { "type": "Polygon", "coordinates": [...] },
  "answered_at": "2026-02-11T11:02:30Z",
  ...
}
```

**Push to seekers:** A question has been answered — new exclusion zone available.

Note: the `hider_location` field is **not** included in seeker-facing responses. Seekers see the answer and exclusion zone, but not where the hider was standing.

---

## Use Case 8: Seeker Asks a Thermometer Question

**Player experience:** The seeker picks a 500 m thermometer from inventory. Their start position is captured. The app shows a progress bar as the seeker travels — "137 m / 500 m." Once they've traveled far enough, the "Lock In" button activates. The seeker taps it to commit their second position. Now the hider is notified and the answer flow is the same as radar, but with "closer" or "farther" instead of "yes" or "no."

### `POST /games/{game_id}/questions` — Seeker asks

```
Request body:
{
  "question_type": "thermometer",
  "slot_index": 0
}

Response 201:
{
  "id": "uuid",
  "question_type": "thermometer",
  "status": "in_progress",
  "parameters": { "min_travel_m": 500 },
  "seeker_location_start": { "type": "Point", "coordinates": [lng, lat] },
  "seeker_location_end": null,
  ...
}
```

Unlike radar, thermometer questions are created in `in_progress` status. The seeker must travel the minimum distance and lock in before the hider is involved.

Travel progress is tracked **client-side** — the client compares its current position against `seeker_location_start` and renders the progress bar locally. No server calls during travel.

### `POST /games/{game_id}/questions/{question_id}/lock-in` — Seeker locks in

The seeker has traveled the minimum distance and commits their second position.

```
Request body: none

Response 200:
{
  "id": "uuid",
  "status": "answerable",
  "seeker_location_end": { "type": "Point", "coordinates": [lng, lat] },
  ...
}
```

The server validates that the distance between `seeker_location_start` and the seeker's current reported position meets `min_travel_m`. Returns 409 if the minimum hasn't been reached.

**Push to hider:** A question is ready for your answer — timer starting.

### Preview and answer

Same flow as radar (Use Case 7). The hider polls `GET .../preview` to see a live "closer / farther" indicator, then calls `POST .../answer` to lock it in. The exclusion zone is a half-plane defined by the perpendicular bisector of the two seeker positions.

---

## Use Case 9: View the Question Map

**Player experience:** At any point during the game, the player sees all past exclusion zones overlaid on the map — circles, half-planes — showing the narrowing search area. They can scroll through the question history to review each one.

### `GET /games/{game_id}/questions`

Full chronological list of all questions in the game.

```
Response 200:
[
  {
    "id": "uuid",
    "sequence": 1,
    "question_type": "radar",
    "status": "answered",
    "parameters": { "radius_m": 3000 },
    "asked_by": "player-uuid",
    "asked_at": "2026-02-11T11:00:00Z",
    "seeker_location_start": { "type": "Point", "coordinates": [lng, lat] },
    "seeker_location_end": null,
    "answered_at": "2026-02-11T11:02:30Z",
    "answer": "yes",
    "exclusion": { "type": "Polygon", "coordinates": [...] }
  },
  {
    "sequence": 2,
    "question_type": "thermometer",
    "status": "in_progress",
    ...
  }
]
```

In-progress and unanswered questions are included so the client can render their current state (e.g., showing the seeker's start point for a thermometer that hasn't been locked in yet).

Fields like `hider_location` are omitted for seeker-facing responses.

---

## Use Case 10: Game Ends

**Player experience:** When the seekers physically spot the hider, the host manually ends the game. All players see the full picture — every location, every question, the hider's path revealed. They can replay the game on a timeline.

### `POST /games/{game_id}/end`

Transition the game to `finished`. All information is revealed to all players.

```
Request body: none

Response 200:
{
  "id": "uuid",
  "status": "finished",
  ...
}
```

**Push to all players:** The game has ended.

### `GET /games/{game_id}/location-history`

Full location update log for all players, for post-game replay.

```
Response 200:
[
  {
    "player_id": "uuid",
    "coordinates": { "type": "Point", "coordinates": [lng, lat] },
    "timestamp": "2026-02-11T10:05:00Z"
  },
  ...
]
```

Only available when game status is `finished`. During active gameplay, location data is scoped by visibility rules via the `POST /location` endpoint.

---

## Endpoint Summary

| Method | Path | Use Case | Who |
|--------|------|----------|-----|
| `GET` | `/maps` | Browse maps | Any |
| `GET` | `/maps/{map_id}` | View map detail | Any |
| `POST` | `/games` | Create a game | Host |
| `POST` | `/games/join` | Join via code | Player |
| `GET` | `/games/{game_id}` | Get game state | Player |
| `PATCH` | `/games/{game_id}/players/{player_id}` | Assign role | Host |
| `POST` | `/games/{game_id}/start` | Start hiding phase | Host |
| `POST` | `/games/{game_id}/end` | End the game | Host |
| `GET` | `/games/{game_id}/map` | Effective map + transit | Player |
| `POST` | `/games/{game_id}/location` | Report + receive locations | Player |
| `GET` | `/games/{game_id}/questions` | List questions | Player |
| `POST` | `/games/{game_id}/questions` | Ask a question | Seeker |
| `POST` | `/games/{game_id}/questions/{id}/lock-in` | Lock in (thermometer) | Seeker |
| `GET` | `/games/{game_id}/questions/{id}/preview` | Preview answer | Hider |
| `POST` | `/games/{game_id}/questions/{id}/answer` | Answer question | Hider |
| `GET` | `/games/{game_id}/location-history` | Replay data | Player |

---

## Open Questions

- **Host identity:** ~~Resolved~~ — `host_client_id` stored on `Game`. Host-only authorization not yet enforced at the endpoint level (any player can currently start/end/assign roles).
- **Push-to-device mechanism:** Time-sensitive events need to reach backgrounded players. Live Activities (ActivityKit) are a strong fit for a multi-hour game session. APNs for alerts. Design TBD.
- **Timer/scheduler:** The `hiding → seeking` transition is time-based. The server needs a way to schedule this and push it to players. Design TBD.
- **Endgame transition:** How and when does `seeking → endgame` trigger? The hider must know their rules changed, but seekers may not realize they're at the right station. Location update intervals may change. Details TBD.
- **Player removal:** Can the host kick a player from the lobby? Can a player leave mid-game?
- **Game state model update:** ~~Resolved~~ — `GameStatus` enum is now `lobby / hiding / seeking / endgame / finished`.
