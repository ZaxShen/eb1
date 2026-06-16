"""Connection configuration for the annotation backend.

The backend talks to a PostgreSQL database (see ``annotation/docker-compose.yml``)
addressed by the ``EB1_ANNOTATION_DSN`` environment variable. The default points
at the local docker compose service so a fresh checkout works without extra
setup.
"""

from __future__ import annotations

import os

DEFAULT_DSN = "postgresql://eb1:eb1@localhost:5544/eb1_annotation"


def annotation_dsn() -> str:
    """Return the annotation Postgres DSN (``EB1_ANNOTATION_DSN`` or the local default)."""
    return os.environ.get("EB1_ANNOTATION_DSN") or DEFAULT_DSN
