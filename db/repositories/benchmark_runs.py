"""Benchmark run repository — eb1_benchmark_runs table."""
from __future__ import annotations

import logging

from psycopg.types.json import Json

from db.repositories.base import BaseRepository

log = logging.getLogger(__name__)
_TABLE = "eb1_benchmark_runs"


class BenchmarkRunRepository(BaseRepository):

    def upsert(self, data: dict) -> int:
        """Insert or update a benchmark run summary. Returns id.

        The unified_score / unified_topic_score / unified_sub_score /
        ue_unified_score columns were added later (see
        db/schema/unified_score.sql). If those columns don't exist yet,
        the upsert falls back to the legacy column list so older DBs
        keep working without a migration.
        """
        row = dict(data)
        if isinstance(row.get("confidence_calibration"), (list, dict)):
            row["confidence_calibration"] = Json(row["confidence_calibration"])
        for key in (
            "unified_score", "unified_topic_score",
            "unified_sub_score", "ue_unified_score",
        ):
            row.setdefault(key, None)

        upsert_with_unified = f"""INSERT INTO {_TABLE} (
                group_id, config_id, summary, run_at,
                total_gt_segments, total_model_segments,
                matched_count, match_rate, avg_iou,
                topic_accuracy, subtopic_accuracy, segment_count_ratio,
                unified_score, unified_topic_score, unified_sub_score,
                ue_gt_segments, ue_matched_count, ue_match_rate,
                ue_topic_accuracy, ue_subtopic_accuracy, ue_unified_score,
                confidence_calibration, rank
            ) VALUES (
                %(group_id)s, %(config_id)s, %(summary)s, %(run_at)s,
                %(total_gt_segments)s, %(total_model_segments)s,
                %(matched_count)s, %(match_rate)s, %(avg_iou)s,
                %(topic_accuracy)s, %(subtopic_accuracy)s, %(segment_count_ratio)s,
                %(unified_score)s, %(unified_topic_score)s, %(unified_sub_score)s,
                %(ue_gt_segments)s, %(ue_matched_count)s, %(ue_match_rate)s,
                %(ue_topic_accuracy)s, %(ue_subtopic_accuracy)s, %(ue_unified_score)s,
                %(confidence_calibration)s, %(rank)s
            ) ON CONFLICT (group_id, config_id) DO UPDATE SET
                summary = EXCLUDED.summary,
                run_at = EXCLUDED.run_at,
                total_gt_segments = EXCLUDED.total_gt_segments,
                total_model_segments = EXCLUDED.total_model_segments,
                matched_count = EXCLUDED.matched_count,
                match_rate = EXCLUDED.match_rate,
                avg_iou = EXCLUDED.avg_iou,
                topic_accuracy = EXCLUDED.topic_accuracy,
                subtopic_accuracy = EXCLUDED.subtopic_accuracy,
                segment_count_ratio = EXCLUDED.segment_count_ratio,
                unified_score = EXCLUDED.unified_score,
                unified_topic_score = EXCLUDED.unified_topic_score,
                unified_sub_score = EXCLUDED.unified_sub_score,
                ue_gt_segments = EXCLUDED.ue_gt_segments,
                ue_matched_count = EXCLUDED.ue_matched_count,
                ue_match_rate = EXCLUDED.ue_match_rate,
                ue_topic_accuracy = EXCLUDED.ue_topic_accuracy,
                ue_subtopic_accuracy = EXCLUDED.ue_subtopic_accuracy,
                ue_unified_score = EXCLUDED.ue_unified_score,
                confidence_calibration = EXCLUDED.confidence_calibration,
                rank = EXCLUDED.rank
            RETURNING id"""

        legacy_upsert = f"""INSERT INTO {_TABLE} (
                group_id, config_id, summary, run_at,
                total_gt_segments, total_model_segments,
                matched_count, match_rate, avg_iou,
                topic_accuracy, subtopic_accuracy, segment_count_ratio,
                ue_gt_segments, ue_matched_count, ue_match_rate,
                ue_topic_accuracy, ue_subtopic_accuracy,
                confidence_calibration, rank
            ) VALUES (
                %(group_id)s, %(config_id)s, %(summary)s, %(run_at)s,
                %(total_gt_segments)s, %(total_model_segments)s,
                %(matched_count)s, %(match_rate)s, %(avg_iou)s,
                %(topic_accuracy)s, %(subtopic_accuracy)s, %(segment_count_ratio)s,
                %(ue_gt_segments)s, %(ue_matched_count)s, %(ue_match_rate)s,
                %(ue_topic_accuracy)s, %(ue_subtopic_accuracy)s,
                %(confidence_calibration)s, %(rank)s
            ) ON CONFLICT (group_id, config_id) DO UPDATE SET
                summary = EXCLUDED.summary,
                run_at = EXCLUDED.run_at,
                total_gt_segments = EXCLUDED.total_gt_segments,
                total_model_segments = EXCLUDED.total_model_segments,
                matched_count = EXCLUDED.matched_count,
                match_rate = EXCLUDED.match_rate,
                avg_iou = EXCLUDED.avg_iou,
                topic_accuracy = EXCLUDED.topic_accuracy,
                subtopic_accuracy = EXCLUDED.subtopic_accuracy,
                segment_count_ratio = EXCLUDED.segment_count_ratio,
                ue_gt_segments = EXCLUDED.ue_gt_segments,
                ue_matched_count = EXCLUDED.ue_matched_count,
                ue_match_rate = EXCLUDED.ue_match_rate,
                ue_topic_accuracy = EXCLUDED.ue_topic_accuracy,
                ue_subtopic_accuracy = EXCLUDED.ue_subtopic_accuracy,
                confidence_calibration = EXCLUDED.confidence_calibration,
                rank = EXCLUDED.rank
            RETURNING id"""

        with self._pool.connection() as conn:
            try:
                result = conn.execute(upsert_with_unified, row).fetchone()
            except Exception as exc:
                log.warning(
                    "Unified score columns missing on %s (%s). "
                    "Falling back to legacy upsert — run "
                    "db/schema/unified_score.sql to enable storage.",
                    _TABLE, exc,
                )
                conn.rollback()
                result = conn.execute(legacy_upsert, row).fetchone()
            conn.commit()
            return result["id"]

    def update_timing(
        self, run_id: int,
        duration_seconds: float, avg_llm_latency_ms: float,
    ) -> None:
        """Update duration and latency after a benchmark run completes."""
        self._execute(
            f"""UPDATE {_TABLE}
                SET duration_seconds = %s, avg_llm_latency_ms = %s
                WHERE id = %s""",
            (duration_seconds, avg_llm_latency_ms, run_id),
        )

    def find_by_group(self, group_id: int) -> list[dict]:
        return self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE group_id = %s ORDER BY rank",
            (group_id,),
        )

    def find_leaderboard(self, group_id: int) -> list[dict]:
        return self._fetch_all(
            f"""SELECT r.*, c.model, c.user_prompt, c.bot_prompt, c.temperature
                FROM {_TABLE} r
                JOIN eb1_pipeline_configs c ON r.config_id = c.id
                WHERE r.group_id = %s ORDER BY r.rank""",
            (group_id,),
        )

    def update_ranks(self, group_id: int) -> None:
        """Compute and set rank within a group.

        Ordered by unified_score DESC (tie-break: subtopic_accuracy,
        topic_accuracy, match_rate). Falls back to the legacy ordering
        when unified_score is unavailable (older schema).
        """
        try:
            self._execute(
                f"""UPDATE {_TABLE} SET rank = sub.rn FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        ORDER BY COALESCE(unified_score, -1) DESC,
                                 subtopic_accuracy DESC,
                                 topic_accuracy DESC,
                                 match_rate DESC
                    ) AS rn
                    FROM {_TABLE} WHERE group_id = %s
                ) sub WHERE {_TABLE}.id = sub.id""",
                (group_id,),
            )
        except Exception as exc:
            log.warning(
                "update_ranks: unified_score column missing (%s). "
                "Falling back to legacy ordering.", exc,
            )
            self._execute(
                f"""UPDATE {_TABLE} SET rank = sub.rn FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        ORDER BY subtopic_accuracy DESC,
                                 topic_accuracy DESC,
                                 match_rate DESC
                    ) AS rn
                    FROM {_TABLE} WHERE group_id = %s
                ) sub WHERE {_TABLE}.id = sub.id""",
                (group_id,),
            )
