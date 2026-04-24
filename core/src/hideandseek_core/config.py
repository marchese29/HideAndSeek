"""Push notification + photo-storage configuration loaded from environment variables."""

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


@dataclass(frozen=True)
class S3Config:
    """AWS S3 configuration for the photo bucket.

    `endpoint_url` is set in local dev (pointing at LocalStack) and left
    None in prod so boto3 resolves the regional endpoint. Unlike SnsConfig
    there is no useful no-op mode: photo endpoints surface a 500 when the
    bucket is missing rather than silently dropping writes.
    """

    bucket_name: str
    endpoint_url: str | None


def load_s3_config() -> S3Config | None:
    """Load S3 config from env vars. Returns None when S3_BUCKET_NAME is missing."""
    bucket_name = os.environ.get('S3_BUCKET_NAME')
    if not bucket_name:
        return None

    return S3Config(
        bucket_name=bucket_name,
        endpoint_url=os.environ.get('AWS_ENDPOINT_URL') or None,
    )
