"""
Tests for Proposal 1 (skip first automated segment) and
Proposal 4 (deterministic scheduling rules).

Uses synthetic data — no DB or LLM dependencies.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from bson import ObjectId

from pipeline.segmentation.deterministic_rules import (
    _ONBOARDING_SUBTOPIC,
    _ONBOARDING_TOPIC,
    _SCHEDULING_INITIATION,
    _SCHEDULING_REMINDER,
    _SCHEDULING_TOPIC,
    classify_first_automated_chunk,
    classify_scheduling_chunk,
    is_first_automated_chunk,
    is_scheduling_chunk,
)
from pipeline.segmentation.windowing import PreSegmentChunk

_NOW = datetime(2026, 4, 1, 12, 0, 0)


def _make_msg(msg_type: str = "automated", text: str = "", minutes_offset: int = 0) -> dict:
    return {
        "_id": ObjectId(),
        "type": msg_type,
        "message": text,
        "createdAt": _NOW + timedelta(minutes=minutes_offset),
    }


def _make_chunk(kind: str, messages: list[dict]) -> PreSegmentChunk:
    return PreSegmentChunk(
        kind=kind,
        messages=messages,
        chat_ids=[ObjectId()] * len(messages),
    )


# ── Proposal 4: Scheduling detection ────────────────────────────────────────


class TestIsSchedulingChunk:

    def test_scheduling_keywords_detected(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Hey! When are you free for a date this week?"),
        ])
        assert is_scheduling_chunk(chunk) is True

    def test_availability_keyword(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Please confirm your availability for Saturday."),
        ])
        assert is_scheduling_chunk(chunk) is True

    def test_reschedule_keyword(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Would you like to reschedule your date?"),
        ])
        assert is_scheduling_chunk(chunk) is True

    def test_time_slot_keyword(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Pick a time slot that works for you."),
        ])
        assert is_scheduling_chunk(chunk) is True

    def test_non_scheduling_message(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Welcome to Acme! Let's set up your profile."),
        ])
        assert is_scheduling_chunk(chunk) is False

    def test_user_engaged_chunk_rejected(self):
        chunk = _make_chunk("user_engaged", [
            _make_msg("user", "When is my date scheduled?"),
        ])
        assert is_scheduling_chunk(chunk) is False

    def test_empty_chunk(self):
        chunk = _make_chunk("bot_only", [])
        assert is_scheduling_chunk(chunk) is False

    def test_multiple_messages_one_scheduling(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Hi there!"),
            _make_msg("automated", "Please confirm your date time slot."),
        ])
        assert is_scheduling_chunk(chunk) is True


class TestClassifySchedulingChunk:

    def test_first_scheduling_is_initiation(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "When are you available?", 0),
            _make_msg("automated", "Pick a time.", 1),
        ])
        segs = classify_scheduling_chunk("user123", chunk, is_first_scheduling=True)
        assert len(segs) == 1
        assert segs[0]["topic"] == _SCHEDULING_TOPIC
        assert segs[0]["sub_topic"] == _SCHEDULING_INITIATION
        assert segs[0]["label_confidence"] == 1.0
        assert segs[0]["has_user_engagement"] is False
        assert len(segs[0]["chat_messages"]) == 2

    def test_subsequent_scheduling_is_reminder(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Reminder: pick a time for your date!", 5),
        ])
        segs = classify_scheduling_chunk("user123", chunk, is_first_scheduling=False)
        assert len(segs) == 1
        assert segs[0]["topic"] == _SCHEDULING_TOPIC
        assert segs[0]["sub_topic"] == _SCHEDULING_REMINDER

    def test_empty_chunk_returns_empty(self):
        chunk = _make_chunk("bot_only", [])
        segs = classify_scheduling_chunk("user123", chunk, is_first_scheduling=True)
        assert segs == []

    def test_timestamps_from_messages(self):
        msgs = [
            _make_msg("automated", "Schedule your date", 0),
            _make_msg("automated", "Pick a time", 10),
        ]
        chunk = _make_chunk("bot_only", msgs)
        segs = classify_scheduling_chunk("user123", chunk, is_first_scheduling=True)
        assert segs[0]["chat_started_at"] == msgs[0]["createdAt"]
        assert segs[0]["chat_ended_at"] == msgs[1]["createdAt"]


# ── Proposal 1: First automated segment ─────────────────────────────────────


class TestIsFirstAutomatedChunk:

    def test_first_all_automated_chunk(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Welcome to Acme!"),
        ])
        assert is_first_automated_chunk(chunk, chunk_index=0) is True

    def test_not_first_chunk(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Welcome to Acme!"),
        ])
        assert is_first_automated_chunk(chunk, chunk_index=1) is False

    def test_user_engaged_chunk_rejected(self):
        chunk = _make_chunk("user_engaged", [
            _make_msg("user", "Hello"),
        ])
        assert is_first_automated_chunk(chunk, chunk_index=0) is False

    def test_mixed_types_rejected(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Welcome!"),
            _make_msg("assistant", "How can I help?"),
        ])
        assert is_first_automated_chunk(chunk, chunk_index=0) is False

    def test_empty_chunk_rejected(self):
        chunk = _make_chunk("bot_only", [])
        assert is_first_automated_chunk(chunk, chunk_index=0) is False


class TestClassifyFirstAutomatedChunk:

    def test_basic_onboarding_classification(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Welcome to Acme! Let's get started.", 0),
            _make_msg("automated", "Please upload a photo.", 1),
        ])
        segs = classify_first_automated_chunk("user456", chunk)
        assert len(segs) == 1
        assert segs[0]["topic"] == _ONBOARDING_TOPIC
        assert segs[0]["sub_topic"] == _ONBOARDING_SUBTOPIC
        assert segs[0]["label_confidence"] == 1.0
        assert segs[0]["has_user_engagement"] is False
        assert segs[0]["response_rate"] == 0.0
        assert len(segs[0]["chat_messages"]) == 2

    def test_non_onboarding_content_still_classified(self):
        """Even without onboarding keywords, first segment is onboarding by position."""
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Hello there, something random.", 0),
        ])
        segs = classify_first_automated_chunk("user456", chunk)
        assert len(segs) == 1
        assert segs[0]["topic"] == _ONBOARDING_TOPIC

    def test_empty_chunk_returns_empty(self):
        chunk = _make_chunk("bot_only", [])
        segs = classify_first_automated_chunk("user456", chunk)
        assert segs == []

    def test_segment_has_all_required_fields(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Welcome!", 0),
        ])
        segs = classify_first_automated_chunk("user456", chunk)
        seg = segs[0]
        required = {
            "user_id", "chat_id", "chat_messages", "cluster",
            "label_confidence", "topic", "sub_topic", "true_topic",
            "true_sub_topic", "summary", "reviewed_by", "sentiment",
            "has_user_engagement", "has_bot_failure", "response_rate",
            "chat_started_at", "chat_ended_at", "classified_at", "reviewed_at",
        }
        assert required.issubset(set(seg.keys()))

    def test_user_id_is_string(self):
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Welcome!", 0),
        ])
        user_id = ObjectId()
        segs = classify_first_automated_chunk(user_id, chunk)
        assert segs[0]["user_id"] == str(user_id)


# ── Integration: P1 + P4 ordering ───────────────────────────────────────────


class TestP1P4Interaction:

    def test_first_scheduling_chunk_p1_takes_priority(self):
        """If the first chunk is automated AND scheduling, P1 wins (onboarding)."""
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Welcome! When are you available for a date?"),
        ])
        # P1 check runs first in the pipeline
        assert is_first_automated_chunk(chunk, chunk_index=0) is True
        # But it's also scheduling
        assert is_scheduling_chunk(chunk) is True
        # In the actual pipeline, P1 runs first → classified as onboarding
        segs = classify_first_automated_chunk("user789", chunk)
        assert segs[0]["topic"] == _ONBOARDING_TOPIC

    def test_second_scheduling_chunk_p4_handles(self):
        """Non-first scheduling chunks are handled by P4."""
        chunk = _make_chunk("bot_only", [
            _make_msg("automated", "Reminder: schedule your date!", 10),
        ])
        assert is_first_automated_chunk(chunk, chunk_index=1) is False
        assert is_scheduling_chunk(chunk) is True
        segs = classify_scheduling_chunk("user789", chunk, is_first_scheduling=False)
        assert segs[0]["topic"] == _SCHEDULING_TOPIC
        assert segs[0]["sub_topic"] == _SCHEDULING_REMINDER
