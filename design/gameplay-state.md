# Gameplay State & SSE

> Status: **Draft**
> Last updated: 2026-03-28

Server changes to support the gameplay screen. Covers role-specific game state SSE endpoints, dual-channel broadcasting with publish-side visibility, location broadcasting, and simplified REST responses.

Depends on: `lobby-server.md` (broadcast infrastructure, SSE patterns, Redis pub/sub).

---

## 1. Design Principles

### State endpoint = SSE endpoint

Each role gets a single SSE endpoint that delivers the full state snapshot on connect, then streams role-appropriate deltas. No separate REST "get state" + SSE "get events" — the SSE connection IS how you get the state. To refresh, reconnect.

This mirrors the lobby pattern (`GET /lobby/events` sends `game_state` then streams deltas), extended to two role-specific endpoints:

- `GET /games/{id}/hider-state` — hider's world view
- `GET /games/{id}/seeker-state` — seeker's world view

### No parallel data structures

The state avoids separate "roster" and "positions" arrays. **Location lives on the player object.** Players are split into `hiders` and `seekers` lists, each carrying identity + last known position (where visible). SSE deltas update players in-place — one source of truth.

### State vs utilities

**State** is the game's current condition — everything the client needs to render the screen and can maintain from SSE deltas: player positions, question lifecycle, exclusion zones, inventory. State is managed entirely through the SSE connection.

**Utilities** are on-demand calculations that the client requests when needed: candidate stations (filtered by exclusions), endgame exclusions (intersected with hiding zone), nearby stations (spatial query). These stay as separate GET endpoints — they're tools in the utility belt, not core game state.

### Visibility at publish, not subscribe

Two Redis channels — one per role. The **publisher** decides which channel(s) each event goes to. SSE endpoints are dumb pipes: subscribe to their channel, forward everything. No per-connection state, no filtering logic on read.

### REST endpoints ACK, SSE delivers state

With SSE managing all state updates, REST mutation endpoints (ask, answer, veto, abandon, lock-in) can return simple ACKs (204 or minimal confirmation). The client's state update comes from the SSE event, not the REST response. This eliminates double-handling and simplifies the client: fire the REST call, wait for the SSE event to update local state.

---

## 2. Player Representations

### `GamePlayer` — a player with location (used where positions are visible)

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | |
| `name` | str | |
| `color` | PlayerColor | |
| `role` | PlayerRole | |
| `coordinates` | GeoJSON Point \| null | Last known position (null if not yet reported) |
| `timestamp` | datetime \| null | Time of last location report |

### `RosterPlayer` — a player without location (used where positions are hidden)

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | |
| `name` | str | |
| `color` | PlayerColor | |
| `role` | PlayerRole | |

Two distinct types because seekers must not receive hider coordinates — not even null-valued fields that imply position tracking.

---

## 3. SSE State Endpoints

### `GET /games/{game_id}/hider-state`

SSE endpoint for hiders. Sends full state on connect, then streams hider-relevant deltas. Requires hider auth (`X-Player-Id` + `X-Player-Secret`). Returns 409 if game is not in `hiding` or `seeking` status.

Subscribes to: `game:{game_id}:hider-events`

**Initial `game_state` event payload: `HiderGameStateResponse`**

| Section | Field | Type | Notes |
|---------|-------|------|-------|
| **Game** | `game_id` | UUID | |
| | `phase` | `hiding` \| `seeking` | Current `GameStatus` |
| | `hiding_time_min` | int | For countdown computation |
| | `hiding_started_at` | datetime | Start of hiding phase |
| | `seeking_started_at` | datetime \| null | Start of seeking phase (null during hiding) |
| | `base_question_delay_min` | int | Auto-answer timer duration |
| | `distance_convention` | `metric` \| `imperial` | From GameMap |
| **Map** | `boundary` | GeoJSON Polygon | Game map boundary |
| | `districts` | list[DistrictResponse] | Boundary + name + class |
| | `stops` | list[StopResponse] | All playable stops: id, name, coordinates |
| **Players** | `self_player_id` | UUID | Caller's player ID |
| | `hiders` | list[GamePlayer] | All hiders with last known positions (including self) |
| | `seekers` | list[GamePlayer] | All seekers with last known positions |
| **Station** | `station_election_status` | StationElectionStatus | `pending`, `elected`, `auto_assigned`, `ambiguous` |
| | `hider_station_id` | UUID \| null | Assigned station (once elected/assigned) |
| **Questions** | `active_question` | HiderActiveQuestion \| null | Current unanswered question (if any) |
| | `question_history` | list[HiderQuestionHistoryEntry] | All resolved questions |

### `GET /games/{game_id}/seeker-state`

SSE endpoint for seekers. Sends full state on connect, then streams seeker-relevant deltas. Requires seeker auth. Returns 409 if game is not in `hiding` or `seeking` status.

Subscribes to: `game:{game_id}:seeker-events`

**Initial `game_state` event payload: `SeekerGameStateResponse`**

| Section | Field | Type | Notes |
|---------|-------|------|-------|
| **Game** | `game_id` | UUID | |
| | `phase` | `hiding` \| `seeking` | |
| | `hiding_time_min` | int | |
| | `hiding_started_at` | datetime | |
| | `seeking_started_at` | datetime \| null | |
| | `base_question_delay_min` | int | |
| | `distance_convention` | `metric` \| `imperial` | |
| **Map** | `boundary` | GeoJSON Polygon | |
| | `districts` | list[DistrictResponse] | |
| | `stops` | list[StopResponse] | All playable stops |
| **Players** | `self_player_id` | UUID | |
| | `hiders` | list[RosterPlayer] | Hiders — identity only, **no location** |
| | `seekers` | list[GamePlayer] | All seekers with last known positions (including self) |
| **Questions** | `active_question` | SeekerActiveQuestion \| null | Current in-flight question |
| | `question_history` | list[SeekerQuestionHistoryEntry] | Resolved questions with answers + exclusions |
| | `total_exclusion` | GeoJSON \| null | Cumulative exclusion zone |
| **Inventory** | `inventory` | list[InventorySlotResponse] | All slots with current ask counts |

### Separate GETs (Utility Endpoints)

On-demand calculations that stay as separate endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /candidate-stations` | Stops not eliminated by exclusions |
| `GET /endgame-exclusions` | Exclusions intersected with hiding zone |
| `GET /nearby-stations` | Stops near a location |
| `GET /hiding-zone` | Hiding zone polygon for a station |

---

## 4. Question Schemas

### Active Question

**`HiderActiveQuestion`:**

| Field | Type | Notes |
|-------|------|-------|
| `question_id` | UUID | |
| `question_type` | QuestionType | `radar`, `thermometer`, `matching`, `measuring` |
| `status` | QuestionStatus | `asked`, `in_progress`, `answerable` |
| `asked_by` | UUID | Seeker's player ID |
| `slot_index` | int | Which inventory slot was used |
| `question_deadline` | datetime \| null | When auto-answer fires (null if timer hasn't started) |

**`SeekerActiveQuestion`:**

| Field | Type | Notes |
|-------|------|-------|
| `question_id` | UUID | |
| `question_type` | QuestionType | |
| `status` | QuestionStatus | |
| `slot_index` | int | |
| `question_deadline` | datetime \| null | |

### Question History

**`HiderQuestionHistoryEntry`:**

| Field | Type | Notes |
|-------|------|-------|
| `question_id` | UUID | |
| `question_type` | QuestionType | |
| `status` | QuestionStatus | `answered`, `vetoed`, `abandoned` |
| `asked_by` | UUID | |
| `slot_index` | int | |
| `answer` | str \| null | `yes`/`no`/`closer`/`farther`/`null` (null if vetoed/abandoned) |

**`SeekerQuestionHistoryEntry`:**

| Field | Type | Notes |
|-------|------|-------|
| `question_id` | UUID | |
| `question_type` | QuestionType | |
| `status` | QuestionStatus | `answered`, `vetoed`, `abandoned` |
| `slot_index` | int | |
| `answer` | str \| null | |
| `exclusion` | GeoJSON \| null | This question's exclusion zone (null if vetoed/abandoned) |
| `total_exclusion` | GeoJSON \| null | Cumulative exclusion after this question |

The `total_exclusion` on each history entry is a snapshot of the cumulative exclusion at that point — useful for UI scrubbing through question history to see how exclusions built up.

### Question Deadline

Computed, not stored:

```
# Thermometer: deadline starts at lock-in
question_deadline = lock_in_timestamp + game.base_question_delay_min * 60

# All other types: deadline starts at ask time
question_deadline = question.created_at + game.base_question_delay_min * 60
```

Null when no timer is running (thermometer before lock-in).

### Other Substructures

**`StopResponse`:**

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | |
| `name` | str | |
| `coordinates` | GeoJSON Point | |

**`InventorySlotResponse`:**

| Field | Type | Notes |
|-------|------|-------|
| `question_type` | QuestionType | |
| `slot_index` | int | |
| `distance` | float \| null | Radar/thermometer distance (null for custom slot) |
| `category` | FeatureCategory \| null | Matching/measuring category |
| `feature_class` | str \| null | Optional feature subclass |
| `ask_count` | int | Times this slot has been used |

---

## 5. Dual-Channel Broadcasting

### Channels

| Channel | Subscriber |
|---------|------------|
| `game:{game_id}:hider-events` | `GET /hider-state` |
| `game:{game_id}:seeker-events` | `GET /seeker-state` |

### Publish Routing

The publisher decides which channel(s) each event goes to at emit time. SSE endpoints are dumb pipes — subscribe and forward, no filtering.

| Event | Hider Channel | Seeker Channel | Notes |
|-------|:---:|:---:|-------|
| `player_location` (hider) | ✅ | ❌ | Seekers can't see hiders |
| `player_location` (seeker) | ✅ | ✅ | Everyone sees seekers |
| `question_asked` | ✅ | ✅ | |
| `question_answerable` | ✅ | ✅ | |
| `question_answered` | ✅ (no geometry) | ✅ (with geometry) | Different payloads per channel |
| `question_vetoed` | ✅ | ✅ | |
| `question_abandoned` | ✅ | ✅ | |
| `phase_changed` | ✅ | ✅ | |
| `station_election` | ✅ | ❌ | Seekers don't see station status |
| `player_left` | ✅ | ✅ | |

Self-location events are delivered — the client handles them. Simpler than server-side filtering.

### SSE Endpoint Implementation

Both endpoints follow the same pattern:
1. Auth + role check (hider or seeker).
2. Subscribe to the role's Redis channel.
3. Fetch current state from DB, send as `game_state` event.
4. Forward all events from Redis as SSE events. No filtering, no transformation.

---

## 6. SSE Delta Events

### Event Types

**`game_state`** — Full snapshot, sent on connect.
```
event: game_state
data: <HiderGameStateResponse | SeekerGameStateResponse>
```

**`player_location`** — A player reported their position. Client updates the matching player in `hiders` or `seekers`. Client should only update if the event's `timestamp` is newer than the existing value (de-bounce for out-of-order delivery).
```
event: player_location
data: {
  "player_id": "uuid",
  "coordinates": {"type": "Point", "coordinates": [lng, lat]},
  "timestamp": "ISO8601"
}
```

**`question_asked`** — Seeker created a new question. Sets `active_question`. Seekers increment `ask_count` on the relevant inventory slot.
```
event: question_asked
data: {
  "question_id": "uuid",
  "question_type": "radar" | "thermometer" | "matching" | "measuring",
  "status": "asked" | "in_progress" | "answerable",
  "asked_by": "uuid",
  "slot_index": 0,
  "question_deadline": "ISO8601" | null
}
```

**`question_answerable`** — Thermometer lock-in completed. Updates `active_question` status + deadline.
```
event: question_answerable
data: {
  "question_id": "uuid",
  "question_deadline": "ISO8601"
}
```

**`question_answered`** — Hider answered. Clears `active_question`, appends to question history.

Hider channel payload:
```
event: question_answered
data: {
  "question_id": "uuid",
  "answer": "yes" | "no" | "closer" | "farther" | null
}
```

Seeker channel payload:
```
event: question_answered
data: {
  "question_id": "uuid",
  "answer": "yes" | "no" | "closer" | "farther" | null,
  "exclusion": <GeoJSON> | null,
  "total_exclusion": <GeoJSON> | null
}
```

**`question_vetoed`** — Hider vetoed. Clears `active_question`, appends to history (no exclusion).
```
event: question_vetoed
data: {"question_id": "uuid"}
```

**`question_abandoned`** — Seeker abandoned. Clears `active_question`, appends to history (no exclusion).
```
event: question_abandoned
data: {"question_id": "uuid"}
```

**`phase_changed`** — Hiding → seeking transition.
```
event: phase_changed
data: {"phase": "seeking"}
```

**`station_election`** — Hider station election status changed. Hider channel only.
```
event: station_election
data: {
  "status": "elected" | "auto_assigned" | "ambiguous",
  "station_id": "uuid" | null
}
```

**`player_left`** — Player left mid-game. Client removes from the appropriate list.
```
event: player_left
data: {"player_id": "uuid"}
```

### Ordering

Location events use **timestamp-based de-bounce**: the client only updates a player's position if the incoming `timestamp` is newer than the stored value. This handles out-of-order delivery from Redis.

Other events don't need ordering guarantees — questions are serialized (one at a time), phase changes are singular, and player departures are idempotent.

### Publishing Triggers

| Trigger | Event Published |
|---------|-----------------|
| `POST /location` | `player_location` |
| `POST /questions/{type}` (ask) | `question_asked` |
| `POST /questions/thermometer/{id}/lock-in` | `question_answerable` |
| `POST /questions/{id}/answer` | `question_answered` |
| `POST /questions/{id}/veto` | `question_vetoed` |
| `POST /questions/{id}/abandon` | `question_abandoned` |
| `transition_hiding_to_seeking` task | `phase_changed` |
| `auto_answer_question` task | `question_answered` |
| `POST /hider-station` | `station_election` |
| `transition_hiding_to_seeking` task (election) | `station_election` |
| `DELETE /players/{id}` (mid-game) | `player_left` |

### Push Interaction

Push notifications continue alongside SSE — push wakes backgrounded clients, SSE updates foregrounded ones. No changes to push infrastructure.

---

## 7. Simplified REST Responses

With SSE managing state updates, mutation endpoints that trigger SSE events can return ACKs instead of full data. The client's state update comes from the SSE event, not the REST response.

### Endpoints That Become ACKs

| Endpoint | Current Response | New Response | Notes |
|----------|-----------------|-------------|-------|
| `POST /questions/{type}` | `AskQuestionResponse` | 204 | `question_asked` SSE event delivers the data |
| `POST /questions/{id}/answer` | `QuestionDetailResponse` | 204 | `question_answered` SSE event delivers answer + exclusion |
| `POST /questions/{id}/veto` | `QuestionDetailResponse` | 204 | `question_vetoed` SSE event signals the change |
| `POST /questions/{id}/abandon` | `QuestionDetailResponse` | 204 | `question_abandoned` SSE event signals the change |
| `POST /questions/thermometer/{id}/lock-in` | `QuestionDetailResponse` | 204 | `question_answerable` SSE event signals the change |
| `POST /location` | `LocationReportResponse` | 204 | `player_location` SSE events deliver visible positions |
| `POST /hider-station` | `HiderStationResponse` | 204 | `station_election` SSE event delivers the change |

This is a significant simplification — REST becomes "command" (fire and confirm), SSE becomes "query" (observe state). The client doesn't need to reconcile REST response data with SSE event data.

**Failure handling:** If the REST call returns an error (4xx/5xx), no SSE event is published (the action didn't succeed). The client's state remains unchanged. If the REST call succeeds (204) but the SSE event is delayed or lost due to a disconnect, the client will get the correct state on SSE reconnect via the full snapshot.

---

## 8. Location Broadcasting

### Current Flow

```
Client → POST /location → save LocationUpdate → return visible players
```

### New Flow

```
Client → POST /location → save LocationUpdate → 204
                        → publish player_location to channel(s)
```

Channel routing by role:
- Hider reports → hider channel only.
- Seeker reports → both channels.

### No Throttling

Every location report is broadcast. The server does the DB write regardless — publishing to Redis adds negligible cost. Newer positions overwrite older ones client-side (timestamp de-bounce). GPS updates are discrete (1-15 seconds). Server-side debounce can be added later without changing the client contract.

---

## 9. Stops in State Response

There is no single endpoint that returns all playable stops. Current options require a location (`nearby-stations`), are phase-restricted (`candidate-stations`), or omit stops entirely (`/map`).

The state snapshot includes a `stops` field: all stops within the game's playable area (transit dataset stops within the game map boundary, minus excluded stop IDs). This is static for the life of the game — no SSE updates needed. Sent once on connect as part of the `game_state` event.

---

## 10. Broadcast Module Changes

### New Event Dataclasses

```python
@dataclass
class PlayerLocationEvent:
    game_id: UUID
    player_id: UUID
    role: PlayerRole
    color: PlayerColor
    coordinates: Point  # shapely
    timestamp: datetime

@dataclass
class QuestionAskedEvent:
    game_id: UUID
    question_id: UUID
    question_type: QuestionType
    status: QuestionStatus
    asked_by: UUID
    slot_index: int
    question_deadline: datetime | None

@dataclass
class QuestionAnswerableEvent:
    game_id: UUID
    question_id: UUID
    question_deadline: datetime

@dataclass
class QuestionAnsweredEvent:
    game_id: UUID
    question_id: UUID
    answer: str | None
    exclusion: Polygon | MultiPolygon | None  # shapely; seeker channel only
    total_exclusion: Polygon | MultiPolygon | None  # shapely; seeker channel only

@dataclass
class QuestionVetoedEvent:
    game_id: UUID
    question_id: UUID

@dataclass
class QuestionAbandonedEvent:
    game_id: UUID
    question_id: UUID

@dataclass
class PhaseChangedEvent:
    game_id: UUID
    phase: GameStatus

@dataclass
class StationElectionEvent:
    game_id: UUID
    status: StationElectionStatus
    station_id: UUID | None

@dataclass
class GamePlayerLeftEvent:
    game_id: UUID
    player_id: UUID
```

### Channel Routing in `emit()`

```python
def emit(event):
    match event:
        # Existing lobby routing
        case LobbyEvent():
            publish_to(f'game:{event.game_id}:lobby:events', event)

        # Gameplay: role-based channel routing
        case PlayerLocationEvent(role=PlayerRole.hider):
            publish_to(f'game:{event.game_id}:hider-events', event)
        case PlayerLocationEvent(role=PlayerRole.seeker):
            publish_to(f'game:{event.game_id}:hider-events', event)
            publish_to(f'game:{event.game_id}:seeker-events', event)
        case QuestionAnsweredEvent():
            # Hider: answer only (strip geometry)
            publish_to(f'game:{event.game_id}:hider-events', strip_geometry(event))
            # Seeker: answer + exclusion geometry
            publish_to(f'game:{event.game_id}:seeker-events', event)
        case StationElectionEvent():
            publish_to(f'game:{event.game_id}:hider-events', event)
        case GameplayEvent():  # all other gameplay events
            publish_to(f'game:{event.game_id}:hider-events', event)
            publish_to(f'game:{event.game_id}:seeker-events', event)
```

---

## 11. Endpoint Summary

### New Endpoints

| Method | Path | Auth | Phase | Description |
|--------|------|------|-------|-------------|
| `GET` | `/games/{id}/hider-state` | Hider | hiding, seeking | SSE: hider state snapshot + deltas |
| `GET` | `/games/{id}/seeker-state` | Seeker | hiding, seeking | SSE: seeker state snapshot + deltas |

### Modified Endpoints (ACK Responses)

| Method | Path | New Response | SSE Event |
|--------|------|-------------|-----------|
| `POST` | `/games/{id}/location` | 204 | `player_location` |
| `POST` | `/games/{id}/questions/{type}` | 204 | `question_asked` |
| `POST` | `/games/{id}/questions/thermometer/{id}/lock-in` | 204 | `question_answerable` |
| `POST` | `/games/{id}/questions/{id}/answer` | 204 | `question_answered` |
| `POST` | `/games/{id}/questions/{id}/veto` | 204 | `question_vetoed` |
| `POST` | `/games/{id}/questions/{id}/abandon` | 204 | `question_abandoned` |
| `POST` | `/games/{id}/hider-station` | 204 | `station_election` |

### Unchanged Utility Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /candidate-stations` | Stops not eliminated by exclusions |
| `GET /endgame-exclusions` | Exclusions intersected with hiding zone |
| `GET /nearby-stations` | Stops near a location |
| `GET /hiding-zone` | Hiding zone polygon for a station |

---

## 12. New Schema Types

| Type | Kind | Notes |
|------|------|-------|
| `GamePlayer` | Pydantic model | Player with last known location |
| `RosterPlayer` | Pydantic model | Player identity only (no location) |
| `HiderGameStateResponse` | Pydantic model | Full hider state snapshot |
| `SeekerGameStateResponse` | Pydantic model | Full seeker state snapshot |
| `HiderActiveQuestion` | Pydantic model | Active question from hider's view |
| `SeekerActiveQuestion` | Pydantic model | Active question from seeker's view |
| `HiderQuestionHistoryEntry` | Pydantic model | Resolved question (no geometry) |
| `SeekerQuestionHistoryEntry` | Pydantic model | Resolved question with exclusion + total_exclusion |
| `StopResponse` | Pydantic model | Stop id, name, coordinates |
| `InventorySlotResponse` | Pydantic model | Slot with type, distance/category, ask_count |
| `GameplayEventType` | StrEnum | Event type enum for the gameplay SSE channel |

---

## 13. Implementation Cycles

### Cycle 1: State Snapshot + SSE Endpoints

Build both SSE endpoints with initial state delivery. No delta events yet.

- `GamePlayer`, `RosterPlayer`, `StopResponse`, `InventorySlotResponse` schemas.
- `HiderGameStateResponse` and `SeekerGameStateResponse` schemas.
- Question history and active question schemas with computed `question_deadline`.
- Query for all playable stops in a game.
- `GET /hider-state` and `GET /seeker-state` as SSE endpoints with role guards.
- Redis subscription to role-specific channels (no events published yet — just plumbing).
- Tests: correct snapshot content for each role, auth guards, phase guards.

### Cycle 2: Location Broadcasting + ACK Responses

Wire location events and simplify REST responses.

- `GameplayEventType` enum and `PlayerLocationEvent` dataclass.
- `POST /location` publishes `PlayerLocationEvent` via `emit()`, returns 204.
- Dual-channel routing: hider location → hider channel, seeker location → both.
- Tests: hider location not on seeker channel, seeker location on both channels, timestamp ordering.

### Cycle 3: Question + Phase Broadcasting

Wire remaining gameplay events and convert question endpoints to ACKs.

- Remaining event dataclasses.
- Ask endpoints publish `QuestionAskedEvent` → both channels, return 204.
- Lock-in publishes `QuestionAnswerableEvent` → both channels, returns 204.
- Answer publishes `QuestionAnsweredEvent` → hider (no geometry) + seeker (with geometry), returns 204.
- Veto/abandon publish to both channels, return 204.
- `transition_hiding_to_seeking` publishes `PhaseChangedEvent` → both channels.
- Station election publishes `StationElectionEvent` → hider channel only.
- `POST /hider-station` returns 204.
- Mid-game removal publishes `GamePlayerLeftEvent` → both channels.
