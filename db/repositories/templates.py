"""Template mapping repository — eb1_template_mappings table."""

from __future__ import annotations

import logging

from db.repositories.base import BaseRepository

log = logging.getLogger(__name__)


class TemplateMappingRepository(BaseRepository):

    def find_all(self) -> list[dict]:
        return self._fetch_all(
            """
            SELECT template_id, topic_slug, subtopic_slug,
                   name, summary, messages
            FROM eb1_template_mappings
            """
        )

    def existing_template_ids(self) -> set[str]:
        rows = self._fetch_all("SELECT template_id FROM eb1_template_mappings")
        return {row["template_id"] for row in rows}

    def upsert(
        self,
        template_id: str,
        topic_slug: str,
        subtopic_slug: str,
        name: str,
        summary: str,
        messages: list[str],
    ) -> None:
        self._execute(
            """
            INSERT INTO eb1_template_mappings
                (template_id, topic_slug, subtopic_slug, name, summary, messages)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (template_id) DO UPDATE SET
                topic_slug = EXCLUDED.topic_slug,
                subtopic_slug = EXCLUDED.subtopic_slug,
                name = EXCLUDED.name,
                summary = EXCLUDED.summary,
                messages = EXCLUDED.messages,
                updated_at = NOW()
            """,
            (template_id, topic_slug, subtopic_slug, name, summary, messages),
        )

    def count(self) -> int:
        return self._count("SELECT COUNT(*) AS cnt FROM eb1_template_mappings")
