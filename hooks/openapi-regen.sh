#!/usr/bin/env bash
# Regenerate the OpenAPI spec and stage it.

set -e

cd server
uv run python scripts/generate_openapi.py

git add openapi/openapi.yaml
