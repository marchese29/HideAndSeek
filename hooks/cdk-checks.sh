#!/usr/bin/env bash
# Run CDK typecheck + synth.

set -e

cd infra/cdk

# Ensure deps are present; npm ci is deterministic when package-lock.json exists.
if [ ! -d node_modules ]; then
    if [ -f package-lock.json ]; then
        npm ci --silent
    else
        npm install --silent
    fi
fi

npx tsc --noEmit
npx cdk synth --quiet

echo "CDK checks passed!"
