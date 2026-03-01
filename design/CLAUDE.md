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

## Conventions

- Store design docs, wireframes, and specifications here.
- Use markdown for text-based design docs.
- Name files descriptively (e.g., `game-mechanics.md`, `map-ui-flow.md`).
- Mark documents with a status (Draft / Implementation / Done) and last-updated date.
