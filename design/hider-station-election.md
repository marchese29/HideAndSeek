# Hider Station Election

> Status: **Implementation**
> Last updated: 2026-03-01
> Supersedes: Station Selection section in `endgame.md`

How the hider's station is determined — voluntary election during hiding, automatic
assignment at the hiding-to-seeking transition, and ambiguity resolution.

---

## Overview

A hider's station is the transit stop that defines their hiding zone during seeking.
Today the server auto-assigns the nearest stop when the hiding timer fires. This design
adds three capabilities:

1. **Voluntary election** — hiders can lock in their station during the hiding phase.
2. **Ambiguity handling** — when auto-assignment can't determine a single station, the
   game enters an ambiguous state that the hider must resolve.
3. **Hiding zone visibility** — any player can preview the hiding zone polygon for a given
   station, and query which stations are near an arbitrary location.

---

## Game Mechanics

### Hider group model

Hiders travel as a group. There is one station per game (not per player). All hiders are
expected to be near the same stop. Station validation checks that **every** hider's latest
location is within the hiding zone radius of the requested stop — not just the centroid.

### Election is permanent

Once a hider elects a station (or one is auto-assigned), the choice is final. No
revocation. The hider's physical location after election is irrelevant to the server —
staying in the zone is honor-system between friends.

### No timing restriction

A hider can elect at any point during the hiding phase. Locking in at the starting
station is legal (if unwise).

---

## Station Status

A new `StationElectionStatus` enum on `Game` tracks where the station assignment stands:

| Status          | Meaning                                             |
|-----------------|-----------------------------------------------------|
| `pending`       | Hiding phase, no election yet (default)             |
| `elected`       | Hider chose via the election endpoint               |
| `auto_assigned` | System picked (only one valid candidate at transition) |
| `ambiguous`     | 0 or 2+ valid candidates at transition; needs hider input |

`hider_station_id` remains nullable. It is set when status moves to `elected` or
`auto_assigned`. It stays null while `ambiguous`.

Questions cannot be answered while station status is `ambiguous`. If the auto-answer timer
fires during ambiguity, the server resolves the station first (see Fallback Resolution
below), then computes the answer in the same transaction.

---

## Transition Logic

When the hiding timer fires (`transition_hiding_to_seeking`):

1. If `hider_station_id` is already set (early election) — skip assignment, transition to
   seeking.
2. Fetch latest `LocationUpdate` for every hider.
3. Compute the set of valid candidate stops: stops where **all** hiders' latest positions
   are within `hiding_zone_radius`.
4. Branch on candidate count:
   - **Exactly 1** — auto-assign that stop, status = `auto_assigned`.
   - **0 or 2+** — status = `ambiguous`, push to hiders to resolve.
5. Transition to `seeking` regardless — ambiguity does not block the phase change.

---

## Fallback Resolution

When the auto-answer timer fires and station status is still `ambiguous`, the server
resolves the station using a cascading strategy before computing the answer. All steps
happen in a single transaction to avoid races.

### Cascade

1. **All-hiders-in-radius** — find stops where every hider's latest position is within
   `hiding_zone_radius`. If one or more exist, pick the stop with the smallest maximum
   distance across all hiders (tightest fit).
2. **Any-hider-in-radius** — find stops where at least one hider is within radius. Pick
   the stop with the shortest minimum hider distance.
3. **Closest pair** — no hider is within radius of any stop. Find the nearest
   (stop, hider) pair across all combinations and use that stop.

The cascade prioritizes the "correct" game state (all hiders in zone) before degrading
gracefully to the best available option.

### After resolution

- Set `hider_station_id` to the chosen stop, status = `auto_assigned`.
- Compute the question answer.
- Push to hiders: "Your station was auto-resolved to {stop name}."

---

## Endpoints

### GET /games/{game_id}/nearby-stations

Stateless query returning playable stops within hiding zone radius of a given point, along
with the hiding zone polygon for each stop. Open to all players.

- **Query params**: `lat` (float), `lng` (float)
- **Response**: list of objects, each containing:
  - Stop fields (id, name, coordinates, etc.)
  - `hiding_zone`: GeoJSON polygon — `buffer(stop, hiding_zone_radius)` intersected with
    the game map boundary.
- **No side effects**: pure geometry query, no location update.
- **Constraints**: no role or game-status restriction.

The spatial query: all stops in the map boundary, not in `excluded_stop_ids`, within
`hiding_zone_radius` of the provided point. Uses `ST_DWithin` on geography for metric
accuracy.

### POST /games/{game_id}/hider-station

Elect a station. Hider-only. Permanent.

- **Body**: `{ "station_id": "<stop uuid>", "location": { ... } }`
- **Side effect**: stores a `LocationUpdate` for the caller.
- **Validation**:
  - Game is in `hiding` phase, or station status is `ambiguous`.
  - `hider_station_id` is currently null (not already elected).
  - The requested stop is a playable stop in the map boundary.
  - **Every** hider's latest location (including the just-stored update for the caller) is
    within `hiding_zone_radius` of the requested stop.
- **On success**: sets `hider_station_id`, status = `elected`. Returns hiding zone polygon.
- **Pushes**: notifies all hiders that the station has been locked in.

### GET /games/{game_id}/hiding-zone

Returns the GeoJSON polygon representing the hiding zone around a given station. Open to
all players — seekers use it to preview zones around candidate stations, hiders use it for
their confirmed station.

- **Query param**: `station_id` (UUID) — the stop to compute the zone for.
- **Response**: GeoJSON polygon — `buffer(station, hiding_zone_radius)` intersected with
  the game map boundary.
- **No side effects**: pure geometry query.

### GET /games/{game_id}/hider-station (existing, extended)

Already exists. Hider-only, seeking phase. Extended to include station election status.

- **Response**: `{ "hider_station_id": "<uuid>", "station_election_status": "<status>" }`
- When `ambiguous`: `hider_station_id` is null but the status tells the hider they need to
  resolve via `POST /hider-station`.

---

## Push Notifications

| Event | Trigger | Recipient |
|-------|---------|-----------|
| Station auto-assigned | Transition found exactly one candidate | Hiders |
| Station ambiguous | Transition found 0 or 2+ candidates | Hiders |
| Station elected | Hider locked in via endpoint | All hiders |
| Station auto-resolved | Fallback picked closest during auto-answer | Hiders |

---

## Interaction with Existing Systems

### Questions

Questions cannot be answered while station status is `ambiguous`. The answer validation
layer checks station status and rejects with a clear error. The auto-answer timer handles
ambiguity by resolving the station first (see Fallback Resolution).

### Endgame exclusions

No change. `GET /endgame-exclusions` already takes a `station_id` parameter from the
seeker. The hider's actual station is still hidden from seekers.

### Candidate stations

No change. The seeker's `GET /candidate-stations` endpoint is unaffected — it uses the
long-game exclusion zones, not the hider's actual station.

### Proximity notifications

No change needed. Proximity notifications (future feature) fire based on the confirmed
`hider_station_id`, which is set by the time seeking begins (or resolved via fallback).

---

## Data Model Changes

### Game table

| Field | Type | Change |
|-------|------|--------|
| `station_election_status` | `StationElectionStatus` enum | **New**. Default `pending`. |
| `hider_station_id` | UUID FK → Stop, nullable | Existing, no change. |

### StationElectionStatus enum

```
pending | elected | auto_assigned | ambiguous
```

Added to `models/types.py`.
