#!/usr/bin/env bash
set -e
cd mobile
scripts/generate-api.sh
cd ..
git add mobile/src/api/schema.d.ts
