"""Tests for _pre_segment and _build_bot_only_segments in segmenter."""

from datetime import datetime, timedelta

from pipeline.segmentation.bot_processor import _build_bot_only_segments
from pipeline.segmentation.windowing import PreSegmentChunk, _pre_segment

# ── Helpers ───────────────────────────────────────────────────────────────────


def _msg(msg_type: str, seconds_offset: int, base: datetime | None = None) -> dict:
    """Create a minimal message dict with type and createdAt."""
    base = base or datetime(2026, 1, 15)
    return {
        "_id": f"{msg_type}_{seconds_offset}",
        "type": msg_type,
        "createdAt": base + timedelta(seconds=seconds_offset),
        "message": f"{msg_type} at +{seconds_offset}s",
    }


def _assert_no_loss(chunks: list[PreSegmentChunk], total: int) -> None:
    """Assert every message appears in exactly one chunk (no loss, no duplication)."""
    all_ids = []
    for c in chunks:
        all_ids.extend(m["_id"] for m in c.messages)
    assert len(all_ids) == total, f"Expected {total} messages, got {len(all_ids)}"
    assert len(set(all_ids)) == total, "Duplicate message IDs found"


# ── Bot-only gap splitting ────────────────────────────────────────────────────


class TestBotOnlyGapSplitting:
    def test_split_by_60s_gap(self):
        """5 non-user msgs: 0-2 within 30s, then 3-4 at +120s. Expect 2 bot chunks."""
        msgs = [
            _msg("automated", 0),
            _msg("automated", 10),
            _msg("automated", 20),
            _msg("automated", 120),  # >60s gap from msg at +20s
            _msg("automated", 130),
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        assert len(chunks) == 2
        assert chunks[0].kind == "bot_only"
        assert chunks[1].kind == "bot_only"
        assert len(chunks[0].messages) == 3
        assert len(chunks[1].messages) == 2
        _assert_no_loss(chunks, 5)

    def test_no_split_within_gap(self):
        """All non-user msgs within 60s. Expect 1 bot chunk."""
        msgs = [
            _msg("automated", 0),
            _msg("assistant", 10),
            _msg("team", 50),
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        assert len(chunks) == 1
        assert chunks[0].kind == "bot_only"
        assert len(chunks[0].messages) == 3


# ── User-engaged window ──────────────────────────────────────────────────────


class TestUserEngagedWindow:
    def test_collects_3_days(self):
        """Bot msgs, user msg, then msgs within 3 days, then msg after 3 days."""
        day = 86400  # seconds in a day
        msgs = [
            _msg("automated", 0),           # bot-only chunk
            _msg("automated", 10),
            _msg("user", day),              # user-engaged trigger at day 1
            _msg("assistant", day + 100),   # within 3-day window
            _msg("automated", day * 3),     # within 3-day window (day 3)
            _msg("automated", day * 5),     # outside 3-day window (day 5 > day 1 + 3)
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        # Expect: bot-only(2 msgs), user-engaged(3 msgs), bot-only(1 msg)
        assert len(chunks) == 3
        assert chunks[0].kind == "bot_only"
        assert len(chunks[0].messages) == 2
        assert chunks[1].kind == "user_engaged"
        assert len(chunks[1].messages) == 3
        assert chunks[1].messages[0]["type"] == "user"
        assert chunks[2].kind == "bot_only"
        assert len(chunks[2].messages) == 1
        _assert_no_loss(chunks, 6)

    def test_boundary_inclusive(self):
        """Message exactly at the 3-day boundary should be included (<=)."""
        day = 86400
        msgs = [
            _msg("user", 0),
            _msg("automated", day * 3),  # exactly at boundary
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        assert len(chunks) == 1
        assert chunks[0].kind == "user_engaged"
        assert len(chunks[0].messages) == 2


# ── Multiple user messages in one window ──────────────────────────────────────


class TestMultipleUsersInWindow:
    def test_trim_to_latest_user(self):
        """Two user msgs in window — trim to latest user msg + replies."""
        day = 86400
        msgs = [
            _msg("user", 0),              # anchor
            _msg("assistant", 100),        # reply to anchor
            _msg("user", day * 2),         # 2nd user msg at day 2 (within 3-day window)
            _msg("assistant", day * 2 + 100),  # reply to 2nd user msg
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        # Trim: latest user msg is at index 2 → keep anchor, reply,
        # 2nd user msg, and its reply (all 4). No trailing bot to trim.
        assert len(chunks) == 1
        assert chunks[0].kind == "user_engaged"
        assert len(chunks[0].messages) == 4
        _assert_no_loss(chunks, 4)

    def test_trim_discards_stale_bot(self):
        """Bot messages after last user reply are trimmed off."""
        day = 86400
        msgs = [
            _msg("user", 0),                   # anchor
            _msg("user", day),                  # 2nd user msg at day 1
            _msg("assistant", day + 100),       # reply to 2nd user msg (within 1h)
            _msg("automated", day * 2),         # stale bot msg (day 2, >1h from last user)
            _msg("automated", day * 2 + 30),    # stale bot msg (within 60s of prev)
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        # Trim: latest user msg at index 1 → keep [anchor, user, reply].
        # Stale bot msgs at day 2 are trimmed and become one bot-only chunk
        # (30s gap < 60s bot_gap_seconds).
        assert len(chunks) == 2
        assert chunks[0].kind == "user_engaged"
        assert len(chunks[0].messages) == 3
        assert chunks[0].messages[0]["type"] == "user"
        assert chunks[0].messages[1]["type"] == "user"
        assert chunks[0].messages[2]["type"] == "assistant"
        assert chunks[1].kind == "bot_only"
        assert len(chunks[1].messages) == 2
        _assert_no_loss(chunks, 5)

    def test_no_trim_single_user(self):
        """Only the anchor user msg — no trim, full window kept."""
        day = 86400
        msgs = [
            _msg("user", 0),
            _msg("assistant", 100),
            _msg("automated", day * 2),  # within 3-day window, no more user msgs
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        # No additional user msgs → full window kept
        assert len(chunks) == 1
        assert chunks[0].kind == "user_engaged"
        assert len(chunks[0].messages) == 3
        _assert_no_loss(chunks, 3)


# ── Preceding bot context linkage ─────────────────────────────────────────────


class TestPrecedingBotContext:
    def test_preceding_chunk_linked(self):
        """User-engaged chunk should reference preceding bot-only chunk."""
        msgs = [
            _msg("automated", 0),
            _msg("automated", 10),
            _msg("user", 100),
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        assert len(chunks) == 2
        assert chunks[0].kind == "bot_only"
        assert chunks[1].kind == "user_engaged"
        assert chunks[1].preceding_bot_chunk is chunks[0]

    def test_standalone_bot_no_preceding(self):
        """A trailing bot-only chunk has no preceding_bot_chunk (it's on bot chunks)."""
        day = 86400
        msgs = [
            _msg("user", 0),
            _msg("automated", day * 10),  # after window
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        assert len(chunks) == 2
        assert chunks[0].kind == "user_engaged"
        assert chunks[0].preceding_bot_chunk is None  # no bot before first user msg
        assert chunks[1].kind == "bot_only"
        assert chunks[1].preceding_bot_chunk is None  # dataclass default


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_messages(self):
        """Empty input returns empty list."""
        assert _pre_segment([], [], bot_gap_seconds=60, user_window_days=3) == []

    def test_all_bot_messages(self):
        """Only non-user messages → all bot-only chunks, no user-engaged."""
        msgs = [
            _msg("automated", 0),
            _msg("assistant", 10),
            _msg("automated", 200),  # gap > 60s
            _msg("team", 210),
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        assert all(c.kind == "bot_only" for c in chunks)
        assert len(chunks) == 2
        _assert_no_loss(chunks, 4)

    def test_all_user_messages(self):
        """Only user messages — trim to latest user, day 5 starts new chunk."""
        day = 86400
        msgs = [
            _msg("user", 0),          # anchor
            _msg("user", 100),         # 2nd user within window → trim point
            _msg("user", day * 5),     # outside 3-day window → new chunk
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        # Trim: user at +100s is latest → chunk1 = [user@0, user@100]
        # user at day 5 is outside window → new user-engaged chunk
        assert len(chunks) == 2
        assert chunks[0].kind == "user_engaged"
        assert len(chunks[0].messages) == 2
        assert chunks[1].kind == "user_engaged"
        assert len(chunks[1].messages) == 1
        _assert_no_loss(chunks, 3)

    def test_user_at_start(self):
        """First message is user → user-engaged chunk with no preceding bot."""
        msgs = [
            _msg("user", 0),
            _msg("assistant", 100),
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        assert len(chunks) == 1
        assert chunks[0].kind == "user_engaged"
        assert chunks[0].preceding_bot_chunk is None
        _assert_no_loss(chunks, 2)

    def test_user_at_end(self):
        """Last message is user → user-engaged chunk with just that message."""
        day = 86400
        msgs = [
            _msg("automated", 0),
            _msg("automated", 10),
            _msg("user", day * 10),  # far after bot msgs
        ]
        chat_ids = ["c1"] * len(msgs)
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        # bot-only(2 msgs) + user-engaged(1 msg)
        assert chunks[-1].kind == "user_engaged"
        assert len(chunks[-1].messages) == 1
        assert chunks[-1].messages[0]["type"] == "user"
        _assert_no_loss(chunks, 3)

    def test_missing_timestamp(self):
        """Messages with no createdAt don't crash — treated as same time."""
        msgs = [
            {"_id": "no_ts_1", "type": "automated", "message": "no ts"},
            _msg("user", 100),
        ]
        chat_ids = ["c1", "c1"]
        # Should not raise
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)
        _assert_no_loss(chunks, 2)


# ── Chat IDs alignment ───────────────────────────────────────────────────────


class TestChatIdsAlignment:
    def test_chat_ids_match_messages(self):
        """Each chunk's chat_ids has same length as its messages."""
        day = 86400
        msgs = [
            _msg("automated", 0),
            _msg("user", 100),
            _msg("automated", day * 10),
        ]
        chat_ids = ["c_bot", "c_user", "c_trail"]
        chunks = _pre_segment(msgs, chat_ids, bot_gap_seconds=60, user_window_days=3)

        for chunk in chunks:
            assert len(chunk.messages) == len(chunk.chat_ids)


# ── _build_bot_only_segments ──────────────────────────────────────────────────


class TestBuildBotOnlySegments:
    def test_produces_correct_document(self):
        """Bot-only segment has null classification fields and correct tags."""
        from bson import ObjectId

        chunk = PreSegmentChunk(
            kind="bot_only",
            messages=[
                {
                    "_id": ObjectId(),
                    "type": "automated",
                    "createdAt": datetime(2026, 1, 15),
                    "message": "hello",
                },
                {
                    "_id": ObjectId(),
                    "type": "automated",
                    "createdAt": datetime(2026, 1, 15, 0, 0, 30),
                    "message": "world",
                },
            ],
            chat_ids=[ObjectId(), ObjectId()],
        )
        user_id = ObjectId()
        segs = _build_bot_only_segments(user_id, chunk)

        assert len(segs) == 1
        seg = segs[0]
        assert seg["user_id"] == str(user_id)
        assert seg["topic"] is None
        assert seg["sub_topic"] is None
        assert seg["summary"] is None
        assert seg["sentiment"] is None
        assert seg["has_user_engagement"] is False
        assert seg["has_bot_failure"] is False
        assert seg["response_rate"] == 0.0  # bot-only — no user engagement
        assert len(seg["chat_messages"]) == 2
        assert seg["chat_started_at"] == datetime(2026, 1, 15)
        assert seg["chat_ended_at"] == datetime(2026, 1, 15, 0, 0, 30)

    def test_empty_chunk_returns_empty(self):
        """Empty chunk produces no segments."""
        chunk = PreSegmentChunk(kind="bot_only")
        from bson import ObjectId

        segs = _build_bot_only_segments(ObjectId(), chunk)
        assert segs == []
