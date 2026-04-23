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

# EAS Build (cloud builds — see "EAS Build & Distribution" below). `eas` does
# NOT auto-load .env like `expo` does — always prefix with the source line.
set -a && source .env && set +a && eas build --profile development --platform ios
set -a && source .env && set +a && eas build --profile preview --platform android
set -a && source .env && set +a && eas build --profile production --platform all
set -a && source .env && set +a && eas credentials   # manage iOS certs / Android keystore
set -a && source .env && set +a && eas env:list --environment production
```

## Development Builds

This app requires **development builds** (not Expo Go) because `react-native-maps` needs native compilation. First build takes several minutes. Requires Xcode + command-line tools for iOS, Android Studio for Android. `expo-dev-client` is installed to support the EAS `development` profile.

## Working from a Git Worktree

A fresh worktree under `.claude/worktrees/<branch>/` does not inherit untracked / gitignored files from the main checkout. To get `npx expo run:ios` working:

1. **Copy `mobile/.env` from the main checkout.** It's gitignored (holds `EAS_PROJECT_*`, etc.). Without it `app.config.ts` resolves to a different app identity.
2. **Copy `mobile/google-services.json` from the main checkout** if you'll build for Android. It's gitignored (every contributor downloads their own copy from Firebase Console — see "Push Notifications" below). iOS builds don't need it.
3. **`.watchmanconfig`** at the worktree root marks it as a Watchman project boundary so the daemon doesn't walk up past the worktree's `.git` file into the main checkout. Already committed at the repo root — no per-worktree action needed.

If Metro complains about a missing transitive module (e.g. `@babel/runtime/helpers/wrapRegExp`), the install is partial — `rm -rf node_modules && npm install` (no flags) fixes it. Cause is unclear; reproduce-and-file if it happens cleanly.

## EAS Build & Distribution

Cloud builds via [EAS](https://expo.dev/eas). Defined in `eas.json` at three profiles:

- **development** — dev-client builds. iOS simulator build (no code signing), Android APK. Used for your local iteration loop.
- **preview** — internal distribution for testers. **Android only** (APK, sideloadable). iOS preview is intentionally skipped; TestFlight via `production` covers the same use case.
- **production** — store-ready builds (iOS IPA signed for App Store, Android AAB). `autoIncrement: true` — EAS manages build numbers remotely (`cli.appVersionSource: "remote"`). `eas submit --profile production` pushes to TestFlight internal testing + Google Play internal track.

**Project-scoped EAS resources (live on expo.dev, not in repo):**

- File env var `GOOGLE_SERVICES_JSON` (secret visibility) — uploaded copy of `google-services.json` for FCM. Wired into `app.config.ts` via `android.googleServicesFile = process.env.GOOGLE_SERVICES_JSON ?? './google-services.json'`.
- String env vars `EAS_PROJECT_OWNER` + `EAS_PROJECT_ID` (plaintext) — mirror local `.env` so `app.config.ts` resolves identically in cloud builds.
- Credentials (managed by `eas credentials`) — iOS distribution cert + App Store provisioning profile + APNs push key; Android upload keystore. EAS holds them; back them up with `eas credentials` → Download.

**Dynamic app config + EAS:** because `app.config.ts` is dynamic, `eas init` can't auto-write `projectId` into it. We resolve `owner` and `extra.eas.projectId` from env vars instead. This keeps personal Expo-account identifiers out of the repo and lets every operator own their own project (mirrors the CDK `no-personal-info-in-repo` rule).

**`.env` sourcing quirk:** `eas` CLI does NOT auto-load `.env` (unlike `expo`). Every `eas` invocation must source it first: `set -a && source .env && set +a && eas ...`.

**`.easignore`:** don't create one. It _replaces_ `.gitignore` rather than augmenting it, which means node_modules etc. would start shipping to EAS. EAS's built-in git-archive upload (used when the working tree is clean) already honors `.gitignore`, so committing before each build is the clean path.

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
    ExclusionOverlay.tsx       # Exclusion zone polygon overlay (translucent red, seeker seeking phase only, zIndex 2000) — optional fillColor/strokeColor/strokeWidth/zIndex props for non-default uses (see seeker history scrubber)
    HidingZoneOverlay.tsx      # Hiding zone polygon overlay (translucent blue fill, zIndex 450, strokeOnly prop for endgame outline)
    SafeZoneOverlay.tsx        # Endgame safe zone polygon overlay (translucent blue fill, zIndex 460)
    QuestionCutoffModal.tsx    # Bottom sheet modal for endgame question cutoff selection (uses QuestionHistoryRow)
    QuestionHistoryRow.tsx     # Shared row (icon + Q# + params + answer/status) — read-only when onPress omitted; used by QuestionCutoffModal + HiderQuestionHistoryModal + SeekerQuestionHistoryModal
    HiderQuestionHistoryModal.tsx # Hider read-only history modal — lists all terminal questions (answered + vetoed + abandoned), accessed from belt
    SeekerQuestionHistoryModal.tsx # Seeker scrubber-over-time modal — standalone mini-map replays cumulative exclusion (red) + per-question delta (question-color solid, @turf/difference subtracts prior cumulative), accessed from belt
    PreviewBoundaryOverlay.tsx # Question preview boundary polyline (solid, type-colored, seeker only, zIndex 1500)
    StopMarker.tsx             # Transit stop dot marker (standalone, unused — replaced by TransitRoute)
    TransitRoute.tsx           # Transit route polyline + white stop dots (hides candidates via hiddenStopIds)
    PlayerPin.tsx              # Player map pin (animated — colored circle + initial + self ring + hider badge + stack count)
    DepartureWarningBanner.tsx # Red warning banner when hiders leave the hiding zone (driven by not_in_zone field)
    FreezeWarningBanner.tsx # Red warning banner when hiders move during freeze (driven by freeze_departed field)
    LocationDeniedBanner.tsx   # Warning banner when location permission denied
    ToastHost.tsx              # Top-of-screen toast banner for informational SSE events (slide-down + swipe-to-dismiss)
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
      HiderBeltUtilities.tsx  # Hider utility buttons (default belt center during seeking) — "History" entry point
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
- `EAS_PROJECT_OWNER` — Expo account slug (`marchese29`); drives `owner` in `app.config.ts`
- `EAS_PROJECT_ID` — EAS project UUID; drives `extra.eas.projectId` in `app.config.ts`
- `GOOGLE_SERVICES_JSON` — only set during EAS cloud builds (points at the mounted file); locally, `app.config.ts` falls back to `./google-services.json`

Copy `.env.example` to `.env` and fill in values. Values for `EAS_PROJECT_*` are tied to a specific Expo account — each operator owns their own. Cloud builds read these from project-scoped EAS env vars, not from `.env`.

## State Management

- **Zustand — AppStore** (`src/store.ts`) — session context. `gameId`, `playerId`, `playerSecret`, `role` (all null initially; credentials set on create/join, role set on game start, all cleared on leave/kick). Also holds transient `pushToken` + `pushProvider` (not persisted to AsyncStorage — re-fetched each launch). Credentials are per-game and server-minted — returned in `JoinGameResponse`. Does NOT hold game data.
- **Zustand — GameplayStore** (`src/stores/gameplayStore.ts`) — **dynamic** gameplay state hydrated from SSE. Not persisted — rebuilt from the SSE snapshot on every connection. Discriminated union: `{ status: 'connecting' }` or `{ status: 'connected', role, state }`. The `hydrate()` action replaces state from a `game_state` SSE event; `reset()` reverts to connecting. State includes `host_player_id` for leave/host-transfer UI. Does NOT include static map data (boundary, stops, routes, timing) — that's in TanStack Query via `useGameInfo`. Used by `useGameplayEvents` hook.
- **Zustand — ToastStore** (`src/stores/toastStore.ts`) — in-app toast queue with `current` (displayed) + `queue` (unbounded FIFO). `push({ message, severity? })` sets `current` if empty, else appends to `queue`. `dismiss(id)` promotes the head of `queue` to `current`. `clear()` wipes both. Dispatched from SSE handlers in `useGameplayEvents` for informational gameplay events; rendered by `<ToastHost />`. `clear()` is called in the `useGameplayEvents` effect cleanup so toasts don't survive navigation away from the game screen.
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
- FCM on Android requires `mobile/google-services.json` from Firebase Console (referenced by `app.config.ts`). **Gitignored** — every contributor downloads their own copy: Firebase Console → Project Settings → your Android app → Download `google-services.json`. EAS cloud builds pull the file from the `GOOGLE_SERVICES_JSON` file env var (secret, project-scoped) so they don't depend on a local copy; `app.config.ts` falls back to `./google-services.json` when the env var is absent (i.e., local builds).

## Map Rendering

- **Map provider**: Platform default (Apple Maps on iOS, Google Maps on Android) — no `provider` prop on `<MapView>`.
- **GeoJSON conversion**: All server geometries are GeoJSON (`[lon, lat]`). `src/utils/geo.ts` provides `toLatLng()`, `lineStringToCoords()`, and `polygonToCoords()` to convert to `react-native-maps` `{ latitude, longitude }` format. Also provides `haversineMeters()` for distance between GeoJSON Points and `metersToConvention()` for meters→km/mi conversion.
- **Initial region**: Computed from boundary polygon via `regionFromBoundary()` with 10% padding. Uses `initialRegion` (not `region`) so users can pan/zoom freely.
- **Boundary**: `BoundaryOverlay` renders `MultiPolygon` as one outline-only `<Polygon>` per part (no fill). Uses `multiPolygonToParts()` from `utils/geo.ts`. `regionFromBoundary()` computes the bounding box across all parts.
- **Transit routes**: Colored `<Polyline>` per route (using the route's hex color from the server) with white dot `<Marker>`s at each stop along the route. Rendered by `TransitRoute` component. Stops on multiple routes get overlapping dots (no deduplication needed).
- **Stops**: Rendered as white dots along route polylines (not standalone markers). Stop data is still delivered as a flat `stops` array; `routes` carry `stop_ids` referencing into that array.
- **Player pins**: `Marker.Animated` with `AnimatedRegion` — colored circle with first initial. Pins glide smoothly (500ms timing animation) when coordinates update. Self pin has white ring. Hider pins are semi-transparent (0.4 opacity) with italic initial — signals their location is approximate/private. Stale locations (>60s) turn gray instead of using the player's color.
- **Stack detection**: Co-located players are detected by rounding coordinates to 4 decimal places (~11m). The topmost pin shows a "+N" count badge.
- **Exclusion zones**: `ExclusionOverlay` renders `total_exclusion` (GeoJSON Polygon or MultiPolygon) as translucent red fill (`rgba(231, 76, 60, 0.25)`) with `zIndex={2000}` by default. Rendered on top of all other overlays (boundary, routes, pins) — seeker seeking phase only. Handles MultiPolygon (multiple `<Polygon>` elements) and polygon holes. Reactively updates via `question_answered` SSE → store → prop change. Optional `fillColor` / `strokeColor` / `strokeWidth` / `zIndex` props let other callers reuse the same polygon-rendering logic with different styling (e.g. the seeker history scrubber renders the per-question delta in the question-type color at `zIndex={2100}` on top of the red cumulative).
- **Preview boundary**: `PreviewBoundaryOverlay` renders exclusion preview boundaries (LineString/MultiLineString) as `<Polyline>` elements. Supports two variants via `variant` prop: `'active'` (3px, full opacity, zIndex 1550) for the currently-asked question's boundary, and `'browse'` (1.5px, 50% opacity, zIndex 1500, default) for speculative browse previews. Both use per-type colors (radar=orange, thermometer=yellow, matching=dark, measuring=green, tentacles=purple). `usePreviewBoundary` hook fetches browse previews from `GET /questions/preview`, cached by question type + quantized location (4 decimal places ≈ 11m). `useActiveQuestionBoundary` hook fetches the active question's boundary using the ask-time location (`seeker_location_start`), cached by `questionId` — seeker only. `useHiderQuestionBoundary` hook does the same for hiders, using `seeker_location_start` and `seeker_location_end` from question events — enabled only when status is `answerable`. Seekers can browse while a question is active — asking clears the browse preview (active overlay takes over), and when an answer lands any in-progress browse preview is promoted to askable in the banner.
- **Tentacle POI markers**: `TentaclePOIOverlay` renders purple dot markers at POI locations during tentacles preview (`zIndex={1600}`). Tap shows POI name callout. Only shown when `tentaclePois` is non-empty.
- **Rendering order**: Players sorted by self-last (highest `zIndex`), then alphabetical. Self pin always renders on top. Browse preview at zIndex 1500, active boundary at zIndex 1550, tentacle POIs at zIndex 1600, exclusion overlay at zIndex 2000 renders above everything.
- **`tracksViewChanges`**: Normally `false` for performance. `Marker.Animated` doesn't reliably re-snapshot on its own, so `PlayerPin` briefly pulses `tracksViewChanges={true}` for 200ms when staleness transitions — just enough for the native map to capture the new color. This preserves position animations (key-based recreation would destroy the `AnimatedRegion`).
- **Zustand selectors**: Use individual primitive/reference selectors (e.g., `s.status`, `s.role`, `s.state`) — never return new object literals from selectors (causes infinite re-render loops with Zustand's `===` equality check).

## Location Tracking

- **Permission flow**: `requestLocationPermission()` in `utils/locationPermission.ts` is called at create/join time (foreground "When In Use"). `requestBackgroundLocationPermission()` is called from a `useEffect` in `app/lobby/[game_id].tsx` — deferred to the lobby so the OS "Always" prompt never interrupts a phase transition during active gameplay. Background permission is strictly optional; foreground-only still works on the gameplay screen.
- **Foreground tracking**: `useLocationTracking` hook combines a `watchPositionAsync` subscription (`Accuracy.High`, `distanceInterval: 25m`) with a trailing 30s heartbeat. Each successful POST (movement or heartbeat) schedules a single `setTimeout` that fires 30s later — movement posts reschedule the timer so a steadily-moving player never sends a redundant heartbeat, and a stationary player gets exactly one POST every 30s. Movement posts use the fix's own timestamp; heartbeat posts use `Date.now()` so the server sees "still here, now". Seekers skip POSTing during the hiding phase (reads phase from `GameplayStore` each call). Posts are also suppressed until `GameplayStore.status === 'connected'` so that seeker fixes arriving before the SSE snapshot hydrates don't slip past the hiding-phase guard and 409 on the server. Re-checks permission on foreground resume.
- **Immediate-fix on eligibility edge**: On top of the watch + heartbeat, `useLocationTracking` watches for the post-eligibility gate (`canPost()` — hydrated + not a seeker during hiding) flipping false→true and fires a one-shot `Location.getCurrentPositionAsync` through the normal `handleFix` path. This covers the two transition moments where a stationary player would otherwise be invisible for up to 30s: hider at lobby→hiding, and seeker at hiding→seeking. Gated on `foregroundGranted` so it no-ops when permission is denied; re-armed whenever eligibility drops back to false (e.g. SSE disconnect resets `status` to `'connecting'`).
- **Background tracking**: `mobile/src/background/locationTask.ts` defines a TaskManager task at module load (imported for side effects from `app/_layout.tsx`). `useLocationTracking` starts/stops this task via `Location.startLocationUpdatesAsync('hideandseek-location', ...)` / `stopLocationUpdatesAsync`, gated on background permission **and** on role + phase: hiders always run it (they report during hiding too); seekers only run it once `phase === 'seeking'`. The hook subscribes to `useGameplayStore` and re-syncs on every change, so the task starts at the hiding→seeking transition without a remount. This avoids no-op POSTs (which the server would 409) for seekers across the whole hiding phase. On Android, the OS delivers movement-triggered and `timeInterval`-triggered (30s) events while the app is locked or backgrounded via a foreground service notification. On iOS, only movement triggers deliver in background — `timeInterval` is ignored and JS timers are suspended, so a stationary iOS player stops reporting until they move (known limitation, to be mitigated via silent-push-wake in a follow-on bead). The task handler reads `gameId`/`playerId`/`playerSecret` from the persisted Zustand blob in AsyncStorage (`app-store` key) and POSTs directly via `fetch` (the React `api` middleware isn't available outside the component tree).
- **Foreground/background mutual exclusion**: The TaskManager subscription is a _second_ `CLLocationManager` (separate from the one `watchPositionAsync` opens). If both run at the same time, they each deliver fixes — and the TaskManager one tends to serve cached/stale coordinates, causing the self pin to bounce. So `shouldRunBackground()` returns `false` while `AppState.currentState === 'active'`; the `AppState.change` listener calls `syncBackground()` on background transitions to start the task, and `checkAndStart()` (which calls `syncBackground()`) on foreground transitions to stop it. Net effect: only one OS subscription is ever active.
- **Platform config** (`app.config.ts`): iOS declares `UIBackgroundModes: ['location']`; Android declares `ACCESS_BACKGROUND_LOCATION`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION`. The existing `expo-location` plugin `locationAlwaysAndWhenInUsePermission` string covers the iOS Always rationale. Adding or changing these requires a native rebuild (`npx expo run:ios` / `run:android`) — not a JS-only reload.
- **Server-confirmed self-location**: Each foreground POST updates `selfLocation` in `GameplayStore` only on success, so the self pin correctly turns gray if the server is unreachable. `GameMap` prefers `selfLocation` over SSE data for the self player. `hydrate()` clears `selfLocation` once the SSE snapshot's timestamp catches up. Background posts do not flow through the store (no React context available); they just broadcast to other players via the server.
- **Permission denied**: `LocationDeniedBanner` renders between map and utility belt when foreground location access is refused. Links to device Settings via `Linking.openSettings()`. Background denial does not trigger this banner — background tracking is opportunistic.
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
- **`player_left`**: Player removed — `removePlayer()` filters player from `hiders`/`seekers` arrays. If the removed `player_id` matches the current player (kicked by host), shows `Alert`, clears session, and navigates home. Otherwise, resolves the player name from the store _before_ removal and pushes a toast (`"<Name> has left the game"`).
- **`host_changed`**: Host transferred — `setHostPlayerId()` updates `host_player_id` on state. Pushes a toast: `"You are the new host"` if the new host is self, else `"<Name> has been made the new host"`.
- **`game_dissolved`**: Game ended (last hider/seeker left) — navigates to the recap screen with `reason` (`last_player` / `no_hiders_remaining` / `no_seekers_remaining`) and `role` as params. Session credentials are cleared when the user taps Home on the recap.
- **`game_ended`**: Host ended the game or seekers found the hiders — navigates to the recap screen with `reason` (`host_ended` / `found`) and `role` as params. Session credentials are cleared when the user taps Home on the recap.
- **`hiding_zone_expanded`**: Hider expanded the hiding zone — sets `hiding_zone_expanded = true` on state, invalidates `['hiding-zone']` TanStack Query cache (forces re-fetch of larger polygon), pushes a toast to all roles including the initiating hider: `"The hiding zone has been expanded to <N> <unit>"`. The radius comes from `delta.effective_radius` (already in convention units); the unit is `km`/`mi` from `useGameInfo().distance_convention`.
- **`proximity_escalated`** / **`proximity_deescalated`**: Seeker distance ring changed — `updateProximityTier()` on state. Drives amber hiding zone color. Hider channel only. Pushes a toast via `proximityEscalationMessage` / `proximityDeescalationMessage` copy.
- **`found_claim`**: A seeker claimed found — `setFoundClaimPending(seekerPlayerId, deadlineUtc)` opens `FoundClaimModal` for hiders and `SeekerFoundClaimWaitingModal` for the claiming seeker. Both channels carry the event with the same server-computed `deadline_utc`.
- **`found_claim_rejected`**: Hiders rejected a claim — seekers see a rejection toast **and** `clearFoundClaim()` closes the seeker waiting modal. Seeker channel only.
- **`found_claim_expired`**: Auto-dismiss fired — `clearFoundClaim()` closes the active modal for whichever role has one, both roles see an expiration toast.
- Delta handlers preserve array reference stability: if no player matched, the original array is returned (no unnecessary re-renders).

## In-App Toasts

- `<ToastHost />` (`src/components/ToastHost.tsx`) renders a single top-of-screen banner driven by `useToastStore`. Mounted as a sibling inside `SafeAreaView` in `app/game/[game_id].tsx` after `FoundClaimModal`.
- **Animation**: built-in React Native `Animated` API (Reanimated is NOT installed — do not introduce it casually, it requires an Expo config plugin + native rebuild). Transforms + opacity with `useNativeDriver: true`. 250ms enter, 200ms exit, 5s hold.
- **Dismissal**: `PanResponder` handles both swipe-up (threshold 30px) and tap (movement < 10px). No `GestureHandlerRootView` exists in the tree — `PanResponder` sidesteps that dependency.
- **Positioning**: reads `useSafeAreaInsets().top` and offsets by `insets.top + 8`. `pointerEvents="box-none"` on the wrapper lets taps through around the banner.
- **Queue policy**: `current` + unbounded FIFO `queue`. All pushes are preserved — each dismiss promotes the head of `queue` to `current`. Losing events was deemed worse than a brief backlog, even under bursty SSE activity.
- **Lifecycle**: `useGameplayEvents` calls `useToastStore.getState().clear()` in its effect cleanup so toasts don't survive navigation away from the game screen. The store is NOT cleared on normal SSE reconnect — a visible toast persists across a momentary network blip.

### Alert vs toast rule

**Toast when the screen stays. Alert when the screen changes.** Self-kick still uses `Alert` because it gates navigation to the home screen. Confirmation-style `Alert.alert()` calls (veto / kick / end-game / set-stop / power-up confirms), the hider `FoundClaimModal`, and the seeker `SeekerFoundClaimWaitingModal` stay as-is because they block gameplay until either the user acts or the server resolves the two-party flow. The station auto-assignment `Alert` in `app/game/[game_id].tsx` also stays modal (blocks the hider until acknowledged).

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

## Hider Question History

Read-only modal accessed from the hider utility belt during the seeking phase. Surfaces every terminal question (answered, vetoed, abandoned) with a per-status indicator so the hider can review past gameplay.

- **Entry point**: `HiderBeltUtilities` renders a "History" button in the belt center when the hider is in the seeking phase and station selection is not active. Owned by `UtilityBelt`, which holds the modal's `visible` state.
- **Row component**: `QuestionHistoryRow` is the shared row used by the hider history modal, `QuestionCutoffModal`, and the seeker history modal's question card. Optional `onPress` — Pressable when provided (cutoff modal), View when omitted (history modals). Right column shows the answer label for `status === 'answered'`, otherwise an italic faded "Vetoed" / "Abandoned" badge.
- **Filter**: hider modal shows all entries from `question_history`; cutoff modal still filters to `answered` only because non-answered questions produced no exclusion to seed from.
- **Data source**: `HiderGameState.question_history` (already populated by `applyQuestionAnswered` from `question_answered` SSE events). Live-updates while the modal is open.

## Seeker Question History

Scrubber modal accessed from the seeker utility belt during the seeking phase. Replays answered questions on a standalone mini-map so seekers can review the marginal information value of each question.

- **Entry point**: `BeltUtilities` renders a "History" button (MaterialCommunityIcons `history`) alongside the existing "Endgame" cell. Owned by `UtilityBelt`, which holds the `seekerHistoryVisible` state and mounts `SeekerQuestionHistoryModal`.
- **Scrubber**: horizontal track with `N+1` stops — position `0` is "Start" (before any questions), positions `1..N` are "after Qn". Tap a dot to jump, or pan anywhere on the track to drag — the responder snaps to the nearest stop on each move. Uses `PanResponder` (same core RN pattern as `ToastHost`), no new gesture/slider dep.
- **Map**: fresh `<MapView>` inside the modal (independent of `GameMap.tsx`). `initialRegion` from `regionFromBoundary`. Composes `BoundaryOverlay`, per-route `TransitRoute`, and two `ExclusionOverlay` layers.
- **Delta visualization**: at position `n >= 1`, render two layers — prior cumulative `questions[n-2]?.total_exclusion` in default red, and the _delta_ (`geometryDifference(questions[n-1].total_exclusion, questions[n-2]?.total_exclusion)`) in the question-type color at `zIndex={2100}`. The delta is geometrically subtracted from prior cumulative so the solid question-color area visually encodes the marginal information value of that specific question. Naive z-ordering would blend colors and leak red through the delta — the subtraction is what prevents that.
- **Geometry**: `src/utils/geometryDifference.ts` wraps `@turf/difference` (v7 takes a `FeatureCollection` of two polygon features, returns a `Feature | null`). Non-polygonal inputs pass through as minuend. `@turf/difference` + `@turf/helpers` are the only turf deps — added for this feature.
- **Question card**: at position `0`, a "Start — before any questions were answered" placeholder. At `1..N`, a `QuestionHistoryRow` (read-only, no `onPress`) for `questions[position-1]`.
- **Empty state**: `questions.length === 0` → centered placeholder, scrubber hidden.
- **Open default**: position seats to the latest question on each open so seekers see the most recent delta immediately.
- **Data source**: `SeekerGameState.question_history` (populated by `applyQuestionAnswered`). Each entry carries both `exclusion` (per-question) and `total_exclusion` (cumulative-through-this-question) — the scrubber uses `total_exclusion` exclusively to derive the delta via subtraction of adjacent cumulatives, which sidesteps any ambiguity about the per-question field's semantics.

## Two-Party Game Completion (Waiting Seeker + Confirming Hider)

- **Store field**: `foundClaimPending: { seekerPlayerId: string; deadlineUtc: string } | null` on `GameplayStore`. Shared by both roles — rendering is role-gated by each modal's `visible` check. `deadlineUtc` comes from the server's `FoundClaimEvent.deadline_utc` so both modals share one authoritative countdown. Preserved across SSE reconnects for both roles (the SSE snapshot doesn't carry `found_claim` state, so losing it on hydrate would regress the UI).
- **Hider modal**: `FoundClaimModal` (`src/components/FoundClaimModal.tsx`) — auto-presented at gameplay screen root when `foundClaimPending !== null` and `role === 'hider'`. `presentationStyle="pageSheet"`, `onRequestClose` is a no-op (Android back button cannot dismiss), no swipe-to-dismiss. Two buttons: **Confirm** → `POST /games/{id}/found/confirm` (game ends via subsequent `game_ended` SSE), **Reject** → `POST /games/{id}/found/reject` (clears claim locally and via the server). Either button on 409 clears local state with "Already Resolved" alert (covers the race where a second hider or the auto-dismiss timer beat this one).
- **Seeker modal**: `SeekerFoundClaimWaitingModal` (`src/components/SeekerFoundClaimWaitingModal.tsx`) — auto-presented when `foundClaimPending !== null` and `role === 'seeker'`. Same non-dismissable `pageSheet` styling as the hider modal; no action buttons (intentionally blocking). Shows the title "Awaiting Confirmation..." and a large M:SS countdown driven by `useCountdownTimer(pending.deadlineUtc)`; the countdown hides at 0 so the UI doesn't lie if SSE resolution lags the deadline by a second or two. Dismissal is SSE-driven: `game_ended` (reason=found) navigates to recap, `found_claim_rejected` calls `clearFoundClaim()` plus the existing rejection toast, `found_claim_expired` already calls `clearFoundClaim()` plus an expiration toast.
- **Backstop**: No SSE replay for missed `found_claim` events. The 2-minute server-side auto-dismiss is the backstop for both roles — if a device was offline when the claim arrived, the event expires silently and the modal never presents. The `found_claim_at` field is not exposed on game state snapshots (intentional, keeps scope tight).

- TypeScript strict mode enabled
- `@/` path alias maps to `src/`
- Use `npx expo install` for Expo-compatible packages (not `npm install`)
- Navigation is stack-based (not tabs) — game flow is sequential
- Routes live in `app/`, everything else in `src/`
- `.npmrc` has `legacy-peer-deps=true` due to Expo SDK peer dependency mismatches
- Create/Join → Lobby navigation uses `router.replace` (no going back to forms)
