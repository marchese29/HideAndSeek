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

- Issue tracking: use `bd` (beads) CLI. Run `bd onboard` to get started.
- Git hooks are in `hooks/` and configured via `git config core.hooksPath hooks`.
- The pre-commit hook auto-regenerates `openapi/openapi.yaml` when `server/` files change.
- OpenAPI spec is the contract between server and iOS app — never edit it directly.

## Beads (Issue Tracking)

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## Landing the Plane (Session Completion)

When ending a work session, complete ALL steps below. Work is NOT complete until `git push` succeeds.

1. **File issues for remaining work** — create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) — tests, linters, builds
3. **Update issue status** — close finished work, update in-progress items
4. **Push to remote**:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # Must show "up to date with origin"
   ```
5. **Hand off** — provide context for next session

## Quick Start

```bash
# Server
cd server && uv sync && uv run uvicorn hideandseek.main:app --reload

# Run server tests
cd server && uv run pytest

# Regenerate OpenAPI spec
cd server && uv run python scripts/generate_openapi.py
```
