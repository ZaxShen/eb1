"""
Bot-only segment processing utilities.

Contains pure and DB-read-only functions for matching bot-only message chunks
against classified templates and building sms_chat_segments documents without
LLM involvement.

These functions have no dependency on the LLM or on segmenter internals, making
them independently testable.
"""

import difflib
import logging
from datetime import datetime, timezone
from typing import Any

from pipeline.segmentation.preprocessing import _normalize_slug
from pipeline.segmentation.windowing import PreSegmentChunk

log = logging.getLogger(__name__)


def _load_template_classifications(
    template_repo,
) -> list[dict]:
    """Load all classified templates from PG for bot-only matching.

    Called once at segmenter startup; the result is read-only and shared
    across worker threads.

    Returns list of {topic, sub_topic, summary, messages: list[str]}.
    """
    rows = template_repo.find_all()
    return [
        {
            "topic": _normalize_slug(str(row.get("topic_slug") or "")),
            "sub_topic": _normalize_slug(str(row.get("subtopic_slug") or "")),
            "summary": row.get("summary"),
            "messages": row.get("messages") or [],
        }
        for row in rows
        if row.get("topic_slug") and row.get("messages")
    ]


def _match_template(
    chunk_messages: list[dict],
    templates: list[dict],
    threshold: float = 0.8,
) -> dict | None:
    """Match automated messages in a bot-only chunk against classified templates.

    For each message with type == "automated", compares its text against every
    template's individual messages using difflib.SequenceMatcher.  Tracks the
    best-matching template across all automated messages in the chunk.

    Returns {topic, sub_topic, summary} from the best-matched template if the
    best similarity ratio >= threshold.  Returns None otherwise.
    """
    if not templates:
        return None

    best_ratio = 0.0
    best_template: dict | None = None

    for msg in chunk_messages:
        if msg.get("type") != "automated":
            continue
        msg_text = msg.get("message", "")
        if not msg_text:
            continue

        for tmpl in templates:
            for tmpl_msg in tmpl["messages"]:
                ratio = difflib.SequenceMatcher(
                    None, msg_text, tmpl_msg,
                ).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_template = tmpl

    if best_ratio >= threshold and best_template is not None:
        return {
            "topic": _normalize_slug(str(best_template["topic"] or "")),
            "sub_topic": _normalize_slug(str(best_template["sub_topic"] or "")),
            "summary": best_template["summary"],
        }
    return None


def _build_bot_only_segments(
    user_id: Any,
    chunk: PreSegmentChunk,
    templates: list[dict] | None = None,
    template_match_threshold: float = 0.8,
) -> list[dict]:
    """Build an sms_chat_segments document from a bot-only chunk.

    When *templates* is provided (from _load_template_classifications),
    attempts to match automated messages against known templates using
    difflib similarity.  Matched segments get topic/subTopic/summary
    filled; unmatched segments keep null classification fields.

    Returns a list with one segment dict (hasUserEngagement=False).
    Wrapped in a list for consistency with _build_segments_from_llm.
    """
    if not chunk.messages:
        return []

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    first_ts = chunk.messages[0].get("createdAt") or now
    last_ts = chunk.messages[-1].get("createdAt") or now

    # Attempt template matching for classification
    match = None
    if templates:
        match = _match_template(
            chunk.messages, templates, template_match_threshold,
        )

    seg: dict = {
        # — identity —
        "user_id": str(user_id),
        "chat_id": str(chunk.chat_ids[0]),
        "chat_messages": [str(m["_id"]) for m in chunk.messages],
        # — confidence —
        "cluster": None,
        "label_confidence": 1.0,  # bot-only — deterministic confidence
        # — labels —
        "topic": match["topic"] if match and match.get("topic") else None,
        "sub_topic": match["sub_topic"] if match and match.get("sub_topic") else None,
        "true_topic": None,
        "true_sub_topic": None,
        "summary": match["summary"] if match else None,
        # — review —
        "reviewed_by": None,
        # — sentiment —
        "sentiment": None,
        # — engagement —
        "has_user_engagement": False,
        "has_bot_failure": False,
        "response_rate": 0.0,  # bot-only — no user engagement
        # — timestamps —
        "chat_started_at": first_ts,
        "chat_ended_at": last_ts,
        "classified_at": now if match else None,
        "reviewed_at": None,
    }
    return [seg]
