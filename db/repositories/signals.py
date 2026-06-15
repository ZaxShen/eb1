"""Signal repository — READ-ONLY access to matching_signals table.

Signal extraction is handled by an independent pipeline.
eb1 only reads distinct user IDs for segment sampling.
"""

from __future__ import annotations

import logging

from db.repositories.base import BaseRepository

log = logging.getLogger(__name__)


class SignalRepository(BaseRepository):

    def distinct_users(self) -> list[str]:
        rows = self._fetch_all(
            "SELECT DISTINCT unnest(users) AS user_id FROM matching_signals"
        )
        return [row["user_id"] for row in rows]

    def count(self) -> int:
        return self._count("SELECT COUNT(*) AS cnt FROM matching_signals")
