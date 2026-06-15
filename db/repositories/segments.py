"""Segment repository — sms_chat_segments table."""

from __future__ import annotations

import logging
from typing import Any

from psycopg.types.json import Json

from db.repositories.base import BaseRepository

log = logging.getLogger(__name__)

_ALLOWED_COLUMNS = frozenset({
    "user_id", "chat_id", "topic", "sub_topic", "true_topic",
    "true_sub_topic", "label_confidence", "is_bot_only",
    "template_id", "run_id", "model", "type",
})

_INSERT_SQL = """
    INSERT INTO sms_chat_segments
        (user_id, chat_id, chat_messages,
         topic, sub_topic, label_confidence, summary, sentiment,
         has_user_engagement, has_bot_failure, response_rate,
         chat_started_at, chat_ended_at, classified_at,
         config_id)
    VALUES (
        %(user_id)s, %(chat_id)s, %(chat_messages)s,
        %(topic)s, %(sub_topic)s, %(label_confidence)s,
        %(summary)s, %(sentiment)s,
        %(has_user_engagement)s, %(has_bot_failure)s,
        %(response_rate)s,
        %(chat_started_at)s, %(chat_ended_at)s, %(classified_at)s,
        %(config_id)s
    )
    RETURNING id
"""


class SegmentRepository(BaseRepository):

    # ── Writes ───────────────────────────────────────────────────────────────

    def insert_many(self, segments: list[dict]) -> int:
        if not segments:
            return 0
        with self._pool.connection() as conn:
            cur = conn.cursor()
            for seg in segments:
                cur.execute(_INSERT_SQL, seg)
                seg["id"] = cur.fetchone()["id"]
            conn.commit()
            return len(segments)

    def delete_unreviewed_for_user(self, user_id: str) -> int:
        return self._execute(
            """
            DELETE FROM sms_chat_segments
            WHERE user_id = %s AND true_topic IS NULL AND true_sub_topic IS NULL
            """,
            (user_id,),
        )

    def delete_unreviewed_all(self) -> int:
        return self._execute(
            "DELETE FROM sms_chat_segments WHERE true_topic IS NULL AND true_sub_topic IS NULL"
        )

    def delete_by_ids(self, ids: list[int]) -> int:
        if not ids:
            return 0
        return self._execute(
            "DELETE FROM sms_chat_segments WHERE id = ANY(%s)",
            (ids,),
        )

    def clear_classification_fields(self) -> int:
        return self._execute(
            """
            UPDATE sms_chat_segments SET
                topic = NULL, sub_topic = NULL, label_confidence = NULL,
                summary = NULL, sentiment = NULL, classified_at = NULL,
                updated_at = NOW()
            WHERE true_topic IS NULL AND true_sub_topic IS NULL
            """
        )

    def bulk_update_clusters(self, updates: list[tuple[int, dict]]) -> int:
        if not updates:
            return 0
        with self._pool.connection() as conn:
            conn.cursor().executemany(
                "UPDATE sms_chat_segments SET cluster = %s, "
                "updated_at = NOW() WHERE id = %s",
                [(Json(d), sid) for sid, d in updates],
            )
            conn.commit()
            return len(updates)

    # ── Reads ────────────────────────────────────────────────────────────────

    def find_by_user(
        self,
        user_id: str,
        *,
        reviewed_only: bool = False,
        unreviewed_only: bool = False,
        limit: int | None = None,
    ) -> list[dict]:
        conditions = ["user_id = %s"]
        params: list[Any] = [user_id]
        if reviewed_only:
            conditions.append("true_topic IS NOT NULL")
        if unreviewed_only:
            conditions.append("true_topic IS NULL AND true_sub_topic IS NULL")
        where = " AND ".join(conditions)
        query = f"SELECT * FROM sms_chat_segments WHERE {where} ORDER BY chat_started_at"
        if limit:
            query += " LIMIT %s"
            params.append(limit)
        return self._fetch_all(query, tuple(params))

    def find_reviewed_for_user(self, user_id: str) -> list[dict]:
        return self.find_by_user(user_id, reviewed_only=True)

    def exists_for_user(self, user_id: str) -> bool:
        row = self._fetch_one(
            "SELECT 1 FROM sms_chat_segments WHERE user_id = %s LIMIT 1",
            (user_id,),
        )
        return row is not None

    def latest_segment_for_user(self, user_id: str) -> dict | None:
        return self._fetch_one(
            """
            SELECT * FROM sms_chat_segments
            WHERE user_id = %s
            ORDER BY chat_started_at DESC LIMIT 1
            """,
            (user_id,),
        )

    def distinct_user_ids(self) -> list[str]:
        rows = self._fetch_all(
            "SELECT DISTINCT user_id FROM sms_chat_segments"
        )
        return [row["user_id"] for row in rows]

    def distinct_reviewed_user_ids(self) -> list[str]:
        rows = self._fetch_all(
            "SELECT DISTINCT user_id FROM sms_chat_segments "
            "WHERE true_topic IS NOT NULL AND true_sub_topic IS NOT NULL"
        )
        return [row["user_id"] for row in rows]

    def count(self, **filters) -> int:
        invalid = set(filters) - _ALLOWED_COLUMNS
        if invalid:
            raise ValueError(f"Invalid filter column(s): {invalid}")
        conditions = []
        params: list[Any] = []
        for key, val in filters.items():
            if val is None:
                conditions.append(f"{key} IS NULL")
            else:
                conditions.append(f"{key} = %s")
                params.append(val)
        where = " AND ".join(conditions) if conditions else "TRUE"
        return self._count(
            f"SELECT COUNT(*) AS cnt FROM sms_chat_segments WHERE {where}",
            tuple(params),
        )

    def count_all(self) -> int:
        return self._count("SELECT COUNT(*) AS cnt FROM sms_chat_segments")

    def find_all(self, **filters) -> list[dict]:
        invalid = set(filters) - _ALLOWED_COLUMNS
        if invalid:
            raise ValueError(f"Invalid filter column(s): {invalid}")
        conditions = []
        params: list[Any] = []
        for key, val in filters.items():
            if val is None:
                conditions.append(f"{key} IS NULL")
            else:
                conditions.append(f"{key} = %s")
                params.append(val)
        where = " AND ".join(conditions) if conditions else "TRUE"
        return self._fetch_all(
            f"SELECT * FROM sms_chat_segments WHERE {where}",
            tuple(params),
        )

    def find_reviewed(self) -> list[dict]:
        """All segments with true_topic IS NOT NULL (ground truth)."""
        return self._fetch_all(
            "SELECT * FROM sms_chat_segments WHERE true_topic IS NOT NULL"
        )

    def find_with_summary(self) -> list[dict]:
        return self._fetch_all(
            "SELECT * FROM sms_chat_segments WHERE summary IS NOT NULL"
        )

    def distinct_topics(self) -> list[str]:
        rows = self._fetch_all(
            "SELECT DISTINCT topic FROM sms_chat_segments WHERE topic IS NOT NULL"
        )
        return [row["topic"] for row in rows]

    def topic_distribution(self) -> list[dict]:
        return self._fetch_all(
            """
            SELECT topic, COUNT(*) AS segment_count,
                   array_agg(DISTINCT sub_topic) FILTER (WHERE sub_topic IS NOT NULL) AS sub_topics
            FROM sms_chat_segments
            GROUP BY topic
            ORDER BY segment_count DESC
            """
        )

    def avg_label_confidence(self) -> float | None:
        row = self._fetch_one(
            "SELECT AVG(label_confidence) AS avg FROM sms_chat_segments "
            "WHERE label_confidence IS NOT NULL"
        )
        return round(float(row["avg"]), 4) if row["avg"] is not None else None
