#!/usr/bin/env bash
# Launch API server + Celery worker together for local development.
# Requires: docker compose up -d postgres redis
set -euo pipefail

cd "$(dirname "$0")/../server"

# One Docker stack, owned by the main checkout (fixed compose project name,
# shared pgdata volume, fixed ports) — running it from a worktree would
# silently hijack the main checkout's containers. Refuse unless overridden.
if [ "${HIDEANDSEEK_ALLOW_WORKTREE_STACK:-}" != "1" ] \
   && _gd=$(git rev-parse --path-format=absolute --git-dir 2>/dev/null) \
   && _gc=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) \
   && [ "$(cd "$_gd" && pwd -P)" != "$(cd "$_gc" && pwd -P)" ]; then
  echo "error: scripts/dev.sh refuses to run from a git worktree." >&2
  echo "There is one Docker stack, owned by the main checkout — running it" >&2
  echo "here would hijack the main checkout's containers (shared pgdata" >&2
  echo "volume, fixed ports). Run scripts/dev.sh from the main checkout." >&2
  echo "Deliberate override: HIDEANDSEEK_ALLOW_WORKTREE_STACK=1 scripts/dev.sh" >&2
  exit 1
fi

# Default to the docker-compose PostgreSQL if DATABASE_URL is not set.
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://hideandseek:hideandseek@localhost:5432/hideandseek}"

# macOS reports SC_OPEN_MAX as 2^63-1, which makes billiard's close_open_fds()
# overflow a C int. Cap the fd limit so Celery Beat can start.
# See: https://github.com/celery/billiard/issues/399
ulimit -n 10240 2>/dev/null || true

trap 'kill 0' EXIT

uv run uvicorn hideandseek.main:app --reload &
uv run celery -A hideandseek_worker.celery_app worker --loglevel=info --beat &

wait
