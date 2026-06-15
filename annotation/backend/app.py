"""FastAPI application for the annotation site.

Wires CORS for the Vite dev origin and mounts the ``/api`` router. Run::

    uv run uvicorn annotation.backend.app:app --reload

The datasets root defaults to ``datasets/``; tests override it via
``annotation.backend.routes.set_datasets_root``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from annotation.backend.routes import router

VITE_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def create_app() -> FastAPI:
    """Build the FastAPI app with CORS and the API router."""
    app = FastAPI(title="UFL Annotation Backend", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=VITE_DEV_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
