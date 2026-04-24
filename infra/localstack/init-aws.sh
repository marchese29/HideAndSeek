#!/usr/bin/env bash
# Bootstraps LocalStack with the SNS platform applications and the S3 photo
# bucket the app expects. Runs once when LocalStack reports "ready" via the
# ready.d hook.
set -euo pipefail

awslocal sns create-platform-application \
    --name hideandseek-ios-dev \
    --platform APNS_SANDBOX \
    --attributes PlatformCredential=dummy

awslocal sns create-platform-application \
    --name hideandseek-android-dev \
    --platform GCM \
    --attributes PlatformCredential=dummy

awslocal s3 mb s3://hideandseek-photos-local
