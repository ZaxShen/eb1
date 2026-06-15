"""Benchmark taxonomy repository — eb1_benchmark_taxonomy tables.

Reads: UNION ALL from prod (eb1_taxonomy_*) + benchmark-only tables.
Writes: benchmark tables only — prod tables are never modified.
"""

from __future__ import annotations

import logging
from datetime import datetime

from db.repositories.base import BaseRepository

log = logging.getLogger(__name__)

_PROD_TOPICS = "eb1_taxonomy_topics"
_PROD_SUBTOPICS = "eb1_taxonomy_subtopics"
_BENCH_TOPICS = "eb1_benchmark_taxonomy_topics"
_BENCH_SUBTOPICS = "eb1_benchmark_taxonomy_subtopics"


class BenchmarkTaxonomyRepository(BaseRepository):
    """Taxonomy repo for benchmark mode.

    Reads return the superset (prod + benchmark-discovered).
    Writes go to benchmark-only tables with group_id/benchmark_run_id.
    """

    def __init__(self, pool):
        super().__init__(pool)
        self._group_id: int | None = None
        self._benchmark_run_id: int | None = None

    def set_run_context(
        self, group_id: int, benchmark_run_id: int,
    ) -> None:
        self._group_id = group_id
        self._benchmark_run_id = benchmark_run_id

    # ── Reads (UNION ALL) ──

    def load_topics(self, type_filter: str) -> list[dict]:
        topics = self._fetch_all(
            f"""
            SELECT slug, name, description, type,
                   confirmed_by, confirmed_at, created_by, updated_by,
                   created_at, updated_at
            FROM {_PROD_TOPICS} WHERE type = %s
            UNION ALL
            SELECT slug, name, description, type,
                   confirmed_by, confirmed_at, created_by, updated_by,
                   created_at, updated_at
            FROM {_BENCH_TOPICS} WHERE type = %s
            ORDER BY slug
            """,
            (type_filter, type_filter),
        )
        if not topics:
            return []

        topic_slugs = [t["slug"] for t in topics]
        subtopics = self._fetch_all(
            f"""
            SELECT slug, topic_slug, name, description,
                   confirmed_by, confirmed_at, created_by, updated_by,
                   created_at, updated_at
            FROM {_PROD_SUBTOPICS}
            WHERE topic_slug = ANY(%s)
            UNION ALL
            SELECT slug, topic_slug, name, description,
                   confirmed_by, confirmed_at, created_by, updated_by,
                   created_at, updated_at
            FROM {_BENCH_SUBTOPICS}
            WHERE topic_slug = ANY(%s)
            ORDER BY topic_slug, slug
            """,
            (topic_slugs, topic_slugs),
        )

        subs_by_topic: dict[str, list[dict]] = {}
        for sub in subtopics:
            subs_by_topic.setdefault(sub["topic_slug"], []).append(sub)

        for topic in topics:
            topic["subtopics"] = subs_by_topic.get(topic["slug"], [])

        return topics

    def get_max_updated_at(self, type_filter: str) -> datetime | None:
        row = self._fetch_one(
            f"""
            SELECT MAX(max_updated) AS max_updated FROM (
                SELECT MAX(greatest(
                    t.updated_at,
                    COALESCE(s.max_sub, t.updated_at)
                )) AS max_updated
                FROM {_PROD_TOPICS} t
                LEFT JOIN (
                    SELECT topic_slug, MAX(updated_at) AS max_sub
                    FROM {_PROD_SUBTOPICS} GROUP BY topic_slug
                ) s ON s.topic_slug = t.slug
                WHERE t.type = %s
                UNION ALL
                SELECT MAX(greatest(
                    t.updated_at,
                    COALESCE(s.max_sub, t.updated_at)
                )) AS max_updated
                FROM {_BENCH_TOPICS} t
                LEFT JOIN (
                    SELECT topic_slug, MAX(updated_at) AS max_sub
                    FROM {_BENCH_SUBTOPICS} GROUP BY topic_slug
                ) s ON s.topic_slug = t.slug
                WHERE t.type = %s
            ) combined
            """,
            (type_filter, type_filter),
        )
        return row["max_updated"] if row else None

    # ── Writes (benchmark tables only) ──

    def upsert_topic(
        self,
        slug: str,
        name: str,
        description: str,
        topic_type: str,
        *,
        confirmed_by: str | None = None,
        confirmed_at: datetime | None = None,
        created_by: str | None = None,
        updated_by: str | None = None,
    ) -> None:
        self._execute(
            f"""
            INSERT INTO {_BENCH_TOPICS}
                (slug, name, description, type, confirmed_by, confirmed_at,
                 created_by, updated_by, group_id, benchmark_run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            """,
            (slug, name, description, topic_type, confirmed_by,
             confirmed_at, created_by, updated_by,
             self._group_id, self._benchmark_run_id),
        )

    def upsert_subtopic(
        self,
        slug: str,
        topic_slug: str,
        name: str,
        description: str,
        *,
        confirmed_by: str | None = None,
        confirmed_at: datetime | None = None,
        created_by: str | None = None,
        updated_by: str | None = None,
    ) -> None:
        self._execute(
            f"""
            INSERT INTO {_BENCH_SUBTOPICS}
                (slug, topic_slug, name, description, confirmed_by,
                 confirmed_at, created_by, updated_by,
                 group_id, benchmark_run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (topic_slug, slug) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            """,
            (slug, topic_slug, name, description, confirmed_by,
             confirmed_at, created_by, updated_by,
             self._group_id, self._benchmark_run_id),
        )
