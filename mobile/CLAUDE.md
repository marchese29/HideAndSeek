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
  _layout.tsx                  # Root Stack layout
  index.tsx                    # Home screen
src/
  api/
    schema.d.ts                # Auto-generated from OpenAPI — DO NOT EDIT
    client.ts                  # openapi-fetch wrapper
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

## Conventions

- TypeScript strict mode enabled
- `@/` path alias maps to `src/`
- Use `npx expo install` for Expo-compatible packages (not `npm install`)
- Navigation is stack-based (not tabs) — game flow is sequential
- Routes live in `app/`, everything else in `src/`
- `.npmrc` has `legacy-peer-deps=true` due to Expo SDK peer dependency mismatches
