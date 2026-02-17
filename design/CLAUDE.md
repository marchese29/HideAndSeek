# Design Artifacts

AI-generated design documents and artifacts for the HideAndSeek game.

## Documents

- `data-model.md` — Server-side data model: transit data, game maps, games, players, location tracking, questions, and exclusion zones.
- `api-surface.md` — REST API surface organized by player use cases: game lifecycle, location reporting, question asking/answering, and map rendering.
- `push-notifications.md` — Push notification design: game events → APNS pushes, payload specs, device token lifecycle, and infrastructure sketch.
- `background-jobs.md` — Background jobs and timers: Celery + Redis for durable game-state timers (hiding→seeking, answer deadlines), resilient push delivery, and task revocation. Includes Docker Compose setup with PostgreSQL.
- `matching-measuring-questions.md` — Matching ("is your nearest X the same as mine?") and measuring ("are you closer to or further from X?") question types. Covers feature categories (map data vs Google Maps Places API), PostGIS spatial queries, bona fide filtering with hierarchical config, server-side Places proxy, and inventory changes.

## Conventions

- Store design docs, wireframes, and specifications here.
- Use markdown for text-based design docs.
- Name files descriptively (e.g., `game-mechanics.md`, `map-ui-flow.md`).
- Mark documents with a status (Draft / Implementation / Done) and last-updated date.
