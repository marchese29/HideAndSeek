#!/usr/bin/env bash
set -e
cd mobile
npx tsc --noEmit
npx expo lint
npx prettier --check .
