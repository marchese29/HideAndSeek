"""Shared structlog-based logging configuration for all HideAndSeek services.

Called at startup by the server (lifespan), the Celery worker (via the
``setup_logging`` signal), and the reconciler (at the top of ``main()``).

Environment variables:
- ``ENV``: ``local`` (default), ``development``, or ``production``.
  - ``local`` / ``development``: DEBUG root, console renderer.
  - ``production``: INFO root, JSON renderer.
- ``LOG_FORMAT``: ``json`` forces JSON rendering regardless of ``ENV``.
- ``SQL_ECHO``: ``1`` / ``true`` / ``yes`` forces ``sqlalchemy.engine`` to INFO
  so SQL statements appear in logs (on by default in ``local``).
"""

from __future__ import annotations

import logging
import os
import sys

import structlog

_TRUTHY = {'1', 'true', 'yes'}

_THIRD_PARTY_NOISE = (
    'uvicorn',
    'uvicorn.access',
    'aioapns',
    'firebase_admin',
    'httpx',
    'asyncio',
)


def setup_logging() -> None:
    """Configure structlog + stdlib root logger for this process."""
    env = os.environ.get('ENV', 'local')
    is_prod = env == 'production'
    is_local = env == 'local'
    force_json = os.environ.get('LOG_FORMAT', '').lower() == 'json'
    sql_echo = os.environ.get('SQL_ECHO', '').lower() in _TRUTHY

    use_json = force_json or is_prod
    root_level = logging.INFO if is_prod else logging.DEBUG
    sql_level = logging.INFO if (is_local or sql_echo) else logging.WARNING

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt='iso'),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if use_json:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(root_level)
    root_logger.handlers.clear()

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root_logger.addHandler(stderr_handler)

    logging.getLogger('sqlalchemy.engine').setLevel(sql_level)

    for name in _THIRD_PARTY_NOISE:
        logging.getLogger(name).setLevel(logging.WARNING)
