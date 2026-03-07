#!/usr/bin/env bash
# Launch API server + Celery worker together for local development.
# Requires: docker compose up -d postgres redis
set -euo pipefail

cd "$(dirname "$0")/../server"

# Default to the docker-compose PostgreSQL if DATABASE_URL is not set.
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://hideandseek:hideandseek@localhost:5432/hideandseek}"

# macOS reports SC_OPEN_MAX as 2^63-1, which makes billiard's close_open_fds()
# overflow a C int. Cap the fd limit so Celery Beat can start.
# See: https://github.com/celery/billiard/issues/399
ulimit -n 10240 2>/dev/null || true

trap 'kill 0' EXIT

uv run uvicorn hideandseek.main:app --reload &
uv run celery -A hideandseek.celery_app worker --loglevel=info --beat &

wait
