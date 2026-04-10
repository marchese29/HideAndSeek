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
src/
  api/
    schema.d.ts                # Auto-generated from OpenAPI — DO NOT EDIT
    client.ts                  # openapi-fetch wrapper + X-Player-Id + X-Player-Secret middleware
    queryClient.ts             # TanStack Query client instance
    questions.ts               # Question API calls (answer, veto, abandon, lock-in). Ask uses api.POST directly.
  store.ts                     # Zustand store (session + push token state)
  stores/
    gameplayStore.ts           # Zustand store for gameplay state (SSE-driven, not persisted)
  types/
    gameplay.ts                # Gameplay type aliases (re-exports from auto-generated schema.d.ts)
  constants/
    colors.ts                  # PlayerColor → hex mapping
  hooks/
    useCountdownTimer.ts       # Countdown timer to an ISO deadline (question deadline display)
    useGameplayEvents.ts       # Gameplay SSE (role-aware endpoint, hydrates GameplayStore)
    useGameTimer.ts            # 1s-tick timer: countdown (hiding) / elapsed (seeking)
    useLocationTracking.ts     # Foreground GPS tracking + POST /location + optimistic self update
    useLobbyEvents.ts          # Lobby SSE subscription with auto-reconnect + connection status
    usePreviewBoundary.ts      # Fetches + caches exclusion preview boundary from server (TanStack Query, quantized location key)
    useQuestionSelection.ts    # Question selection state machine (belt takeover flow)
    usePushToken.ts            # Push permission + native token retrieval (APNs/FCM)
  utils/
    geo.ts                     # GeoJSON ↔ react-native-maps LatLng conversion + regionFromBoundary + haversine distance + convention conversion
    locationPermission.ts      # requestLocationPermission() — foreground permission helper
    time.ts                    # parseUtc() — server timestamp parsing (shared by timer hooks)
  components/                  # Reusable UI components
    GameMap.tsx                # Gameplay map orchestrator (boundary, stops, player pins, preview overlay)
    BoundaryOverlay.tsx        # Game boundary MultiPolygon (outline-only stroke, one <Polygon> per part)
    ExclusionOverlay.tsx       # Exclusion zone polygon overlay (translucent red, seeker seeking phase only, zIndex 2000)
    PreviewBoundaryOverlay.tsx # Question preview boundary polyline (dashed blue, seeker only, zIndex 1500)
    StopMarker.tsx             # Transit stop dot marker (standalone, unused — replaced by TransitRoute)
    TransitRoute.tsx           # Transit route polyline + white stop dots
    PlayerPin.tsx              # Player map pin (animated — colored circle + initial + self ring + hider badge + stack count)
    LocationDeniedBanner.tsx   # Warning banner when location permission denied
    ConnectionDot.tsx          # SSE connection status dot (green/red) — used in lobby
    question-banner/           # Question Banner (active question state for both roles)
      index.ts                 # Barrel export
      QuestionBanner.tsx       # Container — slide animation, role dispatch
      SeekerBanner.tsx         # Seeker: preview/ask/active/thermometer states + abandon/lock-in (min_travel validation)
      HiderBanner.tsx          # Hider: pre-lock-in (gray) / answerable (urgency-colored) + answer/veto
      BannerCountdown.tsx      # MM:SS countdown to question deadline
    utility-belt/              # Gameplay utility belt + question selection
      index.ts                 # Barrel export
      UtilityBelt.tsx          # Container — three-section row, wires question selection hook
      StateAction.tsx          # Role/phase action button (icon + label, "Questions" toggle for seeker)
      GameTimer.tsx            # Live timer with connection-colored background
      BeltActions.tsx          # Info + leave icon buttons (context-aware: host-kick / last-of-role / host-transfer / normal)
      QuestionTypeBar.tsx      # 4 question type buttons (radar/thermo/match/measure)
      ParamPicker.tsx          # Horizontal scrollable inventory slot picker
      CustomDistanceInput.tsx  # Inline numeric input for custom distance slots
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
- **Zustand — GameplayStore** (`src/stores/gameplayStore.ts`) — gameplay state hydrated from SSE. Not persisted — rebuilt from the SSE snapshot on every connection. Discriminated union: `{ status: 'connecting' }` or `{ status: 'connected', role, state }`. The `hydrate()` action replaces state from a `game_state` SSE event; `reset()` reverts to connecting. State includes `host_player_id` for leave/host-transfer UI. Used by `useGameplayEvents` hook.
- **TanStack Query** (`src/api/queryClient.ts`) — server-owned data (lobby game state, maps). SSE events update the cache via `queryClient.setQueryData`. The query cache is the single source of truth for lobby game state. Gameplay state uses the GameplayStore instead (SSE deltas mutate nested state that doesn't fit the query cache model).
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
- **Preview boundary**: `PreviewBoundaryOverlay` renders the exclusion preview boundary (LineString/MultiLineString) as dashed blue `<Polyline>` (`rgba(52, 152, 219, 0.7)`) with `zIndex={1500}`. Shown when a seeker selects a question slot (except thermometer). `usePreviewBoundary` hook fetches from `GET /questions/preview` and caches via TanStack Query keyed by question type + quantized location (4 decimal places ≈ 11m). Disappears when preview is cleared.
- **Rendering order**: Players sorted by self-last (highest `zIndex`), then alphabetical. Self pin always renders on top. Preview boundary at `zIndex={1500}`, exclusion overlay at `zIndex={2000}` renders above everything.
- **`tracksViewChanges`**: Normally `false` for performance. `Marker.Animated` doesn't reliably re-snapshot on its own, so `PlayerPin` briefly pulses `tracksViewChanges={true}` for 200ms when staleness transitions — just enough for the native map to capture the new color. This preserves position animations (key-based recreation would destroy the `AnimatedRegion`).
- **Zustand selectors**: Use individual primitive/reference selectors (e.g., `s.status`, `s.role`, `s.state`) — never return new object literals from selectors (causes infinite re-render loops with Zustand's `===` equality check).

## Location Tracking

- **Permission flow**: `requestLocationPermission()` in `utils/locationPermission.ts` is called at create/join time (before entering the game). This prompts the OS dialog early. The gameplay screen checks existing status — no re-prompt.
- **Foreground tracking**: `useLocationTracking` hook polls `Location.getCurrentPositionAsync()` on a manual 10s `setInterval`. Uses polling instead of `watchPositionAsync` because iOS ignores `timeInterval` — a stationary player would stop reporting entirely. Stops on unmount. Re-checks permission on foreground resume (user may toggle in Settings).
- **Server-confirmed self-location**: Each GPS fix is POSTed to the server; `selfLocation` in `GameplayStore` is only updated on successful response (not optimistic). This means the self pin correctly goes gray if the server is unreachable. `GameMap` prefers `selfLocation` over SSE data for the self player. `hydrate()` clears `selfLocation` once the SSE snapshot's timestamp catches up.
- **Permission denied**: `LocationDeniedBanner` renders between map and utility belt when location access is refused. Links to device Settings via `Linking.openSettings()`.

## SSE Delta Events

- **`game_state`**: Full snapshot on connect — `hydrate()` replaces entire `GameplayStore` state.
- **`player_location`**: Real-time position delta — `updatePlayerLocation()` patches a single player's coordinates in the `hiders`/`seekers` arrays without replacing the full state. For seeker state, only `seekers` is patched (hiders are `RosterPlayer[]` with no coordinates).
- **`phase_changed`**: Hiding-to-seeking transition — `applyPhaseChanged()` patches `phase`, `seeking_started_at`, and (hider only) `station_election_status` + `hider_station_id`.
- **`question_asked`**: New question — `setActiveQuestion()` constructs the role-appropriate active question from the delta. `question_deadline` comes from the server (authoritative). Clears `previewQuestion`. Seeker store also persists `parameters` and `seeker_location_start` for thermometer lock-in distance validation (absent after SSE reconnection — gracefully falls back to enabled).
- **`question_answerable`**: Thermometer lock-in — `updateQuestionAnswerable()` updates status and sets `question_deadline`.
- **`question_answered`**: Terminal — `applyQuestionAnswered()` clears `active_question`, appends to `question_history`, updates `total_exclusion` (seeker). Payload differs by role (hider gets answer details, seeker gets exclusion geometry).
- **`question_vetoed`** / **`question_abandoned`**: Terminal — `clearActiveQuestion()` sets `active_question = null`.
- **`player_left`**: Player removed — `removePlayer()` filters player from `hiders`/`seekers` arrays. If the removed `player_id` matches the current player (kicked by host), shows alert, clears session, and navigates home.
- **`host_changed`**: Host transferred — `setHostPlayerId()` updates `host_player_id` on state.
- **`game_dissolved`**: Game ended (last hider/seeker left) — shows alert, clears session, navigates home.
- Delta handlers preserve array reference stability: if no player matched, the original array is returned (no unnecessary re-renders).

## Conventions

- TypeScript strict mode enabled
- `@/` path alias maps to `src/`
- Use `npx expo install` for Expo-compatible packages (not `npm install`)
- Navigation is stack-based (not tabs) — game flow is sequential
- Routes live in `app/`, everything else in `src/`
- `.npmrc` has `legacy-peer-deps=true` due to Expo SDK peer dependency mismatches
- Create/Join → Lobby navigation uses `router.replace` (no going back to forms)
