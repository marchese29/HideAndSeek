"""Celery application instance."""

from __future__ import annotations

from typing import Any

from celery import Celery
from celery.signals import setup_logging as setup_logging_signal

from hideandseek_core.logging import setup_logging

app = Celery(
    'hideandseek',
    include=['hideandseek_worker.tasks.game_timers', 'hideandseek_worker.tasks.push'],
)
app.config_from_object('hideandseek_worker.celery_config')


@setup_logging_signal.connect
def _configure_logging(**_kwargs: Any) -> None:
    setup_logging()
