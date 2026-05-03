"""FastAPI application entrypoint.

Wires up middleware, routers, lifespan (startup/shutdown), and error handlers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import make_asgi_app

from app import __version__
from app.api import register_routers
from app.api.v1.error_handlers import register_error_handlers
from app.api.v1.middleware import RequestContextMiddleware
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.neo4j import close_driver, verify_connectivity
from app.db.neo4j_schema import init_graph_schema
from app.db.postgres import dispose_engine
from app.db.redis import close_redis, ping as redis_ping

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app.startup", env=settings.app_env, version=__version__)

    # Verify infra reachable + init schema (best-effort: log, don't crash dev)
    try:
        await verify_connectivity()
        await init_graph_schema()
    except Exception as e:  # noqa: BLE001
        logger.warning("neo4j.unavailable", error=str(e))

    try:
        await redis_ping()
        logger.info("redis.connected")
    except Exception as e:  # noqa: BLE001
        logger.warning("redis.unavailable", error=str(e))

    yield

    logger.info("app.shutdown")
    await close_driver()
    await close_redis()
    await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="TAHRIX — Agentic AI Blockchain Cyber Intelligence",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)

register_error_handlers(app)
register_routers(app)

# Prometheus metrics
app.mount("/metrics", make_asgi_app())

# Frontend static files
import os as _os
_frontend_dir = _os.path.join(_os.path.dirname(__file__), "..", "frontend")
if _os.path.isdir(_frontend_dir):
    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        return FileResponse(_os.path.join(_frontend_dir, "index.html"))
    app.mount("/app", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
