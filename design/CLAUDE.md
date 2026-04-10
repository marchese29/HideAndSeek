# Design Artifacts

AI-generated design documents and artifacts for the HideAndSeek game.

## Documents

- `data-model.md` — Server-side data model: transit data, game maps, games, players, location tracking, questions, and exclusion zones.
- `api-surface.md` — REST API surface organized by player use cases: game lifecycle, location reporting, question asking/answering, and map rendering.
- `push-notifications.md` — Push notification design: game events → APNS pushes, payload specs, device token lifecycle, and infrastructure sketch.
- `background-jobs.md` — Background jobs and timers: Celery + Redis for durable game-state timers (hiding→seeking, answer deadlines), resilient push delivery, and task revocation. Includes Docker Compose setup with PostgreSQL.
- `matching-measuring-questions.md` — Matching ("is your nearest X the same as mine?") and measuring ("are you closer to or further from X?") question types. Covers feature categories (map data vs Google Maps Places API), PostGIS spatial queries, bona fide filtering with hierarchical config, server-side Places proxy, and inventory changes.
- `distance-conventions.md` — Metric and imperial distance support: convention enum on GameMap, default inventory sets per convention and game size, map-level overrides, data model renames (`distance_m` → `distance`, etc.), conversion boundary for geo math, and API surface changes.
- `endgame.md` — Endgame design (Implementation): hiding zones, station auto-selection at hiding timer expiry, no server-side endgame state (client-side lens over seeking phase), server-assisted endgame exclusion view, candidate stations query via PostGIS geography buffering, seeker proximity notifications, and hiding zone radius override for mid-game card effects. Implemented in 3 cycles: (1) endgame re-drawing endpoints, (2) hiding station codification, (3) seeker proximity notifications.
- `game-state-split.md` — Game state endpoint redesign: split monolithic `GET /games/{id}` by role (hider/seeker access control) and introduce default-deny question summary. Principles: role = access control only (no response shaping), fixed response shapes, whitelist shared fields.
- `hider-station-election.md` — Hider station election: voluntary lock-in during hiding, ambiguity handling at hiding→seeking transition, fallback resolution cascade (all-in-radius → any-in-radius → closest pair), nearby-stations and hiding-zone query endpoints. Supersedes Station Selection in `endgame.md`.
- `lobby-server.md` — Server-side lobby changes: host-as-player on game creation, auth guards (self-only player updates, host-only start), PlayerColor enum (12 server-assigned colors), 12-player cap, player removal (voluntary leave + host kick + host transfer), real-time lobby updates via SSE over Redis pub/sub, broadcast module design.
- `lobby-mobile.md` — Mobile lobby experience: screen flow (Home → Create/Join → Lobby), map picker, join code input, lobby UI (player list, self-edit sheet, host controls), SSE via react-native-sse, state management (Zustand for client state + TanStack Query for server state), color mapping, navigation patterns.
- `gameplay-state.md` — Gameplay state & SSE: role-specific SSE state endpoints (hider-state/seeker-state), dual-channel Redis broadcasting with publish-side visibility, location broadcasting, simplified ACK REST responses, player representations (GamePlayer with location vs RosterPlayer without), question history with exclusion zones, inventory in state.
- `gameplay-mobile.md` — Mobile gameplay experience: single route with role/phase-dependent rendering, map view (boundary, stops, player pins, total exclusion), SSE-driven Zustand state, question drawer (hider) + question banner (seeker), utility belt, location reporting, stale location indicator, permissions at create/join time.
- `utility-belt.md` — Utility belt HUD redesign: zone-based layout (state action + timer, toolbelt, info + leave), context strip (hider station name, seeker question timeline with exclusion scrubbing), connection status via timer color, phase/role-specific state action button.
- `question-flow-mobile.md` — Mobile question flow: seeker question selection via belt takeover (type → parameter → preview → ask), unified Question Banner for both roles (replaces drawer + old banner), boundary-line exclusion previews, thermometer two-phase UX, hider answer/veto/randomize actions, server preview endpoint. Supersedes question UI in `gameplay-mobile.md` sections 6–7.
- `tentacles-question.md` — Tentacles question type: seeker picks a POI category, server finds all POIs within a configured distance, hider's answer is the nearest POI (or miss if out of range). Non-binary answer, Voronoi-based exclusion. Point geometry only (for now — HideAndSeek-9ci for complex geometries). Server changes (model, ask/answer, exclusion, events, preview) and mobile seeker experience.

## Conventions

- Store design docs, wireframes, and specifications here.
- Use markdown for text-based design docs.
- Name files descriptively (e.g., `game-mechanics.md`, `map-ui-flow.md`).
- Mark documents with a status (Draft / Implementation / Done) and last-updated date.
