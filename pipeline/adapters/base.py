"""Dataset-adapter contract for the universal UFL pipeline.

An adapter normalizes a public bot-human chat corpus into the pipeline's
EXISTING internal message shape — the same dicts that
``pipeline.segmentation.windowing._build_flat_history`` emits today, so the
core segmentation architecture (``_pre_segment``, the LLM segmenter) runs
unchanged on adapted data.

Normalized-message contract
---------------------------
Each adapter produces an ordered ``list[dict]``, one dict per message, sorted
chronologically. Every dict has exactly these keys::

    {
        "_id":       str,       # unique message id (synthetic for public corpora)
        "chat":      str,       # conversation id shared by every message in the chat
        "type":      str,       # one of _USER_FACING_MSG_TYPES (here: "user" | "assistant")
        "message":   str,       # message text content
        "createdAt": datetime,  # per-message timestamp (synthesized when absent)
    }

``type`` must be a user-facing type per ``windowing._USER_FACING_MSG_TYPES``.
The two-role public corpora only ever produce ``"user"`` and ``"assistant"``.

Downstream code calls ``str(m["_id"])`` and ``str(chat["_id"])``; synthetic
string ids are therefore tolerated in place of Mongo ObjectIds.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

_ROLE_MAP: dict[str, str] = {
    "user": "user",
    "human": "user",
    "assistant": "assistant",
    "bot": "assistant",
    "gpt": "assistant",
}


def normalize_role(role: str) -> str:
    """Map a corpus role label to a pipeline message ``type``.

    Recognizes the common two-role vocabularies of public bot-human chat
    corpora (``user``/``human`` -> ``user``, ``assistant``/``bot``/``gpt`` ->
    ``assistant``). Matching is case-insensitive and whitespace-tolerant.

    Raises:
        ValueError: if the role is not a recognized two-role label.
    """
    key = role.strip().lower()
    try:
        return _ROLE_MAP[key]
    except KeyError:
        raise ValueError(f"Unrecognized conversation role: {role!r}") from None


@runtime_checkable
class ConversationLoader(Protocol):
    """A dataset adapter that yields normalized message dicts.

    Implementations read raw corpus rows (already parsed from disk/HF) and
    return ordered normalized message dicts per the contract above. They MUST
    NOT touch MongoDB, PostgreSQL, or any LLM — normalization is pure.
    """

    name: str

    def load_conversation(self, row: dict) -> list[dict]:
        """Normalize one conversation row into ordered message dicts."""
        ...

    def load_conversations(self, rows: list[dict]) -> list[list[dict]]:
        """Normalize many conversation rows, one message list per row."""
        ...
