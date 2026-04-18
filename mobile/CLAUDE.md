# Mobile App (React Native + Expo)

Cross-platform mobile app built with React Native and Expo SDK 55.

## Commands

```bash
npm install                    # Install dependencies
npx expo run:ios               # Build and run on iOS simulator
npx expo run:android           # Build and run on Android emulator
npx expo start                 # Start dev server (for already-built apps)
npx tsc --noEmit               # Type check
npx expo lint                  # Lint
scripts/generate-api.sh        # Regenerate API types from OpenAPI spec
```

## Development Builds

This app requires **development builds** (not Expo Go) because `react-native-maps` needs native compilation. First build takes several minutes. Requires Xcode + command-line tools for iOS, Android Studio for Android.

## Project Structure

```
app/                           # expo-router file-based routes (stack navigator)
  _layout.tsx                  # Root Stack layout + QueryClientProvider
  index.tsx                    # Home screen
  create.tsx                   # Create Game screen (name, map, size picker, timing config)
  join.tsx                     # Join Game screen
  lobby/
    [game_id].tsx              # Lobby screen
  game/
    [game_id].tsx              # Gameplay screen (full-screen, no header)
  recap.tsx                    # Game Over recap screen — role-aware reason line + Home button
src/
  api/
    schema.d.ts                # Auto-generated from OpenAPI — DO NOT EDIT
    client.ts                  # openapi-fetch wrapper + X-Player-Id + X-Player-Secret middleware
    queryClient.ts             # TanStack Query client instance
    questions.ts               # Question API calls (answer, veto, randomize, abandon, lock-in). Ask uses api.POST directly.
    powers.ts                  # Power-up API calls (expand hiding zone)
  store.ts                     # Zustand store (session + push token state)
  stores/
    gameplayStore.ts           # Zustand store for gameplay state (SSE-driven, not persisted)
  types/
    gameplay.ts                # Gameplay type aliases — unions derived from schema via indexed access, auto-update with server changes
  constants/
    colors.ts                  # PlayerColor → hex mapping
    questionColors.ts          # Per-question-type color constants (active/inactive/onActive/rgb) — shared by banner, belt, and map overlays
  hooks/
    useCountdownTimer.ts       # Countdown timer to an ISO deadline (question deadline display)
    useGameInfo.ts             # Static game info (TanStack Query, fetched once, staleTime=Infinity)
    useGameplayEvents.ts       # Gameplay SSE (role-aware endpoint, hydrates GameplayStore)
    useGameTimer.ts            # 1s-tick timer: countdown (hiding) / elapsed (seeking)
    useLocationTracking.ts     # Foreground GPS tracking + POST /location + optimistic self update
    useLobbyEvents.ts          # Lobby SSE subscription with auto-reconnect + connection status
    useActiveQuestionBoundary.ts # Fetches + caches exclusion boundary for the active question — seeker only (TanStack Query, ask-time location)
    useHiderQuestionBoundary.ts # Fetches + caches exclusion boundary for the active question — hider only (TanStack Query, seeker event locations)
    useHidingZone.ts           # Fetches + caches hiding zone polygon for a candidate stop (TanStack Query, staleTime=Infinity)
    usePreviewBoundary.ts      # Fetches + caches exclusion preview boundary for browse slot (TanStack Query, quantized location key)
    useQuestionSelection.ts    # Question selection state machine (belt takeover flow)
    useCandidateStations.ts    # Fetches candidate stations for seeker endgame station picker (TanStack Query, staleTime=30s)
    useEndgameExclusions.ts    # Fetches endgame exclusions for a station + question cutoff, syncs to gameplay store (TanStack Query, staleTime=0)
    usePushToken.ts            # Push permission + native token retrieval (APNs/FCM)
  utils/
    geo.ts                     # GeoJSON ↔ react-native-maps LatLng conversion + regionFromBoundary + haversine distance + convention conversion
    locationPermission.ts      # requestLocationPermission() — foreground permission helper
    time.ts                    # parseUtc() — server timestamp parsing (shared by timer hooks)
  components/                  # Reusable UI components
    GameMap.tsx                # Gameplay map orchestrator (boundary, stops, player pins, preview overlay, candidate stops, endgame overlays)
    BoundaryOverlay.tsx        # Game boundary MultiPolygon (outline-only stroke, one <Polygon> per part)
    CandidateStopOverlay.tsx   # Candidate stop markers (blue dots, green when highlighted, zIndex 500, hider hiding + seeker endgame picking)
    ExclusionOverlay.tsx       # Exclusion zone polygon overlay (translucent red, seeker seeking phase only, zIndex 2000)
    HidingZoneOverlay.tsx      # Hiding zone polygon overlay (translucent blue fill, zIndex 450, strokeOnly prop for endgame outline)
    SafeZoneOverlay.tsx        # Endgame safe zone polygon overlay (translucent blue fill, zIndex 460)
    QuestionCutoffModal.tsx    # Bottom sheet modal for endgame question cutoff selection
    PreviewBoundaryOverlay.tsx # Question preview boundary polyline (solid, type-colored, seeker only, zIndex 1500)
    StopMarker.tsx             # Transit stop dot marker (standalone, unused — replaced by TransitRoute)
    TransitRoute.tsx           # Transit route polyline + white stop dots (hides candidates via hiddenStopIds)
    PlayerPin.tsx              # Player map pin (animated — colored circle + initial + self ring + hider badge + stack count)
    DepartureWarningBanner.tsx # Red warning banner when hiders leave the hiding zone (driven by not_in_zone field)
    FreezeWarningBanner.tsx # Red warning banner when hiders move during freeze (driven by freeze_departed field)
    LocationDeniedBanner.tsx   # Warning banner when location permission denied
    ConnectionDot.tsx          # SSE connection status dot (green/red) — used in lobby
    question-banner/           # Question Banner (active question state for both roles)
      index.ts                 # Barrel export
      QuestionBanner.tsx       # Container — slide animation, role dispatch
      SeekerBanner.tsx         # Seeker: preview/ask/active/thermometer states + abandon/lock-in (min_travel validation)
      HiderBanner.tsx          # Hider: pre-lock-in / answerable (type-colored bg) + answer preview on button + veto + randomize
      BannerCountdown.tsx      # MM:SS countdown to question deadline
    utility-belt/              # Gameplay utility belt + question selection
      index.ts                 # Barrel export
      UtilityBelt.tsx          # Container — three-section row, wires question selection + stop selection + utility buttons
      BeltUtilities.tsx       # Seeker utility buttons (default belt center when question selection closed) — "Endgame" entry point
      EndgameBeltCenter.tsx    # Endgame view belt center — "Long Game" (exit) + "Found Them" (placeholder) buttons
      EndgameStationPicker.tsx # Endgame station picking belt center — checkmark/station name/cancel 3-button layout
      CandidateStatus.tsx      # Belt center status text for hiders (stop name / "Tap a stop" / "No stops in range")
      StateAction.tsx          # Role/phase action button (icon + label, "Questions" toggle for seeker, "Set Stop" for hider, "Powers" for hider seeking)
      GameTimer.tsx            # Live timer with connection-colored background
      BeltActions.tsx          # More button (ellipsis icon) — opens MoreModal for meta-actions
      QuestionTypeBar.tsx      # Question type buttons (radar/thermo/match/measure/tentacles), filtered by inventory
      ParamPicker.tsx          # Horizontal scrollable inventory slot picker
      CustomDistanceInput.tsx  # Inline numeric input for custom distance slots
    more-modal/                # More modal — bottom sheet for game meta-actions
      index.ts                 # Barrel export
      MoreModal.tsx            # Modal container, screen state machine, shared header (back/close)
      MoreMenu.tsx             # Preferences-style menu list (Stats, Preferences, Leave, End Game, Kick)
      PlaceholderScreen.tsx    # Reusable "Coming soon" body for Stats & Preferences
      LeaveGameScreen.tsx      # Leave confirmation + host transfer picker (multi-step)
      EndGameScreen.tsx        # End game confirmation screen
      KickPlayerScreen.tsx     # Player picker + kick confirmation (multi-step, color dots)
      gameActions.ts           # Extracted async functions: doLeave, doEndGame, doKick
    TentaclePOIOverlay.tsx     # Tentacles preview POI markers (purple dots with name callouts)
scripts/
  generate-api.sh              # OpenAPI → TypeScript types
assets/                        # Images, fonts
app.config.ts                  # Expo config (Google Maps key, permissions, notifications)
.env.example                   # Env var template
```

## API Client

Type-safe API client generated from `openapi/openapi.yaml`:

- `openapi-typescript` generates `src/api/schema.d.ts` (TypeScript types)
- `openapi-fetch` provides a typed fetch client using those types
- Run `scripts/generate-api.sh` after OpenAPI spec changes (pre-commit hook does this automatically)

Usage:

```typescript
import { api } from '@/api/client';

const { data, error } = await api.GET('/games/{game_id}', {
  params: { path: { game_id: '...' } },
});
```

## Environment Variables

- `GOOGLE_MAPS_API_KEY` — build-time, used in `app.config.ts` for native map SDK keys
- `EXPO_PUBLIC_API_BASE_URL` — runtime, defaults to `http://localhost:8000`

Copy `.env.example` to `.env` and fill in values.

## State Management

- **Zustand — AppStore** (`src/store.ts`) — session context. `gameId`, `playerId`, `playerSecret`, `role` (all null initially; credentials set on create/join, role set on game start, all cleared on leave/kick). Also holds transient `pushToken` + `pushProvider` (not persisted to AsyncStorage — re-fetched each launch). Credentials are per-game and server-minted — returned in `JoinGameResponse`. Does NOT hold game data.
- **Zustand — GameplayStore** (`src/stores/gameplayStore.ts`) — **dynamic** gameplay state hydrated from SSE. Not persisted — rebuilt from the SSE snapshot on every connection. Discriminated union: `{ status: 'connecting' }` or `{ status: 'connected', role, state }`. The `hydrate()` action replaces state from a `game_state` SSE event; `reset()` reverts to connecting. State includes `host_player_id` for leave/host-transfer UI. Does NOT include static map data (boundary, stops, routes, timing) — that's in TanStack Query via `useGameInfo`. Used by `useGameplayEvents` hook.
- **TanStack Query** (`src/api/queryClient.ts`) — server-owned data (lobby game state, maps, static game info). SSE events update the cache via `queryClient.setQueryData`. The query cache is the single source of truth for lobby game state and static game info (`useGameInfo` hook, `staleTime: Infinity`). Dynamic gameplay state uses the GameplayStore instead (SSE deltas mutate nested state that doesn't fit the query cache model).
- `X-Player-Id` and `X-Player-Secret` headers are injected at runtime via `api.use()` middleware in `client.ts` (only when credentials exist). For endpoints where the OpenAPI spec declares these as required header parameters, also pass `header: authHeader()` in the `params` object to satisfy TypeScript types. Import `authHeader` from `@/api/auth`. `POST /games` and `POST /games/join` do not require auth headers (they mint fresh credentials).
- API base URL is platform-aware: `localhost:8000` for iOS simulator, `10.0.2.2:8000` for Android emulator. Override via `EXPO_PUBLIC_API_BASE_URL`.

## Session Recovery

On app launch, `index.tsx` checks for stored credentials:

1. If `gameId` + `playerId` + `playerSecret` exist in the store, call `GET /games/{game_id}/me`
2. If 200 and `game_status === 'lobby'` → navigate to lobby screen
3. If 200 and `game_status === 'hiding' | 'seeking'` → restore role from response, navigate to gameplay screen
4. If error, finished, dissolved, or unknown → `clearSession()`, show home screen
5. Shows loading indicator while checking

Kicked players' credentials return 403 on `/me` → clean session clear.

## SSE Connection & Reconnect

Two SSE hooks, same reconnection pattern (exponential backoff 1s → 30s, foreground resume):

- **`useLobbyEvents`** — connects to `/games/{id}/lobby/events`, updates TanStack Query cache. On `game_started`, persists role and navigates to gameplay screen.
- **`useGameplayEvents`** — connects to `/games/{id}/hider-state` or `/games/{id}/seeker-state` (role-aware), hydrates `GameplayStore`. The server SSE endpoints use `include_in_schema=False` so their types are defined manually in `src/types/gameplay.ts` (not from the OpenAPI spec).

Both hooks:

- Use `react-native-sse` `EventSource` with auth headers (`x-player-id`, `x-player-secret`)
- Reconnect with exponential backoff on error. Force fresh connection on foreground resume.
- Return `{ connected: boolean }` for `ConnectionDot` and disabled state.

- **Lobby** uses `ConnectionDot` (green/red dot) for connection status.
- **Gameplay** uses the utility belt timer background color instead: orange (hiding), green (seeking), gray (disconnected). All belt actions are disabled while disconnected; the map remains interactive.
- Lobby and gameplay screens both suppress back navigation (`gestureEnabled: false`, `BackHandler` on Android).
- **Gap detection** (`src/utils/sseSequencing.ts`): each SSE event carries a per-channel monotonic sequence in the `id:` field. Both hooks wrap every `addEventListener` with `createSequenceTracker().wrap(...)` — the first event of a connection establishes the baseline (the `game_state` snapshot's id), subsequent events must equal `last + 1`. A gap (`got > expected + 1`), a missing/non-numeric `lastEventId`, or either of the connection reset events (`open`/`error`) clears the baseline and triggers the standard reconnect path; the fresh snapshot on reconnect is the resync. Stale events (`got <= last`) are logged and dropped — they shouldn't normally occur because the server already filters pre-snapshot events in the stream.

## Push Notifications

- **expo-notifications** provides cross-platform push token retrieval and foreground notification handling.
- `usePushToken()` hook (called on home screen) requests permission and stores the native device token (APNs on iOS, FCM on Android) in Zustand. Uses `getDevicePushTokenAsync()` for the raw native token (not Expo push tokens).
- Token + provider are sent to the server on game create/join via `device_token` + `device_token_provider` fields.
- `_layout.tsx` sets `Notifications.setNotificationHandler()` at module level for foreground display behavior.
- Token rotation is handled by `addPushTokenListener` in the hook; the lobby screen watches for changes and PATCHes the player.
- `expo-device` is used to skip push registration on simulators (`Device.isDevice` check).
- Android requires a notification channel (created in `usePushToken`) before the permission prompt appears.
- FCM on Android requires `google-services.json` from Firebase Console in the project root (referenced in `app.config.ts`).

## Map Rendering

- **Map provider**: Platform default (Apple Maps on iOS, Google Maps on Android) — no `provider` prop on `<MapView>`.
- **GeoJSON conversion**: All server geometries are GeoJSON (`[lon, lat]`). `src/utils/geo.ts` provides `toLatLng()`, `lineStringToCoords()`, and `polygonToCoords()` to convert to `react-native-maps` `{ latitude, longitude }` format. Also provides `haversineMeters()` for distance between GeoJSON Points and `metersToConvention()` for meters→km/mi conversion.
- **Initial region**: Computed from boundary polygon via `regionFromBoundary()` with 10% padding. Uses `initialRegion` (not `region`) so users can pan/zoom freely.
- **Boundary**: `BoundaryOverlay` renders `MultiPolygon` as one outline-only `<Polygon>` per part (no fill). Uses `multiPolygonToParts()` from `utils/geo.ts`. `regionFromBoundary()` computes the bounding box across all parts.
- **Transit routes**: Colored `<Polyline>` per route (using the route's hex color from the server) with white dot `<Marker>`s at each stop along the route. Rendered by `TransitRoute` component. Stops on multiple routes get overlapping dots (no deduplication needed).
- **Stops**: Rendered as white dots along route polylines (not standalone markers). Stop data is still delivered as a flat `stops` array; `routes` carry `stop_ids` referencing into that array.
- **Player pins**: `Marker.Animated` with `AnimatedRegion` — colored circle with first initial. Pins glide smoothly (500ms timing animation) when coordinates update. Self pin has white ring. Hider pins are semi-transparent (0.4 opacity) with italic initial — signals their location is approximate/private. Stale locations (>60s) turn gray instead of using the player's color.
- **Stack detection**: Co-located players are detected by rounding coordinates to 4 decimal places (~11m). The topmost pin shows a "+N" count badge.
- **Exclusion zones**: `ExclusionOverlay` renders `total_exclusion` (GeoJSON Polygon or MultiPolygon) as translucent red fill (`rgba(231, 76, 60, 0.25)`) with `zIndex={2000}`. Rendered on top of all other overlays (boundary, routes, pins) — seeker seeking phase only. Handles MultiPolygon (multiple `<Polygon>` elements) and polygon holes. Reactively updates via `question_answered` SSE → store → prop change.
- **Preview boundary**: `PreviewBoundaryOverlay` renders exclusion preview boundaries (LineString/MultiLineString) as `<Polyline>` elements. Supports two variants via `variant` prop: `'active'` (3px, full opacity, zIndex 1550) for the currently-asked question's boundary, and `'browse'` (1.5px, 50% opacity, zIndex 1500, default) for speculative browse previews. Both use per-type colors (radar=orange, thermometer=yellow, matching=dark, measuring=green, tentacles=purple). `usePreviewBoundary` hook fetches browse previews from `GET /questions/preview`, cached by question type + quantized location (4 decimal places ≈ 11m). `useActiveQuestionBoundary` hook fetches the active question's boundary using the ask-time location (`seeker_location_start`), cached by `questionId` — seeker only. `useHiderQuestionBoundary` hook does the same for hiders, using `seeker_location_start` and `seeker_location_end` from question events — enabled only when status is `answerable`. Seekers can browse while a question is active — asking clears the browse preview (active overlay takes over), and when an answer lands any in-progress browse preview is promoted to askable in the banner.
- **Tentacle POI markers**: `TentaclePOIOverlay` renders purple dot markers at POI locations during tentacles preview (`zIndex={1600}`). Tap shows POI name callout. Only shown when `tentaclePois` is non-empty.
- **Rendering order**: Players sorted by self-last (highest `zIndex`), then alphabetical. Self pin always renders on top. Browse preview at zIndex 1500, active boundary at zIndex 1550, tentacle POIs at zIndex 1600, exclusion overlay at zIndex 2000 renders above everything.
- **`tracksViewChanges`**: Normally `false` for performance. `Marker.Animated` doesn't reliably re-snapshot on its own, so `PlayerPin` briefly pulses `tracksViewChanges={true}` for 200ms when staleness transitions — just enough for the native map to capture the new color. This preserves position animations (key-based recreation would destroy the `AnimatedRegion`).
- **Zustand selectors**: Use individual primitive/reference selectors (e.g., `s.status`, `s.role`, `s.state`) — never return new object literals from selectors (causes infinite re-render loops with Zustand's `===` equality check).

## Location Tracking

- **Permission flow**: `requestLocationPermission()` in `utils/locationPermission.ts` is called at create/join time (before entering the game). This prompts the OS dialog early. The gameplay screen checks existing status — no re-prompt.
- **Foreground tracking**: `useLocationTracking` hook polls `Location.getCurrentPositionAsync()` on a manual 10s `setInterval`. Uses polling instead of `watchPositionAsync` because iOS ignores `timeInterval` — a stationary player would stop reporting entirely. Stops on unmount. Re-checks permission on foreground resume (user may toggle in Settings). Seekers skip GPS/POST during the hiding phase (reads phase from `GameplayStore` each tick) — polling resumes automatically when phase transitions to seeking.
- **Server-confirmed self-location**: Each GPS fix is POSTed to the server; `selfLocation` in `GameplayStore` is only updated on successful response (not optimistic). This means the self pin correctly goes gray if the server is unreachable. `GameMap` prefers `selfLocation` over SSE data for the self player. `hydrate()` clears `selfLocation` once the SSE snapshot's timestamp catches up.
- **Permission denied**: `LocationDeniedBanner` renders between map and utility belt when location access is refused. Links to device Settings via `Linking.openSettings()`.
- **Departure warning**: `DepartureWarningBanner` renders absolutely positioned at the bottom of the map area (overlays the map, does not affect flex layout). Shown when `not_in_zone` is non-empty (hider role only, post-election). Red background (`#E74C3C`), resolves player IDs to names from hiders array. Auto-dismisses when all hiders return to zone.
- **Freeze warning**: `FreezeWarningBanner` takes priority over `DepartureWarningBanner` when `freeze_departed` is non-empty (hider role only, during `entered` proximity tier). Same red background, shows "[Name] moved during freeze!". Auto-dismisses when hiders return to freeze positions.
- **Amber hiding zone**: `HidingZoneOverlay` changes from blue to amber (`#F59E0B`) when `proximity_tier === 'entered'`, signaling hiders should stay put. Reverts on de-escalation.
- **Proximity SSE events**: `useGameplayEvents` handles `proximity_escalated` and `proximity_deescalated` events, updating `proximity_tier` in the gameplay store via `updateProximityTier()`. `freeze_departed` is dispatched from `player_location` events via `updateFreezeDeparted()`.

## SSE Delta Events

- **`game_state`**: Dynamic-only snapshot on connect — `hydrate()` replaces entire `GameplayStore` state. Static data (boundary, stops, routes, timing, convention) is NOT in this event — it's fetched once via `GET /games/{id}/info` and cached by `useGameInfo`.
- **`player_location`**: Real-time position delta — `updatePlayerLocation()` patches a single player's coordinates in the `hiders`/`seekers` arrays without replacing the full state. For seeker state, only `seekers` is patched (hiders are `RosterPlayer[]` with no coordinates). Hider location events also carry `candidate_stations` (dispatched via `updateCandidateStations()`), `not_in_zone` (dispatched via `updateNotInZone()`), and `computed_answer` (dispatched via `updateComputedAnswer()`). Array fields use shallow comparison to avoid unnecessary re-renders; `computed_answer` uses reference equality.
- **`station_election`**: Station elected — `applyStationElection()` patches `station_election_status` and `hider_station_id`, nullifies `candidate_stations` when elected/auto_assigned.
- **`phase_changed`**: Hiding-to-seeking transition — `applyPhaseChanged()` patches `phase`, `seeking_started_at`, and (hider only) `station_election_status` + `hider_station_id`.
- **`question_asked`**: New question — `setActiveQuestion()` constructs the role-appropriate active question from the delta. `question_deadline` comes from the server (authoritative). Clears `previewQuestion`. Both roles persist `parameters` and `seeker_location_start` from the delta (absent after SSE reconnection — gracefully falls back). Hider store also persists these for boundary preview. Seeker store uses them for thermometer lock-in distance validation. Clears `computed_answer` for hiders (stale from previous question).
- **`question_answerable`**: Thermometer lock-in — `updateQuestionAnswerable()` updates status and sets `question_deadline`. Hider store also persists `seeker_location_end` for boundary preview.
- **`question_answered`**: Terminal — `applyQuestionAnswered()` clears `active_question`, appends to `question_history`, updates `total_exclusion` (seeker). Payload differs by role (hider gets answer details, seeker gets exclusion geometry).
- **`question_vetoed`** / **`question_abandoned`**: Terminal — `clearActiveQuestion()` sets `active_question = null`.
- **`player_left`**: Player removed — `removePlayer()` filters player from `hiders`/`seekers` arrays. If the removed `player_id` matches the current player (kicked by host), shows alert, clears session, and navigates home.
- **`host_changed`**: Host transferred — `setHostPlayerId()` updates `host_player_id` on state.
- **`game_dissolved`**: Game ended (last hider/seeker left) — navigates to the recap screen with `reason` (`last_player` / `no_hiders_remaining` / `no_seekers_remaining`) and `role` as params. Session credentials are cleared when the user taps Home on the recap.
- **`game_ended`**: Host ended the game or seekers found the hiders — navigates to the recap screen with `reason` (`host_ended` / `found`) and `role` as params. Session credentials are cleared when the user taps Home on the recap.
- **`hiding_zone_expanded`**: Hider expanded the hiding zone — sets `hiding_zone_expanded = true` on state, invalidates `['hiding-zone']` TanStack Query cache (forces re-fetch of larger polygon), shows alert to seekers.
- **`proximity_escalated`** / **`proximity_deescalated`**: Seeker distance ring changed — `updateProximityTier()` on state. Drives amber hiding zone color. Hider channel only.
- **`found_claim`**: Seeker claimed found — `setFoundClaimPending(seekerPlayerId)` opens the `FoundClaimModal`. Hider channel only.
- **`found_claim_rejected`**: Hiders rejected a claim — seekers see a rejection alert. Seeker channel only.
- **`found_claim_expired`**: Auto-dismiss fired — `clearFoundClaim()` closes the modal (hider), both roles see an expiration alert.
- Delta handlers preserve array reference stability: if no player matched, the original array is returned (no unnecessary re-renders).

## Stop Selection (Hider Hiding Phase)

- **Candidate stops**: Server sends `candidate_stations` (stop UUIDs where all hiders are within hiding zone radius) via `game_state` snapshot and `player_location` SSE events. Stored inline on `HiderGameState`.
- **Map overlay**: `CandidateStopOverlay` renders candidate stops as blue dot markers (`zIndex=500`). Highlighted stop turns green. `TransitRoute` hides its white dots for candidate stops via `hiddenStopIds` to avoid Apple Maps z-index conflicts.
- **Zone overlay**: `HidingZoneOverlay` renders the hiding zone polygon (translucent blue, `zIndex=450`). Pre-election: shown for the highlighted candidate stop. Post-election: shown permanently for the elected station (`hider_station_id` fallback in `GameMap`). Camera animates to zone centroid once on election. Fetched via `useHidingZone` hook (`GET /hiding-zone?station_id=`, cached with `staleTime=Infinity`).
- **Selection flow**: Tap a candidate dot on the map → dot highlights green, zone appears, belt center shows stop name. Tap "Set Stop" → native `Alert.alert` confirmation (warns selection is permanent). Confirm → `POST /hider-station`. Tap map background → clears selection.
- **Single candidate**: Auto-highlighted via `useEffect` in `UtilityBelt` — zone and name appear immediately, one tap to confirm.
- **Ambiguous resolution**: When `station_election_status` transitions to `ambiguous` (hiding timer expired with 0 or 2+ candidates), the stop selection UI persists into the seeking phase. `isStopSelectionActive` in `UtilityBelt` gates selection on `stationElectionStatus !== 'elected' && stationElectionStatus !== 'auto_assigned'` + `(phase === 'hiding' || status === 'ambiguous')`. The "Set Stop" button, candidate status, and auto-highlight all remain active during ambiguous seeking. Powers are inaccessible until a station is elected. The hider question banner shows "Pick A Hiding Zone First!" with grayed-out answer/power-up buttons during ambiguity.
- **Auto-assigned cleanup**: When `phase_changed` carries `auto_assigned` or `elected` status, `applyPhaseChanged` nullifies `candidate_stations` (same as `applyStationElection`) so candidate dots disappear immediately.
- **Apple Maps marker tap quirk**: Both `Marker.onPress` and `MapView.onPress` fire on the same tap. A ref-based guard in `GameplayScreen` (`markerPressedRef`) prevents the map press from clearing the marker press's selection.
- **State bridge**: `highlightedStopId` is lifted to `GameplayScreen` (ephemeral UI state, not in Zustand) and passed to both `GameMap` and `UtilityBelt`. Cleared on phase transition.

## Seeker Endgame View

Phone-local seeker mode for narrowing down hider location. Each seeker independently picks a station and question cutoff, then sees the resulting inclusion/exclusion zones.

- **State**: `endgameView` in `GameplayStore` — `{ stationId, afterQuestion, hidingZone, safeZone, totalExclusion } | null`. Preserved across SSE reconnects (phone-local, not server state). Cleared on `reset()`.
- **Flow**: Tap "Endgame" → station picking mode → candidate stations rendered as blue dots (from `GET /candidate-stations`) → tap station → highlights green with hiding zone preview → tap checkmark → question cutoff modal → pick starting question → `GET /endgame-exclusions` → endgame overlays activate.
- **Station picking belt**: 3-button layout (`EndgameStationPicker`) — checkmark (select, disabled until highlighted), station name (center), X (cancel). Map taps clear highlight but stay in picking mode. X exits picking entirely.
- **Endgame belt**: 2-button layout (`EndgameBeltCenter`) — "Long Game" (binoculars, exits endgame view), "Found Them" (map-marker-account). "Found Them" fires a confirmation `Alert.alert` → `POST /games/{id}/found`. Server rejects with 409 (detail surfaced as toast) if the seeker is outside the hiding zone, there's no station elected, or a claim is already pending.
- **Map overlays when endgame active**: Hiding zone = stroke only (no fill). Safe zone = blue fill (`SafeZoneOverlay`, zIndex 460). Endgame exclusion = red fill (reuses `ExclusionOverlay`). Long-game `total_exclusion` hidden.
- **Question cutoff modal**: `QuestionCutoffModal` — pageSheet modal listing answered questions with type-colored icons. "None" option at bottom = no exclusions. Tapping a question passes `after_question = sequence - 1` (inclusive of selected question).
- **Live updates**: When `question_answered` SSE fires during endgame view, `useGameplayEvents` invalidates `['endgame-exclusions']` query cache → `useEndgameExclusions` re-fetches → overlays update via `updateEndgameView()`.
- **Camera animation**: Animates to endgame hiding zone on activation (same pattern as hider station election). Resets when exiting endgame view.
- **Question selection**: Works normally during endgame — the type bar / param picker takes rendering priority over endgame belt center. Closing question selection returns to Long Game / Found Them buttons.

## Two-Party Game Completion (Hider Confirm/Reject)

- **Store field**: `foundClaimPending: { seekerPlayerId: string } | null` on `GameplayStore`. Hider-only — ignored when `role !== 'hider'`. Preserved across SSE hider reconnects (cleared on hydrate for seekers).
- **Modal**: `FoundClaimModal` (`src/components/FoundClaimModal.tsx`) — auto-presented at gameplay screen root when `foundClaimPending !== null` and `role === 'hider'`. `presentationStyle="pageSheet"`, `onRequestClose` is a no-op (Android back button cannot dismiss), no swipe-to-dismiss. Two buttons: **Confirm** → `POST /games/{id}/found/confirm` (game ends via subsequent `game_ended` SSE), **Reject** → `POST /games/{id}/found/reject` (clears claim locally and via the server). Either button on 409 clears local state with "Already Resolved" alert (covers the race where a second hider or the auto-dismiss timer beat this one).
- **Backstop**: No SSE replay for missed `found_claim` events. The 2-minute server-side auto-dismiss is the backstop — if a hider's phone was offline when the claim arrived, the event expires silently and the modal never presents. The `found_claim_at` field is not exposed on `HiderGameStateResponse` (intentional, keeps scope tight).

- TypeScript strict mode enabled
- `@/` path alias maps to `src/`
- Use `npx expo install` for Expo-compatible packages (not `npm install`)
- Navigation is stack-based (not tabs) — game flow is sequential
- Routes live in `app/`, everything else in `src/`
- `.npmrc` has `legacy-peer-deps=true` due to Expo SDK peer dependency mismatches
- Create/Join → Lobby navigation uses `router.replace` (no going back to forms)
