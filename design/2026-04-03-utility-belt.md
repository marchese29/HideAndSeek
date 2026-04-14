# Utility Belt

> Status: **Draft**
> Last updated: 2026-04-03

The gameplay HUD at the bottom of the screen. Provides timers, phase-specific actions, map tools, game info, and meta actions (leave). Replaces the flat "row of slots" concept from `2026-03-29-gameplay-mobile.md` section 6 with a structured, zone-based layout.

Depends on: `2026-03-29-gameplay-mobile.md` (screen layout, SSE state, component hierarchy).

---

## 1. Layout

The belt sits at the bottom of the gameplay screen, above safe area insets. It has two layers:

```
┌─────────────────────────────────────────────────────────────┐
│              CONTEXT STRIP (conditional, see §2)            │
├────────────┬─────────────────────────────┬──────────────────┤
│   STATE    │                             │                  │
│   ACTION   │        TOOLBELT             │  INFO   LEAVE    │
│            │      (placeholder)          │                  │
│   TIMER    │                             │                  │
├────────────┴─────────────────────────────┴──────────────────┤
```

The bottom row has three sections:

| Section | Width | Contents |
|---------|-------|----------|
| **Left: State Action + Timer** | Fixed (~100px) | State/action button on top, timer display below |
| **Center: Toolbelt** | Flex (fills remaining) | Common map tools — placeholder for now |
| **Right: Info + Leave** | Fixed (~90px) | Info button + destructive action button |

The context strip spans the full width above the three sections. It is **hidden** when there's nothing to show (see §2).

---

## 2. Context Strip

A thin horizontal strip across the top of the belt. Its content depends on role, phase, and game state. Hidden when there's nothing meaningful to display.

### Hider — Any Phase

Shows the elected hiding station name once the hider has elected a station. Hidden while `station_election_status === 'pending'`.

- Appears during hiding if the hider elects early.
- Remains visible through seeking. During seeking, station election is more urgent — if `station_election_status === 'ambiguous'`, the strip could show a warning (auto-resolution fires when the first question's timeout expires).
- Static display — station name, not interactive.

### Seeker — Hiding Phase

Not shown. Nothing meaningful to display yet.

### Seeker — Seeking Phase

A scrollable question history timeline. Each answered question is a segment in the strip. Scrubbing through the timeline updates the map's exclusion overlay to show the `total_exclusion` at that point in history (the data is already in `question_history[n].total_exclusion`).

- Appears once the first question is answered.
- Rightmost position = current state. An **endgame button** sits at the far right, past the "now" position — tapping it triggers the seeker's endgame flow (future design).
- Scrolls horizontally. Each segment shows a compact question indicator (type icon + sequence number).

---

## 3. State Action + Timer (Left Section)

A vertically stacked tile: state/action button on top, timer below.

### State / Action Button

The top element of the left tile. Appearance and behavior depend on role, phase, and station election state:

| Role | Phase | Condition | Icon | Label | Behavior |
|------|-------|-----------|------|-------|----------|
| Seeker | Hiding | — | Mask (`mask`) | "Hiding" | Informational only (not pressable) |
| Hider | Hiding | Station not elected | Signpost (`signpost`) | "Set Stop" | Opens station search/election flow |
| Hider | Hiding | Station elected | Mask (`mask`) | "Hidden" | Informational only (not pressable) |
| Seeker | Seeking | — | Question (`chat-question-outline`) | "Ask" | Opens question flow |
| Hider | Seeking | — | Toolbox (`toolbox-outline`) | "Toolbox" | Opens hider action menu (future — placeholder) |

Icons are from `MaterialCommunityIcons` (bundled with `@expo/vector-icons`).

### Timer

Displays the relevant countdown or elapsed time for the current phase.

| Phase | Display | Computation |
|-------|---------|-------------|
| Hiding | Countdown MM:SS | `hiding_started_at + hiding_time_min` minus now |
| Seeking | Elapsed MM:SS (or H:MM:SS) | Now minus `seeking_started_at` |

### Connection Status via Timer Color

The timer tile background indicates SSE connection health. No separate connection dot.

| State | Timer Background |
|-------|-----------------|
| Connected, hiding phase | Orange (`#F39C12`) |
| Connected, seeking phase | Green (`#2ECC71`) |
| Disconnected (any phase) | Gray (`#7F8C8D`) |

When disconnected, all belt actions are disabled.

---

## 4. Toolbelt (Center Section)

A horizontal strip of icon+label tool buttons for map interactions. **Placeholder for now** — renders as an empty zone or a subtle visual indicator.

Future tools (both roles, further design needed):
- Draw/measure distances on map
- Draw shapes/circles for estimation
- Toggle map layers (routes, stops, exclusion zones)
- Map annotation tools

These are map-adjacent actions that don't belong as floating map buttons — the map stays clean for gameplay visuals (pins, exclusions, routes).

---

## 5. Info + Leave (Right Section)

Two buttons on the right edge.

### Info Button

Shows contextual game stats. Could display a single headline number directly on the button face (a "callout number") instead of a generic icon — making a key stat visible at a glance without tapping. Tapping opens a stats sheet.

Possible callout stats:
- **Seeker:** Number of remaining candidate stations
- **Hider:** Distance to elected station, or number of questions answered

The stats sheet (bottom sheet or modal) shows more detail — exact contents are future design.

### Leave Button

A destructive action: leave the game mid-session. Visually distinct (red-tinted or warning-styled) to prevent accidental taps. Requires confirmation dialog.

This enables the "players leaving mid-game" feature (see `HideAndSeek-51l`).

---

## 6. Disabled / Disconnected State

When the SSE connection is lost:
- Timer tile background turns gray.
- All pressable buttons (state action, toolbelt items, info, leave) are disabled at reduced opacity.
- Map remains interactive (panning/zooming is local).

On reconnect, full state rehydrates from `game_state` SSE event and belt returns to normal.

---

## 7. Implementation Cycles

### Cycle A: Belt Shell + Timer + State Action

Build the belt structure and the left tile (the only fully functional section in this cycle).

- Belt container with three-section layout (no context strip yet).
- State/action button rendering per role+phase+election state (placeholder `Alert` for actionable states).
- Timer display with countdown (hiding) / elapsed (seeking).
- Timer background color for connection status (orange/green/gray).
- Remove `ConnectionDot` from gameplay screen (replaced by timer color).
- Leave button (placeholder — confirmation dialog, no server call yet).
- Info button (placeholder — icon only, no stats sheet).
- Center toolbelt zone as empty placeholder.
- Replaces existing utility belt placeholder in gameplay screen.

### Cycle B: Context Strip

Depends on Cycle A (belt shell) and question asking/answering (Cycle 5 bead).

- Context strip component.
- Hider: static station name display (any phase, once elected).
- Seeker seeking: scrollable question history timeline with exclusion scrubbing.
- Endgame button at end of seeker timeline (placeholder action).
