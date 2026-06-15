"""Benchmark group repository — eb1_benchmark_groups table."""
from __future__ import annotations

import logging

from db.repositories.base import BaseRepository

log = logging.getLogger(__name__)
_TABLE = "eb1_benchmark_groups"


class BenchmarkGroupRepository(BaseRepository):

    def get_or_create(
        self,
        name: str,
        type: str = "",
        objective: str = "",
    ) -> int:
        """Return group id for the given name, creating if needed."""
        with self._pool.connection() as conn:
            conn.execute(
                f"""INSERT INTO {_TABLE} (name, type, objective)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET
                        type = EXCLUDED.type,
                        objective = EXCLUDED.objective""",
                (name, type, objective),
            )
            row = conn.execute(
                f"SELECT id FROM {_TABLE} WHERE name = %s", (name,),
            ).fetchone()
            conn.commit()
            return row["id"]

    def find_by_name(self, name: str) -> dict | None:
        return self._fetch_one(
            f"SELECT * FROM {_TABLE} WHERE name = %s", (name,),
        )

    def find_all(self) -> list[dict]:
        return self._fetch_all(f"SELECT * FROM {_TABLE} ORDER BY created_at DESC")
