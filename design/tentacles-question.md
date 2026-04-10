# Tentacles Question Type

> Status: **Draft**
> Last updated: 2026-04-09
> Depends on: `matching-measuring-questions.md` (MapFeature, FeatureCategory, feature resolution), `question-flow-mobile.md` (belt takeover, question banner, preview endpoint)

A new question type where the seeker picks a POI category and the game determines which specific POI the hider is closest to. Unlike all other question types which produce binary answers (yes/no, closer/farther), tentacles produces a **multi-valued answer** — a specific POI — and excludes everything outside that POI's Voronoi cell. High information yield, high draw cost.

---

## 1. Mechanic

**"Here are all the [POI type] within [distance] of me. Which one are you closest to?"**

The seeker picks a POI category (e.g., museums). The server finds all POIs of that category within a configured `distance` of the seeker. The hider's answer is whichever of those in-circle POIs they're nearest to — or a **miss** if the hider is beyond `distance` of the seeker entirely.

### Two-Phase Answer

1. **Distance check**: Is the hider within `distance` of the seeker's ask location?
   - **No** → **miss**. Degrades to a radar miss at `distance` radius. The hider's proximity to the actual POIs is irrelevant.
   - **Yes** → proceed to step 2.
2. **Nearest POI**: Among the POIs within the seeker's `distance` circle, which is the hider closest to? That POI is the answer.

### Exclusion Geometry

- **Miss**: Reuse `exclude_radar` with `hit=False` at the `distance` radius. The seeker's circle is excluded (hider isn't in there).
- **Hit**: Compute Voronoi diagram of the in-circle POIs. The answered POI's Voronoi cell, intersected with the `distance` circle, defines where the hider *is*. **Everything else within the game boundary is excluded** — not just the area inside the circle. This is what makes tentacles so powerful: a hit excludes the vast majority of the map.

### Hider Agency

The hider doesn't pick a POI — the answer is deterministic from their location. Their agency is:
- **During non-endgame play**: move before answering to change which Voronoi cell they're in (or move out of the `distance` circle to force a miss).
- **During endgame**: locked in place, auto-answer applies. No agency.

### Why It's Balanced

The power of the exclusion (entire map minus one Voronoi cell) is offset by:
- **High draw cost** — tentacles cards are expensive to use from the inventory.
- **Miss risk** — if the hider is outside `distance`, the seeker burns an expensive ask for a mere radar miss.
- **Hider movement** — outside endgame, the hider can reposition to change the outcome or dodge the circle entirely.
- **Information leakage on miss** — a miss still reveals useful info (hider is NOT within `distance` of the seeker), but at the cost of a high-value card.

---

## 2. POI Configuration

### Per-Map Tentacle Config

Each `GameMap` defines which POI categories support tentacles and at what distance. This lives in a new JSON column on `GameMap`:

```python
# New JSON column on GameMap
tentacle_categories: Mapped[list] = mapped_column(JSON, default=list)
```

Each entry:

```json
{
  "category": "museum",
  "distance": 1.0
}
```

Where `distance` is in the map's convention units (miles for imperial, meters for metric).

Games inherit the map's tentacle config. Game-level overrides follow the existing three-level fallback pattern (request → map → code default), but since tentacles are map-specific and density-sensitive, there are **no code-level defaults** — if the map doesn't define tentacle categories, the question type is unavailable.

### Category Reuse

Tentacles uses the same `FeatureCategory` enum and `MapFeature`/`GameMapFeature` tables as matching and measuring. The same POI datasets (museums, hospitals, zoos, etc.) serve all three question types. The difference is in how the question is resolved and what geometry results.

A category can be available for matching, measuring, *and* tentacles on the same map, tracked independently in the inventory.

### No Fixed Category Set

Unlike matching and measuring which maintain `MATCHING_CATEGORIES` and `MEASURING_CATEGORIES` classification sets, tentacles has **no fixed category set**. Any category with Point-geometry features on the map can be enabled for tentacles. The map constructor decides what makes sense for their map by adding entries to `tentacle_categories`.

The server validates two things:
1. The category has features linked to this map (via `GameMapFeature`).
2. The features have Point geometry (not LineString or Polygon).

This means a map constructor could add a new `FeatureCategory` value and enable it for tentacles without any code changes beyond the enum — they just populate `MapFeature` rows, link them via `GameMapFeature`, and add the entry to `tentacle_categories`.

### Point Geometry Requirement

Tentacles currently requires **Point geometry** features only. This ensures Voronoi computation is exact — no approximation or sampling needed. The Voronoi of a set of points is mathematically well-defined and Shapely computes it precisely.

LineString and Polygon features (transit lines, admin areas, coastlines) are not supported for tentacles yet. Supporting them requires pre-computing generalized Voronoi diagrams at map ingestion time (see HideAndSeek-9ci). An approximate runtime approach (dense sampling along lines/polygon boundaries + cell merging) was considered and rejected — rounding errors at cell boundaries could produce incorrect answers, which would be a game-ruining experience.

### Typical Configurations

For reference, here are typical tentacle configs. Map constructors set these — this is guidance, not enforcement:

| Category | Typical Distance (Imperial) | Notes |
|---|---|---|
| Museum | 1 mi | Dense in cities |
| Library | 1 mi | Dense in cities |
| Movie theater | 1 mi | Dense in cities |
| Hospital | 1 mi | Moderate density |
| Park | 1 mi | Dense in cities, uses pin location |
| Zoo | 15 mi | Sparse — large games only |
| Aquarium | 15 mi | Sparse — large games only |
| Amusement park | 15 mi | Sparse — large games only |
| Golf course | 5 mi | Moderate density |
| Commercial airport | 15 mi | Sparse |
| Foreign consulate | 5 mi | Dense in capital cities |

---

## 3. Server Changes

### 3.1 Types & Enums

**`QuestionType` enum** — add `tentacles`:

```python
class QuestionType(StrEnum):
    radar = 'radar'
    thermometer = 'thermometer'
    matching = 'matching'
    measuring = 'measuring'
    tentacles = 'tentacles'
```

### 3.2 Data Model

**`GameMap`** — new JSON column `tentacle_categories`:

```python
tentacle_categories: Mapped[list] = mapped_column(JSON, default=list)
# e.g., [{"category": "museum", "distance": 1.0}, {"category": "zoo", "distance": 15.0}]
```

**`TentacleQuestionParams`** — new params table (one-to-one with Question):

```python
class TentacleQuestionParams(Base):
    __tablename__ = 'tentacle_question_params'

    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('question.id'), primary_key=True)
    category: Mapped[FeatureCategory]
    poi_ids: Mapped[list] = mapped_column(JSON)  # in-circle MapFeature stable_ids, locked at ask time
    hit: Mapped[bool | None] = mapped_column(default=None)  # populated at answer time
    hider_feature_id: Mapped[str | None] = mapped_column(default=None)  # populated at answer time (hit only)

    question: Mapped[Question] = relationship(back_populates='tentacle_params')
```

`distance` is not stored on the params — it's derivable from the game's map config (`tentacle_categories`). POI names are not stored — they're on `MapFeature.name`, fetchable by `stable_id`.

**`Question`** — new relationship:

```python
tentacle_params: Mapped[TentacleQuestionParams | None] = relationship(
    back_populates='question',
    uselist=False,
)
```

### 3.3 Inventory

**`InventorySlot`** — tentacles slots are created at game start from the map's `tentacle_categories`. Each tentacle category is one slot:

```python
InventorySlot(
    question_type=QuestionType.tentacles,
    slot_index=...,
    category=FeatureCategory.museum,
    distance=1.0,       # stored in the existing `distance` field
)
```

The `distance` field on `InventorySlot` already exists (used for radar/thermometer radii). For tentacles, it stores the configured tentacle distance for the category — dual-purposed but semantically clear from the `question_type`.

### 3.4 Ask Flow

**`ask_tentacles()`** in `logic/ask.py`:

1. Validate the slot: category must be in the map's `tentacle_categories`.
2. Resolve the seeker's current location.
3. Find all `MapFeature` rows for this category within `distance` of the seeker's position (spatial query with `ST_DWithin`).
4. Validate features are Point geometry (reject if any are not).
5. If no POIs are within range, the question is still valid — it means a hit is impossible and the answer will necessarily be a miss. We allow this (it's a wasted card, but that's strategy).
6. Store the in-circle POI stable_ids in `TentacleQuestionParams.poi_ids`.
7. Status → `answerable` immediately (same as matching/measuring — no travel phase).

### 3.5 Answer Flow

**`answer_tentacles()`** in `logic/answer.py`:

```python
def answer_tentacles(question: Question, game: Game) -> None:
    params = question.tentacle_params
    assert params is not None
    assert question.hider_location is not None
    boundary = game.game_map.boundary
    convention = game.game_map.convention

    distance_m = to_meters(
        resolve_tentacle_distance(game.game_map, params.category),
        convention,
    )

    # Phase 1: distance check
    dist_to_seeker = distance(question.seeker_location_start, question.hider_location)

    if dist_to_seeker > distance_m:
        # Miss — degrade to radar miss
        params.hit = False
        exclusion = exclude_radar(boundary, question.seeker_location_start, distance_m, hit=False)
        question.answer = 'miss'
    else:
        # Hit — find nearest POI among the in-circle set
        params.hit = True
        features = get_features_by_stable_ids(game, params.poi_ids)

        nearest_feature = min(
            features,
            key=lambda f: distance(question.hider_location, f.shape),
        )

        params.hider_feature_id = nearest_feature.stable_id
        question.answer = nearest_feature.stable_id

        # Voronoi exclusion: everything outside the answered POI's cell is excluded
        exclusion = exclude_tentacles(
            boundary,
            question.seeker_location_start,
            distance_m,
            answered_poi=nearest_feature.shape,
            other_pois=[f.shape for f in features if f.stable_id != nearest_feature.stable_id],
        )

    question.exclusion = exclusion
    question.total_exclusion = _accumulate_exclusion(game, exclusion)
    question.answered_at = datetime.now(UTC)
    question.status = QuestionStatus.answered
```

**`resolve_tentacle_distance()`** — helper that looks up the configured distance for a category from `GameMap.tentacle_categories`.

**Key difference from other answer functions**: `question.answer` is either `'miss'` or a `stable_id` string — not a binary value. This is the first non-binary answer in the system. The `answer` column is already `str | None`, so no schema change is needed.

### 3.6 Exclusion Geometry

**`exclude_tentacles()`** in `exclusion.py`:

```python
def exclude_tentacles(
    game_map: BaseGeometry,
    seeker_location: Point,
    distance_m: float,
    answered_poi: BaseGeometry,
    other_pois: Sequence[BaseGeometry],
) -> BaseGeometry:
    """Exclusion zone for a tentacles hit.

    Computes Voronoi cells for all in-circle POIs (points only), intersects the
    answered POI's cell with the distance circle to get the "safe zone" where the
    hider is. Excludes everything else in the game boundary.

    On a miss, the caller should use exclude_radar(hit=False) instead.
    """
    circle = _buffer(seeker_location, distance_m)

    all_pois = [answered_poi] + list(other_pois)
    centroid = game_map.centroid
    proj = f'+proj=aeqd +lat_0={centroid.y} +lon_0={centroid.x} +datum=WGS84 +units=m'
    to_local = Transformer.from_crs('EPSG:4326', proj, always_xy=True).transform
    to_wgs = Transformer.from_crs(proj, 'EPSG:4326', always_xy=True).transform

    local_map = transform(to_local, game_map)
    local_circle = transform(to_local, circle)
    local_answered = transform(to_local, answered_poi)
    local_all = [transform(to_local, p) for p in all_pois]

    points = [p.centroid for p in local_all]
    regions = voronoi_polygons(MultiPoint(points), extend_to=local_map.envelope)

    answered_cell = None
    for cell in regions.geoms:
        if cell.contains(local_answered.centroid):
            answered_cell = cell
            break

    if answered_cell is None:
        raise RuntimeError("No Voronoi cell containing answered POI was found")

    # Safe zone = answered cell intersected with the distance circle
    safe_zone = answered_cell.intersection(local_circle)

    # Exclude everything outside the safe zone (within the game boundary)
    exclusion = local_map.difference(safe_zone)
    return transform(to_wgs, exclusion)
```

**Edge case — single POI in circle**: If only one POI is within range, the Voronoi cell is the entire plane. The safe zone is just the `distance` circle. The exclusion is `game_map - circle`. This is equivalent to `exclude_radar(hit=True)`.

### 3.7 Preview

**`boundary_tentacles()`** in `exclusion.py`:

Unlike binary question types where the preview shows *the* dividing line, tentacles has multiple possible outcomes. The preview shows the **distance circle** plus **Voronoi cell boundaries** within it — so the seeker can see how the space would be partitioned.

```python
def boundary_tentacles(
    game_map: BaseGeometry,
    seeker_location: Point,
    distance_m: float,
    pois: Sequence[BaseGeometry],
) -> BaseGeometry:
    """Preview boundary for a tentacles question.

    Returns the distance circle ring plus Voronoi cell edges within the circle,
    clipped to the game map. Shows all possible partition outcomes.
    """
```

For a single POI, returns just the circle ring (no Voronoi partitioning to show).

**Preview response** also includes the list of in-circle POIs with their names and locations, so the seeker can see what they'd be asking about. This is a new field on `PreviewResult`:

```json
{
  "boundary": "<GeoJSON>",
  "tentacle_pois": [
    { "feature_id": "seattle-art-museum", "name": "Seattle Art Museum", "location": {...} },
    { "feature_id": "museum-of-flight", "name": "Museum of Flight", "location": {...} }
  ]
}
```

### 3.8 Events

**`TentacleEventParams`** — new parameter model in `broadcast/events.py`:

```python
class TentacleEventParams(BaseModel):
    type: Literal['tentacles'] = 'tentacles'
    category: str
    distance: float
    poi_ids: list[str]
    poi_names: list[str]
```

Event params include `distance` and `poi_names` because events are ephemeral snapshots — the client shouldn't need to fetch map config or join to `MapFeature` to render a notification. This is denormalization for the event payload, not for storage.

**Question events** — `QuestionAskedEvent.from_question()` and the answered events need to handle tentacles params:

- `QuestionAskedEvent` includes `TentacleEventParams` in the params union. Seekers see the POI list and circle.
- `SeekerQuestionAnsweredEvent` includes the answer (`stable_id` or `'miss'`) and the exclusion geometry as usual.
- `HiderQuestionAnsweredEvent` includes the hider's nearest POI (or miss status).

**Answered event shape for tentacles** — the existing `answer` field carries `'miss'` or the POI `stable_id`. For seekers, this is paired with the POI name from the event params so the UI can display "Closest to: Seattle Art Museum" rather than a raw ID.

### 3.9 Queries

**`get_features_within_distance()`** — new query in `queries/features.py`:

```python
def get_features_within_distance(
    game: Game,
    category: FeatureCategory,
    location: Point,
    distance_m: float,
) -> list[MapFeature]:
    """Find all MapFeatures of a category within distance_m of a location.

    Uses ST_DWithin for indexed spatial filtering. Returns features linked
    to the game's map via GameMapFeature.
    """
```

**`get_features_by_stable_ids()`** — new query for answer-time resolution:

```python
def get_features_by_stable_ids(
    game: Game,
    stable_ids: list[str],
) -> list[MapFeature]:
    """Fetch MapFeatures by their stable_ids, scoped to the game's map."""
```

---

## 4. Mobile: Seeker Experience

### 4.1 Type Selection

Tentacles appears as a fifth button in the belt takeover type selection (section 2 of `question-flow-mobile.md`):

| Button | Icon | Label |
|--------|------|-------|
| Tentacles | `map-marker-multiple` (or similar tentacle/octopus icon) | Tentacles |

The button is only visible if the game has tentacles inventory slots (i.e., the map defines `tentacle_categories`).

### 4.2 Parameter Selection

The belt zone shows a horizontal picker of tentacle category slots from the inventory:

Each item shows:
- The category label (e.g., "Museum", "Zoo")
- The configured distance (e.g., "1 mi", "15 mi")
- The `ask_count` (e.g., "x2" if asked twice before)

Selecting a category triggers the preview.

### 4.3 Preview

**Map overlay:**
- The `distance` circle centered on the seeker's position (same visual treatment as the radar preview circle).
- **Voronoi cell boundaries** within the circle — thin lines showing how the circle would be partitioned. Each cell is labeled or color-coded with the POI it corresponds to.
- **POI markers** within the circle — distinct markers (different from transit stops) showing the POIs that would be in play. Each marker shows the POI name.

**Belt zone:**
- Lists the in-circle POIs by name (scrollable if many).
- Shows the total count (e.g., "4 museums in range").
- If zero POIs are in range, shows a warning: "No [category] in range — a hit is impossible. Ask anyway?" This is a valid but wasteful play.

**Preview updates** as the seeker moves (debounced). The set of in-circle POIs and the Voronoi partitioning change with the seeker's position.

### 4.4 Ask Confirmation

Standard confirmation dialog: "Ask tentacles question? ([category], [distance])"

### 4.5 Active Question Banner (Seeker)

Same as non-thermometer questions:
- Question type icon + "Tentacles — Museum (1 mi)"
- Status: "Waiting for answer..."
- Countdown timer + Abandon button

### 4.6 Answer Resolution (Seeker)

On `question_answered` SSE event:

**Miss:**
- Exclusion overlay updates (circle excluded — same visual as a radar miss)
- Banner briefly shows "Miss — hider not in range" before sliding down
- Timeline entry in context strip: "Tentacles Museum — Miss"

**Hit:**
- Exclusion overlay updates — dramatic visual since most of the map gets excluded
- Banner briefly shows "Hit — closest to [POI name]" before sliding down
- The answered POI's Voronoi cell (intersected with the circle) remains un-excluded on the map — a small island of possibility
- Timeline entry: "Tentacles Museum — [POI name]"

### 4.7 Answer Visualization Details

When a tentacles hit resolves, the map should briefly highlight the Voronoi cell that the hider is in (the "safe zone") before the exclusion overlay settles. This helps seekers immediately understand the spatial implication of the answer. The highlight can be a brief pulse or glow on the safe zone polygon, then it fades to the standard "non-excluded area" rendering.

For the timeline scrubbing feature (from `utility-belt.md`), the tentacles exclusion zone is treated like any other — scrubbing to this question shows the exclusion it produced. The timeline entry could show a small POI icon or the category icon.

---

## 5. Hider Experience (Deferred)

The hider experience is deferred until the broader hider UX is more developed. Key considerations for future design:

- **During answerable phase**: The server computes the hider's nearest in-circle POI from their current location. The hider sees which POI they'd answer with (and can move to change it, outside endgame).
- **Confirmation**: The hider confirms the server-computed answer. The answer is deterministic from their location — confirmation adds transparency and catches GPS drift.
- **Stalling**: Pre-endgame, stalling (not answering until the timer forces auto-answer) is valid strategy — it gives the hider time to reposition.
- **Auto-answer**: In endgame, the hider is locked in place. The server auto-answers based on their location. Same mechanic as other question types.
- **Veto**: The hider can veto a tentacles question (same as any question). Given tentacles' power, vetoing it may be strategically optimal even at the cost of a veto card.

---

## 6. Interaction with Other Systems

### Question Slicing (HideAndSeek-vg2)

Question slicing applies to tentacles the same way as matching/measuring — the set of in-circle POIs could be filtered to candidates relevant in the current game state (e.g., POIs within the non-excluded region). This is a future refinement, not a tentacles-specific design concern.

### Expand Hiding Zone Powerup (HideAndSeek-pwz)

No special interaction. The hiding zone radius is independent of tentacles' `distance`.

### Randomize Powerup (HideAndSeek-fcz)

The hider can use the randomize powerup on a tentacles question, same as any other. The replacement question is randomly selected from the remaining inventory.

### Endgame

Tentacles in endgame is particularly powerful — the hider can't move, so the answer is guaranteed accurate and the exclusion is massive. Map constructors should consider this when setting draw costs.

---

## 7. Resolved Decisions

- **Miss = radar miss**: When the hider is outside the seeker's `distance` circle, the question degrades to `exclude_radar(hit=False)`. The hider's proximity to the actual POIs is irrelevant for the miss case.
- **Exclusion on hit = game boundary minus Voronoi cell**: Not just "within the circle" — the answered POI's Voronoi cell (intersected with the distance circle) is the safe zone, and everything else on the entire map is excluded.
- **Map-data only**: No Google Places fallback for tentacles. The question requires the complete dataset of a category within the circle to compute correct Voronoi cells. If the map doesn't define features for a tentacle category, that category is unavailable.
- **Separate params table**: `TentacleQuestionParams` is a new table, not reusing `FeatureQuestionParams`, because tentacles stores a POI list (not a single resolution) and a hit/miss flag.
- **Lean params**: `distance` is not stored on params (derivable from map config). POI names are not stored (fetchable from `MapFeature.name` by `stable_id`). Only snapshot-dependent data lives on the params table.
- **Non-binary answer**: `question.answer` stores `'miss'` or a `stable_id` string. The existing `str | None` column accommodates this without schema change.
- **No code-level defaults for categories**: Tentacle categories and distances are fully determined by the map's `tentacle_categories` config. No fallback — if the map doesn't define them, tentacles is unavailable.
- **No fixed category set**: Unlike matching/measuring which maintain classification sets, tentacles has no `TENTACLES_CATEGORIES`. Any category with Point-geometry features on the map can be enabled by the map constructor. Validation is geometry-based, not category-based.
- **Point geometry only (for now)**: Tentacles requires Point features to ensure exact Voronoi computation. LineString and Polygon support is deferred to HideAndSeek-9ci (pre-computed Voronoi diagrams at map ingestion). For non-Point categories: matching polygons use containment checks (`ST_Contains`), all others would reduce to their line boundary before Voronoi computation.
- **POI set locked at ask time**: The in-circle POIs are determined and stored when the seeker asks. They are not re-resolved at answer time — the seeker commits to the set they previewed, even if they move afterward.
- **No minimum POI count**: The server does not reject asks with 0 or 1 POIs in the circle. Zero POIs guarantees a miss (wasted card). Single POI degrades to radar-hit semantics on hit. Bad tactical decisions are the seeker's problem.

## 8. Open Questions

- **Draw cost curve**: How does the cost escalate on re-ask? Linear, exponential, or fixed premium? Re-asking the *same category* from a different location gives a different POI partition — the cost curve should discourage spam but allow strategic re-use.
- **Hider preview granularity**: When the hider sees "your answer would be [POI name]," should they also see the full Voronoi partitioning? This reveals how much information the seekers would gain, which might influence the veto decision. Deferred with hider experience.
- **Visual design for Voronoi cells**: How to render the multi-cell partition on mobile in a way that's readable. Color-coding cells vs. just showing boundary lines. This is a mobile design detail, not a server concern.
