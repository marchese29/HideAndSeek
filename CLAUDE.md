# HideAndSeek Monorepo

Geographic "Hide and Seek" game — hiders use public transit to hide in a game area while seekers narrow down their location through yes/no questions.

## Monorepo Layout

- `ios/` — iOS app (SwiftUI + Google Maps). See `ios/CLAUDE.md`.
- `server/` — Python FastAPI backend (UV). See `server/CLAUDE.md`.
- `openapi/` — Auto-generated OpenAPI spec from FastAPI. See `openapi/CLAUDE.md`.
- `design/` — AI-generated design artifacts. See `design/CLAUDE.md`.
- `hooks/` — Git hooks (auto-configured via `core.hooksPath`).
- `.beads/` — Beads issue tracker.

## Conventions

- Issue tracking: use `bd` (beads) CLI. Run `bd ready` to check status.
- Git hooks are in `hooks/` and configured via `git config core.hooksPath hooks`.
- The pre-commit hook auto-regenerates `openapi/openapi.yaml` when `server/` files change.
- OpenAPI spec is the contract between server and iOS app — never edit it directly.

## Quick Start

```bash
# Server
cd server && uv sync && uv run uvicorn hideandseek.main:app --reload

# Run server tests
cd server && uv run pytest

# Regenerate OpenAPI spec
cd server && uv run python scripts/generate_openapi.py
```
