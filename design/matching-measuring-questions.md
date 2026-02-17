# Matching & Measuring Questions

> Status: **Draft**
> Last updated: 2026-02-16
> Prerequisite: PostGIS migration (separate task — convert existing JSON geometry columns to PostGIS `geometry`/`geography` types, add GeoAlchemy2)

Two new question types that expand the game beyond point-to-point distance checks. Both rely on resolving "nearest qualifying X" from a player's position — matching compares identity, measuring compares distance.

---

## Question Definitions

**Matching** — "Is your nearest ____ the same as my ____?"
- Seeker's nearest qualifying X vs hider's nearest qualifying X.
- Answer: `"yes"` / `"no"`.

**Measuring** — "Compared to me, are you closer to or further from ____?"
- Seeker's distance to their nearest qualifying X vs hider's distance to their nearest qualifying X.
- Not the *same* X — each player's nearest is resolved independently.
- Answer: `"closer"` / `"farther"`.

---

## Feature Categories

Each category is either **map data** (baked into the GameMap, stored as PostGIS geometry, static for the life of the map) or **Google Maps** (resolved dynamically via the Places API at question time).

### Guiding Principle

If it's geographic infrastructure that shapes how the game plays, it's map data. If it's the kind of thing a player would search for on Google Maps during a real game, use the API.

Map data is appropriate for features that are:
- Structural/geographic (boundaries, coastlines, transit networks)
- Finite and well-defined within a game area
- Unlikely to change during the lifespan of a map

Google Maps is appropriate for features that are:
- Numerous and discoverable (POIs)
- Subject to opening/closing over time
- What a real player would literally search for on Google Maps

### Category Taxonomy

| Category | Data Source | Geometry Type | Resolution Method |
|---|---|---|---|
| Administrative area | Map data | Polygon | `ST_Contains` for matching, `ST_Distance` to boundary for measuring |
| Transit line | Map data | LineString | `ST_Distance` to line, matching by route ID of nearest line |
| Body of water | Map data | Polygon / LineString | `ST_Distance` to geometry, matching by feature ID |
| Airport | Google Maps | Point | Nearby Search, `type: "airport"` |
| Hospital | Google Maps | Point | Nearby Search, `type: "hospital"` |
| Library | Google Maps | Point | Nearby Search, `type: "library"` |
| Park | Google Maps | Point | Nearby Search, `type: "park"` |
| Museum | Google Maps | Point | Nearby Search, `type: "museum"` |
| Zoo | Google Maps | Point | Nearby Search, `type: "zoo"` |
| Theme park | Google Maps | Point | Nearby Search, `type: "amusement_park"` |
| Golf course | Google Maps | Point | Nearby Search, `type: "golf_course"` |
| Foreign consulate | Google Maps | Point | Nearby Search, `type: "embassy"` |

### Bona Fide Filtering (Google Maps Categories)

Not every Places API result is a legitimate game target. A phantom listing or a tiny urgent care clinic shouldn't count as "a hospital." The server applies quality filters:

- `business_status == "OPERATIONAL"` — must be open/active
- `user_ratings_total >= N` — configurable threshold per category (e.g., hospitals might require 50+ reviews, parks might require 20+)
- Correct `types` tag — the result must include the expected Google Maps place type

#### Hierarchical Configuration

Thresholds are resolved with a four-tier override chain (most specific wins):

1. **Global** — baseline defaults for all categories (e.g., `min_ratings = 20`)
2. **Global category** — per-category defaults (e.g., `hospital.min_ratings = 50`, `park.min_ratings = 30`)
3. **Map** — a specific GameMap overrides for all categories on that map (e.g., a rural map lowers everything to `min_ratings = 5`)
4. **Category-in-map** — a specific category on a specific map (e.g., `hospital` on the rural map needs at least 10)

Resolution order: category-in-map > map > global-category > global. This lets us start with sensible defaults and adjust for maps where conditions differ (rural areas with fewer reviews, dense urban areas where parks need a higher bar).

The search radius for Google Maps queries follows the same hierarchy: a global default (50 km), overridable at each tier.

---

## Map Data: New Tables

Map-sourced categories require new geometry stored alongside the GameMap. These are stored as proper PostGIS geometry with spatial indexes.

### MapFeature Table

A single table for all map-scoped geographic features (administrative areas, water features). Transit lines already exist in the transit dataset.

```python
class MapFeature(SQLModel, table=True):
    __tablename__ = 'map_feature'

    id: uuid.UUID                          # PK
    map_id: uuid.UUID                      # FK → GameMap
    category: str                          # "administrative_area", "water_feature"
    stable_id: str                         # Unique within map+category (e.g., "california")
    name: str                              # Human-readable (e.g., "California")
    feature_class: int | None              # Tier for hierarchical categories (admin areas)
    geometry: Geometry                     # PostGIS geometry column (Polygon, LineString, etc.)
```

Spatial index on `geometry`. Composite unique constraint on `(map_id, category, stable_id)`.

**Why one table instead of separate tables per category?** The resolution logic is the same — find nearest geometry of a given category from a point. A single table with a `category` discriminator keeps the query layer simple and avoids table proliferation as categories grow.

### Feature Classes (Hierarchical Categories)

Administrative areas support hierarchy via `feature_class` (tier level, same pattern as `districts`). For example, a US map might define:
- Class 1: State (California, Oregon, ...)
- Class 2: County (Los Angeles County, ...)

The class labels are stored on GameMap (similar to `district_classes`):

```python
# New JSON column on GameMap
feature_classes: list = Field(default_factory=list, sa_type=sa.JSON)
# e.g., [{"category": "administrative_area", "feature_class": 1, "label": "State"}]
```

When asking a question about administrative areas, the seeker **must** specify which class. The question is "are you in the same state as me?" or "are you closer to a state border?" — never "any border type." The `feature_class` is a required parameter for administrative area questions. The inventory slot can lock this, or the seeker picks at ask time.

### Transit Lines for Matching/Measuring

Transit routes already exist in the transit dataset with `shape` geometry (LineString). After PostGIS migration, these become proper PostGIS geometry columns. Resolution uses:

- **Matching**: `ST_Distance(route.shape, point)` ordered ascending, take the nearest → compare route IDs
- **Measuring**: `ST_Distance(route.shape, point)` → compare distances

No new tables needed. The `effective_map` query already filters routes by the game map's exclusions — the same filtered set is used for question resolution.

### What About Administrative Borders?

"Border" isn't a separate feature — it's derived from administrative area boundaries. "Are you closer to a border?" means "what is your distance to the nearest edge of any administrative area polygon?" This is `ST_Distance(point, ST_Boundary(polygon))`, not a separate dataset.

---

## Server as Places Proxy

The client must never call the Google Maps Places API directly for question resolution. All POI lookups go through the server. This ensures:

1. **Determinism** — seeker and hider see the same resolved places
2. **Auto-answer capability** — the server can resolve the hider's nearest X without client involvement
3. **API key security** — Google Maps API key stays server-side
4. **Consistency** — bona fide filters are applied uniformly

### Preview Endpoint

Before a seeker commits to a matching or measuring question, they need to see what "their nearest X" resolves to:

```
POST /games/{game_id}/questions/preview
```

**Request:**
```json
{
  "question_type": "matching",
  "category": "hospital",
  "location": { "type": "Point", "coordinates": [-71.06, 42.36] }
}
```

**Response:**
```json
{
  "nearest": {
    "place_id": "ChIJ...",
    "name": "Massachusetts General Hospital",
    "location": { "type": "Point", "coordinates": [-71.069, 42.363] },
    "distance_m": 450
  }
}
```

For map-data categories (admin areas, transit lines, water features), the server resolves against PostGIS geometry instead of calling Google Maps. The response shape is the same — `place_id` is replaced with `feature_id`:

```json
{
  "nearest": {
    "feature_id": "california",
    "name": "California",
    "distance_m": 0
  }
}
```

For point-in-polygon categories like administrative areas, `distance_m` is 0 when the point is inside the polygon. For measuring against borders, the relevant distance is to the polygon edge — this distinction is handled by the question type (matching uses containment, measuring uses edge distance).

The preview endpoint is informational and stateless — it doesn't consume inventory or create a question. The hider also uses it during the answerable phase to see a live preview of what their answer would be (same as the existing preview endpoint for radar/thermometer).

---

## Question Lifecycle

Both matching and measuring follow the same lifecycle as radar:

```
asked → answerable → answered
```

No `in_progress` phase — there's no seeker travel requirement. The question is answerable immediately upon asking.

### Resolution Flow

1. **Seeker previews** — calls preview endpoint, sees "Your nearest hospital is Mass General (450 m)"
2. **Seeker asks** — `POST /games/{game_id}/questions` with `question_type` and `category`
3. **Server resolves seeker side** — stores resolved feature in `parameters`
4. **Status → `answerable`** — hider is notified, answer timer starts
5. **Hider previews** — the preview endpoint resolves the hider's nearest X from their current position (live, updates as hider moves)
6. **Hider answers** — `POST .../answer`, server snapshots hider location, resolves hider's nearest X, computes answer
7. **Status → `answered`** — seekers see the result

### Hider Gamesmanship

The hider can move within their allowed zone before answering to change which X is nearest to them. This is intentional and a core part of the strategy — same as thermometer where movement affects the answer.

---

## Question Parameters

### Matching

```json
{
  "category": "hospital",
  "source": "google_maps",
  "seeker_resolution": {
    "place_id": "ChIJ...",
    "name": "Massachusetts General Hospital",
    "location": { "type": "Point", "coordinates": [-71.069, 42.363] }
  },
  "hider_resolution": {
    "place_id": "ChIJ...",
    "name": "Boston Medical Center",
    "location": { "type": "Point", "coordinates": [-71.072, 42.334] }
  }
}
```

`seeker_resolution` is populated at ask-time. `hider_resolution` is populated at answer-time.

### Measuring

Same structure, with distances included for transparency:

```json
{
  "category": "hospital",
  "source": "google_maps",
  "seeker_resolution": {
    "place_id": "ChIJ...",
    "name": "Massachusetts General Hospital",
    "location": { "type": "Point", "coordinates": [-71.069, 42.363] },
    "distance_m": 450
  },
  "hider_resolution": {
    "place_id": "ChIJ...",
    "name": "Boston Medical Center",
    "location": { "type": "Point", "coordinates": [-71.072, 42.334] },
    "distance_m": 1200
  }
}
```

### Map-Data Variant

For map-sourced categories, `place_id` is replaced with `feature_id`:

```json
{
  "category": "administrative_area",
  "source": "map_data",
  "feature_class": 1,
  "seeker_resolution": {
    "feature_id": "california",
    "name": "California"
  },
  "hider_resolution": {
    "feature_id": "california",
    "name": "California"
  }
}
```

---

## Inventory Changes

The current `QuestionInventory` has typed slot lists with `DistanceSlot`. Matching and measuring don't use distance — they use categories.

### Updated Inventory Model

```python
class CategorySlot(BaseModel):
    category: str | None = None  # null = seeker picks at ask time

class QuestionInventory(BaseModel):
    radars: list[DistanceSlot] = []
    thermometers: list[DistanceSlot] = []
    matching: list[CategorySlot] = []
    measuring: list[CategorySlot] = []
```

A `CategorySlot` with `category: null` means the seeker chooses the category when asking (from the set of categories available on this map + Google Maps categories). A slot with `category: "hospital"` locks it to hospitals.

For administrative area questions, the `feature_class` (state vs county, etc.) is specified at ask time as a question parameter — analogous to how radar has `radius_m` and thermometer has `min_travel_m`. The inventory slot determines the category, the seeker determines the granularity.

### Available Categories

Which categories are available for a game depends on what the map provides:

- **Always available** (Google Maps): airport, hospital, library, park, museum, zoo, theme_park, golf_course, consulate
- **Available if map defines them**: administrative_area, transit_line, water_feature

The client discovers available categories from the map data (presence of `MapFeature` rows for the map, transit routes in the dataset) plus the hardcoded Google Maps list.

---

## Answer Computation

### Matching

```python
if source == "map_data":
    seeker_feature = resolve_map_feature(category, seeker_location, game_map)
    hider_feature = resolve_map_feature(category, hider_location, game_map)
else:
    seeker_feature = resolve_google_place(category, seeker_location, filters)
    hider_feature = resolve_google_place(category, hider_location, filters)

if seeker_feature is None or hider_feature is None:
    answer = None  # null — question not answerable
else:
    answer = "yes" if seeker_feature.id == hider_feature.id else "no"
```

### Measuring

```python
if source == "map_data":
    seeker_dist = distance_to_nearest_feature(category, seeker_location, game_map)
    hider_dist = distance_to_nearest_feature(category, hider_location, game_map)
else:
    seeker_place = resolve_google_place(category, seeker_location, filters)
    hider_place = resolve_google_place(category, hider_location, filters)
    seeker_dist = geojson_distance(seeker_location, seeker_place.location)
    hider_dist = geojson_distance(hider_location, hider_place.location)

if seeker_dist is None or hider_dist is None:
    answer = None  # null — question not answerable
elif hider_dist < seeker_dist:
    answer = "closer"
else:
    answer = "farther"
```

### Null Answer

The game provides for a `null` answer meaning "question not answerable." This can occur when:
- No qualifying feature is found for the category at one or both player positions (e.g., no operational hospital within search radius)
- A player's position can't be resolved (e.g., no location data available for auto-answer)

This is expected to be rare for most categories but is a legitimate game outcome. The slot is still consumed — the question was asked, it just couldn't produce a definitive answer.

### PostGIS Resolution Queries

These are the spatial queries needed for map-data categories:

**Administrative area — matching (point-in-polygon):**
```sql
SELECT stable_id, name FROM map_feature
WHERE map_id = :map_id AND category = 'administrative_area'
  AND feature_class = :class
  AND ST_Contains(geometry, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
LIMIT 1;
```

**Administrative area — measuring (distance to nearest boundary edge of specified class):**
```sql
SELECT stable_id, name, ST_Distance(
    ST_Boundary(geometry)::geography,
    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
) AS distance_m
FROM map_feature
WHERE map_id = :map_id AND category = 'administrative_area'
  AND feature_class = :class
ORDER BY distance_m
LIMIT 1;
```

Note: for matching, `ST_Contains` identifies which polygon the player is inside — this is containment, not distance. For measuring, distance is to the nearest boundary edge of any polygon of the specified class (including the one the player is inside — they're measuring how far they are from leaving it).

**Water feature — nearest:**
```sql
SELECT stable_id, name, ST_Distance(
    geometry::geography,
    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
) AS distance_m
FROM map_feature
WHERE map_id = :map_id AND category = 'water_feature'
ORDER BY distance_m
LIMIT 1;
```

**Transit line — nearest:**
```sql
SELECT r.stable_id, r.name, ST_Distance(
    r.shape::geography,
    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
) AS distance_m
FROM route r
JOIN transit_dataset td ON r.transit_dataset_id = td.id
JOIN game_map gm ON gm.transit_dataset_id = td.id
WHERE gm.id = :map_id
  AND r.stable_id NOT IN (SELECT unnest(gm.excluded_route_ids))
ORDER BY distance_m
LIMIT 1;
```

All distance results are in meters (using `::geography` cast for geodesic math). Spatial indexes on `geometry` columns make these queries fast even with complex polygons.

---

## API Surface Changes

### New Endpoint

| Method | Path | Purpose | Who |
|---|---|---|---|
| `POST` | `/games/{game_id}/questions/preview` | Preview nearest feature for a location | Seeker (pre-ask) or Hider (during answerable phase) |

### Modified Endpoint

`POST /games/{game_id}/questions` — gains support for `question_type: "matching"` and `question_type: "measuring"`. Request body adds:

```json
{
  "question_type": "matching",
  "slot_index": 0,
  "custom_category": "hospital"
}
```

`custom_category` is required when the slot's `category` is null (seeker picks). Location is inferred from the seeker's latest reported position (same as radar/thermometer).

For administrative area questions, `feature_class` is also required:

```json
{
  "question_type": "measuring",
  "slot_index": 0,
  "custom_category": "administrative_area",
  "feature_class": 1
}
```

The ask endpoint calls the resolution logic internally to resolve and store the seeker's nearest feature in `parameters`.

### Modified Responses

`QuestionResponse` — no structural changes needed. The `parameters` dict already accommodates arbitrary JSON. The `answer` field values (`"yes"` / `"no"` for matching, `"closer"` / `"farther"` for measuring) are already used by existing question types.

---

## Exclusion Zones (Deferred)

Exclusion geometry for matching and measuring is significantly more complex than radar circles or thermometer half-planes. For matching, the exclusion zone is conceptually a Voronoi cell around the resolved feature. For measuring, it's a distance-comparison region. Both require spatial computation that's non-trivial to represent as GeoJSON polygons.

This is deferred — `exclusion` will remain `null` for these question types initially, consistent with the current approach of deferring exclusion zone computation for all question types.

---

## Google Maps Places API Integration

### Nearby Search (New)

The server needs a new integration with the [Places API (New)](https://developers.google.com/maps/documentation/places/web-service/nearby-search) — the current generation, not the deprecated legacy endpoints.

**Request pattern:**
```
POST https://places.googleapis.com/v1/places:searchNearby

Headers:
  X-Goog-Api-Key: <server-side key>
  X-Goog-FieldMask: places.id,places.displayName,places.location,places.types,places.businessStatus,places.userRatingCount

Body:
{
  "includedTypes": ["hospital"],
  "locationRestriction": {
    "circle": {
      "center": { "latitude": 42.36, "longitude": -71.06 },
      "radius": 50000.0
    }
  },
  "maxResultCount": 5,
  "rankPreference": "DISTANCE"
}
```

**Flow:**
1. Request 5 nearest results ranked by distance
2. Apply bona fide filters (operational, min ratings, correct type)
3. Take the nearest qualifying result
4. If no results qualify, widen the search radius and retry (up to a max)

**Key considerations:**
- `rankPreference: "DISTANCE"` ensures nearest-first ordering
- Request more than 1 result so filtering doesn't leave us empty
- Search radius: 50 km default, configurable per category
- The API key is server-side only, set via env var (`GOOGLE_MAPS_API_KEY`)
- Use `X-Goog-FieldMask` to request only the fields we need (keeps us in the Basic pricing tier)

### Cost

Places API (New) pricing: Nearby Search is $32 per 1,000 requests at Basic tier. A single question costs 2 API calls (seeker ask + hider answer), plus previews. Budget ~5 calls per question. At $0.032/call, this is negligible for a casual game.

### Caching

Place results can be cached briefly (15–60 minutes) keyed by `(category, lat_rounded, lng_rounded)` to reduce redundant API calls when previewing repeatedly from roughly the same location. Cache is server-side in-memory or Redis.

---

## Resolved Decisions

- **Bona fide thresholds**: Hierarchical 4-tier config: category-in-map > map > global-category > global. Allows sensible defaults with per-map tuning.
- **Search radius**: Global default (50 km), overridable at each config tier.
- **Transit line matching**: Route-level (e.g., "Central Line"). Mode-level (metro vs bus) could be a separate category added later.
- **Admin area class**: Must be specified as part of the question. Matching checks containment ("are you in the same state?"), measuring checks distance to border ("are you closer to a state border?"). Never "any border type."
- **Parks**: Google Maps. Too numerous and variable to curate as map data. Use higher bona fide thresholds to filter pocket parks.
- **Null answers**: The game provides for a `null` answer ("question not answerable"). Rare but legitimate — slot is still consumed.

## Open Questions

- **Polygon-sized POIs**: Some Google Maps places are large enough to be polygons rather than points (e.g., Central Park, large theme parks). For distance measuring, treating them as their centroid point could be misleading. Possible future approach: declare places under a certain area threshold as point-like, treat larger ones as polygons with distance-to-boundary semantics. Punt for now — treat all Google Maps results as points.
- **Hider preview for admin areas (matching)**: The hider already knows which area they're in — the preview trivially shows "yes" or "no." Consistent with radar (hider knows if they're within X km) so probably fine, but worth confirming this doesn't reduce strategic depth.
- **Config storage**: Where do the hierarchical bona fide thresholds and search radius overrides live? Global defaults could be server config (env vars or a config file). Map-level and category-in-map overrides could be JSON columns on `GameMap`.
