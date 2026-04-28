# Question Picker Modal — Mobile

> Status: **Draft**
> Last updated: 2026-04-28

Replace the seeker's in-belt parameter picker with a modal that owns parameter selection, preview, and submission for every question type. The belt continues to host the type-icon takeover; the modal takes over once a type is chosen.

Depends on: `2026-04-03-utility-belt.md` (belt layout), `2026-04-04-question-flow-mobile.md` (current question selection + banner), `2026-04-21-photo-questions.md` (photo subjects, the proximate driver), `2026-04-09-tentacles-question.md` (POI markers in preview).

Supersedes: parameter selection ("Step 2") + preview-banner / Ask flow in `2026-04-04-question-flow-mobile.md` §2.

Resolves: HideAndSeek-5zu (control-area cramping / photo-subject horizontal scroll). Implementation tracked under epic HideAndSeek-muo.

---

## 1. Motivation

The in-belt `ParamPicker` is a horizontally-scrolling pill grid. It worked when the largest type had ~5 numeric distances. Photo questions added ~10 subjects per game size; tentacles will grow as we add categories. Three problems compound:

1. **Cardinality skew.** Pills work fine for radar/thermometer (4–5 + custom), tolerably for matching/measuring, and poorly for photo. Per-type divergent in-belt layouts would be worse than a single richer surface that scales — we'd rather not have radar feel airy and photo feel cramped.
2. **Belt vertical budget is finite.** The belt is one row at narrow widths; even growing it to two rows (out of scope here, see §10) only buys us breathing room before it eats the map.
3. **Pill-tap → preview-fetch storm.** Every pill tap fires `usePreviewBoundary` today. Mobile cache absorbs the cost, but the in-belt UX still encourages browsing-by-default rather than committing.

The map must stay the visual core of gameplay — that constraint rules out persistent param surfaces that compete with it for vertical space.

---

## 2. Design Principles

**Uniform shell, layouts tuned per family.** Every type opens the same modal. Inside, the layout matches the data shape — distance is a scrubber, category-with-map is a row + sub-sheet, photo is a list. We're not chasing identical interaction across types; we're consolidating the planning surface.

**Modal as planning surface.** Picking is deliberate, not browsing-by-default. The modal is invoked when the user has decided to ask, dismissed when they've decided what (or changed their mind). The map continues to own the screen the rest of the time.

**Submit lives in the modal.** Tapping Submit is the ask. We delete the seeker banner's preview state, the Ask button, and the pre-ask "Are you sure?" `Alert.alert`. The active-question banner stays — it owns post-ask UI only.

**Preview where the picking happens (when it applies).** Distance and category-with-map families render the live preview in their embedded modal map; the main map's `'browse'` overlay variant is removed. Photo has no map and no preview — it's a list.

**Re-ask visibility carries over.** Every family surfaces the inventory's `ask_count` per option as a "x*N*" badge so the seeker can see at a glance whether they've asked this exact slot before — same affordance the current pill picker provides via its corner badge. Distance: badge rides each scrubber lock. Category-with-map: badge rides each row in the sub-sheet. Photo: badge rides each subject row.

---

## 3. Flow

```
Seeker taps "Questions" (belt state action)
  → Belt center: type-icon takeover (unchanged from today)

Seeker taps a type icon
  → QuestionPickerModal opens with family layout for that type
  → Header carries type name + close button
  → Submit pinned to bottom; disabled until a selection exists

Seeker interacts to select a parameter
  → Selection state updates
  → If family has a map preview, preview boundary updates in modal map
  → Submit lights up

Seeker taps Submit
  → POST to type-appropriate /ask endpoint
  → Modal dismisses
  → SSE delivers question_asked → active-question banner appears

Seeker taps Cancel / dismisses sheet
  → Modal closes, belt returns to type-icon takeover
  → No state lingers, no server call
```

The flow collapses today's `closed → type → param → custom → ask → confirmAlert → ask` into `closed → type → modal → submit`.

---

## 4. Modal Anatomy

A `pageSheet` modal — same primitive as `SeekerQuestionHistoryModal` and `QuestionCutoffModal`. The shell carries:

- **Header** — title (type label), close button, type-color tinting from `questionColors.ts`.
- **Body** — family-specific layout (see below). Sized to fit on a single screen for distance and category-with-map families. Photo body is a vertical scroll list.
- **Footer** — Submit button pinned to the bottom of the modal so it's always reachable without scrolling. Disabled until a selection exists.

### 4.1 Distance family (radar, thermometer)

```
[Header — "Radar"]
[Embedded map (preview boundary)]
[Scrubber with locking points + Custom affordance]
[Submit (pinned)]
```

- **Embedded map** — fresh `<MapView>`, same construction as the seeker history scrubber's mini-map. Composes `BoundaryOverlay`, per-route `TransitRoute`, and `PreviewBoundaryOverlay` (`'active'` variant) once a value is chosen.
- **Scrubber** — horizontal track with discrete locking points at each inventory distance. Tap-a-lock or drag-and-snap both work. The `ask_count` badge rides each lock when nonzero.
- **Custom affordance** — a chip beside or below the scrubber. Tap → inline numeric input (reuses the logic of today's `CustomDistanceInput`) → confirm → the custom value joins the track as a "ghost lock" at its proportional position for the rest of the modal session. Cancel clears it.
- **Map camera** — `initialRegion` from `regionFromBoundary(gameInfo.boundary)` so the player sees the whole game map. Once the user pans/zooms, camera state is theirs; the modal does **not** re-zoom on subsequent param changes. (Acceptable consequence: the preview boundary may land off-screen if the player has panned far away — a pan-to-find is fine.)

### 4.2 Category-with-map family (tentacles, matching, measuring)

```
[Header — "Tentacles" / "Matching" / "Measuring"]
[Embedded map (preview boundary + tentacle POIs when applicable)]
[Current selection row (mirrors seeker history's question card style)]
[Submit (pinned)]
```

- **Embedded map** — same construction as the distance family's. For tentacles, also composes `TentaclePOIOverlay` once a category is selected so POI markers appear inside the modal map.
- **Current selection row** — single row showing either "Tap to choose…" placeholder text or the chosen category + (for tentacles) distance. Tapping the row opens a sub-sheet picker.
- **Sub-sheet picker** — bottom-presented sheet over the modal containing the category list. Scrollable if needed. Pick → sheet dismisses → row updates → preview re-renders. This keeps the main modal compact (no inline expansion eating vertical space) and matches the established `pageSheet`-over-`pageSheet` pattern.
- **Map camera** — same rule as distance: open framing on first paint, no re-zoom on category change.

### 4.3 Photo family

```
[Header — "Photo"]
[Scrollable list of subjects]
[Submit (pinned)]
```

- **No map** — photo questions have null exclusion semantics; the map adds nothing to subject choice. The vertical space goes to the list instead.
- **List** — one row per subject. Each row is a photo-color square (using `questionColors.ts:photo`) holding a representative icon on the left, with the subject label filling the rest of the row.
- **Selection model** — radio: at most one subject selected at a time. Tapping a row selects it (and deselects any prior selection); Submit lights up. Tapping the same row again deselects. No tap-to-submit shortcut — Submit always commits.
- **Scroll** — the list scrolls within the modal; the Submit footer stays pinned. The other families fit without scroll; photo is the one that needs it because of subject count (~10–18 per game size).

---

## 5. State Machine Changes

`useQuestionSelection` simplifies:

| Today | After |
|-------|-------|
| `closed` | `closed` |
| `type` | `type` (belt-takeover, unchanged) |
| `param` | — collapsed into modal |
| `custom` | — collapsed into modal |

Replaced by:

| New | Meaning |
|-----|---------|
| `closed` | belt utilities visible |
| `type` | belt center showing type-icon takeover |
| `modal` | modal open, fixed `{ questionType }` for this open |

`selectSlot` / `openCustom` / `submitCustom` move into the modal as local state. The hook returns to the simpler responsibility of "which top-level mode is the belt in."

`gameplayStore.previewQuestion` and `setPreviewQuestion` go away — the modal owns its preview state. The `PreviewBoundaryOverlay` `'browse'` variant is deleted; the `'active'` variant stays (used both by the main map for the active question and by the modal for live previews).

---

## 6. Selection Persistence + Accidental-Submit Guard

**Selection persists across modal opens** for the duration of the gameplay session. If the seeker submits radar 0.5km, then later reopens the picker for radar, the 0.5km lock is pre-selected and Submit is enabled on first paint. This is convenience for repeat asks; it lives in component / picker-scoped state, not in the gameplay store, and clears on game end with everything else.

> **Open call (revisit before HideAndSeek-muo.2 / distance family):** the persistence rule may not be the right behavior for distance — a scrubber pre-snapped to the previous question's distance may feel too sticky. Confirm or revise this rule per family before implementing each slice.

**Accidental-submit guard.** Because Submit can be enabled on first open (via persisted selection), we want a confirmation Alert *only* when Submit is the very first thing the user touches in this modal session. Concretely:

- Each modal open initializes `hasInteracted = false`.
- Any picker-touch (scrubber drag, scrubber lock tap, custom value entry, sub-sheet category pick, photo row tap) sets `hasInteracted = true`.
- If Submit is pressed while `hasInteracted === false`, show `Alert.alert('Confirm', 'Ask <question>?', [Cancel, Confirm])`. Confirm proceeds with the POST.
- If Submit is pressed while `hasInteracted === true`, POST immediately — the user's act of selecting was the intent.

This is the only "are you sure" we keep. The pre-ask Alert in the current banner flow goes away regardless.

---

## 7. Active-Question Handling

The picker modal can be opened while a question is in flight, **and stays open with live-reactive Submit gating** while open. The modal renders the live preview as the seeker picks. Submit's enabled state is a function of `(hasSelection AND !hasActiveQuestion)` recomputed on every `gameplayStore` change, so:

- **Modal open, question terminates while open** (`question_answered` / `question_abandoned` / `question_vetoed` SSE) → Submit lights up the moment the store updates. No implicit submission, no UI jump — the seeker explicitly taps Submit.
- **Modal open, another seeker asks a question while open** (`question_asked` SSE) → Submit disables immediately and the "Waiting on Q*N*…" hint appears. The seeker can keep adjusting their selection; preview keeps updating; Submit just isn't tappable until the in-flight question terminates.
- **Modal open with no in-flight question, then a question is asked, then terminates** — the modal rides through the whole arc without closing. The seeker's selection state is not cleared by the SSE events.

The `hasInteracted` flag from §6 is unaffected by these SSE transitions — it tracks user-driven picker touches only. So if the user opened the modal with a persisted selection, watched a question fly by without touching anything, and then taps Submit when it re-lights, the accidental-submit confirm Alert still fires (which is the intent of §6).

Today's `useQuestionSelection` auto-closes the selection on rising-edge `hasActiveQuestion`. That behavior is removed in the new design — the modal observes the store and gates Submit, but never closes itself.

If the seeker dismisses the modal before submitting, no in-flight selection survives — the next time they reopen, picker state restores from the last *submitted* selection (per §6), not from a partial pre-empt.

---

## 8. Banner Changes

`SeekerBanner` loses its preview state entirely. The banner renders only when there is an active question. The Ask button + the pre-ask `Alert.alert` are deleted. Branches simplify to: `asked` | `answerable` (thermometer lock-in) | `submitted` (photo) | terminal → unmount. Abandon and lock-in stay — those are post-ask actions.

`HiderBanner` is unchanged; it never had a preview state.

---

## 9. Server / API Impact

None. The picker calls the same `POST /games/{game_id}/questions/<type>` endpoints with the same payloads. The preview fetch hook `usePreviewBoundary` and the `GET /questions/preview` endpoint are unchanged; the modal calls the hook from inside its scope rather than from the belt.

---

## 10. Out of Scope (filed separately)

- **2-row utility belt** — independent goal (utility-count headroom; today fits ~3, want ~6). New bead.
- **Hider powers modal** — when hider powers grow beyond expand-zone, mirror this pattern. Punted explicitly.
- **Hider question UX** — the answer flow is unchanged; this design is seeker-only.

---

## 11. Bead Breakdown

Filed under epic **HideAndSeek-muo** — Question picker modal. Each child is a vertical slice that ships a working slice of the picker; the legacy in-belt path lives until all families migrate, then comes down in a single teardown bead.

1. **HideAndSeek-muo.1 — Shell + photo family, end-to-end.** `QuestionPickerModal` shell (header, pinned Submit footer, sub-sheet primitive scaffolded for later use), photo family body (radio list of subject rows, no map), per-type routing in the belt: tap Photo → modal, all other types still use the in-belt picker. Submit POSTs and dismisses. Live-reactive active-question gating subscribed to `gameplayStore.active_question`. Selection persistence + first-touch accidental-submit confirm guard. Photo subject rows include the `ask_count` re-ask badge. Photo is the gameplay driver behind 5zu and has the simplest body — proves the shell on the smallest surface.

2. **HideAndSeek-muo.2 — Distance family.** Scrubber with locking points + Custom affordance + embedded modal map (`usePreviewBoundary` / `PreviewBoundaryOverlay`). Routes radar + thermometer to the modal. Each scrubber lock carries the `ask_count` re-ask badge. **Open call before starting:** re-evaluate the §6 default-selection rule for this family — defaulting to the previous question's distance may be too sticky. Confirm or revise before implementing.

3. **HideAndSeek-muo.3 — Category-with-map family.** Current-selection row + sub-sheet category picker (reuses the primitive from muo.1) + tentacles `TentaclePOIOverlay` in the modal map. Routes tentacles + matching + measuring to the modal. Each sub-sheet row carries the `ask_count` re-ask badge. With this slice, all question types use the modal.

4. **HideAndSeek-muo.4 — Teardown.** Delete `ParamPicker.tsx`, `CustomDistanceInput.tsx`, `param`/`custom` states + rising-edge auto-close in `useQuestionSelection`, `gameplayStore.previewQuestion` + setter, `SeekerBanner` preview branch + Ask button + pre-ask Alert, `PreviewBoundaryOverlay` `'browse'` variant, per-type routing branch in the belt. CLAUDE.md updates.

Dependencies: muo.1 unblocks muo.2 and muo.3; muo.2 + muo.3 both unblock muo.4.

---

## 12. Open Questions

None at draft time.
