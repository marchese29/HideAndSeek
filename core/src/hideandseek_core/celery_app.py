"""Celery application instance."""

from __future__ import annotations

from celery import Celery

app = Celery(
    'hideandseek',
    include=['hideandseek.tasks.game_timers', 'hideandseek.tasks.push'],
)
app.config_from_object('hideandseek_core.celery_config')
