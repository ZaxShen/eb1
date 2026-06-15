"""Taxonomy repository — eb1_taxonomy_topics + eb1_taxonomy_subtopics."""

from __future__ import annotations

import logging
from datetime import datetime

from db.repositories.base import BaseRepository

log = logging.getLogger(__name__)

_TOPICS = "eb1_taxonomy_topics"
_SUBTOPICS = "eb1_taxonomy_subtopics"


class TaxonomyRepository(BaseRepository):

    def load_topics(self, type_filter: str) -> list[dict]:
        topics = self._fetch_all(
            f"SELECT * FROM {_TOPICS} WHERE type = %s ORDER BY slug",
            (type_filter,),
        )
        if not topics:
            return []

        topic_slugs = [t["slug"] for t in topics]
        subtopics = self._fetch_all(
            f"""
            SELECT * FROM {_SUBTOPICS}
            WHERE topic_slug = ANY(%s)
            ORDER BY topic_slug, slug
            """,
            (topic_slugs,),
        )

        subs_by_topic: dict[str, list[dict]] = {}
        for sub in subtopics:
            subs_by_topic.setdefault(sub["topic_slug"], []).append(sub)

        for topic in topics:
            topic["subtopics"] = subs_by_topic.get(topic["slug"], [])

        return topics

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
            INSERT INTO {_TOPICS}
                (slug, name, description, type, confirmed_by, confirmed_at,
                 created_by, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            """,
            (slug, name, description, topic_type, confirmed_by, confirmed_at,
             created_by, updated_by),
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
        with self._pool.connection() as conn:
            conn.execute(
                f"""
                INSERT INTO {_SUBTOPICS}
                    (slug, topic_slug, name, description, confirmed_by,
                     confirmed_at, created_by, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (topic_slug, slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = NOW()
                """,
                (slug, topic_slug, name, description, confirmed_by,
                 confirmed_at, created_by, updated_by),
            )
            conn.execute(
                f"UPDATE {_TOPICS} SET updated_at = NOW() WHERE slug = %s",
                (topic_slug,),
            )
            conn.commit()

    def batch_upsert(self, topics: list[dict], topic_type: str) -> None:
        with self._pool.connection() as conn:
            for topic in topics:
                conn.execute(
                    f"""
                    INSERT INTO {_TOPICS}
                        (slug, name, description, type, confirmed_by,
                         confirmed_at, created_by, updated_by)
                    VALUES (%(slug)s, %(name)s, %(description)s, %(type)s,
                            %(confirmed_by)s, %(confirmed_at)s,
                            %(created_by)s, %(updated_by)s)
                    ON CONFLICT (slug) DO UPDATE SET
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = NOW()
                    """,
                    {**topic, "type": topic_type},
                )
                for sub in topic.get("subtopics", []):
                    conn.execute(
                        f"""
                        INSERT INTO {_SUBTOPICS}
                            (slug, topic_slug, name, description,
                             confirmed_by, confirmed_at,
                             created_by, updated_by)
                        VALUES (%(slug)s, %(topic_slug)s, %(name)s,
                                %(description)s, %(confirmed_by)s,
                                %(confirmed_at)s, %(created_by)s,
                                %(updated_by)s)
                        ON CONFLICT (topic_slug, slug) DO UPDATE SET
                            name = EXCLUDED.name,
                            description = EXCLUDED.description,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = NOW()
                        """,
                        {**sub, "topic_slug": topic["slug"]},
                    )
            conn.commit()

    def get_max_updated_at(self, type_filter: str) -> datetime | None:
        row = self._fetch_one(
            f"""
            SELECT MAX(greatest(
                t.updated_at,
                COALESCE(s.max_sub, t.updated_at)
            )) AS max_updated
            FROM {_TOPICS} t
            LEFT JOIN (
                SELECT topic_slug, MAX(updated_at) AS max_sub
                FROM {_SUBTOPICS}
                GROUP BY topic_slug
            ) s ON s.topic_slug = t.slug
            WHERE t.type = %s
            """,
            (type_filter,),
        )
        return row["max_updated"] if row else None
