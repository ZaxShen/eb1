"""PostgreSQL connection pool management."""

import logging

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config.settings import settings

log = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        if not settings.postgres_dsn:
            raise RuntimeError(
                "postgres_dsn is not set. Add POSTGRES_DSN to .env or environment."
            )
        _pool = ConnectionPool(
            conninfo=settings.postgres_dsn,
            min_size=2,
            max_size=10,
            kwargs={"autocommit": False, "row_factory": dict_row},
        )
        _pool.wait()
        log.info("[pg] Connection pool ready (min=2, max=10)")
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
        log.info("[pg] Connection pool closed")
