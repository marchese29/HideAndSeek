"""Celery configuration.

Broker resolution order:
1. CELERY_BROKER_URL env var (explicit — Docker, CI, production)
2. Auto-detect Redis on localhost:6379 (local dev with Redis running)
3. Eager mode — tasks run synchronously in-process (no broker needed)

To force eager mode when Redis is running: CELERY_BROKER_URL='' uv run uvicorn ...
"""

from __future__ import annotations

import os

import structlog

from hideandseek.redis_client import get_redis_url

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _resolve_broker() -> str:
    """Determine the broker URL, probing local Redis if no env var is set."""
    explicit = os.environ.get('CELERY_BROKER_URL')
    if explicit is not None:
        return explicit
    return get_redis_url() or ''


_broker = _resolve_broker()

broker_url = _broker or 'memory://'
result_backend = os.environ.get('CELERY_RESULT_BACKEND', _broker or 'cache+memory://')

task_always_eager = not _broker

task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'UTC'
enable_utc = True
