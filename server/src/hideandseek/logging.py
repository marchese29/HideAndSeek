"""Centralized structured logging configuration using structlog."""

from __future__ import annotations

import logging
import os
import sys

import structlog

from hideandseek.utils import find_server_root


def setup_logging() -> None:
    """Configure structlog and stdlib logging for the application.

    Two logger namespaces:
    - ``hideandseek.access`` — request/response access logs (middleware).
      In ``local`` mode, writes to ``server/logs/access.log`` **and** stderr.
      In ``development`` and ``production``, writes to stderr only.
    - ``hideandseek.*`` — general application logs.
      Writes to stderr.

    Environment variables:
    - ``ENV``: ``local`` (default), ``development``, or ``production``.
      - ``local``: DEBUG, console renderer, access log file + stderr.
      - ``development``: DEBUG, console renderer, access log stderr only.
      - ``production``: INFO, JSON renderer, access log stderr only.
    - ``LOG_FORMAT``: Override renderer — ``json`` forces JSON regardless of ENV.
    """
    env = os.environ.get('ENV', 'local')
    is_prod = env == 'production'
    is_local = env == 'local'
    force_json = os.environ.get('LOG_FORMAT', '').lower() == 'json'
    use_json = force_json or is_prod
    root_level = logging.INFO if is_prod else logging.DEBUG

    # Shared structlog processors
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

    # Configure structlog
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Formatter that structlog-enabled handlers share
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # --- Root logger (general app logs → stderr) ---
    root_logger = logging.getLogger()
    root_logger.setLevel(root_level)
    # Remove any pre-existing handlers (e.g. basicConfig defaults)
    root_logger.handlers.clear()

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root_logger.addHandler(stderr_handler)

    # --- Access logger (request/response → file + stderr in local, stderr only otherwise) ---
    access_logger = logging.getLogger('hideandseek.access')
    access_logger.setLevel(logging.DEBUG)
    access_logger.propagate = False  # Don't duplicate into the root stream

    if is_local:
        log_dir = find_server_root() / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        access_file_handler = logging.FileHandler(log_dir / 'access.log')
        access_file_handler.setFormatter(formatter)
        access_logger.addHandler(access_file_handler)

    access_console_handler = logging.StreamHandler(sys.stderr)
    access_console_handler.setFormatter(formatter)
    access_logger.addHandler(access_console_handler)

    # Quiet noisy third-party loggers
    logging.getLogger('uvicorn').setLevel(logging.WARNING)
    logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
