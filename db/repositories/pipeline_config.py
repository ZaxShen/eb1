"""Pipeline config repository — eb1_pipeline_configs table."""

from __future__ import annotations

import logging
import re

from db.repositories.base import BaseRepository

log = logging.getLogger(__name__)


def _normalize_prompt(value: str) -> str:
    """Normalize prompt name to short form (e.g. 'v3', 'v1').

    Handles:
      'v3'                  → 'v3'
      'latest'              → 'latest' (resolved elsewhere)
      'eb1_prompt_user_v3'  → 'v3'
      'eb1_prompt_bot_v1'   → 'v1'
      'bot_v1'              → 'v1'
    """
    m = re.match(r"^eb1_prompt_(?:user|bot)_(v\d+)$", value)
    if m:
        return m.group(1)
    if value.startswith("bot_"):
        return value[4:]
    return value


class PipelineConfigRepository(BaseRepository):

    def get_or_create(
        self,
        model: str,
        user_prompt: str,
        bot_prompt: str,
        temperature: float = 0.0,
    ) -> int:
        """Return config_id for the given combination, creating if needed.

        Prompt names are normalized to short form (e.g. 'v3', 'v1')
        so that 'eb1_prompt_user_v3' and 'v3' resolve to the same row.
        """
        user_prompt = _normalize_prompt(user_prompt)
        bot_prompt = _normalize_prompt(bot_prompt)
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO eb1_pipeline_configs (model, user_prompt, bot_prompt, temperature)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (model, user_prompt, bot_prompt, temperature) DO NOTHING
                """,
                (model, user_prompt, bot_prompt, temperature),
            )
            row = conn.execute(
                """
                SELECT id FROM eb1_pipeline_configs
                WHERE model = %s AND user_prompt = %s AND bot_prompt = %s AND temperature = %s
                """,
                (model, user_prompt, bot_prompt, temperature),
            ).fetchone()
            conn.commit()
            return row["id"]

    def find_by_id(self, config_id: int) -> dict | None:
        return self._fetch_one(
            "SELECT * FROM eb1_pipeline_configs WHERE id = %s",
            (config_id,),
        )
