"""API v1 package — router registration."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from app.api.v1.endpoints import audit, auth, cases, health, labels, resolve, telegram, webhooks, agent


def register_routers(app: FastAPI) -> None:
    api = APIRouter(prefix="/api/v1")
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(cases.router)
    api.include_router(resolve.router)
    api.include_router(telegram.router)
    api.include_router(webhooks.router)
    api.include_router(audit.router)
    api.include_router(labels.router)
    api.include_router(agent.router)
    app.include_router(api)
