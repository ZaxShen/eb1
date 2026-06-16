"""FastAPI application for the annotation site.

Wires CORS for the Vite dev origin and mounts the ``/api`` router. Run::

    uv run uvicorn annotation.backend.app:app --reload

The backend reads its PostgreSQL connection from ``EB1_ANNOTATION_DSN`` (see
``annotation/docker-compose.yml`` and ``annotation.backend.config``). The E2E
harness and tests point this at an isolated database and seed it via
``annotation.backend.db.seed_conversations``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from annotation.backend.routes import auth_router, router

VITE_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def create_app() -> FastAPI:
    """Build the FastAPI app with CORS and the API router."""
    app = FastAPI(title="eb1 Annotation Backend", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=VITE_DEV_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router)
    app.include_router(router)
    return app


app = create_app()
