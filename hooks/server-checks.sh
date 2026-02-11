#!/usr/bin/env bash
# Run server lint, format, typecheck, and tests.

set -e

cd server

uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest

echo "All checks passed!"
