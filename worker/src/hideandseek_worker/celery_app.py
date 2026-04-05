"""Celery application instance."""

from __future__ import annotations

from celery import Celery

app = Celery(
    'hideandseek',
    include=['hideandseek_worker.tasks.game_timers', 'hideandseek_worker.tasks.push'],
)
app.config_from_object('hideandseek_worker.celery_config')
