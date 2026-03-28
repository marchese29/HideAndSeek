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
src/
  api/
    schema.d.ts                # Auto-generated from OpenAPI — DO NOT EDIT
    client.ts                  # openapi-fetch wrapper + X-Player-Id + X-Player-Secret middleware
    queryClient.ts             # TanStack Query client instance
  store.ts                     # Zustand store (session credentials: playerId, playerSecret, gameId)
  constants/
    colors.ts                  # PlayerColor → hex mapping
  hooks/                       # Custom React hooks
  components/                  # Reusable UI components
scripts/
  generate-api.sh              # OpenAPI → TypeScript types
assets/                        # Images, fonts
app.config.ts                  # Expo config (Google Maps key, permissions)
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

- **Zustand** (`src/store.ts`) — session context. `gameId`, `playerId`, `playerSecret` (all null initially, set on create/join, cleared on leave/kick). Credentials are per-game and server-minted — returned in `JoinGameResponse`. Does NOT hold game data.
- **TanStack Query** (`src/api/queryClient.ts`) — server-owned data (game state, maps). SSE events update the cache via `queryClient.setQueryData`. The query cache is the single source of truth for game state.
- `X-Player-Id` and `X-Player-Secret` headers are injected at runtime via `api.use()` middleware in `client.ts` (only when credentials exist). For endpoints where the OpenAPI spec declares these as required header parameters, also pass `header: authHeader()` in the `params` object to satisfy TypeScript types. Import `authHeader` from `@/api/auth`. `POST /games` and `POST /games/join` do not require auth headers (they mint fresh credentials).
- API base URL is platform-aware: `localhost:8000` for iOS simulator, `10.0.2.2:8000` for Android emulator. Override via `EXPO_PUBLIC_API_BASE_URL`.

## Session Recovery

On app launch, `index.tsx` checks for stored credentials:

1. If `gameId` + `playerId` + `playerSecret` exist in the store, call `GET /games/{game_id}/me`
2. If 200 and game is in lobby → navigate to lobby screen
3. If error or game not in lobby → `clearSession()`, show home screen
4. Shows loading indicator while checking

Kicked players' credentials return 403 on `/me` → clean session clear.

## Conventions

- TypeScript strict mode enabled
- `@/` path alias maps to `src/`
- Use `npx expo install` for Expo-compatible packages (not `npm install`)
- Navigation is stack-based (not tabs) — game flow is sequential
- Routes live in `app/`, everything else in `src/`
- `.npmrc` has `legacy-peer-deps=true` due to Expo SDK peer dependency mismatches
- Create/Join → Lobby navigation uses `router.replace` (no going back to forms)
