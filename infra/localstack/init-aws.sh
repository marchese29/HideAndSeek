#!/usr/bin/env bash
# Bootstraps LocalStack with the two SNS platform applications the app expects.
# Runs once when LocalStack reports "ready" via the ready.d hook.
set -euo pipefail

awslocal sns create-platform-application \
    --name hideandseek-ios-dev \
    --platform APNS_SANDBOX \
    --attributes PlatformCredential=dummy

awslocal sns create-platform-application \
    --name hideandseek-android-dev \
    --platform GCM \
    --attributes PlatformCredential=dummy
