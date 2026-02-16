#!/usr/bin/env bash
# Launch API server + Celery worker together for local development.
# Redis auto-detected on localhost:6379 (install: brew install redis && brew services start redis).
# Uses SQLite by default (no DATABASE_URL needed).
set -euo pipefail

cd "$(dirname "$0")/../server"

# macOS reports SC_OPEN_MAX as 2^63-1, which makes billiard's close_open_fds()
# overflow a C int. Cap the fd limit so Celery Beat can start.
# See: https://github.com/celery/billiard/issues/399
ulimit -n 10240 2>/dev/null || true

trap 'kill 0' EXIT

uv run uvicorn hideandseek.main:app --reload &
uv run celery -A hideandseek.celery_app worker --loglevel=info --beat &

wait
