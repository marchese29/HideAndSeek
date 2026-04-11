#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

if [ ! -d node_modules ]; then
    echo "mobile/node_modules missing — running npm install..."
    npm install --silent
fi

npx openapi-typescript ../openapi/openapi.yaml -o src/api/schema.d.ts
echo "API types generated at src/api/schema.d.ts"
