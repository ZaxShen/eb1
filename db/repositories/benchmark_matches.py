"""Benchmark match repository — eb1_benchmark_matches table."""
from __future__ import annotations

import logging

from db.repositories.base import BaseRepository

log = logging.getLogger(__name__)
_TABLE = "eb1_benchmark_matches"


class BenchmarkMatchRepository(BaseRepository):

    def insert_many(self, matches: list[dict]) -> int:
        if not matches:
            return 0
        with self._pool.connection() as conn:
            for m in matches:
                conn.execute(
                    f"""INSERT INTO {_TABLE} (
                        benchmark_run_id,
                        gt_segment_id, gt_user_id, gt_topic, gt_sub_topic,
                        gt_has_user_engagement,
                        bench_segment_id, model_topic, model_sub_topic,
                        model_confidence, model_summary,
                        iou, matched, topic_match, subtopic_match
                    ) VALUES (
                        %(benchmark_run_id)s,
                        %(gt_segment_id)s, %(gt_user_id)s, %(gt_topic)s, %(gt_sub_topic)s,
                        %(gt_has_user_engagement)s,
                        %(bench_segment_id)s, %(model_topic)s, %(model_sub_topic)s,
                        %(model_confidence)s, %(model_summary)s,
                        %(iou)s, %(matched)s, %(topic_match)s, %(subtopic_match)s
                    )""",
                    m,
                )
            conn.commit()
        return len(matches)

    def delete_by_run(self, benchmark_run_id: int) -> int:
        return self._execute(
            f"DELETE FROM {_TABLE} WHERE benchmark_run_id = %s",
            (benchmark_run_id,),
        )

    def find_by_run(self, benchmark_run_id: int) -> list[dict]:
        return self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE benchmark_run_id = %s ORDER BY gt_user_id",
            (benchmark_run_id,),
        )

    def find_mismatches(self, benchmark_run_id: int) -> list[dict]:
        return self._fetch_all(
            f"""SELECT * FROM {_TABLE}
                WHERE benchmark_run_id = %s
                AND matched = TRUE AND topic_match = FALSE""",
            (benchmark_run_id,),
        )
