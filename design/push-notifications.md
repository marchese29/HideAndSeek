# Push Notifications Design

> Status: **Draft**
> Last updated: 2026-02-14

How the server notifies players of game events via Apple Push Notification service (APNs). Defines what triggers each push, what goes over the wire, what the client does on receipt, and how the device token lifecycle works.

---

## Core Principles

1. **Push carries enough data to act on** — event type, game ID, and enough context (question type, parameters, answer) for the client to display meaningful UI without a server round-trip.
2. **Everything pushed is fetchable** — every piece of information delivered via push is also available through existing REST endpoints. Push is never the only path to state changes.
3. **No-op when unconfigured** — the server runs without APNS credentials in dev/test. Push calls log and return silently.

---

## Game Actions and Push Events

### Lobby Phase

**No push.** Everyone is actively on their phone. The client polls `GET /games/{game_id}` to pick up player joins and role assignments.

### Game Started (lobby → hiding)

**Push all players.** Players may have set their phone down while waiting for the host.

| Field | Value |
|-------|-------|
| Event | `game_started` |
| Recipients | All players |
| Alert | "Game on! The hiding phase has begun." |

### Hiding Phase

**No push.** The hider is actively traveling. Seekers wait — their client shows a countdown derived from `timing.hiding_time_min` and the game's started timestamp.

### Hiding → Seeking (server timer)

**Push all players.** This transition is automatic — nobody triggers it. Without push, clients must poll to discover the phase change. This is the single most important push in the game.

| Field | Value |
|-------|-------|
| Event | `phase_changed` |
| Recipients | All players |
| Alert | "Seeking phase has begun! Seekers, start hunting." |

### Radar Question Asked

**Push hider only.** A radar question goes directly to `answerable` — the hider's answer timer starts immediately.

| Field | Value |
|-------|-------|
| Event | `question_asked` |
| Recipients | Hider(s) |
| Alert | "A 3 km radar question has been asked. Your answer timer is running." |
| Data | Question ID, type (`radar`), parameters (`radius_m`), status (`answerable`) |

### Thermometer Question Asked

**Push hider.** The hider should know a thermometer is in progress and how far the seeker needs to travel — it gives them a sense of timing and urgency even though the question isn't answerable yet.

| Field | Value |
|-------|-------|
| Event | `question_asked` |
| Recipients | Hider(s) |
| Alert | "A 500 m thermometer question has started. The seeker is traveling." |
| Data | Question ID, type (`thermometer`), parameters (`min_travel_m`), status (`in_progress`) |

### Thermometer Locked In

**Push hider only.** The seeker has traveled the minimum distance and committed their second position. The question is now `answerable` and the hider's timer starts.

| Field | Value |
|-------|-------|
| Event | `question_answerable` |
| Recipients | Hider(s) |
| Alert | "A thermometer question is ready for your answer." |
| Data | Question ID |

### Question Answered

**Push all seekers.** A new exclusion zone is available — the core feedback loop of the game.

| Field | Value |
|-------|-------|
| Event | `question_answered` |
| Recipients | All seekers |
| Alert | "Question answered: Yes! A new exclusion zone is on the map." (or "No", "Closer", "Farther") |
| Data | Question ID, answer, question type |

### Seeking → Endgame

The endgame triggers when seekers arrive at the hider's station. The hider's rules change (they must stay put), but the seekers may not realize they've arrived — they might just be passing through.

- **Push hider** — visible alert. Their rules change and they need to know immediately.
- **Silent push to seekers** — `content-available` only, no alert. The device needs to adjust behavior (e.g., more frequent location updates) but the humans shouldn't be told — they may not know they're at the right station.

| Field | Value |
|-------|-------|
| Event | `phase_changed` |
| Hider receives | Alert: "Endgame! Stay where you are." |
| Seekers receive | Silent push (no alert, `content-available` only) |

### Game Ended

**No push.** At this point the seekers have physically found the hider — everyone is standing together and probably talking. The app learns the game ended on its next poll or location report.

---

## Payload Specifications

All push notifications use the same APNS payload structure. Game-specific data lives under the `data` key.

### Standard Payload (with alert)

```json
{
  "aps": {
    "alert": {
      "title": "Hide & Seek",
      "body": "<alert text>"
    },
    "sound": "default",
    "content-available": 1,
    "interruption-level": "time-sensitive"
  },
  "data": {
    "event_type": "<event type>",
    "game_id": "<game UUID>",
    "question_id": "<optional>",
    "question_type": "<optional: radar|thermometer>",
    "question_status": "<optional: in_progress|answerable|answered>",
    "parameters": "<optional: type-specific>",
    "answer": "<optional: yes|no|closer|farther>"
  }
}
```

### Silent Payload (seekers in endgame)

```json
{
  "aps": {
    "content-available": 1
  },
  "data": {
    "event_type": "phase_changed",
    "game_id": "<game UUID>"
  }
}
```

No `alert`, no `sound` — iOS wakes the app in the background to process the event, but the user sees nothing.

### Event Types Reference

| Event Type | Trigger | Data Fields | Recipients |
|------------|---------|-------------|------------|
| `game_started` | `POST /games/{id}/start` | — | All players |
| `phase_changed` | Server timer or transition | — | All players (silent for seekers in endgame) |
| `question_asked` | `POST /games/{id}/questions` | `question_id`, `question_type`, `parameters`, `question_status` | Hider(s) |
| `question_answerable` | `POST /games/{id}/questions/{id}/lock-in` | `question_id` | Hider(s) |
| `question_answered` | `POST /games/{id}/questions/{id}/answer` | `question_id`, `question_type`, `answer` | All seekers |

---

## Client Behavior

| App State | Banner | Action |
|-----------|--------|--------|
| **Foregrounded** | Suppressed (handled in-app) | Parse payload → update UI from push data → sync full state in background |
| **Backgrounded** | Shown by system | `content-available` triggers background fetch → local state updated → UI ready when user taps |
| **Killed / Not running** | Shown by system | On tap: app launches → reads payload → fetches current state → navigates to game |

For silent pushes (endgame seekers), the app updates local state without any user-visible indication.

---

## Device Token Lifecycle

### Token on Join

The device token is collected as part of player registration — `POST /games/join` and `POST /games` (for the host). The app is a game companion; push notifications are central to the experience, so requiring a device token at join time is appropriate.

```
POST /games/join

Request body:
{
  "join_code": "ABCD",
  "name": "Alice",
  "color": "#FF5733",
  "device_token": "<hex-encoded APNS device token>",
  "device_token_environment": "production"
}
```

```
POST /games

Request body:
{
  "map_id": "uuid",
  "device_token": "<hex-encoded APNS device token>",
  "device_token_environment": "production"
}
```

- **Upsert semantics**: the server stores/updates the device token for this `client_id` (from `X-Client-Id` header). If the token changed since last time (iOS rotated it, reinstall, etc.), the new one replaces the old.
- **`device_token_environment`**: `"production"` for App Store / TestFlight, `"sandbox"` for development builds. APNs sandbox and production are separate services.
- The response shapes for both endpoints are unchanged — the device token is accepted and stored silently.

### Token Belongs to Client, Not Game

A device token maps to a `client_id` in its own table (`DeviceToken`), separate from `Player`. When the server needs to push:

1. Look up `Player` records for the game (filtered by role if needed).
2. Get each player's `client_id`.
3. Look up the device token for each `client_id`.
4. Send the push.

### Stale Token Handling

- Tokens refresh naturally: every game join upserts the latest token, so stale tokens are replaced before they matter.
- APNs error responses (410 Gone, `InvalidDeviceToken`) cause the server to delete the stale token from the database.
- No retry logic for invalid tokens.

---

## Infrastructure Sketch

Architectural notes for the server-side build.

### APNS Integration

- **`aioapns`** library for async APNS communication (compatible with FastAPI).
- **Token-based auth** using a `.p8` key file from Apple Developer portal.
- Credentials via environment variables: `APNS_KEY_PATH`, `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_TOPIC`, `APNS_USE_SANDBOX`.
- The `.p8` key file is never committed to the repo.

### Data Model

New `DeviceToken` table:

| Field | Type | Notes |
|-------|------|-------|
| client_id | UUID | PK |
| token | str | Hex-encoded APNS device token |
| environment | str | `"production"` or `"sandbox"` |
| updated_at | datetime | Last registration time |

Separate from `Player` because a `client_id` can span multiple games and may register a token before joining any game.

### Push Service

A thin service layer encapsulating APNS interaction:

- **`notify_game(game_id, event_type, role_filter?, ...)`** — push to all players in a game, optionally filtered by role.
- **No-op when unconfigured** — logs the would-be notification and returns when APNS credentials are absent.
- **Fire-and-forget** — dispatched via FastAPI's `BackgroundTasks` so the HTTP response returns immediately.

### Router → Push Mapping

| Router Handler | Push Call |
|----------------|----------|
| `POST /games/{id}/start` | `notify_game(game_id, "game_started")` |
| Server timer (hiding → seeking) | `notify_game(game_id, "phase_changed")` |
| `POST /games/{id}/questions` (radar) | `notify_game(game_id, "question_asked", role_filter="hider", ...)` |
| `POST /games/{id}/questions` (thermometer) | `notify_game(game_id, "question_asked", role_filter="hider", ...)` |
| `POST /games/{id}/questions/{id}/lock-in` | `notify_game(game_id, "question_answerable", role_filter="hider", ...)` |
| `POST /games/{id}/questions/{id}/answer` | `notify_game(game_id, "question_answered", role_filter="seeker", ...)` |
| Seeking → endgame transition | Hider: `notify_game(game_id, "phase_changed", role_filter="hider")` / Seekers: silent push |

---

## iOS Requirements

- **Xcode capabilities**: Push Notifications + Background Modes (Remote notifications).
- **Token registration**: register for remote notifications on launch, pass token to server on game join/create.
- **Permission flow**: request on first launch or first game join. If denied, show a non-blocking in-app reminder.
- **Notification handling**: parse push payload → update UI from push data immediately → sync full state in background.

---

## Scope Boundaries

Explicitly **out of scope**:

- **Timer/scheduler for hiding → seeking** — separate design concern. This document assumes the transition happens and defines the push that follows.
- **Live Activities (ActivityKit)** — persistent lock screen widget showing phase, time remaining, question count. Worth designing separately once core push infrastructure works.
- **Silent push for location polling** — not needed. The client already reports location on a timer via `POST /games/{game_id}/location`.
- **Lobby push notifications** — polling is sufficient. Everyone has the app open.
- **Client-side polling strategy** — to be designed with the iOS client. This document ensures everything pushed is also fetchable via existing REST endpoints.
- **Android / FCM** — iOS only for now. The pattern ports cleanly to FCM when needed.
