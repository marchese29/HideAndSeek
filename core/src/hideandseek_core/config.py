"""Push notification configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SnsConfig:
    """AWS SNS Mobile Push configuration.

    `endpoint_url` is set in local dev (pointing at LocalStack) and left
    None in prod so boto3 resolves the regional endpoint.
    """

    region: str
    apns_app_arn: str
    fcm_app_arn: str
    endpoint_url: str | None


def load_sns_config() -> SnsConfig | None:
    """Load SNS config from env vars. Returns None when a required var is missing."""
    region = os.environ.get('AWS_REGION')
    apns_app_arn = os.environ.get('SNS_APNS_APP_ARN')
    fcm_app_arn = os.environ.get('SNS_FCM_APP_ARN')

    if not region or not apns_app_arn or not fcm_app_arn:
        return None

    return SnsConfig(
        region=region,
        apns_app_arn=apns_app_arn,
        fcm_app_arn=fcm_app_arn,
        endpoint_url=os.environ.get('AWS_ENDPOINT_URL') or None,
    )
