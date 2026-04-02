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
  create.tsx                   # Create Game screen
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
  store.ts                     # Zustand store (session + push token state)
  stores/
    gameplayStore.ts           # Zustand store for gameplay state (SSE-driven, not persisted)
  types/
    gameplay.ts                # Gameplay SSE state types (manual — not from OpenAPI)
  constants/
    colors.ts                  # PlayerColor → hex mapping
  hooks/
    useGameplayEvents.ts       # Gameplay SSE (role-aware endpoint, hydrates GameplayStore)
    useLobbyEvents.ts          # Lobby SSE subscription with auto-reconnect + connection status
    usePushToken.ts            # Push permission + native token retrieval (APNs/FCM)
  utils/
    geo.ts                     # GeoJSON ↔ react-native-maps LatLng conversion + regionFromBoundary
  components/                  # Reusable UI components
    GameMap.tsx                # Gameplay map orchestrator (boundary, stops, player pins)
    BoundaryOverlay.tsx        # Game boundary polygon (outline-only stroke)
    StopMarker.tsx             # Transit stop dot marker (non-tappable)
    PlayerPin.tsx              # Player map pin (colored circle + initial + self ring + hider badge + stack count)
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
- **Zustand — GameplayStore** (`src/stores/gameplayStore.ts`) — gameplay state hydrated from SSE. Not persisted — rebuilt from the SSE snapshot on every connection. Discriminated union: `{ status: 'connecting' }` or `{ status: 'connected', role, state }`. The `hydrate()` action replaces state from a `game_state` SSE event; `reset()` reverts to connecting. Used by `useGameplayEvents` hook.
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

- `ConnectionDot` component renders a green/red dot to show connection status. All interactive controls are disabled while disconnected.
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
- **GeoJSON conversion**: All server geometries are GeoJSON (`[lon, lat]`). `src/utils/geo.ts` provides `toLatLng()` and `polygonToCoords()` to convert to `react-native-maps` `{ latitude, longitude }` format.
- **Initial region**: Computed from boundary polygon via `regionFromBoundary()` with 10% padding. Uses `initialRegion` (not `region`) so users can pan/zoom freely.
- **Boundary**: Outline-only `<Polygon>` stroke, no fill.
- **Stops**: Small gray dots, non-tappable (`tappable={false}`). Visual indicators only.
- **Player pins**: Custom `<View>` markers — colored circle with first initial. Self pin has white ring. Hider pins have "?" badge. Stale locations (>60s) render at 0.4 opacity.
- **Stack detection**: Co-located players are detected by rounding coordinates to 4 decimal places (~11m). The topmost pin shows a "+N" count badge.
- **Rendering order**: Players sorted by self-last (highest `zIndex`), then alphabetical. Self pin always renders on top.
- **`tracksViewChanges={false}`**: All markers use this for performance. Marker appearance updates require app restart or SSE reconnect to re-snapshot.
- **Zustand selectors**: Use individual primitive/reference selectors (e.g., `s.status`, `s.role`, `s.state`) — never return new object literals from selectors (causes infinite re-render loops with Zustand's `===` equality check).

## Conventions

- TypeScript strict mode enabled
- `@/` path alias maps to `src/`
- Use `npx expo install` for Expo-compatible packages (not `npm install`)
- Navigation is stack-based (not tabs) — game flow is sequential
- Routes live in `app/`, everything else in `src/`
- `.npmrc` has `legacy-peer-deps=true` due to Expo SDK peer dependency mismatches
- Create/Join → Lobby navigation uses `router.replace` (no going back to forms)
