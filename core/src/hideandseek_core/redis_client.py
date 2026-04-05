"""Redis client factory for pub/sub and general use.

Resolution order:
1. REDIS_URL env var (explicit — Docker, CI, production)
2. Auto-detect Redis on localhost:6379 (local dev)
3. None — callers handle the missing-Redis case (no-op publish, etc.)
"""

from __future__ import annotations

import os
from functools import cache
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import redis
    import redis.asyncio

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_LOCAL_REDIS_URL = 'redis://localhost:6379/0'


@cache
def get_redis_url() -> str | None:
    """Return the Redis URL, probing localhost if no env var is set.

    Returns None when Redis is unreachable (callers degrade gracefully).
    Cached so the probe only happens once per process.
    """
    explicit = os.environ.get('REDIS_URL')
    if explicit is not None:
        return explicit or None  # empty string → None

    # Fall back to CELERY_BROKER_URL for backwards compat
    celery_url = os.environ.get('CELERY_BROKER_URL')
    if celery_url is not None:
        return celery_url or None

    try:
        import redis as _redis  # noqa: PLC0415

        conn = _redis.Redis.from_url(_LOCAL_REDIS_URL, socket_connect_timeout=0.5)
        conn.ping()
        conn.close()
        logger.info('redis_auto_detected', url=_LOCAL_REDIS_URL)
        return _LOCAL_REDIS_URL
    except Exception:
        logger.info('redis_unavailable', reason='no Redis configured or reachable')
        return None


def get_sync_redis() -> redis.Redis | None:
    """Sync Redis client for publishing. Returns None when Redis is unavailable."""
    import redis as _redis  # noqa: PLC0415

    url = get_redis_url()
    if url is None:
        return None
    return _redis.Redis.from_url(url)


def get_async_redis() -> redis.asyncio.Redis | None:
    """Async Redis client for subscribing (SSE streams). Returns None when unavailable."""
    import redis.asyncio as _aioredis  # noqa: PLC0415

    url = get_redis_url()
    if url is None:
        return None
    return _aioredis.Redis.from_url(url)
