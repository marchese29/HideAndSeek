# Distance Conventions: Metric and Imperial Support

> Status: **Draft**
> Last updated: 2026-02-21

How the game supports both metric (meters) and imperial (miles) distance conventions for radar and thermometer questions.

Addresses:
- **HideAndSeek-obz** — Support metric and imperial distance conventions
- **HideAndSeek-976** — Fixed radar/thermometer distances per game size with map overrides

---

## Overview

Distance conventions control two things:

1. **The values presented to players** — API inputs and outputs use convention units (meters or miles), so clients never convert.
2. **The question inventory** — each convention has its own set of round-number distances for radar and thermometer slots.

All internal geo math remains in meters. Conversion happens at the boundary: when an imperial value enters the system (from a request or from storage), it's multiplied by 1609.344 to get meters before any distance calculations.

---

## Convention Enum

```
metric   → all distances in meters
imperial → all distances in miles
```

A `DistanceConvention` enum (`metric` / `imperial`) lives on **`GameMap`**, not on `Game`. Maps are tied to geography, and geography determines the natural convention. Games inherit the convention from their map.

This also simplifies map-level inventory overrides: a map only needs to define one set of custom distances (in its own convention), not one per convention.

---

## Default Inventory Sets

When a map does **not** provide a `default_inventory` override, the game is populated from these code-level constants based on the map's convention and size.

### Radar (same for all game sizes)

| Metric (meters) | Imperial (miles) |
|------------------|------------------|
| 500              | 0.25             |
| 1,000            | 0.5              |
| 2,000            | 1                |
| 5,000            | 2                |
| 10,000           | 5                |
| 15,000           | 10               |
| 40,000           | 25               |
| 80,000           | 50               |
| 160,000          | 100              |

### Thermometer (varies by game size)

| Size   | Metric (meters)              | Imperial (miles)       |
|--------|------------------------------|------------------------|
| Small  | 1,000 · 5,000 · 10,000      | 0.5 · 1 · 5           |
| Medium | + 15,000                     | + 10                   |
| Large  | + 75,000                     | + 25                   |

Medium includes everything in small plus the addition. Large includes everything in medium plus the addition.

### Custom slots

Custom slots (where the seeker picks an arbitrary distance in convention units) are **always available** — one for radar, one for thermometer. They are not part of the inventory template and cannot be overridden or removed. They don't appear in `InventorySlot` rows; they're implicit.

---

## Map-Level Override

A map may provide a `default_inventory` to replace the code-level defaults entirely. When present:

- Distances are in the map's convention units.
- No game-size variation — the override is the complete set.
- The override must include both `radars` and `thermometers` arrays.
- Custom slots are still available regardless — they are not part of the override.

When absent, the code-level defaults above are used, keyed by the map's convention and size.

---

## Data Model Changes

### GameMap

Add a `convention` column:

| Field      | Type                | Notes                           |
|------------|---------------------|---------------------------------|
| convention | DistanceConvention  | `metric` or `imperial`          |

No changes to `default_inventory` structure — it already stores distance values; those values are now interpreted in the map's convention units rather than assumed as meters.

### InventorySlot

Rename `distance_m` → `distance`:

| Field    | Type   | Notes                                                         |
|----------|--------|---------------------------------------------------------------|
| distance | float  | In convention units (meters or miles). Never null — custom slots are implicit, not stored. |

The type changes from `int` to `float` to accommodate imperial values like 0.25 and 0.5.

### RadarParams

Rename `radius_m` → `radius`:

| Field  | Type  | Notes                        |
|--------|-------|------------------------------|
| radius | float | In convention units.         |

### ThermometerParams

Rename `min_travel_m` → `min_travel`:

| Field      | Type  | Notes                        |
|------------|-------|------------------------------|
| min_travel | float | In convention units.         |

### FeatureQuestionParams

Rename distance fields:

| Field             | Type   | Notes                                        |
|-------------------|--------|----------------------------------------------|
| seeker_distance   | float  | In convention units.                         |
| hider_distance    | float? | In convention units. Null until answer time.  |

---

## Conversion Boundary

A single utility converts convention values to meters for geo math:

```python
def to_meters(value: float, convention: DistanceConvention) -> float:
    if convention == DistanceConvention.imperial:
        return value * 1609.344
    return value
```

This is called at the point where a stored or incoming distance value is fed into geo calculations (exclusion zones, distance comparisons, radar checks). The inverse (`from_meters`) is needed when computing a distance result that will be stored or returned in convention units (e.g., `seeker_distance` and `hider_distance` on feature questions, which are computed from geodesic math).

```python
def from_meters(meters: float, convention: DistanceConvention) -> float:
    if convention == DistanceConvention.imperial:
        return meters / 1609.344
    return meters
```

---

## API Surface Changes

### Inputs

Endpoints that accept distance values already receive them as numbers. The semantic changes from "meters" to "convention units":

- `AskRadarRequest.radius` — value in convention units (was `radius_m`, assumed meters)
- `AskThermometerRequest.min_travel` — value in convention units (was `min_travel_m`, assumed meters)
- Custom slots: the seeker sends their chosen distance in convention units.

The server reads the game's map convention to interpret the value. No convention field in the request — it's unambiguous from the game context.

### Outputs

Response schemas include the convention so clients know what unit the numbers represent:

- `GameResponse` gains a `convention` field (read from the game's map).
- `QuestionResponse` distance fields use the renamed parameter names (`radius`, `min_travel`, `seeker_distance`, etc.) — all in convention units.
- `InventorySlotResponse` uses `distance` instead of `distance_m`.

Clients display values directly — no conversion needed.

---

## What Does NOT Change

- **Geo math** — `geo.py` functions (`distance`, `distance_to_feature`) continue to work in meters. Exclusion zone geometry (circles, bisectors, buffers) is computed in meters.
- **Geometry storage** — `exclusion` and `total_exclusion` columns store WKB geometry. These are spatial objects, not distance values.
- **Matching/measuring inventory** — `CategoryUsage` is unrelated to distance conventions.
- **Location tracking** — coordinates are lat/lng, unaffected.
