#!/usr/bin/env bash
# Run models lint, format, and typecheck.

set -e

cd models

uv run ruff check .
uv run ruff format --check .
uv run pyright

echo "Models checks passed!"
