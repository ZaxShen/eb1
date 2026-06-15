"""WildChat dataset adapter.

Normalizes WildChat conversation rows into the pipeline's internal message
shape (see ``pipeline.adapters.base`` for the contract). WildChat rows carry::

    {
        "conversation_hash": str,
        "model":             str,
        "timestamp":         datetime | str,   # conversation-level only
        "turn":              int,
        "language":          str,
        "conversation":      [{"role": "user"|"assistant", "content": str}, ...],
    }

WildChat has no per-turn timestamps, so per-message ``createdAt`` is synthesized
from the conversation-level ``timestamp`` plus the message index (+i seconds) to
preserve chronological ordering and gap logic. Synthetic string ids replace
Mongo ObjectIds: ``conversation_hash`` is the chat id and ``f"{hash}:{i}"`` is
each message ``_id``.

This module performs NO MongoDB / PostgreSQL / LLM access.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pipeline.adapters.base import normalize_role


def _coerce_timestamp(value) -> datetime:
    """Return a datetime for the conversation-level timestamp.

    Accepts a datetime, an ISO-8601 string (with optional trailing 'Z'), or a
    Unix epoch number. Falls back to the Unix epoch when absent/unparseable so
    ordering stays well-defined.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


class WildChatLoader:
    """Adapter from WildChat rows to normalized pipeline message dicts."""

    name = "wildchat"

    def load_conversation(self, row: dict) -> list[dict]:
        """Normalize one WildChat row into ordered message dicts.

        Returns an ordered ``list[dict]`` with keys
        ``{_id, chat, type, message, createdAt}``. Message ``type`` is in
        ``{"user", "assistant"}``; ``createdAt`` is synthesized as
        ``conversation timestamp + i seconds`` for message index ``i``.
        """
        chat_id = str(row["conversation_hash"])
        base_ts = _coerce_timestamp(row.get("timestamp"))

        messages: list[dict] = []
        for i, turn in enumerate(row.get("conversation") or []):
            messages.append({
                "_id": f"{chat_id}:{i}",
                "chat": chat_id,
                "type": normalize_role(turn["role"]),
                "message": turn.get("content") or "",
                "createdAt": base_ts + timedelta(seconds=i),
            })
        return messages

    def load_conversations(self, rows: list[dict]) -> list[list[dict]]:
        """Normalize many WildChat rows, one message list per row."""
        return [self.load_conversation(row) for row in rows]
