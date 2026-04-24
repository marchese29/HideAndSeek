"""S3 photo-storage client — typed thin wrapper over boto3 S3."""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING, BinaryIO

import boto3
import structlog

from hideandseek_core.config import S3Config

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import GetObjectOutputTypeDef

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@cache
def get_s3_client(config: S3Config) -> S3Client:
    """Return a cached boto3 S3 client for the given config.

    S3Config is frozen/hashable — `functools.cache` returns the same client
    across calls with equal configs, matching boto3's guidance to reuse
    clients rather than recreate per operation.
    """
    return boto3.client('s3', endpoint_url=config.endpoint_url)


def upload_bytes(
    config: S3Config,
    key: str,
    body: bytes | BinaryIO,
    content_type: str,
) -> None:
    """Upload an object to the bucket under `key`."""
    get_s3_client(config).put_object(
        Bucket=config.bucket_name,
        Key=key,
        Body=body,
        ContentType=content_type,
    )


def get_object_stream(config: S3Config, key: str) -> GetObjectOutputTypeDef:
    """Return the full GetObject response (caller reads Body / ContentType / ContentLength)."""
    return get_s3_client(config).get_object(Bucket=config.bucket_name, Key=key)


def delete_object(config: S3Config, key: str) -> None:
    """Delete an object. Idempotent — S3 returns 204 even if the key is absent."""
    get_s3_client(config).delete_object(Bucket=config.bucket_name, Key=key)
