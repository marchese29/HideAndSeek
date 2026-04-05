# HideAndSeek Monorepo

Geographic "Hide and Seek" game — hiders use public transit to hide in a game area while seekers narrow down their location through yes/no questions.

## Monorepo Layout

UV workspace with a root `pyproject.toml` and two Python packages (`models/`, `server/`). A single `uv.lock` at the root governs all dependencies.

- `models/` — SQLAlchemy models package (`hideandseek-models`). See `models/CLAUDE.md`.
- `mobile/` — Mobile app (React Native + Expo). See `mobile/CLAUDE.md`.
- `server/` — Python FastAPI backend (UV), depends on `hideandseek-models`. See `server/CLAUDE.md`.
- `openapi/` — Auto-generated OpenAPI spec from FastAPI. See `openapi/CLAUDE.md`.
- `design/` — AI-generated design artifacts. See `design/CLAUDE.md`.
- `hooks/` — Git hooks (symlinked into `.git/hooks/`; see Setup below).
- `docker-compose.yml` — Docker Compose (PostGIS + Redis + API server + Celery worker).
- `scripts/dev.sh` — Local dev launcher (uvicorn + Celery worker with Redis).
- `scripts/manual-test.sh` — End-to-end metric game flow against a running Docker server (seeds data, exercises all endpoints).
- `scripts/manual-test-imperial.sh` — End-to-end imperial convention game flow with assertions (run after `manual-test.sh`).
- `.beads/` — Beads issue tracker.

## CLAUDE.md Is the Source of Truth

**Every commit should update a CLAUDE.md file.** These files are how we communicate conventions, architecture decisions, and project knowledge across sessions. If a commit adds a feature, changes a convention, introduces a dependency, or alters how something works, the relevant CLAUDE.md file(s) MUST be updated in the same commit.

If you believe a commit genuinely does not require a CLAUDE.md update (e.g., a pure typo fix in a code comment), you MUST explain to the user why no update is needed before committing. The default assumption is that an update IS needed.

CLAUDE.md files exist at:
- `CLAUDE.md` (this file) — monorepo-wide conventions and workflow
- `models/CLAUDE.md` — models package conventions
- `mobile/CLAUDE.md` — mobile app build, architecture, conventions
- `server/CLAUDE.md` — server commands, style, conventions
- `openapi/CLAUDE.md` — how the spec is generated and used
- `design/CLAUDE.md` — design artifact conventions

## Conventions

- Issue tracking: use `bd` (beads) CLI. Run `bd onboard` to get started.
- Git hooks: `hooks/pre-commit` is the versioned pre-commit hook (server checks + OpenAPI regen + beads JSONL flush). It's symlinked into `.git/hooks/`. Beads installs its own shims for other hooks (`pre-push`, `post-merge`, `post-checkout`, `prepare-commit-msg`) directly in `.git/hooks/`. See Setup below.
- The pre-commit hook runs in dependency order: models checks → server checks → OpenAPI regen → API types regen → mobile checks. Models changes cascade to server checks and OpenAPI regen (server depends on models).
- The OpenAPI regen step auto-stages the updated spec (`git add openapi/openapi.yaml`), so it's included in the commit automatically — no manual step needed.
- Hook steps use `run_if_changed` with hash caching (`.git/hooks-cache/`) to skip work when staged content hasn't changed since the last successful run.
- To add a new cached hook step: write a script in `hooks/`, then add a `run_if_changed` call in `hooks/pre-commit`. Signature: `run_if_changed <cache_key> <skip_msg> <run_msg> <command> <path...>` — paths are listed after the command, supporting multiple trigger paths.
- OpenAPI spec is the contract between server and mobile app — never edit it directly.

## Beads (Issue Tracking)

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## Verification

When server code changes, verify with **both** automated and manual checks before committing:

1. **Automated**: `uv run pytest`, `uv run ruff check .`, `uv run pyright`
2. **Manual**: Prefer Docker (`docker compose up --build`) for manual testing — it runs PostgreSQL, Redis, and the Celery worker, matching production. Seed test data if needed, and exercise new/changed endpoints with `curl`. Verify request/response shapes, error cases, and side effects.

Manual testing catches issues that unit tests miss: serialization quirks, middleware interactions, dependency wiring, and real request flow.

## Landing the Plane (Session Completion)

When ending a work session, complete ALL steps below. Work is NOT complete until `git push` succeeds.

1. **File issues for remaining work** — create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) — automated tests + manual endpoint verification (see Verification above)
3. **Update issue status** — close finished work, update in-progress items
4. **Push to remote**:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # Must show "up to date with origin"
   ```
5. **Hand off** — provide context for next session

## Setup (after fresh clone)

```bash
# Hooks: install beads shims, then symlink our pre-commit over theirs
bd hooks install
ln -sf ../../hooks/pre-commit .git/hooks/pre-commit  # target is relative to symlink location
```

## Quick Start

```bash
# Models package (standalone lint + typecheck)
cd models && uv run ruff check .     # Lint
cd models && uv run pyright           # Type check

# Server (Docker — preferred, runs PostGIS + Redis + Celery worker)
docker compose up --build          # Start all 4 services (localhost:8000)
docker compose down                # Stop (data preserved in pgdata volume)
docker compose down -v             # Stop and wipe database

# Server (local + Celery worker — requires: docker compose up -d postgres redis)
scripts/dev.sh                     # Launches uvicorn + Celery worker together

# Run server tests (requires Docker — testcontainers spins up PostGIS automatically)
cd server && uv run pytest

# Regenerate OpenAPI spec
cd server && uv run python scripts/generate_openapi.py

# Import Seattle transit data (downloads GTFS feed, filters, deduplicates, writes to DB)
cd server && uv run python scripts/import_seattle_gtfs.py

# Seed Seattle GameMap (boundary + 5 KCC districts; requires transit data above)
cd server && uv run python scripts/seed_seattle_map.py

# Mobile app (development build — not Expo Go, native modules require it)
cd mobile && npm install              # Install dependencies
cd mobile && npx expo run:ios         # Build and run on iOS simulator
cd mobile && npx expo run:android     # Build and run on Android emulator
cd mobile && npx tsc --noEmit         # Type check
cd mobile && npx expo lint            # Lint

# Regenerate API types from OpenAPI spec
cd mobile && scripts/generate-api.sh
```
