# Hider Long-Game Experience

> Status: **Draft**
> Last updated: 2026-04-10

The hider's experience during active gameplay — station selection, zone awareness, departure
warnings, and question answer previews. Covers server-side enrichment of location events and
the mobile UX that consumes them.

Depends on: `hider-station-election.md` (election mechanics), `gameplay-state.md` (SSE
contract), `gameplay-mobile.md` (screen layout), `question-flow-mobile.md` (question banner).

---

## 1. Design Principles

**Push, not poll.** The server computes location-derived context on every hider location
update and pushes it via SSE. The client never polls for nearby stations, zone status, or
answer previews — it reacts to enriched location events.

**Fatten events, don't multiply them.** New contextual data rides on the existing
`PlayerLocationEvent` as optional fields rather than introducing companion event types. Fewer
event types means simpler client state machines and no cross-event timing issues.

**Server is authoritative.** Zone containment checks, candidate station resolution, and
answer computation all happen server-side. The client renders what it's told — no client-side
geo math for gameplay-critical state.

---

## 2. Enriched PlayerLocationEvent

The existing `PlayerLocationEvent` gains three optional fields. Each is populated
conditionally based on game phase, election status, and active question state. All three
fields are null on seeker location events — seekers don't trigger these computations. The
event is only published to the hider SSE channel for hider location updates (existing
behavior), so seekers never see these fields.

### Schema

```python
class PlayerLocationEvent(GameplayEventSchema):
    # existing
    player_id: uuid.UUID
    name: str
    color: PlayerColor
    role: PlayerRole
    coordinates: GeoJSONPoint
    timestamp: datetime

    # --- new fields ---

    # Hiding phase, pre-election: stop IDs where ALL hiders are within hiding_zone_radius.
    # Mirrors the same resolution logic used for auto-assignment at the hiding→seeking
    # transition. Null after election, null for seeker location events.
    candidate_stations: list[uuid.UUID] | None = None

    # Post-election: player IDs of all hiders whose latest location is outside the hiding
    # zone. Empty list means everyone is in the zone. Null before election, null for seeker
    # location events.
    not_in_zone: list[uuid.UUID] | None = None

    # Seeking phase with an answerable question: the answer that would be produced if the
    # question were answered right now, computed from all hiders' current locations.
    # Null when no answerable question, null for seeker location events.
    computed_answer: str | None = None
```

### When each field is populated

| Condition | `candidate_stations` | `not_in_zone` | `computed_answer` |
|-----------|:---:|:---:|:---:|
| Hiding phase, `pending` election, hider moves | list of stop UUIDs | null | null |
| Hiding or seeking phase, station elected, hider moves | null | list of player UUIDs | see below |
| Seeking phase, answerable question, hider moves | null | list of player UUIDs | answer string |
| Seeker moves (any phase) | null | null | null |

### Computation details

#### `candidate_stations`

Reuses `get_stops_within_radius_of_all(game, hider_locations, radius_m)` — the same query
the auto-assignment logic runs at the hiding→seeking transition. On every hider location
update during hiding phase with `station_election_status == pending`:

1. Fetch the latest `LocationUpdate` for every hider (including the just-stored one for the
   reporting player).
2. Run the spatial query: stops where all hiders are within `hiding_zone_radius`.
3. Return their UUIDs.

The client already has the full stop list (id, name, coordinates) from the game's static
info, so UUIDs are sufficient to resolve display data.

If no candidates exist (hiders are spread too far apart or not near any stop), the list is
empty — the client can display guidance like "No stops in range — regroup near a stop."

#### `not_in_zone`

On every hider location update after station election:

1. Fetch the latest `LocationUpdate` for every active hider.
2. For each hider, check `ST_DWithin(stop.coordinates, hider_location, radius_m)`.
3. Return player UUIDs of those outside the zone.

An empty list means all hiders are in the zone. The client replaces its zone violation state
on every event — no accumulation, no edge cases with players leaving the game.

#### `computed_answer`

On every hider location update when there is an active question with status `answerable`:

1. Snapshot all hiders' latest locations (same as the real answer flow).
2. Compute the hypothetical answer using the same logic as the real answer functions, but
   without persisting anything.
3. Return the answer string (`"yes"`, `"no"`, `"closer"`, `"farther"`, or the feature name
   for matching/measuring/tentacles).

This requires a read-only variant of the answer computation. The existing `answer_*`
functions mutate the question and persist exclusion zones, so a new set of pure functions is
needed:

```python
def preview_radar_answer(question: Question, hider_location: Point, game: Game) -> str:
    """'yes' if hider within radius, 'no' otherwise."""

def preview_thermometer_answer(question: Question, hider_location: Point) -> str:
    """'closer' if hider nearer to end, 'farther' otherwise."""

def preview_matching_answer(question: Question, hider_location: Point, game: Game) -> str:
    """'yes' if same feature, 'no' if different. Feature name if miss."""

def preview_measuring_answer(question: Question, hider_location: Point, game: Game) -> str:
    """'closer' if seeker closer, 'farther' otherwise."""
```

These live in `core/logic/answer.py` alongside the real answer functions, sharing the same
geo math internals.

---

## 3. Game State Snapshot

The `HiderGameStateResponse` (delivered as the initial `game_state` SSE event on connect)
must include the same enrichment fields so that a reconnecting client has the current state
without waiting for the next location event.

### New fields on `HiderGameStateResponse`

```python
class HiderGameStateResponse(SSEExposed):
    # ... existing fields ...

    # Same semantics as on PlayerLocationEvent — computed at snapshot time
    candidate_stations: list[uuid.UUID] | None = None
    not_in_zone: list[uuid.UUID] | None = None
    computed_answer: str | None = None
```

The snapshot builder (`build_hider_game_state`) computes these using the same functions as
the location update handler — based on the current phase, election status, and active
question at the time of the snapshot.

---

## 4. Server-Side Implementation

### Location update handler changes

The location update handler (`POST /location`) currently stores the update and emits a
`PlayerLocationEvent`. The enrichment logic plugs in between storage and emission:

```python
# After create_location_update(), before emit_gameplay():

candidate_stations = None
not_in_zone = None
computed_answer = None

if player.role == PlayerRole.hider:
    if game.station_election_status == StationElectionStatus.pending:
        # Hiding phase, no election yet — compute candidates
        candidate_stations = compute_candidate_station_ids(game)

    elif game.hider_station_id is not None:
        # Station elected — check zone containment for all hiders
        not_in_zone = compute_not_in_zone(game)

        # If there's an answerable question, preview the answer
        active_q = get_active_answerable_question(game)
        if active_q is not None:
            computed_answer = preview_answer(active_q, game)
```

The computation functions query the DB (latest locations for all hiders, active question) and
return simple values. They live in core — the router calls them, the logic stays clean.

### Hider location computation

The `computed_answer` field requires determining the "hider location" that would be used if
the question were answered now. This must match the real answer flow. Today, `answer_question`
in the router snapshots the hider location at answer time. For multi-hider games, the
location is a representative point (e.g., centroid of all hider positions). The preview
function must use the same methodology.

### Performance

Each hider location update adds:
- **Pre-election**: one spatial query (`get_stops_within_radius_of_all`) — already optimized
  with spatial indexes.
- **Post-election**: one `ST_DWithin` check per hider (trivial).
- **Answerable question**: one distance computation per question type (trivial geo math, no
  DB beyond fetching the question).

At 10-second location intervals with a handful of hiders, this is negligible.

---

## 5. Mobile — Stop Selection Flow

### 5.1. Candidate station awareness (hiding phase)

During the hiding phase before election, each `player_location` event for a hider carries
`candidate_stations` — the list of stop UUIDs where all hiders are currently in range.

The client maintains this list in the gameplay store and uses it to:

1. **Highlight candidate stops on the map.** Candidate stops render with a distinct marker
   style (larger, colored, or pulsing) vs. the default white dots. This gives hiders a
   real-time sense of which stops they're converging on.

2. **Show a status indicator.** The utility belt's state action area shows:
   - "No stops in range" — candidates list is empty. Hiders need to regroup.
   - "{Stop name}" — exactly one candidate. Ready to elect.
   - "{N} stops in range" — multiple candidates. Tappable to see list.

3. **Enable the "Set Stop" action.** The state action button is enabled when at least one
   candidate exists.

### 5.2. Stop selection and election

When the hider taps "Set Stop" (or taps a highlighted candidate on the map):

**If one candidate:** Show a confirmation sheet with the stop name and a preview of the
hiding zone boundary on the map. Confirm → `POST /hider-station`.

**If multiple candidates:** Show a bottom sheet with a scrollable list of candidate stops.
Each row shows the stop name. Tapping a row:
- Highlights that stop on the map with a pin marker.
- Fetches and renders the hiding zone polygon via `GET /hiding-zone?station_id=`.
- Does NOT elect — the hider is previewing.

A confirm button at the bottom of the sheet elects the currently highlighted stop via
`POST /hider-station`. The hider can tap different rows to compare zones before committing.

**On election failure (422):** "Not all hiders are in range" — the candidate list may have
changed between the last location event and the election attempt. The next location event
will carry an updated list.

**On election success:** The `StationElectionEvent` SSE event updates the store. The
candidate list goes null, `not_in_zone` begins appearing on subsequent location events.

### 5.3. Ambiguous resolution (post-transition)

If the hiding timer expires without election and the server sets status to `ambiguous`, the
flow is the same as manual selection but with different entry:

- The `phase_changed` event carries `station_election_status: ambiguous`.
- The client shows an alert or persistent banner: "Multiple stops in range — select your
  station."
- The stop selection sheet opens (or can be reopened from the state action button).
- `POST /hider-station` is still valid during `ambiguous` status.
- The candidate list comes from the location events (same `candidate_stations` field, since
  election status is not yet `elected`).

---

## 6. Mobile — Hiding Zone Visualization

### 6.1. Zone overlay (post-election)

Once the station is elected:

1. Fetch the hiding zone polygon via `GET /hiding-zone?station_id={hider_station_id}`.
2. Render it as a persistent polygon overlay on the map:
   - Semi-transparent fill (e.g., blue at 15% opacity).
   - Solid border stroke.
   - Rendered below player pins, above transit routes (similar z-index strategy as the seeker
     exclusion overlay).
3. The overlay persists for the rest of the game. It is not dismissable.

### 6.2. Map centering

After election, the map camera animates to center on the hiding zone's centroid. The hider
can still pan/zoom freely — this is a default position, not a lock. Subsequent "recenter"
actions (e.g., tapping a recenter button) return to the zone centroid rather than the
player's current position.

---

## 7. Mobile — Zone Departure Warnings

### 7.1. Warning banner

When `not_in_zone` on a location event contains any player IDs, display a warning banner:

- **Single player:** "{Name} has left the hiding zone!"
- **Multiple players:** "{Name1}, {Name2} have left the hiding zone!"
- Banner style: warning/alert color (red or orange background).
- Position: above the utility belt, below the question banner (if present).

### 7.2. Dismissal

The banner dismisses when `not_in_zone` becomes an empty list (all hiders back in zone).
The client replaces the violation set on every location event — no local state accumulation.

### 7.3. Edge cases

- **Player leaves game while out of zone:** They disappear from `not_in_zone` on the next
  hider location event (they're no longer an active hider). Banner updates naturally.
- **Player kicked while out of zone:** Same — `PlayerLeftEvent` removes them from the
  roster, and the next location event's `not_in_zone` won't include them.
- **Self out of zone:** The banner applies to all hiders including the viewer. The hider
  sees their own name if they've wandered out.

---

## 8. Mobile — Question Answer Preview

### 8.1. Computed answer display

When `computed_answer` is present on a location event, display it on the question banner:

- Text overlay on the hider question banner: "Current answer: {answer}"
- Updates on every location event (every ~10 seconds).
- For binary answers: "Yes" / "No" / "Closer" / "Farther".
- For feature-based answers (matching/measuring/tentacles): the feature name.
- Color-coded or styled to distinguish from the actual answer action.

This helps hiders understand how their position affects the answer and make informed decisions
about whether to answer now or reposition first.

### 8.2. Exclusion boundary preview

When a question becomes answerable (`question_answerable` event), the hider should see the
question's exclusion boundary on the map — the same boundary seekers see as a preview.

- Fetch via `GET /questions/preview` using the active question's parameters.
- Render as a non-dismissable overlay (dashed line, similar to seeker preview styling).
- This lets hiders see the dividing line and understand which side of it they're on.
- The preview parameters come from the `QuestionAskedEvent` (which carries `parameters`,
  `seeker_location_start`) and `QuestionAnswerableEvent` (which carries
  `seeker_location_end` for thermometer).

---

## 9. Interaction with Existing Systems

### Station election

This design does not change the election mechanics defined in `hider-station-election.md`.
The `POST /hider-station` endpoint, validation rules, and `StationElectionEvent` are
unchanged. This design adds the client-side UX for invoking those mechanics and the
server-side enrichment that makes them discoverable without polling.

### Question flow

The question banner for hiders (`HiderBanner.tsx`) already handles the full answer/veto/
countdown flow. This design adds the `computed_answer` text overlay and the exclusion boundary
preview — both are additive, no changes to the existing answer/veto actions.

### Location tracking

The `POST /location` endpoint signature and response (204 No Content) are unchanged. The
enrichment happens inside the handler before emitting the SSE event. The mobile location
tracking hook (`useLocationTracking`) requires no changes.

### SSE auto-sync

The new fields on `PlayerLocationEvent` auto-register in the OpenAPI spec via the existing
`GameplayEventSchema` base class. The new fields on `HiderGameStateResponse` auto-register
via the `SSEExposed` mixin. The `openapi-typescript` pipeline generates updated TypeScript
types. No manual type maintenance needed.

### Static game info separation

The `game_state` SSE snapshot currently bundles static map data (boundary, districts, stops,
routes) with dynamic gameplay state (players, questions, election status). The static data
never changes mid-game but is recomputed on every SSE reconnect. A separate endpoint for
static game info (`GET /games/{id}/info` or similar) would let the client fetch this once and
cache it, while the SSE snapshot carries only dynamic state. This is tracked separately as a
prerequisite improvement (see §10).

---

## 10. Suggested Implementation Breakdown

### Prerequisite: Static game info endpoint

Separate static map data (boundary, districts, stops, routes, distance convention, timing
config) from the dynamic SSE game state snapshot into a dedicated `GET` endpoint. The client
fetches this once on game entry, the SSE `game_state` event carries only dynamic state. This
reduces reconnection payload size and clarifies the data lifecycle. **Tracked as a separate
bead.**

### Cycle 1: Enriched location events + game state (server)

Add the three optional fields to `PlayerLocationEvent` and `HiderGameStateResponse`, and wire
the computation into the location update handler and game state builder. This is the
foundation — all mobile work depends on it.

- Add `candidate_stations`, `not_in_zone`, `computed_answer` fields to `PlayerLocationEvent`.
- Add the same three fields to `HiderGameStateResponse`.
- Implement `compute_candidate_station_ids()` — reuse existing spatial query.
- Implement `compute_not_in_zone()` — `ST_DWithin` check per hider.
- Implement answer preview functions — read-only answer computation.
- Wire into `POST /location` handler with conditional logic by phase/status.
- Wire into `build_hider_game_state()` with the same logic.
- Tests for each enrichment path.

### Cycle 2: Stop selection UX (mobile)

The critical path for hider gameplay — hiders can't play without selecting a station.

- Consume `candidate_stations` from location events in gameplay store.
- Highlight candidate stops on map (distinct marker style).
- State action button shows candidate count / name.
- Bottom sheet for multi-candidate selection with zone preview.
- Single-candidate confirmation flow.
- `POST /hider-station` call on confirm.
- Handle `StationElectionEvent` to update store.
- Ambiguous resolution flow (same UI, different entry point).

### Cycle 3: Zone visualization + warnings (mobile)

Post-election map experience.

- Fetch and render hiding zone polygon overlay (semi-transparent fill).
- Center map on zone centroid after election.
- Zone departure warning banner driven by `not_in_zone`.
- Banner dismissal when all hiders return.

### Cycle 4: Answer preview (mobile)

Seeking phase hider enrichment.

- Display `computed_answer` on question banner.
- Fetch and render exclusion boundary preview when question becomes answerable.
- Wire preview parameters from question asked/answerable events.
