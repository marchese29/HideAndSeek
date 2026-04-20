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

# CdnStack reads DOMAIN_NAME + HOSTED_ZONE_NAME via lib/env.ts::requireEnv.
# Source the operator's gitignored .env so `cdk synth` can resolve them.
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

npx tsc --noEmit
npx cdk synth --quiet

echo "CDK checks passed!"
