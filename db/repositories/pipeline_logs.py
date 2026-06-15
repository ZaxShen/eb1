"""Pipeline event logs — eb1_pipeline_logs + benchmark variant."""

from __future__ import annotations

from psycopg.types.json import Json

from db.repositories.base import BaseRepository

_PROD_TABLE = "eb1_pipeline_logs"
_BENCH_TABLE = "eb1_benchmark_pipeline_logs"


class PipelineLogRepository(BaseRepository):

    def log(
        self,
        event_type: str,
        payload: dict,
        *,
        user_id: str | None = None,
        config_id: int | None = None,
    ) -> None:
        self._execute(
            f"""
            INSERT INTO {_PROD_TABLE}
                (event_type, user_id, payload, config_id)
            VALUES (%s, %s, %s, %s)
            """,
            (event_type, user_id, Json(payload), config_id),
        )

    def log_remap(
        self,
        user_id: str,
        direction: str,
        original_topic: str,
        original_sub_topic: str | None,
        remapped_topic: str,
        config_id: int | None = None,
    ) -> None:
        self.log(
            "taxonomy_remap",
            {
                "direction": direction,
                "original_topic": original_topic,
                "original_sub_topic": original_sub_topic,
                "remapped_topic": remapped_topic,
            },
            user_id=user_id,
            config_id=config_id,
        )


class BenchmarkPipelineLogRepository(BaseRepository):

    def __init__(self, pool):
        super().__init__(pool)
        self._group_id: int | None = None
        self._benchmark_run_id: int | None = None

    def set_run_context(
        self, group_id: int, benchmark_run_id: int,
    ) -> None:
        self._group_id = group_id
        self._benchmark_run_id = benchmark_run_id

    def log(
        self,
        event_type: str,
        payload: dict,
        *,
        user_id: str | None = None,
        config_id: int | None = None,
    ) -> None:
        self._execute(
            f"""
            INSERT INTO {_BENCH_TABLE}
                (event_type, user_id, payload, config_id,
                 group_id, benchmark_run_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (event_type, user_id, Json(payload), config_id,
             self._group_id, self._benchmark_run_id),
        )

    def log_remap(
        self,
        user_id: str,
        direction: str,
        original_topic: str,
        original_sub_topic: str | None,
        remapped_topic: str,
        config_id: int | None = None,
    ) -> None:
        self.log(
            "taxonomy_remap",
            {
                "direction": direction,
                "original_topic": original_topic,
                "original_sub_topic": original_sub_topic,
                "remapped_topic": remapped_topic,
            },
            user_id=user_id,
            config_id=config_id,
        )
