"""LMSYS-Chat-1M dataset adapter.

Normalizes LMSYS conversation rows into the pipeline's internal message shape
(see ``pipeline.adapters.base`` for the contract). LMSYS rows carry::

    {
        "conversation_id": str,
        "model":           str,
        "conversation":    [{"role": "user"|"assistant", "content": str}, ...],
    }

LMSYS has no per-turn timestamps, so per-message ``createdAt`` is synthesized
from the Unix epoch plus the message index (+i seconds) to preserve
chronological ordering and gap logic, exactly as ``WildChatLoader`` does.
Synthetic string ids replace Mongo ObjectIds: ``conversation_id`` is the chat id
and ``f"{conversation_id}:{i}"`` is each message ``_id``.

This module performs NO MongoDB / PostgreSQL / LLM access.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pipeline.adapters.base import normalize_role

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class LMSYSLoader:
    """Adapter from LMSYS-Chat-1M rows to normalized pipeline message dicts."""

    name = "lmsys"

    def load_conversation(self, row: dict) -> list[dict]:
        """Normalize one LMSYS row into ordered message dicts.

        Returns an ordered ``list[dict]`` with keys
        ``{_id, chat, type, message, createdAt}``. Message ``type`` is in
        ``{"user", "assistant"}``; ``createdAt`` is synthesized as
        ``epoch + i seconds`` for message index ``i``.
        """
        chat_id = str(row["conversation_id"])

        messages: list[dict] = []
        for i, turn in enumerate(row.get("conversation") or []):
            messages.append({
                "_id": f"{chat_id}:{i}",
                "chat": chat_id,
                "type": normalize_role(turn["role"]),
                "message": turn.get("content") or "",
                "createdAt": _EPOCH + timedelta(seconds=i),
            })
        return messages

    def load_conversations(self, rows: list[dict]) -> list[list[dict]]:
        """Normalize many LMSYS rows, one message list per row."""
        return [self.load_conversation(row) for row in rows]
