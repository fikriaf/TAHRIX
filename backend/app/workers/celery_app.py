"""Celery application — async task runner for heavy work (investigations, ingestion)."""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "tahrix",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,           # 10 min hard limit per task
    task_soft_time_limit=540,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)
