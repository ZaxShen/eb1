"""Base repository with shared connection helpers.

Pool connections are pre-configured with ``row_factory=dict_row``
(see ``db.pg.get_pool``), so all queries return dicts by default.
"""

from __future__ import annotations

import logging

from psycopg_pool import ConnectionPool

log = logging.getLogger(__name__)


class BaseRepository:

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def _execute(self, query: str, params: tuple | dict | None = None) -> int:
        with self._pool.connection() as conn:
            cur = conn.execute(query, params)
            conn.commit()
            return cur.rowcount

    def _fetch_one(self, query: str, params: tuple | dict | None = None) -> dict | None:
        with self._pool.connection() as conn:
            row = conn.execute(query, params).fetchone()
            conn.commit()
            return row

    def _fetch_all(self, query: str, params: tuple | dict | None = None) -> list[dict]:
        with self._pool.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            conn.commit()
            return rows

    def _count(self, query: str, params: tuple | dict | None = None) -> int:
        """Execute a SELECT COUNT(*) AS cnt query and return the integer count."""
        row = self._fetch_one(query, params)
        return row["cnt"] if row else 0
