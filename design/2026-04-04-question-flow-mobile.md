# Question Flow — Mobile

> Status: **Draft**
> Last updated: 2026-04-04

Mobile UX for asking questions (seeker) and answering questions (hider) during the seeking phase. Covers the full lifecycle from question selection through resolution.

Depends on: `2026-04-03-utility-belt.md` (belt layout, state action button), `2026-03-29-gameplay-mobile.md` (screen layout, SSE state, map layers), `2026-03-29-gameplay-state.md` (SSE events, question lifecycle).

Supersedes: the placeholder "Ask question" slot in `2026-03-29-gameplay-mobile.md` section 6, the Question Drawer (hider bottom sheet) in `2026-03-29-gameplay-mobile.md` section 7, and the Seeker Question Banner in `2026-03-29-gameplay-mobile.md` section 7.

---

## 1. Design Principles

**Plan, then act.** Both asking and answering have two phases: a planning phase where the player previews the outcome, and an action phase where they commit. The map overlay does the heavy lifting for context — the UI chrome stays minimal.

**Belt takeover for planning.** Question selection occupies the toolbelt center zone rather than a modal or bottom sheet. The map must remain visible and interactive during planning because exclusion previews are the primary decision input.

**Banner for active questions.** Once a question is in flight, a unified Question Banner occupies the context strip's space above the belt's main row. The banner handles status, timers, and actions for both roles. No drawer or bottom sheet.

**Boundary lines, not filled zones.** Exclusion previews show the dividing boundary line(s) on the map rather than two overlapping filled regions. Since question outcomes are always binary and complementary (they partition the game area), the boundary line communicates both outcomes simultaneously. The boundary is determined entirely by the seeker's location and question parameters — it does not depend on the hider's position.

---

## 2. Seeker: Question Selection (Belt Takeover)

Tapping the **Ask** state action button (seeking phase) toggles the toolbelt center zone between normal content and question selection. Tapping Ask again dismisses the selection and restores the toolbelt. The left section (timer) and right section (info + leave) remain visible throughout.

Selection is disabled when `activeQuestion != null` (one active question rule, enforced server-side).

### Step 1: Type Selection

The toolbelt zone shows four buttons, one per question type:

| Button | Icon | Label |
|--------|------|-------|
| Radar | `radar` | Radar |
| Thermometer | `thermometer` | Thermo |
| Matching | `map-marker-check` | Match |
| Measuring | `map-marker-distance` | Measure |

Tapping a type advances to parameter selection. Tapping the Ask button dismisses back to normal belt.

### Step 2: Parameter Selection

The toolbelt zone shows a scrollable picker for the selected type's inventory slots. Content depends on type:

**Radar / Thermometer:**
A horizontal picker of distance values from the inventory slots (e.g., 0.25, 0.5, 1.0, ... miles). Each item shows:
- The distance value
- The `ask_count` (e.g., "x2" if asked twice before)
- The last item is the **custom** slot (`distance: null`) — shows a text input for entering a custom distance

**Matching / Measuring:**
A horizontal picker of POI categories from the inventory slots. Each item shows:
- The category label (e.g., "Hospital", "Park")
- The `feature_class` tier if applicable
- The `ask_count`

Tapping a parameter highlights it and triggers the preview (step 3). Tapping a different parameter switches the preview. Tapping the Ask button dismisses everything.

### Step 3: Preview + Ask

When a parameter is selected:

**Map overlay:** A preview boundary line appears on the map showing where the exclusion divide would fall if the question were asked from the seeker's current location. This is a client request to the preview endpoint (see section 7). The line updates as the seeker moves (debounced).

**Question Banner slides up** (replacing the context strip, see section 5) with:
- Question type icon + parameter summary (e.g., "Radar 1.0 mi")
- **Ask** button — tapping opens a confirmation dialog ("Ask this question?")
- Confirming fires the `POST /questions/{type}` request

After the ask succeeds, the flow transitions to the active question state (section 3).

---

## 3. Seeker: Active Question Banner

Once a question is asked, the banner transitions from the "Ask" state to the active state. The toolbelt zone returns to its normal content.

### Non-Thermometer Questions

Banner shows:
- Question type icon + parameter summary
- Status label ("Waiting for answer...")
- Countdown timer (from `question_deadline`)
- **Abandon** button — destructive color (red-tinted), tapping opens a confirmation dialog ("Abandon this question? The ask is consumed.")

### Thermometer Questions

Thermometer has an extra `in_progress` phase before the hider can answer.

**In-progress state** (seeker is traveling):
- Question type icon + "Thermometer — travel to lock in"
- **Thermometer distance circle** on the map — a circle centered on the ask location with the min_travel radius, rendered in a color distinct from exclusion zones (e.g., blue or purple). Shows the seeker how far they need to move.
- **Lock In** button — disabled until the seeker has traveled at least `min_travel` distance from the ask location. Tapping opens a confirmation dialog ("Lock in your current position?"). Confirming fires `POST /questions/thermometer/{id}/lock-in`.
- **Abandon** button — destructive color, with confirmation dialog

**Post-lock-in state:**
- Same as non-thermometer active banner (timer + abandon)
- Thermometer distance circle dismissed from map

### Resolution

On any terminal SSE event (`question_answered`, `question_vetoed`, `question_abandoned`):
- Banner slides down to reveal the context strip
- Map exclusion overlay updates (if answered)
- Context strip timeline now includes the resolved question

---

## 4. Hider: Active Question Banner

The banner slides up when a `question_asked` SSE event arrives, replacing the context strip. The hider has no question selection flow — they only react to incoming questions.

### Thermometer Pre-Lock-In

When the question status is `asked` or `in_progress` (seeker hasn't locked in yet):
- Banner background: **gray** — no actions available
- Shows: question type icon + "Thermometer from [name] — waiting for lock-in"
- No action buttons
- No map overlay

### All Other States (Answerable)

When the question status is `answerable` (all types post-lock-in, or non-thermometer immediately):

**Banner background color** shifts based on time remaining on the auto-answer timer:
- **Green**: more than 2 minutes remaining
- **Yellow**: 2 minutes or less remaining
- **Red**: 60 seconds or less remaining

Banner shows:
- Question type icon + "[Type] from [name]"
- Countdown timer (from `question_deadline`)
- **Answer** button — primary color. Tapping opens a confirmation dialog ("Answer from your current location?"). Confirming fires `POST /questions/{id}/answer`.
- **Power-up** button — tapping opens a dialog with options:
  - **Veto** — decline to answer (no exclusion zone produced). Honor system — the game trusts the hider has a veto card available.
  - **Randomize** — force a random replacement question (powerup, see `HideAndSeek-fcz`)
  - Each option has its own confirmation step

**Map overlay:** The boundary line for the active question is displayed on the map. This boundary is static — it's determined by the seeker's ask location and question parameters, not the hider's position. The hider can see which side of the boundary they're on and what exclusion the seeker would gain. Since the boundary doesn't change, it's fetched once when the question becomes answerable.

### Resolution

On terminal SSE event:
- Banner slides down to reveal the context strip
- Hider context strip shows station name (unchanged)

---

## 5. Banner and Context Strip

The Question Banner and the context strip (`2026-04-03-utility-belt.md` section 2) occupy the **same space** above the belt's main row. They never display simultaneously.

**Animation:** The banner slides up from the bottom of the context strip space (drawer-style), covering the context strip. On dismiss, it slides back down to reveal the context strip underneath. This gives spatial continuity — the context strip feels like it's "behind" the banner.

| State | What's Shown |
|-------|-------------|
| No active question, no history | Nothing (strip hidden) |
| No active question, has history | Context strip (seeker: question timeline; hider: station name) |
| Seeker planning (pre-ask preview) | Question Banner with Ask button |
| Active question (either role) | Question Banner (role-dependent, see sections 3–4) |

When the banner slides down on question resolution, the context strip is immediately up to date — for seekers, the timeline includes the just-resolved question.

---

## 6. Map Overlays

### Exclusion Preview Boundary (Both Roles)

A boundary line showing where the exclusion divide falls for a question. The boundary is determined entirely by the seeker's location and question parameters — it is answer-agnostic and position-agnostic for the hider.

- **Radar:** Circle at seeker's location with the selected radius.
- **Thermometer:** Not applicable at planning time (requires two positions). After lock-in, shows the perpendicular bisector between the start and end positions.
- **Matching:** Voronoi cell boundary around the seeker's nearest feature of the selected category.
- **Measuring:** Distance buffer boundary around the nearest feature(s) of the selected category.

**Seeker sees this during planning** — it updates as they move (debounced preview endpoint calls).

**Hider sees this during an active answerable question** — it's fetched once since the boundary is fixed for the life of the question.

Both share the same preview endpoint (section 7).

### Thermometer Distance Circle (Seeker, In-Progress)

A circle overlay centered on the seeker's ask location with a radius of `min_travel`. Rendered in a distinct color from exclusion zones (e.g., blue/purple with translucent fill). Shows the seeker the minimum distance they must travel before lock-in is enabled. Dismissed after lock-in.

### Existing: Total Exclusion

The existing `total_exclusion` polygon overlay (seeker, seeking phase) continues to render as described in `2026-03-29-gameplay-mobile.md`. Preview boundary lines render on top of it.

---

## 7. Server: Preview Endpoint

A single read-only endpoint returns the exclusion boundary geometry for a question configuration. Used by both roles — the seeker during planning, the hider during an active question.

```
POST /games/{game_id}/questions/preview
```

**Request body:**
- `question_type`: radar | thermometer | matching | measuring
- `slot_index`: inventory slot to preview
- `location`: position to compute the boundary from (GeoJSON Point) — the seeker's current or ask location
- `custom_distance`: optional, for custom radar/thermometer slots
- `seeker_location_end`: optional, for thermometer post-lock-in (the end position)

**Response:**
- `boundary`: GeoJSON geometry (the dividing line/curve, clipped to game map)
- `feature_preview`: (matching/measuring only) `{ feature_id, name, distance }` — the resolved feature at the given location

**Behavior:**
- No side effects — does not create questions, consume inventory, or modify state
- Auth: standard player-in-game check (either role)
- For radar: computes circle boundary at the given location with the slot's distance (or `custom_distance`)
- For thermometer: requires both `location` (start) and `seeker_location_end` (end) to compute the bisector. Returns 422 if `seeker_location_end` is missing.
- For matching/measuring: resolves the nearest feature and computes Voronoi/buffer boundary
- Client should debounce calls during movement (seeker planning). Hider fetches once per question.

The existing `PreviewQuestionRequest` and `FeaturePreviewResponse` schemas can be extended to support this endpoint.

---

## 8. Confirmation Dialogs

All mutating actions require confirmation:

| Action | Dialog Text | Destructive? |
|--------|------------|:---:|
| Ask (seeker) | "Ask this question?" | No |
| Lock In (seeker) | "Lock in your current position?" | No |
| Abandon (seeker) | "Abandon this question? The ask is consumed." | Yes |
| Answer (hider) | "Answer from your current location?" | No |
| Veto (hider) | "Veto this question? No exclusion zone will be produced." | No |
| Randomize (hider) | "Use randomize power-up? The question will be replaced." | No |

Abandon is the only destructive action (consumes the ask with no benefit). Veto and randomize are strategic game actions the hider uses at their discretion.

---

## 9. State Interactions

### One Active Question Rule

The server enforces a maximum of one unanswered question per game. The client reflects this:
- Ask button is disabled (reduced opacity) when `activeQuestion != null`
- If the seeker is mid-selection when a stale state somehow allows it, the server returns 409

### Connection Loss

When SSE is disconnected:
- Banner actions (Ask, Abandon, Answer, Veto, Randomize, Lock In) are all disabled
- Preview overlays freeze (no location updates being sent)
- Timer continues counting locally (may drift)
- On reconnect: `game_state` rehydrates — banner state corrects, overlays refresh

### Thermometer Travel Validation

The lock-in button's enabled state is computed client-side by comparing the distance between the seeker's current location and the ask location (`seeker_location_start` from the `question_asked` event) against the `min_travel` parameter. This is an approximation — the server validates the actual distance at lock-in time.

---

## 10. Open Questions

- **Thermometer planning preview**: No exclusion preview at ask time since it requires two positions. Could show the preview after lock-in but before the hider answers — the seeker would see both possible thermometer outcomes (the perpendicular bisector). Worth exploring as a refinement.
- **Preview debounce strategy**: How aggressively to debounce preview requests as the seeker moves. Radar previews are cheap (circle geometry); matching/measuring involve feature resolution and Voronoi computation.
- **Hider answer indicator**: The boundary line is static, but the hider's side of the line (and thus their answer) may change as they move. Should the banner or map indicate which answer would currently result? (e.g., a subtle label on the hider's side of the boundary)
- **Randomize power-up availability**: The randomize option in the power-up menu should only appear when the hider has the power-up available. Placeholder for now — depends on `HideAndSeek-fcz` implementation.

---

## 11. Relationship to Implementation Cycles

This design affects several existing beads:

- **Cycle 5** (`HideAndSeek-ww7`): Question Drawer + Question Banner — this design replaces both with the unified Question Banner and belt takeover flow. Cycle 5's scope changes significantly.
- **Cycle B** (`HideAndSeek-wpx`): Context Strip — the banner/context strip replacement rule (section 5) is a dependency. Cycle B needs to account for the banner taking over its space.
- **Cycle 6** (`HideAndSeek-0py`): Exclusion Zone Rendering — the preview overlays (section 6) are related but distinct from the `total_exclusion` rendering in Cycle 6. The preview endpoint (section 7) is new server work.

Suggested implementation order:
1. Server preview endpoint (section 7) — unblocks both seeker and hider preview overlays
2. Belt takeover + type/parameter selection (section 2) — seeker planning flow
3. Question Banner — unified component for both roles (sections 3–5)
4. Map overlays — preview boundaries, thermometer circle (section 6)
