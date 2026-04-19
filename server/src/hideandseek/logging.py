"""Server logging: delegates to core, adds the request/response access logger."""

from __future__ import annotations

import logging
import os
import sys

from hideandseek.utils import find_server_root
from hideandseek_core.logging import setup_logging as _setup_base


def setup_logging() -> None:
    """Configure logging for the API process.

    Runs the shared core setup, then builds the ``hideandseek.access`` logger
    used by ``AccessLogMiddleware``. In ``local`` mode access logs also go to
    ``server/logs/access.log`` alongside stderr; in other modes, stderr only.
    """
    _setup_base()
    _configure_access_logger()


def _configure_access_logger() -> None:
    # Reuse the formatter core installed on the root handler so the access
    # logger renders identically to everything else.
    formatter = logging.getLogger().handlers[0].formatter
    is_local = os.environ.get('ENV', 'local') == 'local'

    access_logger = logging.getLogger('hideandseek.access')
    access_logger.setLevel(logging.DEBUG)
    access_logger.propagate = False
    access_logger.handlers.clear()

    if is_local:
        log_dir = find_server_root() / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / 'access.log')
        file_handler.setFormatter(formatter)
        access_logger.addHandler(file_handler)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    access_logger.addHandler(stderr_handler)
