"""SuperDialseg dataset adapter.

Normalizes SuperDialseg dialogues into the pipeline's internal message shape
(see ``pipeline.adapters.base`` for the contract). SuperDialseg dialogues
carry::

    {
        "dialogue_id": str,
        "utterances":  [{"speaker": "User"|"Agent", "text": str,
                         "segment_id": int|str}, ...],
    }

SuperDialseg roles map ``User -> user`` and ``Agent -> assistant`` (handled by
``normalize_role``). It has no per-turn timestamps, so per-message ``createdAt``
is synthesized from the Unix epoch plus the message index (+i seconds) to
preserve chronological ordering, exactly as ``WildChatLoader`` does. Synthetic
string ids replace Mongo ObjectIds: ``dialogue_id`` is the chat id and
``f"{dialogue_id}:{i}"`` is each message ``_id``.

SuperDialseg's distinguishing value is its GOLD segmentation: each utterance
carries a ``segment_id``, and a topical segment is a maximal run of consecutive
utterances sharing the same ``segment_id``. :meth:`SuperDialsegLoader.gold_segments`
recovers those spans as the reliable-label anchor.

This module performs NO MongoDB / PostgreSQL / LLM access.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# SuperDialseg's two speakers. "Agent" is not a universal role alias, so the
# adapter maps its corpus-specific vocabulary locally rather than through the
# shared ``normalize_role`` (which covers user/human/assistant/bot/gpt).
_ROLE_MAP: dict[str, str] = {"user": "user", "agent": "assistant"}


def _normalize_speaker(speaker: str) -> str:
    """Map a SuperDialseg speaker (User/Agent) to a pipeline message ``type``."""
    key = speaker.strip().lower()
    try:
        return _ROLE_MAP[key]
    except KeyError:
        raise ValueError(f"Unrecognized SuperDialseg speaker: {speaker!r}") from None


class SuperDialsegLoader:
    """Adapter from SuperDialseg dialogues to normalized pipeline message dicts."""

    name = "superdialseg"

    def load_conversation(self, dialogue: dict) -> list[dict]:
        """Normalize one SuperDialseg dialogue into ordered message dicts.

        Returns an ordered ``list[dict]`` with keys
        ``{_id, chat, type, message, createdAt}``. Message ``type`` is in
        ``{"user", "assistant"}`` (User -> user, Agent -> assistant);
        ``createdAt`` is synthesized as ``epoch + i seconds`` for index ``i``.
        """
        chat_id = str(dialogue["dialogue_id"])

        messages: list[dict] = []
        for i, utt in enumerate(dialogue.get("utterances") or []):
            messages.append({
                "_id": f"{chat_id}:{i}",
                "chat": chat_id,
                "type": _normalize_speaker(utt["speaker"]),
                "message": utt.get("text") or "",
                "createdAt": _EPOCH + timedelta(seconds=i),
            })
        return messages

    def load_conversations(self, dialogues: list[dict]) -> list[list[dict]]:
        """Normalize many SuperDialseg dialogues, one message list per dialogue."""
        return [self.load_conversation(d) for d in dialogues]

    def gold_segments(self, dialogue: dict) -> list[dict]:
        """Recover gold topical segments from a SuperDialseg dialogue.

        A gold segment is a maximal run of consecutive utterances sharing the
        same ``segment_id``. Returns an ordered ``list[dict]``, one per span::

            {"conversation": str, "segment_id": <id>, "message_indices": [int]}

        ``message_indices`` are positions in the dialogue's utterance order, so
        they align with the normalized message stream from
        :meth:`load_conversation`.
        """
        chat_id = str(dialogue["dialogue_id"])
        utterances = dialogue.get("utterances") or []

        spans: list[dict] = []
        current: dict | None = None
        for i, utt in enumerate(utterances):
            seg_id = utt["segment_id"]
            if current is None or seg_id != current["segment_id"]:
                current = {
                    "conversation": chat_id,
                    "segment_id": seg_id,
                    "message_indices": [i],
                }
                spans.append(current)
            else:
                current["message_indices"].append(i)
        return spans
