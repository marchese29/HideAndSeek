# Lobby Mobile Experience

> Status: **Draft**
> Last updated: 2026-03-07

Mobile app screens, navigation, state management, and real-time connectivity for game creation, joining, and the lobby. Companion to `lobby-server.md` which defines the API changes.

---

## 1. Screen Flow

```
Home  ──→  Create Game  ──→  Lobby  ──→  [game started → gameplay screens]
  │
  └────→  Join Game  ──────→  Lobby
```

All screens are stack-pushed (sequential flow, back button pops). The lobby replaces the create/join screen in the stack (no going "back" to the creation form once in the lobby).

### Routes

| Route | Screen | Description |
|-------|--------|-------------|
| `/` | Home | Entry point — create or join |
| `/create` | Create Game | Map picker + name + settings |
| `/join` | Join Game | Join code + name |
| `/lobby/{game_id}` | Lobby | Shared waiting room |

---

## 2. Home Screen

Two primary actions:

- **Create Game** — navigates to `/create`
- **Join Game** — navigates to `/join`

Minimal screen. No map, no game state. Just the two entry points. Future: recent games list, account/settings.

---

## 3. Create Game Screen

The host configures a new game and enters their player name.

### Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| Map | Picker | yes | Select from `GET /maps` list |
| Name | Text input | yes | Host's display name |
| Hiding time | Slider / presets | no | Defaults from selected map |
| Question delay | Numeric stepper | no | Defaults from selected map |

### Map Picker

v1: flat list from `GET /maps` (paginated). Each item shows map name, size badge, and region. Tapping a map selects it (highlight/checkmark). The selected map's defaults populate the timing fields.

Future: geo-aware search, map preview with boundary overlay.

### Timing Controls

- **Hiding time**: show the map's default as the initial value. Offer preset buttons (30m, 60m, 3h) plus a custom input. The map may not have a default — in that case, use the code-level defaults (small=30, medium=60, large=180).
- **Question delay**: numeric stepper, default from the map or 5 minutes. Shown alongside hiding time — both are first-class settings.

### Submit

"Create Game" button → `POST /games` with `{map_id, name, device_token, hiding_time_min?, base_question_delay_min?}` → receive `JoinGameResponse` → navigate to `/lobby/{game_id}`, passing `player_id` in navigation params.

---

## 4. Join Game Screen

A player enters the join code and their name.

### Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| Join code | Text input (4 chars) | yes | Auto-uppercase, large font |
| Name | Text input | yes | Display name |

### Join Code Input

- 4-character input, auto-uppercased.
- Large monospace font, letter-spaced for readability.
- Auto-submit when 4 characters entered (or explicit "Join" button).

### Submit

"Join Game" button → `POST /games/join` with `{join_code, name, device_token}` → receive `JoinGameResponse` → navigate to `/lobby/{game_id}`, passing `player_id` in navigation params.

### Error States

- Invalid code → "No game found with that code" (404)
- Game already started → "This game has already started" (409)
- Game full → "This game is full" (409)

---

## 5. Lobby Screen

The shared waiting room. All players see the same view with minor differences based on whether they're the host.

### Layout (top to bottom)

1. **Join code banner** — large, prominent, tap to copy to clipboard. Subtitle: "Share this code with friends."
2. **Player list** — scrollable list of all players in the game.
3. **Action bar** — bottom of screen, host-only start button.

### Player List

Each player card shows:

- **Color swatch** — filled circle in the player's assigned color (client maps `PlayerColor` enum → hex).
- **Name** — player's display name.
- **Host badge** — crown icon on the host's card, visible to everyone.
- **Role badge** — "Hider" / "Seeker" pill, or "No role" in muted style.

**Your own card** is visually distinct (highlighted border or background) and tappable to open an edit sheet.

### Self-Edit Sheet

Tapping your own player card opens a bottom sheet with:

- **Name** — editable text input, pre-filled with current name.
- **Color picker** — grid of 12 color swatches. Taken colors are visually dimmed/disabled (crossed out or reduced opacity). Tapping an available color selects it.
- **Role toggle** — two-option toggle: Hider / Seeker. Can also be unset (tap active role to deselect).

Each change fires `PATCH /games/{game_id}/players/{player_id}` immediately (optimistic UI with rollback on error). Color change returns 409 if taken — show a brief toast and refresh available colors.

### Start Button (Host Only)

- Visible only to the host.
- **Disabled** (grayed out with helper text) until:
  - All players have a role assigned.
  - At least one hider exists.
  - At least one seeker exists.
- Helper text below the button explains what's missing: "Waiting for all players to pick a role" / "Need at least one hider" / etc.
- Tapping when enabled → `POST /games/{game_id}/start` → game transitions to hiding, SSE delivers `game_started` event to all clients, navigation proceeds to gameplay screens.

### Host Actions

- **Kick player**: swipe-to-delete or long-press on another player's card → confirmation dialog → `DELETE /games/{game_id}/players/{player_id}`.

### Leaving the Lobby

- Back button or explicit "Leave" button.
- Non-host: `DELETE /games/{game_id}/players/{player_id}` (self), navigate to Home.
- Host with other players: prompt to select a new host from the player list → `DELETE` with `new_host_id` in the request body → navigate to Home.
- Host alone: `DELETE` → game dissolved → navigate to Home.

---

## 6. Real-Time Updates (SSE)

### Connection

On entering the lobby screen, open an SSE connection:

```
GET /games/{game_id}/events?client_id={client_id}
```

Using `react-native-sse` (pure JS EventSource implementation, uses XMLHttpRequest internally — no native modules, works with Expo development builds). Known caveat: Expo's CDP interceptor and Flipper's network inspector can interfere with SSE streaming in debug mode. Workaround: disable network inspection during SSE development, or test in release builds. Production is unaffected.

### Event Handling

Events update the TanStack Query cache directly, so all components re-render automatically:

| SSE Event | Cache Update |
|-----------|-------------|
| `game_state` | Replace entire game query data |
| `player_joined` | Append player to game's player list |
| `player_updated` | Upsert player by ID in game's player list |
| `player_left` | Remove player by ID from game's player list |
| `host_changed` | Update host indicator (stored in client state) |
| `game_started` | Update game status, trigger navigation to gameplay |

### Idempotency

The initial `game_state` event may overlap with incremental events (see race condition in `lobby-server.md`). Clients handle this by upserting players by ID — receiving a `player_joined` for someone already in the player list is a no-op.

### Reconnection

`react-native-sse` handles reconnection automatically. On reconnect, the server sends a fresh `game_state` event — the client replaces its cache, converging to the correct state.

### Lifecycle

- **Mount**: open SSE connection.
- **Unmount** (leave lobby, game starts): close SSE connection.
- **App backgrounded**: SSE connection will be dropped by the OS eventually. On foreground resume, the library reconnects and gets a fresh `game_state`.

---

## 7. State Management

### Zustand — Client State

A single Zustand store for identity and session context that persists across screens:

```typescript
interface AppStore {
  clientId: string;          // Generated once, persisted to device storage
  gameId: string | null;     // Set on create/join, cleared on leave
  playerId: string | null;   // Set on create/join, cleared on leave
  hostClientId: string | null; // From game state, used for host UI checks

  setGame: (gameId: string, playerId: string, hostClientId: string) => void;
  clearGame: () => void;
}
```

`clientId` is generated on first launch (UUID v4) and stored in `expo-secure-store` or `AsyncStorage`. This is the value sent as `X-Client-Id` on REST requests and as the query param on SSE.

### TanStack Query — Server State

Server-fetched data lives in the TanStack Query cache, not in Zustand. Key queries:

| Query Key | Endpoint | Used By |
|-----------|----------|---------|
| `['maps']` | `GET /maps` | Create Game screen |
| `['maps', mapId]` | `GET /maps/{map_id}` | Create Game (detail/defaults) |
| `['game', gameId]` | `GET /games/{game_id}` | Lobby screen (initial + SSE updates) |

The lobby screen initializes the `['game', gameId]` cache from the `JoinGameResponse` returned by create/join. SSE events then keep it up to date via `queryClient.setQueryData`.

### Why This Split?

- **Zustand** holds things the server doesn't own: device identity, "which game am I in right now." Lightweight, synchronous, selector-based (avoids re-renders).
- **TanStack Query** holds things the server owns: maps list, game state, player list. Handles caching, deduplication, background refresh, and integrates cleanly with SSE via `setQueryData`.

No Redux, no Context for state — Context is used only for React-level providers (QueryClientProvider, etc.).

---

## 8. Color Mapping

The server sends `PlayerColor` enum values (`red`, `blue`, etc.). The client maps these to hex codes for rendering:

```typescript
const COLOR_HEX: Record<PlayerColor, string> = {
  red: '#E74C3C',
  blue: '#3498DB',
  green: '#2ECC71',
  orange: '#F39C12',
  purple: '#9B59B6',
  teal: '#1ABC9C',
  pink: '#E91E63',
  amber: '#FF9800',
  cyan: '#00BCD4',
  lime: '#8BC34A',
  indigo: '#3F51B5',
  coral: '#FF6F61',
};
```

The color picker in the self-edit sheet shows all 12 swatches. Taken colors (used by other players in the game) are visually dimmed and non-interactive.

---

## 9. Device Token

Push notification token is obtained via `expo-notifications` at app launch (or on the create/join screen if permissions haven't been granted yet). The token is sent with `POST /games` and `POST /games/join` when available, or `null` if the user hasn't granted notification permissions.

If a player is in the lobby without a device token, show a persistent warning banner: "Notifications are off — you'll miss important game updates. Tap to enable." Tapping opens the system notification permission prompt. On grant, the client obtains the token and patches it via `PATCH /games/{game_id}/players/{player_id}` with `{device_token: "..."}`.

The game is fully playable without notifications, but the experience degrades (missed question alerts, no game-started push when backgrounded, etc.).

---

## 10. Navigation Patterns

### Stack Behavior

- Home → Create/Join: standard push.
- Create/Join → Lobby: **replace** (not push). The user shouldn't go "back" to the creation form from the lobby. Use `router.replace('/lobby/{game_id}')`.
- Lobby → Gameplay: replace again (lobby is no longer relevant once the game starts).
- Leave lobby → Home: pop to root.

### Deep Linking (Future)

Join codes could map to deep links: `hideandseek://join/{code}`. Opens the app, pre-fills the join code, and navigates to the join screen. Not in v1.

---

## 11. Dependencies

| Package | Purpose | Notes |
|---------|---------|-------|
| `react-native-sse` | EventSource (SSE) client | Pure JS, no native modules. Install via `npx expo install`. |
| `@tanstack/react-query` | Server state management | Cache, deduplication, background refresh. |
| `zustand` | Client state management | Lightweight, selector-based subscriptions. |

---

## 12. Error Handling

| Scenario | Behavior |
|----------|----------|
| Create/Join API failure | Show error message inline, keep form populated |
| SSE connection lost | Auto-reconnect (library handles). On reconnect, fresh `game_state` re-syncs |
| PATCH player returns 409 (color taken) | Toast message, refresh available colors from cache |
| Game started while editing | `game_started` event triggers navigation regardless of edit state |
| Host leaves while you're in lobby | `player_left` for host + `host_changed` updates UI |
| You get kicked | `player_left` event for your own player_id → toast "You were removed from the game" → navigate to Home |
