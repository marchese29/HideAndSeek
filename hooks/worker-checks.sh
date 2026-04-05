#!/usr/bin/env bash
set -e
cd worker
uv run ruff check .
uv run ruff format --check .
uv run pyright
