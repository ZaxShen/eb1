"""
Deterministic classification rules that bypass the LLM.

Proposal 4: Scheduling segments (Wednesday pool) are classified by position:
  - First scheduling push → scheduling_initiation
  - All subsequent → scheduling_reminder

Proposal 1: Every user's first chat segment is automated onboarding.
  Classify deterministically as onboarding/welcome without LLM.

These rules run BEFORE the LLM is called. When a rule matches, the segment
is built directly — no LLM call is made.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from pipeline.segmentation.windowing import PreSegmentChunk

log = logging.getLogger(__name__)

# ── Scheduling keywords (Proposal 4) ────────────────────────────────────────

_SCHEDULING_KEYWORDS = re.compile(
    r"(schedul|availab|date\s+time|when\s+are\s+you\s+free"
    r"|confirm.*date|reschedul|pick\s+a\s+time|time\s+slot"
    r"|book\s+(a|your)\s+date|set\s+up\s+a\s+date"
    r"|date\s+is\s+(set|confirmed|booked)"
    r"|what\s+time|select.*time)",
    re.IGNORECASE,
)

_SCHEDULING_TOPIC = "scheduling"
_SCHEDULING_INITIATION = "availability_request"
_SCHEDULING_REMINDER = "availability_reminder"

# ── Onboarding keywords (Proposal 1) ────────────────────────────────────────

_ONBOARDING_KEYWORDS = re.compile(
    r"(welcome\s+to|get\s+(started|set\s+up)|profile|sign\s*up"
    r"|onboard|new\s+here|first\s+time|let'?s\s+begin"
    r"|upload\s+(a\s+)?photo|verify\s+your|application)",
    re.IGNORECASE,
)

_ONBOARDING_TOPIC = "onboarding"
_ONBOARDING_SUBTOPIC = "welcome"


def is_scheduling_chunk(chunk: PreSegmentChunk) -> bool:
    """Check if a bot-only chunk is about scheduling.

    A chunk is scheduling-related if ALL messages are non-user (bot_only)
    and at least one message matches scheduling keywords.
    """
    if chunk.kind != "bot_only" or not chunk.messages:
        return False
    return any(
        _SCHEDULING_KEYWORDS.search(m.get("message", ""))
        for m in chunk.messages
    )


def classify_scheduling_chunk(
    user_id: Any,
    chunk: PreSegmentChunk,
    is_first_scheduling: bool,
) -> list[dict]:
    """Build a deterministic scheduling segment.

    is_first_scheduling: True if this user has not had a scheduling segment
    before (→ initiation). False → reminder.
    """
    if not chunk.messages:
        return []

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    first_ts = chunk.messages[0].get("createdAt") or now
    last_ts = chunk.messages[-1].get("createdAt") or now

    sub_topic = _SCHEDULING_INITIATION if is_first_scheduling else _SCHEDULING_REMINDER
    summary = (
        "Bot initiates scheduling for the first time."
        if is_first_scheduling
        else "Bot sends a scheduling reminder."
    )

    log.info(
        "P4: User %s — deterministic scheduling: %s/%s (%d msgs)",
        user_id, _SCHEDULING_TOPIC, sub_topic, len(chunk.messages),
    )

    return [{
        "user_id": str(user_id),
        "chat_id": str(chunk.chat_ids[0]),
        "chat_messages": [str(m["_id"]) for m in chunk.messages],
        "cluster": None,
        "label_confidence": 1.0,
        "topic": _SCHEDULING_TOPIC,
        "sub_topic": sub_topic,
        "true_topic": None,
        "true_sub_topic": None,
        "summary": summary,
        "reviewed_by": None,
        "sentiment": None,
        "has_user_engagement": False,
        "has_bot_failure": False,
        "response_rate": 0.0,
        "chat_started_at": first_ts,
        "chat_ended_at": last_ts,
        "classified_at": now,
        "reviewed_at": None,
    }]


def is_first_automated_chunk(
    chunk: PreSegmentChunk,
    chunk_index: int,
) -> bool:
    """Check if this is the very first chunk for a user and all automated.

    Proposal 1: The first chunk in a user's history is always an automated
    onboarding push. We detect it as: chunk_index == 0, bot_only, and all
    messages are type "automated".
    """
    if chunk_index != 0:
        return False
    if chunk.kind != "bot_only":
        return False
    if not chunk.messages:
        return False
    return all(m.get("type") == "automated" for m in chunk.messages)


def classify_first_automated_chunk(
    user_id: Any,
    chunk: PreSegmentChunk,
) -> list[dict]:
    """Build a deterministic onboarding segment for the first automated chunk.

    Proposal 1: Skip LLM for the first automated segment — always onboarding.
    """
    if not chunk.messages:
        return []

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    first_ts = chunk.messages[0].get("createdAt") or now
    last_ts = chunk.messages[-1].get("createdAt") or now

    # Check if messages match onboarding keywords for higher confidence
    has_onboarding_signal = any(
        _ONBOARDING_KEYWORDS.search(m.get("message", ""))
        for m in chunk.messages
    )

    topic = _ONBOARDING_TOPIC
    sub_topic = _ONBOARDING_SUBTOPIC
    summary = "Automated onboarding push — first segment for this user."

    if not has_onboarding_signal:
        log.debug(
            "P1: User %s — first automated chunk has no onboarding keywords, "
            "classifying as onboarding anyway (position-based rule).",
            user_id,
        )

    log.info(
        "P1: User %s — deterministic first segment: %s/%s (%d msgs)",
        user_id, topic, sub_topic, len(chunk.messages),
    )

    return [{
        "user_id": str(user_id),
        "chat_id": str(chunk.chat_ids[0]),
        "chat_messages": [str(m["_id"]) for m in chunk.messages],
        "cluster": None,
        "label_confidence": 1.0,
        "topic": topic,
        "sub_topic": sub_topic,
        "true_topic": None,
        "true_sub_topic": None,
        "summary": summary,
        "reviewed_by": None,
        "sentiment": None,
        "has_user_engagement": False,
        "has_bot_failure": False,
        "response_rate": 0.0,
        "chat_started_at": first_ts,
        "chat_ended_at": last_ts,
        "classified_at": now,
        "reviewed_at": None,
    }]
