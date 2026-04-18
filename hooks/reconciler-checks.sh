#!/usr/bin/env bash
set -e
cd reconciler
uv run ruff check .
uv run ruff format --check .
uv run pyright
