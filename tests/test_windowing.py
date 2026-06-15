"""Unit tests for windowing and pre-segmentation."""

from datetime import datetime, timedelta, timezone

from pipeline.segmentation.windowing import (
    PreSegmentChunk,
    _build_context_string,
    _pre_segment,
    _trim_to_latest_user,
    _window_messages,
)


class TestWindowMessages:

    def test_small_list_single_window(self):
        msgs = [{"type": "user"}, {"type": "assistant"}]
        result = _window_messages(msgs, window_size=10)
        assert len(result) == 1
        assert result[0] == msgs

    def test_zero_window_size_single_window(self):
        msgs = [{"type": "user"}] * 5
        result = _window_messages(msgs, window_size=0)
        assert len(result) == 1

    def test_splits_at_user_boundary(self):
        msgs = [
            {"type": "user"},
            {"type": "assistant"},
            {"type": "user"},
            {"type": "assistant"},
        ]
        result = _window_messages(msgs, window_size=2)
        assert len(result) == 2
        assert result[0][0]["type"] == "user"
        assert result[1][0]["type"] == "user"

    def test_empty_input(self):
        assert _window_messages([], window_size=5) == []


class TestPreSegment:

    def _msg(self, msg_type, minutes_offset=0):
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes_offset)
        return {"type": msg_type, "createdAt": ts}

    def test_single_user_message(self):
        msgs = [self._msg("user", 0)]
        chunks = _pre_segment(msgs, ["c1"], bot_gap_seconds=60, user_window_days=3)
        assert len(chunks) == 1
        assert chunks[0].kind == "user_engaged"

    def test_bot_only_sequence(self):
        msgs = [self._msg("assistant", 0), self._msg("automated", 1)]
        chunks = _pre_segment(msgs, ["c1", "c1"], bot_gap_seconds=60, user_window_days=3)
        assert len(chunks) == 1
        assert chunks[0].kind == "bot_only"

    def test_bot_then_user_creates_two_chunks(self):
        msgs = [self._msg("assistant", 0), self._msg("user", 5)]
        chunks = _pre_segment(msgs, ["c1", "c1"], bot_gap_seconds=60, user_window_days=3)
        assert len(chunks) == 2
        assert chunks[0].kind == "bot_only"
        assert chunks[1].kind == "user_engaged"
        assert chunks[1].preceding_bot_chunk is chunks[0]

    def test_empty_returns_empty(self):
        assert _pre_segment([], [], bot_gap_seconds=60, user_window_days=3) == []

    def test_bot_gap_splits_chunks(self):
        """Two bot messages with > gap_seconds between them -> 2 bot_only chunks."""
        # 5 min = 300 seconds > 120 second threshold -> split
        msgs = [self._msg("assistant", 0), self._msg("assistant", 5)]
        chunks = _pre_segment(msgs, ["c1", "c1"], bot_gap_seconds=120, user_window_days=3)
        assert len(chunks) == 2
        assert all(c.kind == "bot_only" for c in chunks)


class TestTrimToLatestUser:

    def test_no_trim_when_single_user(self):
        chunk = PreSegmentChunk(
            kind="user_engaged",
            messages=[
                {"type": "user", "createdAt": datetime(2026, 1, 1)},
                {"type": "assistant", "createdAt": datetime(2026, 1, 1, 0, 5)},
            ],
            chat_ids=["c1", "c1"],
        )
        _trim_to_latest_user(chunk)
        assert len(chunk.messages) == 2

    def test_trims_after_reply_window(self):
        chunk = PreSegmentChunk(
            kind="user_engaged",
            messages=[
                {"type": "user", "createdAt": datetime(2026, 1, 1, 0, 0)},
                {"type": "user", "createdAt": datetime(2026, 1, 1, 1, 0)},
                {"type": "assistant", "createdAt": datetime(2026, 1, 1, 1, 5)},
                {"type": "assistant", "createdAt": datetime(2026, 1, 1, 5, 0)},
            ],
            chat_ids=["c1"] * 4,
        )
        _trim_to_latest_user(chunk)
        # Last user at index 1 (1:00), reply at 1:05 within 1 hour
        # Message at 5:00 is 4 hours after last user -> trimmed
        assert len(chunk.messages) == 3


class TestBuildContextString:

    def test_empty_context(self):
        assert _build_context_string("", [], 0) == ""

    def test_appends_new_segments(self):
        new_segs = [{"topic": "onboarding", "sub_topic": "welcome", "summary": "New user"}]
        result = _build_context_string("", new_segs, 0)
        assert "onboarding" in result
        assert "welcome" in result
