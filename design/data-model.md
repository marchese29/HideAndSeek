# Data Model Design

> Status: **Draft**
> Last updated: 2026-02-10

Server-side data model for the HideAndSeek game. Covers transit data, game maps, games, players, location tracking, and the question/exclusion system.

---

## Transit Data

Imported from GTFS but stored in our own format. A `TransitDataset` is an immutable snapshot — if the source agency updates their feed, import a new dataset rather than mutating an existing one.

### TransitDataset

| Field        | Type     | Notes                                    |
|--------------|----------|------------------------------------------|
| id           | UUID     | PK                                       |
| name         | str      | e.g. "London Underground Jan 2026"       |
| region       | str      | City/region label for browsing           |
| source_url   | str?     | GTFS feed URL, null if hand-curated      |
| imported_at  | datetime |                                          |
| stops        | [Stop]   | Embedded or related                      |
| routes       | [Route]  | Embedded or related                      |

### Stop

| Field       | Type          | Notes                           |
|-------------|---------------|---------------------------------|
| id          | str           | Stable ID (from GTFS or minted) |
| name        | str           |                                 |
| coordinates | GeoJSON Point |                                 |

### Route

| Field  | Type               | Notes                             |
|--------|--------------------|-----------------------------------|
| id     | str                | Stable ID                         |
| name   | str                | e.g. "Central Line"               |
| color  | str                | Hex color for map rendering       |
| type   | str                | metro / bus / tram / rail / ferry  |
| shape  | GeoJSON LineString | Geographic path of the route      |
| stops  | [RouteStop]        | Ordered stop associations         |

### RouteStop

| Field    | Type | Notes                    |
|----------|------|--------------------------|
| route_id | str  | FK                       |
| stop_id  | str  | FK                       |
| sequence | int  | Ordering along the route |

---

## Game Maps

A `GameMap` defines a playable board. It references a `TransitDataset` and layers customization on top: a boundary polygon, stop/route exclusions, district definitions, and default question inventory.

The filtering pipeline for playable stations:

```
Full TransitDataset → spatial filter (boundary) → exclude stops/routes → playable stations
```

### GameMap

| Field              | Type               | Notes                                        |
|--------------------|--------------------|-------------------------------------------------|
| id                 | UUID               | PK                                              |
| name               | str                | e.g. "London Zone 1-3"                          |
| size               | enum               | small / medium / large / special                 |
| transit_dataset_id | UUID               | FK → TransitDataset                             |
| boundary           | GeoJSON Polygon    | Playable area                                   |
| excluded_stop_ids  | [str]              | Stops removed from play                         |
| excluded_route_ids | [str]              | Routes removed from play                        |
| districts          | [District]         | For district-type questions                     |
| district_classes   | [DistrictClass]    | Labels for each tier level                      |
| default_inventory  | QuestionInventory  | Default question pool for games on this map     |
| notes              | str?               | Flavor text, special rules                      |

### District

Districts are hierarchical. The `class` field is an integer tier — smaller numbers are more specific (e.g. neighborhood), larger numbers are broader (e.g. county). The meaning of each tier is map-specific and defined in `district_classes` on the GameMap.

| Field    | Type            | Notes                          |
|----------|-----------------|--------------------------------|
| id       | str             | Unique within the map          |
| name     | str             | e.g. "Zone 1", "Manhattan"    |
| class    | int             | Tier level (1 = most specific) |
| boundary | GeoJSON Polygon |                                |

### DistrictClass

| Field | Type | Notes                                        |
|-------|------|----------------------------------------------|
| class | int  | Tier level, matches District.class           |
| label | str  | Human-readable name, e.g. "Borough", "Zone" |

---

## Games and Players

### Game

| Field      | Type              | Notes                                           |
|------------|-------------------|-------------------------------------------------|
| id         | UUID              | PK                                              |
| map_id     | UUID              | FK → GameMap                                    |
| status     | enum              | lobby / active / finished                       |
| join_code  | str               | Short code for players to join                  |
| timing     | TimingRules       | Timing configuration                            |
| inventory  | QuestionInventory | Available questions (copied from map, editable) |
| created_at | datetime          |                                                 |

A game can be cloned from a previous game with roles rotated via a copy/rotate operation. This creates a new game instance — rounds are not modeled within a single game.

### TimingRules

All durations in **minutes**.

| Field                       | Type         | Notes                                            |
|-----------------------------|--------------|--------------------------------------------------|
| hiding_time_min             | int          | Time hider has before seeking begins             |
| location_question_delay_min | int          | How long hider has to answer a location question |
| move_hide_time_min          | int          | Time to relocate when playing a "move" card      |
| rest_periods                | [RestPeriod] | Times of day when play stops                     |

### RestPeriod

| Field | Type | Notes                      |
|-------|------|----------------------------|
| start | time | e.g. 22:00 — play stops   |
| end   | time | e.g. 07:00 — play resumes |

### QuestionInventory

Defines the pool of questions available in a game. Each entry is usable once. The map provides defaults; the game can override.

| Field        | Type           | Notes                                        |
|--------------|----------------|----------------------------------------------|
| radars       | [DistanceSlot] | Fixed-distance radars plus one custom slot   |
| thermometers | [DistanceSlot] | Fixed min-travel distances plus one custom   |

More question types (cardinal, district, etc.) to be added later.

### DistanceSlot

| Field      | Type | Notes                                                            |
|------------|------|------------------------------------------------------------------|
| distance_m | int? | Fixed distance in meters, null = custom (seeker picks at ask time) |

### Player

| Field   | Type | Notes                                              |
|---------|------|----------------------------------------------------|
| id      | UUID | Client-generated, stored on device                 |
| game_id | UUID | FK → Game                                          |
| name    | str  |                                                    |
| color   | str  | Hex color, unique within game                      |
| role    | enum | hider / seeker                                     |

No authentication. The client generates a UUID on first launch and sends it with every request. If the device is wiped, the player is gone — acceptable for a casual session-based game.

---

## Location Tracking

All players report location. Visibility rules are enforced by the server:
- **Hiders** see seeker locations in real time.
- **Seekers** see nothing (hider locations are hidden during gameplay).

### LocationUpdate

| Field       | Type          | Notes           |
|-------------|---------------|-----------------|
| player_id   | UUID          | FK → Player     |
| game_id     | UUID          | FK → Game       |
| timestamp   | datetime      |                 |
| coordinates | GeoJSON Point |                 |

Append-only log. Useful for post-game replay and third-party spectating in the future.

---

## Questions and Exclusion Zones

Questions are the core game mechanic. Each question is a **stateful process**, not an instant event. Each question can only be asked once — using it spends it from the game's inventory.

### Question Lifecycle

```
asked → [in_progress] → answerable → answered
```

1. **Asked** — A seeker initiates a question. The seeker team's location is snapshotted (average of all seekers' last known positions).
2. **In-progress** — Only for question types that require additional seeker action (e.g., thermometer: seeker must travel at least X km from their start point). The app tracks progress toward the condition. The hider is not yet on the clock.
3. **Answerable** — Conditions met (e.g., seeker locked in their second location). The hider's answer timer starts. The hider sees a real-time preview of what the answer *would be* if they answered right now — computed on the fly, **not stored**.
4. **Answered** — The hider taps "answer now." Their location is snapshotted, the server computes the definitive answer, and the exclusion zone is locked in.

For simple question types (radar), the lifecycle skips straight from `asked` to `answerable`.

### Question

| Field                 | Type          | Notes                                           |
|-----------------------|---------------|-------------------------------------------------|
| id                    | UUID          | PK                                              |
| game_id               | UUID          | FK → Game                                       |
| sequence              | int           | Ordering within the game for chronological retrieval |
| type                  | enum          | radar / thermometer (more later)                |
| status                | enum          | asked / in_progress / answerable / answered     |
| parameters            | JSON          | Type-specific (see below)                       |
| asked_by              | UUID          | FK → Player (the seeker who asked)              |
| asked_at              | datetime      |                                                 |
| seeker_location_start | GeoJSON Point | Seeker team position at ask time                |
| seeker_location_end   | GeoJSON Point?| Nullable. Second seeker position (thermometer)  |
| answered_at           | datetime?     |                                                 |
| hider_location        | GeoJSON Point?| Hider position when they locked in the answer   |
| answer                | str?          | Server-computed: yes / no / closer / farther    |
| exclusion             | GeoJSON?      | The resulting exclusion geometry                |

### Question Type Details

**Radar** — "Am I within X km of you?"
- Parameters: `{ "radius_m": 3000 }`
- Lifecycle: asked → answerable (immediate) → answered
- Exclusion: circle centered on `seeker_location_start`. Inside if "yes", outside if "no".

**Thermometer** — "I'm going to travel at least X km. Did I get closer or farther?"
- Parameters: `{ "min_travel_m": 500 }`
- Lifecycle: asked → in_progress (seeker traveling) → answerable (seeker locks in second point) → answered
- The seeker moves freely in any direction. The app tracks distance from `seeker_location_start` and unlocks the "lock in" button once the minimum is reached.
- Once locked in, `seeker_location_end` is captured and the hider's answer clock starts.
- Exclusion: perpendicular bisector half-plane between the two seeker points. The "closer" or "farther" side is excluded accordingly.

### Exclusion Zone Ordering

The server returns exclusion zones in chronological order (by `sequence`). Undo/redo is handled entirely client-side by maintaining a cursor over this ordered list. The server has no concept of undo state.
