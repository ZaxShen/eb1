"""
Windowing and pre-segmentation utilities for the segmenter pipeline.

Extracted from segmenter.py to keep the module focused on orchestration.
This module owns:
  - PreSegmentChunk dataclass
  - Message filtering constants (_USER_FACING_MSG_TYPES, _REPLY_WINDOW)
  - Flat history construction (_build_flat_history)
  - Pre-segmentation logic (_pre_segment, _trim_to_latest_user)
  - Windowing helpers (_window_messages, _window_chat_ids)
  - Context loading helpers (_load_previous_segments, _build_context_string)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pymongo.database import Database

from pipeline.config.loader import AnalyzerConfig

log = logging.getLogger(__name__)


# ── Pre-segmentation dataclass ────────────────────────────────────────────────


@dataclass
class PreSegmentChunk:
    """A chunk of messages identified by the deterministic pre-segmenter.

    kind: "bot_only" — consecutive non-user messages with no following user response
          "user_engaged" — user message + all messages within user_window_days
    messages: list of message dicts (same format as _build_flat_history output)
    chat_ids: parallel list of chat ObjectIds (same length as messages)
    preceding_bot_chunk: reference to the immediately preceding bot-only chunk,
                         or None. Only set on user_engaged chunks. Used to send
                         bot context to the LLM.
    """

    kind: str  # "bot_only" or "user_engaged"
    messages: list[dict] = field(default_factory=list)
    chat_ids: list[Any] = field(default_factory=list)
    preceding_bot_chunk: "PreSegmentChunk | None" = None


# ── Constants ─────────────────────────────────────────────────────────────────

_USER_FACING_MSG_TYPES = ["user", "assistant", "automated", "team"]

_REPLY_WINDOW = timedelta(hours=1)
"""Max time after the latest user message for a non-user message to count as
a direct reply.  Messages beyond this gap are stale bot noise and get trimmed
back into bot-only scanning."""


# ── Flat history construction ─────────────────────────────────────────────────


def _build_flat_history(
    input_db: Database, chat: dict, cfg: AnalyzerConfig
) -> tuple[list[dict], list[Any]]:
    """Fetch all user-facing messages for the sms_chats document, sorted by createdAt.

    Includes: user, assistant, automated, team, and system messages whose content
    is "[Tool Call] noReply" (conversation-ending boundary signal for the Analyzer).
    Excludes: all other system messages, admin (email verifications).

    Deduplicates by _id to guard against PROD duplicates (Bug 2 — Phase 2a).
    """
    msgs = list(
        input_db[cfg.col_input_chat_message]
        .find({
            "chat": chat["_id"],
            "$or": [
                {"type": {"$in": _USER_FACING_MSG_TYPES}},
                {"type": "system", "message": "[Tool Call] noReply"},
            ],
        })
        .sort("createdAt", 1)
    )
    # Deduplicate by _id (preserves order since msgs is already sorted)
    seen: set = set()
    unique_msgs: list[dict] = []
    for m in msgs:
        if m["_id"] not in seen:
            seen.add(m["_id"])
            unique_msgs.append(m)
    if len(unique_msgs) < len(msgs):
        log.warning(
            "Chat %s had %d duplicate message IDs (removed). %d unique remain.",
            chat["_id"], len(msgs) - len(unique_msgs), len(unique_msgs),
        )
    msgs = unique_msgs

    # Deduplicate bot messages with identical content within a short window.
    # PROD sometimes inserts the same message as both automated + assistant
    # with slightly different timestamps (~0.5-1 s apart).  For each non-user
    # message, we check whether a message with the same content was already
    # seen within the last 2 seconds — if so, it's a duplicate regardless of
    # type.  User messages are never deduped (a user may legitimately send
    # the same text twice).
    _DEDUP_WINDOW_SECS = 2
    before_content_dedup = len(msgs)
    content_deduped: list[dict] = []
    # Track (content, timestamp) of recently seen non-user messages
    recent_bot: list[tuple[str | None, datetime | None]] = []
    for m in msgs:
        if m.get("type") == "user":
            content_deduped.append(m)
            continue
        text = m.get("message")
        ts = m.get("createdAt")
        is_dup = False
        if ts is not None:
            for prev_text, prev_ts in recent_bot:
                if (
                    prev_text == text
                    and prev_ts is not None
                    and abs((ts - prev_ts).total_seconds()) <= _DEDUP_WINDOW_SECS
                ):
                    is_dup = True
                    break
        if is_dup:
            continue
        content_deduped.append(m)
        recent_bot.append((text, ts))
        # Prune entries outside the dedup window to prevent O(n²) growth
        if ts is not None:
            cutoff = ts - timedelta(seconds=_DEDUP_WINDOW_SECS)
            recent_bot = [(t, s) for t, s in recent_bot if s is None or s >= cutoff]
    if len(content_deduped) < before_content_dedup:
        log.info(
            "Chat %s: removed %d duplicate bot messages "
            "(same content within %ds). %d remain.",
            chat["_id"],
            before_content_dedup - len(content_deduped),
            _DEDUP_WINDOW_SECS,
            len(content_deduped),
        )
    msgs = content_deduped

    # Repeat the chat_id for every message so downstream code stays compatible
    chat_ids = [chat["_id"]] * len(msgs)
    return msgs, chat_ids


# ── Pre-segmentation ──────────────────────────────────────────────────────────


def _trim_to_latest_user(chunk: PreSegmentChunk) -> None:
    """Trim a user-engaged chunk to the latest user message + immediate replies.

    After collecting all messages within the window, find the last user
    message (excluding the anchor at index 0).  If additional user messages
    exist (index > 0), keep only the direct replies that follow — non-user
    messages within ``_REPLY_WINDOW`` of the latest user message's timestamp.
    Anything beyond that is stale bot noise and is discarded (it re-enters
    bot-only scanning in the outer loop).

    If there are no additional user messages beyond the anchor, the chunk is
    left unchanged (full window kept).
    """
    msgs = chunk.messages
    if len(msgs) <= 1:
        return  # only the anchor — nothing to trim

    # Find the index of the last user message (skip index 0 = anchor)
    last_user_idx = 0
    for idx in range(1, len(msgs)):
        if msgs[idx].get("type") == "user":
            last_user_idx = idx

    if last_user_idx == 0:
        return  # no additional user messages — keep full window

    # Keep: everything up to last user message + replies within 1 hour.
    last_user_ts = msgs[last_user_idx].get("createdAt")
    trim_end = last_user_idx + 1
    while trim_end < len(msgs):
        curr_ts = msgs[trim_end].get("createdAt")
        if last_user_ts is not None and curr_ts is not None:
            if (curr_ts - last_user_ts) > _REPLY_WINDOW:
                break  # beyond reply window — stale bot messages
        trim_end += 1

    chunk.messages = msgs[:trim_end]
    chunk.chat_ids = chunk.chat_ids[:trim_end]


def _pre_segment(
    messages: list[dict],
    chat_ids: list[Any],
    bot_gap_seconds: int = 60,
    user_window_days: int = 3,
) -> list[PreSegmentChunk]:
    """Split messages into bot-only and user-engaged chunks.

    Walk messages chronologically:
    - Non-user messages accumulate into bot-only chunks. A gap exceeding
      bot_gap_seconds between consecutive non-user messages starts a new chunk.
    - When a user message is encountered, close the open bot-only chunk (linking
      it as preceding context) and start a user-engaged chunk that collects all
      messages within user_window_days of the first triggering user message.
    - After the window is collected, it is trimmed: if additional user messages
      exist beyond the anchor, the chunk ends at the latest user message + its
      trailing non-user replies.  Trimmed messages re-enter bot-only scanning.
    - After the window expires (or is trimmed), resume bot-only scanning.

    Returns an ordered list of PreSegmentChunk covering ALL messages exactly once.
    """
    if not messages:
        return []

    chunks: list[PreSegmentChunk] = []
    gap_delta = timedelta(seconds=bot_gap_seconds)
    window_delta = timedelta(days=user_window_days)

    i = 0
    n = len(messages)
    last_bot_chunk: PreSegmentChunk | None = None

    while i < n:
        msg = messages[i]

        if msg.get("type") != "user":
            # ── Bot-only accumulation ──
            if last_bot_chunk is None:
                last_bot_chunk = PreSegmentChunk(kind="bot_only")

            # Check gap with previous message in the current bot-only chunk
            if last_bot_chunk.messages:
                prev_ts = last_bot_chunk.messages[-1].get("createdAt")
                curr_ts = msg.get("createdAt")
                if prev_ts is not None and curr_ts is not None:
                    if (curr_ts - prev_ts) > gap_delta:
                        # Gap exceeded — close current bot-only chunk, start new
                        chunks.append(last_bot_chunk)
                        last_bot_chunk = PreSegmentChunk(kind="bot_only")

            last_bot_chunk.messages.append(msg)
            last_bot_chunk.chat_ids.append(chat_ids[i])
            i += 1

        else:
            # ── User-engaged trigger ──
            # Close any open bot-only chunk and link it as preceding context
            preceding = last_bot_chunk
            if preceding is not None:
                chunks.append(preceding)
                last_bot_chunk = None

            # Start user-engaged chunk anchored to this user message's timestamp
            anchor_ts = msg.get("createdAt")
            engaged = PreSegmentChunk(
                kind="user_engaged",
                preceding_bot_chunk=preceding,
            )
            engaged.messages.append(msg)
            engaged.chat_ids.append(chat_ids[i])
            i += 1

            # Collect all following messages within the window
            while i < n:
                next_ts = messages[i].get("createdAt")
                if anchor_ts is not None and next_ts is not None:
                    if (next_ts - anchor_ts) > window_delta:
                        break  # Window expired
                # Within window (or missing timestamps — keep to avoid data loss)
                engaged.messages.append(messages[i])
                engaged.chat_ids.append(chat_ids[i])
                i += 1

            # Trim window: if additional user messages exist inside the
            # window, cut to the latest user message + its trailing replies
            # (non-user messages after it, still within the window).
            # This avoids sending stale bot messages to the LLM when the
            # user stopped engaging mid-window.
            pre_trim = len(engaged.messages)
            _trim_to_latest_user(engaged)
            trimmed = pre_trim - len(engaged.messages)
            i -= trimmed  # rewind so trimmed messages become next bot-only

            chunks.append(engaged)

    # Flush any trailing bot-only chunk
    if last_bot_chunk is not None:
        chunks.append(last_bot_chunk)

    return chunks


# ── Windowing helpers ─────────────────────────────────────────────────────────


def _window_split_indices(messages: list[dict], window_size: int) -> list[int]:
    """Return the start indices for each window boundary.

    Splits at the nearest user-message boundary at or after each nominal
    split point. If no user message follows a split point, the remainder
    becomes one final window.

    Returns a list of start indices (always starts with 0). An empty list
    is returned when windowing is not needed (window_size <= 0 or too few
    messages).
    """
    n = len(messages)
    if window_size <= 0 or n <= window_size:
        return []

    starts: list[int] = []
    start = 0

    while start < n:
        starts.append(start)
        nominal_end = start + window_size
        if nominal_end >= n:
            break

        split_at = nominal_end
        while split_at < n and messages[split_at].get("type") != "user":
            split_at += 1

        if split_at >= n:
            break

        start = split_at

    return starts


def _window_messages(
    messages: list[dict], window_size: int
) -> list[list[dict]]:
    """Split messages into windows of approximately window_size.

    If window_size <= 0 or len(messages) <= window_size, returns [messages].
    Otherwise, splits at the nearest user-message boundary to avoid
    cutting mid-conversation-turn.

    A window boundary is placed at the first "user"-type message at or after
    each nominal split point (i * window_size). If no user message follows a
    split point, the remainder becomes its own final window.
    """
    if not messages:
        return []

    starts = _window_split_indices(messages, window_size)
    if not starts:
        return [messages]

    n = len(messages)
    windows: list[list[dict]] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else n
        windows.append(messages[start:end])
    return windows


def _window_chat_ids(
    chat_ids: list[Any],
    messages: list[dict],
    window_size: int,
) -> list[list[Any]]:
    """Return chat_id sub-lists that mirror the windows produced by _window_messages.

    Uses the same boundary logic so the two lists stay aligned.
    """
    if not chat_ids:
        return []

    starts = _window_split_indices(messages, window_size)
    if not starts:
        return [chat_ids]

    n = len(messages)
    result: list[list[Any]] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else n
        result.append(chat_ids[start:end])
    return result


# ── Context loading helpers ───────────────────────────────────────────────────


def _load_previous_segments(
    segment_repo, user_id: Any, cfg: AnalyzerConfig
) -> str:
    """Load existing segment summaries for a user as a context string.

    Queries sms_chat_segments for this user, sorted by chat_started_at.
    Returns a formatted '## Active Topics' block, or empty string when no
    segments exist.

    Example output (when segments exist):

        ## Active Topics (from previous windows)
        - match_discussion / getting_to_know_match: "User asked about hobbies"
        - technical_issue / scheduling_bug: "User reported calendar not syncing" (messages 3-4)

    """
    docs = segment_repo.find_by_user(str(user_id))

    if not docs:
        return ""

    lines = ["## Active Topics (from previous windows)"]
    for doc in docs:
        topic = doc.get("topic") or "unknown"
        sub_topic = doc.get("sub_topic") or "unknown"
        summary = doc.get("summary") or ""
        lines.append(f'- {topic} / {sub_topic}: "{summary}"')

    return "\n".join(lines) + "\n\n"


def _build_context_string(
    existing_context: str,
    new_segments: list[dict],
    offset: int,
) -> str:
    """Append new window's segment summaries to the running context string.

    Produces an updated '## Active Topics' block that merges the existing
    context with summaries from the most recent window.  The offset is the
    global message-index base for the current window (used in descriptions
    only; the LLM sees 0-based indices within each window).
    """
    lines: list[str] = []

    # Strip the existing header so we don't duplicate it
    header = "## Active Topics (from previous windows)"
    body = existing_context
    if body.startswith(header):
        body = body[len(header):].lstrip("\n")

    # Re-emit existing lines
    if body.strip():
        existing_lines = [ln for ln in body.splitlines() if ln.strip()]
        lines.extend(existing_lines)

    # Append summaries from the new window
    for seg in new_segments:
        topic = seg.get("topic") or "unknown"
        sub_topic = seg.get("sub_topic") or "unknown"
        summary = seg.get("summary") or ""
        lines.append(f'- {topic} / {sub_topic}: "{summary}"')

    if not lines:
        return ""

    return header + "\n" + "\n".join(lines) + "\n\n"
