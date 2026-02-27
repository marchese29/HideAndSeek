# Game State Endpoint Redesign

> Status: **Implementation**
> Last updated: 2026-02-26

Redesign of game-scoped endpoints to split by role and game phase instead of returning one monolithic response with role-based field filtering.

## Principles

1. **Role = access control.** Role determines *whether you can call* an endpoint, never *what you get back*. No conditional field nulling based on caller role.
2. **Fixed response shapes.** Every endpoint always returns the same shape. No conditional fields based on role, phase, or anything else.
3. **Default-deny on shared endpoints.** The shared question summary uses an explicit whitelist of safe fields. New fields added to the question model are invisible on shared endpoints until consciously included.
4. **Post-game is its own concern.** Replay and reveal are separate endpoints (TBD), not the same endpoints changing shape in `finished` state.

## Current Problems

- `GET /games/{id}` returns inventory, players, timing, hider secrets, and timestamps — all in one response, regardless of phase or role.
- `hider_station_id` is conditionally nulled for seekers in the response schema.
- `hider_location` on questions is conditionally nulled for seekers.
- `FeatureParamsResponse.hider_resolution` leaks the hider's nearest feature and distance to all players.
- `exclusion`/`total_exclusion` on questions gives hiders the seeker's tactical view.
- Any new parameter added to questions is automatically visible to all roles.
- Endgame endpoints (`/endgame-exclusions`, `/candidate-stations`) don't check player role at all — hiders can access seeker tactical data.

---

## Endpoint Design

### Shared (any player in the game)

#### `GET /games/{id}` — Game state

Core identity, status, player list, and game inventory (static ruleset). Safe to poll frequently. No role branching.

```json
{
  "id": "uuid",
  "map_id": "uuid",
  "status": "lobby | hiding | seeking | finished",
  "convention": "metric | imperial",
  "join_code": "ABCD | null",
  "timing": { "hiding_time_min": 30, "..." : "..." },
  "players": [
    { "id": "uuid", "name": "Alice", "color": "#FF5733", "role": "hider | seeker | null" }
  ],
  "created_at": "datetime",
  "hiding_started_at": "datetime | null",
  "seeking_started_at": "datetime | null",
  "inventory": {
    "radar_slots": [
      { "distance": 3.0 },
      { "distance": 5.0 },
      { "distance": null }
    ],
    "thermometer_slots": [
      { "distance": 0.5 },
      { "distance": null }
    ],
    "categories": ["hospital", "school", "park"]
  }
}
```

Inventory is the game's static ruleset — the tools available in this game, set at creation. No IDs, no consumed flags. The client derives what's been spent from the question summary list.

Inventory is public knowledge — hiders can use it to strategize (e.g., deciding what cards to play based on questions asked).

No `hider_station_id` — hiders get that from their own endpoint.

#### `GET /games/{id}/questions` — Question summary list

Lightweight changelog for polling. Both roles use this to detect new activity. Uses an explicit **whitelist** of safe fields — new fields added to the question model do not appear here until consciously included.

```json
[
  {
    "id": "uuid",
    "sequence": 1,
    "question_type": "radar",
    "status": "answered",
    "asked_by": "player-uuid",
    "asked_at": "datetime",
    "answerable_at": "datetime | null",
    "answered_at": "datetime | null",
    "answer": "yes | no | closer | farther | null"
  }
]
```

No parameters, no locations, no geometry. Just enough for a timeline and "has anything new happened?" polling. The hider notices a new ID and fetches the detail endpoint to see what they're answering. The seeker checks the exclusions endpoint for geometry.

Always returns this shape regardless of game phase.

### Hider-only (403 for non-hiders)

#### `GET /games/{id}/hider-station` — Assigned station

The hider's codified station during seeking.

```json
{
  "hider_station_id": "uuid"
}
```

Only meaningful in seeking state (station is assigned at the hiding-to-seeking transition).

#### `GET /games/{id}/questions/{qid}` — Question detail

Full question detail for the hider to understand and answer a question. Returns everything about the question **except** exclusion geometry (`exclusion`, `total_exclusion`). No other field filtering — parameters, seeker locations, hider_location, hider_resolution are all present.

```json
{
  "id": "uuid",
  "sequence": 1,
  "question_type": "radar",
  "status": "answerable",
  "parameters": { "type": "radar", "radius": 3.0 },
  "asked_by": "player-uuid",
  "asked_at": "datetime",
  "seeker_location_start": { "type": "Point", "coordinates": [lng, lat] },
  "seeker_location_end": null,
  "answerable_at": "datetime",
  "answered_at": null,
  "hider_location": null,
  "answer": null
}
```

For matching/measuring, `parameters` includes `seeker_resolution` and `hider_resolution` (populated at answer time). The hider knows their own location — the only information advantage is exclusion geometry, which is excluded.

### Seeker-only (403 for non-seekers)

#### `GET /games/{id}/exclusions` — Tactical map

Exclusion geometry per question — the seeker's narrowing search area. This is the data that hiders must not see during active play.

```json
{
  "exclusions": [
    {
      "question_id": "uuid",
      "sequence": 1,
      "question_type": "radar",
      "exclusion": { "type": "Polygon", "coordinates": ["..."] }
    }
  ],
  "total_exclusion": { "type": "Polygon", "coordinates": ["..."] }
}
```

Seekers don't need a per-question detail endpoint — they get the summary list (what questions exist, what the answers were) plus this endpoint (the geometry).

#### `GET /games/{id}/endgame-exclusions` — Endgame exclusion view

Already exists. Currently has no role gating — needs seeker-only access control added.

#### `GET /games/{id}/candidate-stations` — Candidate stations

Already exists. Currently has no role gating — needs seeker-only access control added.

---

## Unchanged Endpoints

These endpoints are not affected by this redesign:

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/maps`, `/maps/{id}` | Pre-game, no role concerns |
| `POST` | `/games` | Game creation |
| `POST` | `/games/join` | Join by code |
| `PATCH` | `/games/{id}/players/{pid}` | Role assignment in lobby |
| `POST` | `/games/{id}/start` | Start hiding phase |
| `POST` | `/games/{id}/end` | End game |
| `GET` | `/games/{id}/map` | Effective map (cacheable, static) |
| `POST` | `/games/{id}/location` | Location reporting |
| `GET` | `/games/{id}/location-history` | Post-game replay (TBD redesign) |
| `POST` | `/games/{id}/questions/radar` | Ask radar (seeker-only access control) |
| `POST` | `/games/{id}/questions/thermometer` | Ask thermometer |
| `POST` | `/games/{id}/questions/matching` | Ask matching |
| `POST` | `/games/{id}/questions/measuring` | Ask measuring |
| `POST` | `/games/{id}/questions/{qid}/lock-in` | Thermometer lock-in |
| `POST` | `/games/{id}/questions/{qid}/answer` | Hider answers |

---

## Migration Summary

| Current | New |
|---------|-----|
| `GET /games/{id}` returns everything with role branching | Slim: core state + static inventory template. No role branching. |
| `hider_station_id` on game state, nulled for seekers | Removed from game state. Hider-only `/hider-station` endpoint. |
| `GET /games/{id}/questions` returns full detail with role-filtered fields | Whitelist summary (default-deny). Hiders use `/questions/{qid}` for detail. Seekers use `/exclusions` for geometry. |
| `hider_location` nulled for seekers | Not on summary. On hider detail only. |
| `hider_resolution` visible to all | Not on summary. On hider detail only. |
| `exclusion`/`total_exclusion` visible to all | Not on summary or hider detail. Seeker-only `/exclusions` endpoint. |
| `GameResponse.from_model(game, caller_role)` | `from_model(game)` — no role parameter |
| `QuestionResponse.from_model(q, hide_hider_location)` | `QuestionSummary` (whitelist) + `QuestionDetail` (full minus exclusions) — no role parameters |
| Inventory includes IDs, consumed flags, used categories | Static template: distances and available categories only |
| Endgame endpoints have no role check | Seeker-only access control added |

## Open Questions

- **Post-game replay:** How should the post-game "reveal everything" experience work? Separate endpoint(s) designed for replay, not the same endpoints changing shape. TBD.
