#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
npx openapi-typescript ../openapi/openapi.yaml -o src/api/schema.d.ts
echo "API types generated at src/api/schema.d.ts"
