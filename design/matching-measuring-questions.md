# Matching & Measuring Questions

> Status: **Draft**
> Last updated: 2026-02-17
> Prerequisite: ~~PostGIS migration~~ Done (commit `8988690` — geoalchemy2 + shapely with `ShapelyGeometry` column type)

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

Every category resolves to "find nearest from a set of known features." The data source for each category is determined per-map:

- **Map-defined** (preferred) — features are stored as `MapFeature` rows with geometry. The map creator imports datasets (public data, manual curation) when building the map. Enables exclusion zone computation because we have the complete dataset.
- **Google Maps fallback** — if the map doesn't define features for a category and doesn't explicitly exclude it, the server resolves via the Places API at question time. No exclusion zones outside of endgame (incomplete data).
- **Excluded** — the map explicitly marks a category as unavailable. The category doesn't appear in the game.

### Per-Map Category States

For any given category on a given map, exactly one of:

1. **Map defines features** → use them. Exclusion zones supported.
2. **Map has no features, category not excluded** → Google Maps fallback. No exclusion zones (except endgame).
3. **Map explicitly excludes category** → category unavailable for this game.

This gives map creators full control. Want better park data than Google? Import a parks dataset. Playing on a flat map with no mountains? Exclude the category. No features defined and no exclusion? Google fills in.

### Category Taxonomy

Matching and measuring have different category lists — not every category supports both question types. Each question may only be asked once per game (so admin division with 3 defined classes = 3 available questions). Running out of inventory is uncommon but choosing when to use each question is part of the strategy.

**Matching Categories** — "Is your nearest ____ the same as mine?"

| Category | Geometry | Map Resolution | Google Fallback Type | Notes |
|---|---|---|---|---|
| Commercial airport | Point | `ST_Distance`, compare IDs | `airport` | |
| Transit line | LineString | `ST_Distance` on route shape, compare route IDs | — | Map-only (uses existing transit dataset) |
| Admin division (per class) | Polygon | `ST_Contains`, compare IDs | — | Map-only. Classes 1–4, each class = separate question |
| Mountain | Point | `ST_Distance`, compare IDs | — | Map-only. Peak datasets are readily available |
| Landmass | Polygon | `ST_Contains`, compare IDs | — | Map-only |
| Park | Point | `ST_Distance`, compare IDs | `park` | Uses pin location, accepts edge cases for large parks |
| Amusement park | Point | `ST_Distance`, compare IDs | `amusement_park` | |
| Zoo | Point | `ST_Distance`, compare IDs | `zoo` | |
| Aquarium | Point | `ST_Distance`, compare IDs | `aquarium` | |
| Golf course | Point | `ST_Distance`, compare IDs | `golf_course` | |
| Museum | Point | `ST_Distance`, compare IDs | `museum` | |
| Movie theater | Point | `ST_Distance`, compare IDs | `movie_theater` | |
| Hospital | Point | `ST_Distance`, compare IDs | `hospital` | |
| Library | Point | `ST_Distance`, compare IDs | `library` | |
| Foreign consulate | Point | `ST_Distance`, compare IDs | `embassy` | |
| ~~Street or path~~ | — | — | — | **Punted.** Only useful in endgame; complex to resolve reliably |

**Measuring Categories** — "Compared to me, are you closer to or further from ____?"

| Category | Geometry | Map Resolution | Google Fallback Type | Notes |
|---|---|---|---|---|
| Commercial airport | Point | `ST_Distance` + haversine | `airport` | |
| High speed train line | LineString | `ST_Distance` + haversine | — | Map-only. Distinct from regular transit lines |
| Rail station | Point | `ST_Distance` + haversine | `train_station` | Distinct from in-game transit stops — includes all rail stations regardless of game exclusions |
| International border | LineString | `ST_Distance` + haversine | — | Map-only |
| Admin division border (per class) | LineString | `ST_Distance` + haversine | — | Map-only. Classes 1–2 only, each class = separate question |
| Coastline | LineString | `ST_Distance` + haversine | — | Map-only |
| Mountain | Point | `ST_Distance` + haversine | — | Map-only |
| Park | Point | `ST_Distance` + haversine | `park` | Uses pin location, accepts edge cases |
| Amusement park | Point | `ST_Distance` + haversine | `amusement_park` | |
| Zoo | Point | `ST_Distance` + haversine | `zoo` | |
| Aquarium | Point | `ST_Distance` + haversine | `aquarium` | |
| Golf course | Point | `ST_Distance` + haversine | `golf_course` | |
| Museum | Point | `ST_Distance` + haversine | `museum` | |
| Movie theater | Point | `ST_Distance` + haversine | `movie_theater` | |
| Hospital | Point | `ST_Distance` + haversine | `hospital` | |
| Library | Point | `ST_Distance` + haversine | `library` | |
| Foreign consulate | Point | `ST_Distance` + haversine | `embassy` | |
| ~~Body of water~~ | — | — | — | **Punted.** Rules allow any named body of water that isn't a pool — rivers, lakes, ponds, etc. Curating this would be extremely burdensome for map creators. Google Maps doesn't have a clean category for it either. Revisit later |

Categories marked "Map-only" have no Google fallback — if the map doesn't define features for them, the category is unavailable.

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

Map-defined features are stored as standalone entities and linked to maps via a join table. This allows multiple maps to share the same feature datasets — e.g., a "US State Boundaries" dataset can be imported once and linked to any map covering that area. Map creators build on each other's work.

### MapFeature Table

Features exist independently of any map. A single table for **all** feature types — geographic infrastructure (admin areas, borders, coastlines) and POIs (parks, hospitals, airports). Transit lines are the one exception (they already exist in the transit dataset).

```python
class FeatureCategory(str, Enum):
    # Matching-only
    transit_line = "transit_line"
    administrative_area = "administrative_area"
    landmass = "landmass"

    # Measuring-only
    high_speed_train_line = "high_speed_train_line"
    rail_station = "rail_station"
    international_border = "international_border"
    admin_division_border = "admin_division_border"
    coastline = "coastline"

    # Both matching and measuring
    commercial_airport = "commercial_airport"
    mountain = "mountain"
    park = "park"
    amusement_park = "amusement_park"
    zoo = "zoo"
    aquarium = "aquarium"
    golf_course = "golf_course"
    museum = "museum"
    movie_theater = "movie_theater"
    hospital = "hospital"
    library = "library"
    foreign_consulate = "foreign_consulate"


class MapFeature(SQLModel, table=True):
    __tablename__ = 'map_feature'

    id: uuid.UUID                          # PK
    category: FeatureCategory
    stable_id: str                         # Unique within category (e.g., "california", "central-park-nyc")
    name: str                              # Human-readable (e.g., "California", "Central Park")
    feature_class: int | None              # Tier for hierarchical categories (admin areas, borders)
    geometry: BaseGeometry = Field(        # Point, Polygon, LineString depending on category
        sa_column=sa.Column(ShapelyGeometry('GEOMETRY', srid=4326))
    )
```

Composite unique constraint on `(category, stable_id)`.

### GameMapFeature Join Table

Links features to maps. A map includes a feature by creating a row here. Querying "all parks on this map" is a join through this table.

```python
class GameMapFeature(SQLModel, table=True):
    __tablename__ = 'game_map_feature'

    game_map_id: uuid.UUID                 # FK → GameMap (composite PK)
    map_feature_id: uuid.UUID              # FK → MapFeature (composite PK)
```

Composite primary key on `(game_map_id, map_feature_id)`.

**Why one table instead of separate tables per category?** The resolution logic is the same — find nearest geometry of a given category from a point. A single `MapFeature` table with a `category` discriminator keeps the query layer simple and avoids table proliferation as categories grow. A map with imported park, hospital, and airport datasets just has more rows linked through `GameMapFeature`.

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

When asking a question about administrative areas, the seeker **must** specify which class. The question is "are you in the same state as me?" (`administrative_area`, class 1) or "are you closer to a state border?" (`admin_division_border`, class 1) — never "any border type." The `feature_class` is a required parameter for these questions.

### Transit Lines (Matching Only)

The `transit_line` category supports matching only ("is your nearest transit line the same as mine?"). Transit routes already exist in the transit dataset with `shape: LineString` as a `ShapelyGeometry` column. Resolution uses the DB to find the nearest route (spatial index sort with exclusion filtering), then compares route IDs.

No new tables needed. The `effective_map` query already filters routes by the game map's exclusions — the same filtered set is used for question resolution.

**High speed train lines** (`high_speed_train_line`) are a separate measuring-only category stored in `MapFeature`, distinct from the in-game transit dataset. These are curated by the map creator and represent long-distance rail corridors (e.g., Shinkansen, TGV), not local transit routes.

### Borders vs Administrative Area Boundaries

Borders are **not** derived from administrative area polygon boundaries at query time. A polygon's boundary includes coastlines, map edges, and other non-border perimeters — the Pacific coastline of California isn't a "state border" in the game sense.

Instead, borders are stored as separate `MapFeature` entries with LineString geometry representing the shared edge between two adjacent areas. When building a map, the map creator extracts these shared edges and stores them explicitly. Two separate categories:

- **`admin_division_border`** — shared edges between adjacent admin divisions. Uses the same `feature_class` tiers (e.g., class 1 = state borders, class 2 = county borders). Classes 1–2 only. Measuring only.
- **`international_border`** — country borders. No `feature_class` tiers. Measuring only.

Administrative areas and borders support different question types:
- **`administrative_area`** → matching only ("are you in the same state?")
- **`admin_division_border`** / **`international_border`** → measuring only ("are you closer to a state border?")

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

For map-defined categories, the server resolves against `MapFeature` rows in the DB. The response shape is the same — `place_id` is replaced with `feature_id`:

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

## Inventory & Available Categories

### Once-Per-Game Rule

Each matching or measuring category may only be asked **once per game**. For categories with `feature_class` (admin divisions, admin division borders), each class counts as a separate question — a map with 3 admin division classes gives 3 matching questions.

Running out of inventory is uncommon, but choosing when to use each question is part of the strategy (e.g., saving certain categories for endgame when they're more informative).

### Updated Inventory Model

Matching and measuring inventory is the set of available categories, not a slot list. The `QuestionInventory` tracks which categories have been used:

```python
class QuestionInventory(BaseModel):
    radars: list[DistanceSlot] = []
    thermometers: list[DistanceSlot] = []
    matching_used: list[str] = []          # e.g., ["hospital", "administrative_area:1"]
    measuring_used: list[str] = []         # e.g., ["commercial_airport"]
```

A category is available if it's in the game's available set (see below) and not yet in the `_used` list. For classed categories, the key includes the class (e.g., `"administrative_area:1"`).

### Available Categories

Which categories are available for a game depends on the map's state for each category:

1. **Map defines features** (`GameMapFeature` rows exist for this category) → category available, uses map data
2. **Map has no features, category not excluded** → category available via Google Maps fallback (only for categories with a Google fallback type — see taxonomy)
3. **Map explicitly excludes category** → category unavailable

```python
# New JSON column on GameMap
excluded_categories: list[str] = Field(default_factory=list, sa_type=sa.JSON)
# e.g., ["mountain", "landmass"]  — these categories won't appear in the game
```

Categories with no Google fallback type (marked "Map-only" in the taxonomy) are only available if the map defines features for them. If the map has no transit lines and no mountains, those categories simply aren't in the game — no explicit exclusion needed.

The client discovers available categories from the map data:
- Query `GameMapFeature` join to find which categories the map defines
- Check `excluded_categories` on `GameMap` to filter out excluded ones
- Add Google fallback categories that aren't excluded and don't have map-defined features

---

## Answer Computation

### Matching

The source (`map_data` or `google_maps`) is determined per-map per-category at question time — see "Per-Map Category States" above.

```python
if source == "map_data":
    seeker_feature = resolve_map_feature(category, seeker_location, game_map)
    hider_feature = resolve_map_feature(category, hider_location, game_map)
else:  # google_maps fallback
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
else:  # google_maps fallback
    seeker_place = resolve_google_place(category, seeker_location, filters)
    hider_place = resolve_google_place(category, hider_location, filters)
    seeker_dist = haversine_distance(seeker_location, seeker_place.location)
    hider_dist = haversine_distance(hider_location, hider_place.location)

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

This is expected to be rare for most categories but is a legitimate game outcome. The question is still consumed (marked as used for that category) — it just couldn't produce a definitive answer.

### Python-Side Resolution (shapely)

Spatial resolution for map-data categories splits responsibility between the database and Python:

- **Database** — spatial filtering and sorting. Uses spatial indexes to find the containing polygon or nearest feature without loading bulk geometry into memory. PostGIS uses the `<->` KNN operator for indexed nearest-neighbor lookups; SpatiaLite falls back to a full scan (fine for test data sizes).
- **Python** — distance computation. Once the DB returns the relevant feature(s), Python computes geodesic distance in meters using `nearest_points` + haversine, consistent with how radar and thermometer already compute answers.

**Core distance pattern** — given a feature returned by the DB, compute distance in meters:

```python
from shapely.ops import nearest_points
from hideandseek.geo import haversine

def distance_to_feature(player: Point, feature_geometry: BaseGeometry) -> float:
    """Distance in meters from a player point to the nearest point on a geometry."""
    nearest_pt = nearest_points(feature_geometry, player)[0]
    return haversine((nearest_pt.y, nearest_pt.x), (player.y, player.x))
```

All map-defined queries join through `GameMapFeature` to scope features to the current map.

**Administrative area — matching (point-in-polygon):**

The DB filters to the polygon containing the player:

```python
stmt = (
    select(MapFeature)
    .join(GameMapFeature)
    .where(
        GameMapFeature.game_map_id == map_id,
        MapFeature.category == FeatureCategory.administrative_area,
        MapFeature.feature_class == class_id,
        func.ST_Contains(MapFeature.geometry, player_wkb),
    )
    .limit(1)
)
```

**Border — measuring (nearest border line):**

The DB finds the nearest border using `ST_Distance` on the actual geometry, Python computes the final distance in meters:

```python
stmt = (
    select(MapFeature)
    .join(GameMapFeature)
    .where(
        GameMapFeature.game_map_id == map_id,
        MapFeature.category == FeatureCategory.admin_division_border,
        MapFeature.feature_class == class_id,
    )
    .order_by(func.ST_Distance(MapFeature.geometry, player_wkb))
    .limit(1)
)
nearest_border = session.exec(stmt).first()
dist_m = distance_to_feature(player, nearest_border.geometry)
```

Note: administrative areas use containment for matching — "are you in the same state?" Borders are separate LineString features representing shared edges between adjacent areas (not polygon perimeters, which would include coastlines and map edges). See "Borders vs Administrative Area Boundaries" above.

**Generic nearest feature (parks, hospitals, mountains, etc.):**

Same pattern for any category — DB sorts by actual geometry distance, Python computes distance in meters:

```python
stmt = (
    select(MapFeature)
    .join(GameMapFeature)
    .where(
        GameMapFeature.game_map_id == map_id,
        MapFeature.category == category,
    )
    .order_by(func.ST_Distance(MapFeature.geometry, player_wkb))
    .limit(1)
)
```

The slight inaccuracy of using Cartesian distance for the DB-side sort (vs geodesic) is negligible at game-area scales — it only affects ordering, and the final distance in meters is always computed geodesically by Python.

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
  "category": "hospital"
}
```

The seeker picks a category from the available set. The server validates that the category hasn't been used yet and is available for this map and question type. Location is inferred from the seeker's latest reported position (same as radar/thermometer).

For classed categories, `feature_class` is also required:

```json
{
  "question_type": "measuring",
  "category": "admin_division_border",
  "feature_class": 1
}
```

The ask endpoint calls the resolution logic internally to resolve and store the seeker's nearest feature in `parameters`.

### Modified Responses

`QuestionResponse` — no structural changes needed. The `parameters` dict already accommodates arbitrary JSON. The `answer` field values (`"yes"` / `"no"` for matching, `"closer"` / `"farther"` for measuring) are already used by existing question types.

---

## Exclusion Zones

Exclusion geometry for matching and measuring is significantly more complex than radar circles or thermometer half-planes. For matching, the exclusion zone is conceptually a Voronoi cell around the resolved feature. For measuring, it's a distance-comparison region. Both require spatial computation that's non-trivial to represent as GeoJSON polygons.

### Tiered Strategy

Exclusion zone support depends on the data source and dataset size:

1. **Map-defined, < N features** — compute synchronously, return `exclusion` in the question response. Feasible because the complete dataset is small (e.g., a map with 5 admin divisions → simple polygon).

2. **Map-defined, >= N features** — kick to a background job. The question's `exclusion` starts as `null` with a pending status. When the background job completes, the server pushes the computed exclusion zone to seekers.

3. **Google Maps fallback + endgame** — the endgame resets with a significantly smaller map area. The server can fetch a more complete set of features for the reduced area via the Places API, then compute the exclusion zone as a background job.

4. **Google Maps fallback + not endgame** — no exclusion zone. We don't have the complete dataset (only queried for nearest features, not all features on the map), so we can't compute an accurate zone. The answer itself is still informative; it just doesn't render as a map overlay.

The threshold N and the specifics of exclusion zone calculation, scheduling, and delivery are deferred to a separate design document.

---

## Google Maps Places API Integration (Fallback)

When a map doesn't define features for a category and doesn't exclude it, the server falls back to the Google Maps Places API for resolution. This is a degraded mode — no exclusion zones outside of endgame — but keeps categories playable without map creator effort.

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

- **Map-defined preferred, Google fallback**: All categories can be map-defined via `MapFeature` + `GameMapFeature`. If the map doesn't define features for a category and doesn't exclude it, categories with a Google fallback type resolve via the Places API. Map-only categories (no fallback type) are simply unavailable if not defined.
- **Once per game**: Each matching/measuring category can only be asked once per game. Classed categories (admin divisions, admin division borders) get one question per defined class.
- **Features are shared entities**: `MapFeature` rows exist independently of maps, linked via the `GameMapFeature` join table. Multiple maps can share the same feature datasets.
- **`FeatureCategory` enum**: All categories are enumerated. The enum is the source of truth for valid category values.
- **Bona fide thresholds** (Google fallback): Hierarchical 4-tier config: category-in-map > map > global-category > global. Allows sensible defaults with per-map tuning.
- **Search radius** (Google fallback): Global default (50 km), overridable at each config tier.
- **Transit line matching**: Route-level (e.g., "Central Line"), matching only. Uses the existing transit dataset, not `MapFeature`. High speed train lines are a separate measuring-only category in `MapFeature`.
- **Admin areas vs borders**: Administrative areas (`administrative_area`) support matching only (polygon containment). Admin division borders (`admin_division_border`) and international borders (`international_border`) support measuring only (distance to LineString). Borders are explicit geometry — shared edges between adjacent areas, not derived from polygon boundaries (which include coastlines and map edges).
- **Mountains are map-defined**: Peak datasets are readily available as public data. Stored as Points in `MapFeature`. No Google fallback.
- **Null answers**: The game provides for a `null` answer ("question not answerable"). Rare but legitimate — the question is still consumed.
- **Split spatial responsibility**: The database handles spatial filtering and sorting (containment checks, nearest-neighbor via spatial index), Python handles distance computation (shapely `nearest_points` + haversine for meters). PostGIS uses the `<->` KNN operator; SpatiaLite falls back to full scan in tests.
- **Tiered exclusion zones**: Map-defined categories support exclusion zones (sync for small datasets, background job for large). Google fallback only supports exclusion in endgame. Calculation and scheduling details deferred to a separate design.

## Open Questions

- **Large-area Google Maps POIs**: Google fallback treats results as points. For very large places (Central Park, large theme parks), the pin location may not reflect intuitive "closeness." Map-defined features avoid this (DB sorts by actual geometry proximity, Python uses `nearest_points` on the full shape). Punt for now — map creators who care can import better data.
- **Hider preview for admin areas (matching)**: The hider already knows which area they're in — the preview trivially shows "yes" or "no." Consistent with radar (hider knows if they're within X km) so probably fine, but worth confirming this doesn't reduce strategic depth.
- **Config storage**: Where do the hierarchical bona fide thresholds and search radius overrides live? Global defaults could be server config (env vars or a config file). Map-level and category-in-map overrides could be JSON columns on `GameMap`.
- **Map creation API surface**: With `MapFeature` as a shared entity and `GameMapFeature` as the join table, the API for map creation needs design: bulk import of feature datasets, linking/unlinking features to maps, listing available datasets. This is a separate design concern.
- **Body of water**: Punted for now. Rules allow any named body of water that isn't a pool. Extremely burdensome for map creators (rivers, lakes, ponds, etc.) and no clean Google Maps category. Could revisit with a public dataset approach if demand warrants it.
- **Street or path**: Punted. Only useful in endgame and complex to resolve reliably.
