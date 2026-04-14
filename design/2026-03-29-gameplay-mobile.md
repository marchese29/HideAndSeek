# Gameplay Mobile Experience

> Status: **Draft**
> Last updated: 2026-03-29

Mobile app screens, navigation, state management, and real-time connectivity for the gameplay phase (hiding + seeking). Companion to `2026-03-29-gameplay-state.md` which defines the server contract.

Depends on: `2026-03-07-lobby-mobile.md` (SSE patterns, state management conventions, color mapping).

---

## 1. Screen Flow

```
Lobby  ──[game_started]──→  Gameplay  ──[game finished]──→  [endgame — future design]
```

The gameplay screen **replaces** the lobby in the navigation stack via `router.replace()`. There is no back button — the game screen takes over the app for the duration of the game. No mid-game leave support (future design).

On app launch, if stored credentials point to an active game (`hiding` or `seeking`), the app navigates directly to the gameplay screen (same session recovery pattern as the lobby).

### Routes

| Route | Screen | Description |
|-------|--------|-------------|
| `/game/[game_id]` | Gameplay | Map + question UI + utility belt |

A single route handles both roles. The screen renders differently based on the player's role (hider or seeker) and the game phase (hiding or seeking), driven by the SSE state.

---

## 2. Screen Layout

The gameplay screen is a full-screen vertical stack:

```
┌─────────────────────────────┐
│  Connection dot (top-right) │
│                             │
│                             │
│         MAP VIEW            │
│    (fills available space)  │
│                             │
│                             │
├─────────────────────────────┤  ← Question UI (role-dependent,
│  QUESTION DRAWER / BANNER   │     when question is active)
├─────────────────────────────┤
│  UTILITY BELT               │  ← Fixed height strip at bottom
└─────────────────────────────┘
```

### Map View

Takes up all vertical space not occupied by the utility belt (and question UI when visible). Supports standard map interactions: pinch to zoom, pan, rotate.

### Question UI

Appears when `active_question != null`. Renders differently by role:

- **Hider:** A **drawer** (bottom sheet) that collapses to a bar or expands over the map to show question details and answer actions.
- **Seeker:** A **banner** — a compact, non-expandable strip showing the question status. Since seekers can't answer, they just need to see "question pending" / "waiting for hider."

Both dismiss when the question resolves.

### Utility Belt

A fixed-height strip at the bottom of the screen (above safe area insets). Contents vary by role and phase — see section 6.

---

## 3. Map View Details

### Base Map

`react-native-maps` `<MapView>` filling the available space. Initial region centered on the game map boundary.

### Map Layers

| Layer | When Visible | Rendering |
|-------|-------------|-----------|
| **Boundary** | Always | Translucent polygon outline marking the game area |
| **Stops** | Always | Small dots at each station location. Tappable — shows station name in a callout |
| **Total exclusion** | Seeker, seeking phase | Single semi-transparent polygon from `total_exclusion`. Updated on each `question_answered` event |
| **Player pins** | Always | Colored pins for each visible player. See Player Pins below |

Districts are available in the state data but **not rendered** on the gameplay map — they add visual clutter without actionable value during play.

### Player Pins

Each player is rendered as a colored map marker using their `PlayerColor` hex value.

**Differentiation by role:**
- **Seekers:** Standard pin shape (or circle marker).
- **Hiders:** Distinct pin shape or icon (e.g., different silhouette) so roles are distinguishable at a glance. Only visible to other hiders.

**Self marker:** The player's own pin has a distinct ring, border, or pulse effect.

**Stale location indicator:** If `now - player.timestamp > STALE_THRESHOLD` (e.g., 60 seconds), the pin renders with reduced opacity or a greyed-out color. This signals the player's position may be outdated (GPS lost, app backgrounded, bad signal). The threshold is a client-side constant.

**Tapping a pin:** Opens a callout showing the player's name and color swatch. If the location is stale, shows "Last seen X ago."

### Exclusion Zone Rendering (Seekers)

Only the `total_exclusion` polygon is rendered on the main map — a single semi-transparent overlay (e.g., translucent red). This keeps the map clean. Per-question exclusion breakdowns are available in `question_history` for future features (history scrubbing, detailed exclusion inspector) but not rendered on the primary map view.

---

## 4. SSE Connection

### Hook: `useGameplayEvents`

Follows the same pattern as `useLobbyEvents`:

```typescript
function useGameplayEvents(gameId: string): { connected: boolean }
```

On mount:
1. Read `role` from the current game state (or initial `game_state` event).
2. Open SSE connection to the role-appropriate endpoint:
   - Hider → `GET /games/{gameId}/hider-state`
   - Seeker → `GET /games/{gameId}/seeker-state`
3. Auth via `x-player-id` and `x-player-secret` headers.
4. On `game_state` event: hydrate the gameplay Zustand store.
5. On delta events: update the store incrementally.
6. Return `{ connected }` for UI (connection dot, disabled controls).

Reconnection, exponential backoff, and app foreground resume follow the lobby pattern.

### Event Handling

| SSE Event | Store Update |
|-----------|-------------|
| `game_state` | Replace entire gameplay store state |
| `player_location` | Update `coordinates` + `timestamp` on matching player (only if incoming timestamp is newer) |
| `question_asked` | Set `active_question`. Seekers: increment `ask_count` on matching inventory slot |
| `question_answerable` | Update `active_question.status` + `question_deadline` |
| `question_answered` | Clear `active_question`, append to `question_history`. Seekers: update `total_exclusion` |
| `question_vetoed` | Clear `active_question`, append to `question_history` |
| `question_abandoned` | Clear `active_question`, append to `question_history` |
| `phase_changed` | Update `phase`. Set `seekingStartedAt` from current time |
| `station_election` | Update `station_election_status` + `hider_station_id` (hider only) |
| `player_left` | Remove player from `hiders` or `seekers` list |

---

## 5. State Management

### Zustand — Gameplay State

The gameplay state is managed in a dedicated Zustand store, hydrated from SSE. This differs from the lobby (which used TanStack Query cache) because the SSE connection is the sole source of truth and delta events mutate nested state (player positions, question history).

```typescript
interface GameplayState {
  // Game config (static for game lifetime)
  gameId: string;
  phase: 'hiding' | 'seeking';
  hidingTimeMin: number;
  hidingStartedAt: string;
  seekingStartedAt: string | null;
  baseQuestionDelayMin: number;
  distanceConvention: 'metric' | 'imperial';
  selfPlayerId: string;

  // Map (static for game lifetime)
  boundary: GeoJSON.Polygon;
  stops: Stop[];

  // Players (dynamic — updated by player_location + player_left)
  hiders: GamePlayer[];
  seekers: GamePlayer[];

  // Questions (dynamic)
  activeQuestion: ActiveQuestion | null;
  questionHistory: QuestionHistoryEntry[];

  // Hider-specific
  stationElectionStatus?: StationElectionStatus;
  hiderStationId?: string | null;

  // Seeker-specific
  totalExclusion?: GeoJSON.Geometry | null;
  inventory?: InventorySlot[];

  // Hydration
  hydrated: boolean;
  hydrate: (state: GameStateResponse) => void;
}
```

The `hydrate` action replaces the entire store from a `game_state` SSE event. Delta handlers use `set()` to update specific fields.

### TanStack Query — Utility Endpoints

Utility calculations use TanStack Query (on-demand fetches):

| Query Key | Endpoint | When Used |
|-----------|----------|-----------|
| `['candidate-stations', gameId]` | `GET /candidate-stations` | Seeker utility action |
| `['endgame-exclusions', gameId, stationId]` | `GET /endgame-exclusions` | Seeker endgame tool |
| `['nearby-stations', gameId, lat, lng]` | `GET /nearby-stations` | Hider station search |
| `['hiding-zone', gameId, stationId]` | `GET /hiding-zone` | Hider station preview |

### Zustand Store Split

The existing `AppStore` (credentials: `gameId`, `playerId`, `playerSecret`) remains unchanged. The new `GameplayStore` is a separate Zustand store — not persisted to storage (rebuilt from SSE on every connection).

---

## 6. Utility Belt

A horizontal strip at the bottom of the screen. Each utility is a tappable icon + label. Contents change based on role and phase:

### Hiding Phase — Hider

| Slot | Utility | Action |
|------|---------|--------|
| 1 | Set current stop | Opens station search/selection flow |
| 2+ | Placeholder | Future utilities (TBD) |

### Hiding Phase — Seeker

| Slot | Utility | Action |
|------|---------|--------|
| 1 | Hiding countdown | Time remaining (from `hidingStartedAt` + `hidingTimeMin`). Informational, not tappable |

### Seeking Phase — Hider

| Slot | Utility | Action |
|------|---------|--------|
| 1+ | Placeholder | Future utilities (measure, draw, etc.) |

### Seeking Phase — Seeker

| Slot | Utility | Action |
|------|---------|--------|
| 1 | Ask question | Opens question flow (modal — future design) |
| 2+ | Placeholder | Future utilities (measure, draw, etc.) |

### Timers

- **Hiding countdown** (seeker, hiding phase): in the utility belt. Counts down from `hidingStartedAt` + `hidingTimeMin`.
- **Seeking elapsed** (both roles, seeking phase): a timer showing how long seeking has been active (from `seekingStartedAt`). Exact placement TBD — could be a map overlay or in the utility belt.

### Component

```typescript
function UtilityBelt({ role, phase }: { role: PlayerRole; phase: GamePhase })
```

Each slot is a `<Pressable>` with an icon and short label. Disabled utilities show at reduced opacity.

---

## 7. Question UI

### Hider: Question Drawer

A bottom sheet anchored above the utility belt with two snap points:

**Collapsed (bar, ~50px):**
- Question type icon (distinct per type: radar, thermometer, matching, measuring)
- Brief label — e.g., "Radar question from Bob"
- Countdown timer from `question_deadline`. Shows "Waiting..." if deadline is null (thermometer before lock-in)
- Status pill: `answerable` (green) vs `asked`/`in_progress` (yellow)

**Expanded (~60% of screen):**
- Slides up over the map (map still partially visible above). Does not replace the whole screen.
- Contents are question-type-dependent — **placeholder views for now.** Each type will eventually show contextual information.
- Action buttons: Answer, Veto, Schedule Veto. These fire REST endpoints (204 ACK). State updates arrive via SSE.
- Disabled when `connected === false`.

**Dismiss:** Swipe down to collapse. Question resolution events (`question_answered`, `question_vetoed`, `question_abandoned`) dismiss entirely with animation.

**Implementation:** `@gorhom/bottom-sheet` or similar, with snap points at bar height and expanded height.

### Seeker: Question Banner

A compact, non-expandable strip (~40px) between the map and utility belt. Visible when `active_question != null`:

- Question type icon + "Question asked" / "Waiting for answer..."
- Countdown timer if `question_deadline` is set
- Status: `asked`/`in_progress`/`answerable` shown as a brief label

The banner is informational only — no actions. It tells the seeker their question is in flight and whether the hider has a deadline running.

Dismisses on question resolution.

---

## 8. Phase-Specific Views

### Hiding Phase — Hider

- **Map:** stops, all player positions (both roles), boundary.
- **Utility belt:** "Set current stop" + placeholders.
- **Question UI:** not visible (no questions during hiding).
- **Goal:** travel to a station and optionally elect it.

### Hiding Phase — Seeker

- **Map:** stops, seeker positions only, boundary.
- **Utility belt:** hiding countdown timer.
- **Question UI:** not visible.
- **Note:** hiders appear in the roster (available in state) but have no pins on the map.

### Seeking Phase — Hider

- **Map:** stops, all player positions, boundary.
- **Utility belt:** placeholders (future tools).
- **Question UI:** drawer appears when a question is asked.

### Seeking Phase — Seeker

- **Map:** stops, seeker positions, total exclusion zone, boundary.
- **Utility belt:** "Ask question" + placeholders.
- **Question UI:** banner appears when a question is in flight.

---

## 9. Permissions

### Location + Notifications (Early Request)

Both location and notification permissions are requested during game creation or joining — **not** deferred to the gameplay screen. Location is crucial to the game's function; notifications are important for background alerts.

The create/join flow requests both entitlements together:
1. Request notification permission (`expo-notifications`).
2. Request location permission (`expo-location`, foreground only for now).
3. Proceed to lobby regardless of outcome (both are technically optional but strongly encouraged).

If location is denied, the gameplay screen shows a persistent banner: "Location required — enable in Settings to play." The map renders without the player's own pin, and `POST /location` calls are skipped.

If notifications are denied, the existing lobby banner pattern applies.

---

## 10. Location Reporting

The client reports its position via `POST /games/{gameId}/location` (returns 204) at regular intervals while the game is active.

### Reporting Pattern

Use `expo-location` for foreground location tracking:

```typescript
Location.watchPositionAsync(callback, {
  accuracy: Location.Accuracy.High,
  distanceInterval: 10,   // meters — report when moved 10m+
  timeInterval: 5000,     // ms — at most every 5s
})
```

On each update: fire `POST /location`. The SSE event broadcasts to other players. The client also updates its own pin locally for immediate feedback (don't wait for the SSE echo).

### Background Location (Future)

`expo-location` supports background location, but requires additional configuration. Defer to a future design — for now, location only reports while the app is foregrounded.

---

## 11. Connection & Disabled State

Same pattern as the lobby:

- **Connection dot** in the top-right corner (green/red).
- When disconnected:
  - Utility belt actions disabled (reduced opacity, non-tappable).
  - Question drawer actions (answer/veto) disabled.
  - Map remains interactive (panning/zooming is local state).
  - Subtle banner: "Reconnecting..."
- On reconnect: fresh `game_state` rehydrates the store.

---

## 12. Navigation & Lifecycle

### Entering Gameplay

Lobby SSE `game_started` event → lobby screen navigates:

```typescript
router.replace(`/game/${gameId}`);
```

The gameplay screen mounts, opens its SSE connection, and hydrates from `game_state`.

### Session Recovery

On app launch:
1. Check Zustand store for `gameId` + `playerId` + `playerSecret`.
2. If present, call `GET /games/{gameId}/me` to validate credentials.
3. If game is `hiding` or `seeking` → navigate to `/game/{gameId}`.
4. If `finished` → navigate to endgame (future). If `lobby` → navigate to lobby. If `dissolved`/not found → clear session.

### Screen Lock

The gameplay screen disables:
- Hardware back button (`gestureEnabled: false`).
- Header back button (`headerBackVisible: false`).
- No "Leave" action (future design).

---

## 13. Dependencies

| Package | Purpose | Notes |
|---------|---------|-------|
| `react-native-maps` | Map rendering | Already installed. Native module — requires dev build |
| `react-native-sse` | SSE client | Already installed. Same pattern as lobby |
| `expo-location` | GPS tracking | Foreground tracking. Permission requested at create/join |
| `@gorhom/bottom-sheet` | Question drawer (hider) | Bottom sheet with snap points. Evaluate vs alternatives |

`zustand`, `@tanstack/react-query`, `expo-notifications` already installed.

---

## 14. Component Hierarchy

```
GameplayScreen
├── ConnectionDot                      (existing, reused)
├── MapView
│   ├── BoundaryOverlay               (Polygon)
│   ├── StopMarkers                   (dots, tappable with name callout)
│   ├── ExclusionOverlay              (single Polygon — seeker, seeking only)
│   └── PlayerMarkers
│       ├── SeekerPin                 (standard shape, colored)
│       ├── HiderPin                  (distinct shape — hider view only)
│       ├── SelfIndicator             (ring/pulse on own pin)
│       └── StaleIndicator            (reduced opacity when timestamp old)
├── QuestionDrawer                     (hider only, bottom sheet)
│   ├── CollapsedBar                  (type icon, label, countdown, status)
│   └── ExpandedView                  (placeholder per question type)
├── QuestionBanner                     (seeker only, compact strip)
└── UtilityBelt
    └── UtilitySlot                   (icon + label, pressable)
```

---

## 15. Error Handling

| Scenario | Behavior |
|----------|----------|
| SSE connection lost | Auto-reconnect with backoff. Dot red, controls disabled |
| SSE reconnect | Fresh `game_state` rehydrates store. Dot green |
| Location denied | Persistent banner. Map renders, own pin missing |
| REST mutation fails | Toast with error. State unchanged (no SSE event) |
| Game ends | Navigate to endgame (future) |
| App backgrounded | SSE drops. On foreground: reconnect, fresh snapshot |
| Stale player location | Pin renders with reduced opacity / grey |

---

## 16. Implementation Cycles

### Cycle 1: Screen Skeleton + SSE Connection

- `/game/[game_id]` route with screen lock (no back).
- `GameplayStore` Zustand store with `hydrate` action.
- `useGameplayEvents` hook (role-aware endpoint, connect/reconnect).
- Screen layout: map placeholder + utility belt placeholder + connection dot.
- Session recovery: detect active game on launch → navigate to gameplay.
- Lobby `game_started` → `router.replace('/game/{gameId}')`.

### Cycle 2: Map Rendering

- `<MapView>` with initial region from boundary.
- Boundary polygon overlay.
- Stop markers (dots, tappable with name callout).
- Player pins with color, role differentiation, self indicator.
- Stale location indicator (reduced opacity after threshold).

### Cycle 3: Location Reporting + Permissions

- Request location + notification permissions at create/join time.
- `expo-location` foreground tracking.
- `POST /location` on each update (204).
- Immediate local pin update.
- Permission denied banner.

### Cycle 4: Utility Belt

- `UtilityBelt` component with phase/role switching.
- Hiding countdown timer (seeker).
- Seeking elapsed timer.
- "Ask question" slot (seeker, seeking — placeholder modal).
- "Set current stop" slot (hider, hiding — placeholder flow).
- Remaining slots as disabled placeholders.

### Cycle 5: Question Drawer (Hider) + Question Banner (Seeker)

- Hider drawer: bottom sheet, collapsed bar + expanded snap points.
- Collapsed bar: question type icon, label, countdown, status.
- Expanded: placeholder per type. Answer/veto buttons (REST 204).
- Seeker banner: compact strip with type, status, countdown.
- Both dismiss on question resolution.

### Cycle 6: Exclusion Zone Rendering

- Render `total_exclusion` as translucent polygon overlay (seeker, seeking).
- Update overlay on `question_answered` events.
