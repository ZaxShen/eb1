"""Benchmark repository — eb1_benchmark_raw table."""

from __future__ import annotations

import logging

from psycopg.types.json import Json

from db.repositories.base import BaseRepository

log = logging.getLogger(__name__)

_TABLE = "eb1_benchmark_raw"

_INSERT_SQL = f"""
    INSERT INTO {_TABLE} (
        user_id, chat_id, chat_messages,
        topic, sub_topic, label_confidence, summary, sentiment,
        has_user_engagement, has_bot_failure, response_rate,
        chat_started_at, chat_ended_at, classified_at,
        benchmark_run_id
    ) VALUES (
        %(user_id)s, %(chat_id)s, %(chat_messages)s,
        %(topic)s, %(sub_topic)s, %(label_confidence)s,
        %(summary)s, %(sentiment)s,
        %(has_user_engagement)s, %(has_bot_failure)s, %(response_rate)s,
        %(chat_started_at)s, %(chat_ended_at)s, %(classified_at)s,
        %(benchmark_run_id)s
    )
    RETURNING id
"""


class BenchmarkSegmentRepository(BaseRepository):

    # ── Writes ───────────────────────────────────────────────────────────────

    def insert_many(self, segments: list[dict]) -> int:
        if not segments:
            return 0
        with self._pool.connection() as conn:
            cur = conn.cursor()
            for seg in segments:
                row = dict(seg)
                cur.execute(_INSERT_SQL, row)
                seg["id"] = cur.fetchone()["id"]
            conn.commit()
            return len(segments)

    def delete_by_run(self, benchmark_run_id: int) -> int:
        """DELETE WHERE benchmark_run_id = ?"""
        return self._execute(
            f"DELETE FROM {_TABLE} WHERE benchmark_run_id = %s",
            (benchmark_run_id,),
        )

    def delete_by_run_and_user(self, benchmark_run_id: int, user_id: str) -> int:
        """DELETE WHERE benchmark_run_id = ? AND user_id = ?"""
        return self._execute(
            f"DELETE FROM {_TABLE} WHERE benchmark_run_id = %s AND user_id = %s",
            (benchmark_run_id, user_id),
        )

    # ── Reads ────────────────────────────────────────────────────────────────

    def count_by_run(self, benchmark_run_id: int) -> int:
        return self._count(
            f"SELECT COUNT(*) AS cnt FROM {_TABLE} WHERE benchmark_run_id = %s",
            (benchmark_run_id,),
        )

    def find_by_run(self, benchmark_run_id: int) -> list[dict]:
        """All segments for a benchmark_run_id."""
        return self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE benchmark_run_id = %s ORDER BY chat_started_at",
            (benchmark_run_id,),
        )

    def find_one_by_run(self, benchmark_run_id: int) -> dict | None:
        """Fetch one segment for a benchmark_run_id."""
        return self._fetch_one(
            f"SELECT * FROM {_TABLE} WHERE benchmark_run_id = %s LIMIT 1",
            (benchmark_run_id,),
        )

    def find_with_summary_by_run(
        self,
        benchmark_run_id: int,
        *,
        user_engaged_only: bool = False,
    ) -> list[dict]:
        """Segments with non-null summary for a benchmark run."""
        conditions = [
            "benchmark_run_id = %s",
            "summary IS NOT NULL",
        ]
        params: list = [benchmark_run_id]
        if user_engaged_only:
            conditions.append("has_user_engagement = true")
        where = " AND ".join(conditions)
        return self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE {where} "
            "ORDER BY chat_started_at",
            tuple(params),
        )

    def bulk_update_clusters(
        self, updates: list[tuple[int, dict]],
    ) -> int:
        if not updates:
            return 0
        with self._pool.connection() as conn:
            conn.cursor().executemany(
                f"UPDATE {_TABLE} SET cluster = %s, "
                "updated_at = NOW() WHERE id = %s",
                [(Json(d), sid) for sid, d in updates],
            )
            conn.commit()
            return len(updates)
