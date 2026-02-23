# Endgame Design

> Status: **Implementation**
> Last updated: 2026-02-22

How the game transitions from the long game to the endgame, and how the endgame plays out.

## Implementation Cycles

1. **Endgame re-drawing endpoints** — exclusion view + candidate stations (read-only query endpoints)
2. **Hiding station codification** — auto-select station at hiding→seeking, role-aware visibility
3. **Seeker proximity notifications** — track proximity state, fire push on boundary crossings

---

## Overview

A Hide and Seek game has two conceptual phases:

- **Long game** — seekers narrow down the hider's station using questions with exclusion zones across the full map. The hider is free to move within their hiding zone.
- **Endgame** — seekers are physically at or near the hider's station. The hider must stay put while seekers search for them within a known radius.

The endgame is **not a server-side game state**. The game remains in `seeking` status throughout. Endgame is a client-side lens — seekers decide when they believe they've reached the hider's area and reinterpret exclusion zones accordingly. The server provides the ingredients (hiding zone geometry, per-question exclusion zones) and the client owns the presentation.

---

## Hiding Zone

The hiding zone is a circle centered on the hider's confirmed station with a radius that depends on game size:

| Game size      | Metric  | Imperial |
|----------------|---------|----------|
| Small / Medium | 500m    | 0.25 mi  |
| Large          | 1,000m  | 0.5 mi   |

The radius is overrideable on the `GameMap` definition.

### Data model

`GameMap` gains an optional `hiding_zone_radius` field (in convention units). When null, the code-level defaults above are used based on the map's size and convention.

`Game` gains an optional `hiding_zone_radius_override` field (in convention units). When null, the map's value (or code-level default) is used. This can be updated mid-game — e.g., when a hider draws a card that expands their hiding zone.

The effective hiding zone radius is: `game.hiding_zone_radius_override ?? game_map.hiding_zone_radius ?? code_default(map.size, map.convention)`.

---

## Station Selection

When the hiding timer expires and the game transitions from `hiding` to `seeking`, the server determines which transit stop the hider is at:

1. Look up the hider's latest `LocationUpdate`.
2. Find the nearest playable stop (filtered by the map's boundary and exclusions).
3. That stop is the hider's station — no confirmation needed.

The hider should be near their chosen station when the timer fires. If they're equidistant between two, the closest one wins. No ambiguity resolution mechanic — keeping it simple avoids a state where the game proceeds without a known hiding zone.

The hider can arrive at their spot early, but this is invisible to seekers. Everyone waits for the full hiding timer regardless.

### Data model

`Game` gains:
- `hider_station_id` (UUID, FK → Stop) — set when the hiding timer fires and the game transitions to `seeking`. Non-nullable after that point.
- `hiding_zone_radius_override` (float?) — see Hiding Zone section above.

The hiding zone geometry (circle around the station at the appropriate radius) is derived at query time using PostGIS geography casting — `ST_Buffer(coordinates::geography, radius_meters)::geometry` — which produces an accurate metric circle at any latitude without needing a Python-side projection. Not stored.

---

## GameStatus Changes

The `endgame` value is **removed** from the `GameStatus` enum. The game lifecycle becomes:

```
lobby → hiding → seeking → finished
```

The `seeking` phase covers both the long game and the endgame. The transition to `finished` happens when seekers report finding the hider (see Win Condition below).

---

## Exclusion Zones

### Long game

Exclusion zones are computed against the full map boundary, as today. The `total_exclusion` column on each question stores the cumulative union across all answered questions — this is an optimization for the long-game view.

### Endgame view (server-assisted)

The endgame exclusion view is computed server-side. The client never does geo math — it just renders what the server returns.

The seekers provide two inputs: which station they believe the hider is at, and which question they consider the start of the endgame. The server cannot use the real hider station — that would leak the answer if seekers are near two stations.

- `GET /games/{game_id}/endgame-exclusions?station_id={stop_id}&after_question={sequence}` — returns exclusion zones for all questions with `sequence > after_question`, recomputed against a hiding zone circle centered on the specified station, with a fresh cumulative `total_exclusion` built from those questions only.

Key rules:
- The effective boundary becomes the hiding zone circle (centered on the seeker-specified station) instead of the full map.
- Per-question `exclusion` geometries are intersected with the hiding zone circle.
- **Long-game exclusions do not carry over** — because the hider was free to move within the zone during the long game. Any area excluded during the long game could have been re-entered by the hider before they stopped moving.
- The cumulative `total_exclusion` is rebuilt fresh from the endgame-scoped questions only.

This is a **read-only view** — it doesn't modify stored exclusion data. The full-map exclusions remain on each question for the long-game view. The client toggles between views by either fetching the normal question list (long game) or this endpoint (endgame).

### Candidate stations

A convenience endpoint returns the playable stops that haven't been fully excluded by the long game:

- `GET /games/{game_id}/candidate-stations?offset=0&limit=50` — returns paginated stops whose hiding zone circle is **not fully covered** by the latest `total_exclusion` geometry.

A station is eliminated only when the exclusion zone completely covers the entire hiding zone circle around it — because the hider could be anywhere in that circle, not just at the station point. In PostGIS terms: a stop is still a candidate when `NOT ST_Covers(total_exclusion, ST_Buffer(stop.coordinates::geography, hiding_zone_radius_m)::geometry)`. The `::geography` cast produces an accurate metric circle at any latitude; casting back to `::geometry` allows the `ST_Covers` check against the stored exclusion zone. This runs entirely in PostGIS — no Python-side projection needed.

Note: this query requires PostGIS (not SpatiaLite). Candidate stations is a seeking-phase query for real games, so this is acceptable.

As more questions are answered and the exclusion zone grows, the candidate list shrinks.

---

## Question Inventory

The question inventory does **not** reset for the endgame. Seekers use whatever slots remain from the long game. Short-distance radars and custom-distance questions become valuable in the endgame — spending them wisely during the long game is part of the strategy.

---

## Seeker Proximity Notifications

The server monitors seeker locations relative to the hider's hiding zone and sends push notifications to the hider. These fire on every boundary crossing (not one-shot):

| Event | Trigger | Recipient |
|-------|---------|-----------|
| `seekers_approaching` | A seeker enters the warning radius (2× hiding zone radius) | Hider(s) |
| `seekers_entered_zone` | A seeker enters the hiding zone | Hider(s) |
| `seekers_left_zone` | A seeker leaves the hiding zone (having previously entered) | Hider(s) |

These are informational only — no game state changes. The hider uses them to know when to stay put. Enforcement of the "stay put" rule is honor-system.

Proximity checks run on every seeker `LocationUpdate`. The server tracks the previous proximity state per seeker to detect boundary crossings and avoid duplicate notifications.

---

## Win Condition

The game ends when seekers physically spot the hider. This is an out-of-app event reported through an in-app mechanism:

- `POST /games/{game_id}/end` — transitions the game to `finished`, records the end time.

No time limit on the endgame. The game stays in `seeking` until someone reports it's over.

---

## What Does NOT Change

- **Question lifecycle** — ask, answer, exclusion computation all work the same.
- **Geo math** — all server-side distance calculations remain in meters.
- **Location tracking** — continuous `LocationUpdate` reporting for all players.
- **Visibility rules** — seekers still cannot see hider locations.
