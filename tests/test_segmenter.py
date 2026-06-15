"""
Unit tests for segmenter deterministic functions.

Covers:
  - _parse_llm_segments  (pipeline/segmentation/segmenter.py)
  - _build_segments_from_llm  (pipeline/segmentation/segmenter.py)
  - load_prompt         (pipeline/prompts/analyzer/__init__.py)
  - PromptTemplate.build_system_prompt / build_user_prompt

No LLM calls. No DB connections.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from bson import ObjectId

from pipeline.prompts.analyzer import PromptTemplate, load_prompt
from pipeline.segmentation.segmenter import (
    _build_fallback_segments,
    _build_segments_from_llm,
    _dedup_non_user_across_segments,
    _find_bot_failure_indices,
    _parse_llm_segments,
)
from pipeline.segmentation.windowing import _build_context_string, _window_messages

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_messages(n: int, chat_id: ObjectId | None = None) -> tuple[list[dict], list[ObjectId]]:
    """Build a list of n mock messages with _id, createdAt, and chat fields."""
    if chat_id is None:
        chat_id = ObjectId()
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    msgs = []
    for i in range(n):
        from datetime import timedelta
        msgs.append({
            "_id": ObjectId(),
            "createdAt": base + timedelta(minutes=i),
            "chat": chat_id,
            "type": "user" if i % 2 == 0 else "assistant",
            "message": f"message {i}",
        })
    chat_ids = [chat_id] * n
    return msgs, chat_ids


def _valid_raw_segment(**overrides) -> dict:
    """Return a minimal valid raw LLM segment dict, with optional overrides."""
    base = {
        "messageIndices": [0, 1],
        "summary": "test summary",
        "topic": "match_status",
        "subTopic": "match_drop_timing",
        "sentiment": "positive",
        "labelConfidence": 0.9,
    }
    base.update(overrides)
    return base


def _raw_json(**overrides) -> str:
    """Wrap a single valid raw segment in a JSON segments envelope."""
    seg = _valid_raw_segment(**overrides)
    return json.dumps({"segments": [seg]})


# ══════════════════════════════════════════════════════════════════════════════
# _parse_llm_segments
# ══════════════════════════════════════════════════════════════════════════════


class TestParseV2Segments:

    def test_valid_single_segment(self):
        raw = _raw_json()
        result = _parse_llm_segments(raw, n_msgs=5)
        assert len(result) == 1
        seg = result[0]
        assert seg["messageIndices"] == [0, 1]
        assert seg["summary"] == "test summary"
        assert seg["topic"] == "match_status"
        assert seg["subTopic"] == "match_drop_timing"
        assert seg["sentiment"] == "positive"
        assert seg["labelConfidence"] == 0.9

    def test_valid_multi_segment(self):
        payload = {
            "segments": [
                _valid_raw_segment(messageIndices=[0, 1], summary="first"),
                _valid_raw_segment(messageIndices=[2, 3], summary="second"),
            ]
        }
        result = _parse_llm_segments(json.dumps(payload), n_msgs=5)
        assert len(result) == 2

    def test_markdown_fences_stripped(self):
        inner = _raw_json()
        wrapped = f"```json\n{inner}\n```"
        result = _parse_llm_segments(wrapped, n_msgs=5)
        assert len(result) == 1
        assert result[0]["summary"] == "test summary"

    def test_missing_required_field_skips_segment(self):
        seg_ok = _valid_raw_segment(messageIndices=[0], summary="ok")
        seg_bad = {k: v for k, v in _valid_raw_segment(messageIndices=[1]).items() if k != "summary"}
        payload = {"segments": [seg_ok, seg_bad]}
        result = _parse_llm_segments(json.dumps(payload), n_msgs=5)
        # Only the valid segment should be kept
        assert len(result) == 1
        assert result[0]["summary"] == "ok"

    def test_empty_message_indices_skips_segment(self):
        raw = _raw_json(messageIndices=[])
        result = _parse_llm_segments(raw, n_msgs=5)
        assert result == []

    def test_out_of_bounds_indices_dropped(self):
        # n_msgs=5 means valid indices are 0–4; index 99 must be dropped
        raw = _raw_json(messageIndices=[0, 1, 99])
        result = _parse_llm_segments(raw, n_msgs=5)
        assert len(result) == 1
        assert result[0]["messageIndices"] == [0, 1]

    def test_out_of_bounds_all_invalid_skips_segment(self):
        raw = _raw_json(messageIndices=[99, 100])
        result = _parse_llm_segments(raw, n_msgs=5)
        assert result == []

    def test_invalid_sentiment_normalized_to_neutral(self):
        raw = _raw_json(sentiment="angry")
        result = _parse_llm_segments(raw, n_msgs=5)
        assert len(result) == 1
        assert result[0]["sentiment"] == "neutral"

    def test_label_confidence_clamped_above_one(self):
        raw = _raw_json(labelConfidence=1.5)
        result = _parse_llm_segments(raw, n_msgs=5)
        assert len(result) == 1
        assert result[0]["labelConfidence"] == 0.99  # clamped to < 1.0

    def test_label_confidence_clamped_below_zero(self):
        raw = _raw_json(labelConfidence=-0.3)
        result = _parse_llm_segments(raw, n_msgs=5)
        assert len(result) == 1
        assert result[0]["labelConfidence"] == 0.0

    def test_no_json_object_returns_empty(self):
        result = _parse_llm_segments("not json at all", n_msgs=5)
        assert result == []

    def test_json_decode_error_returns_empty(self):
        result = _parse_llm_segments("{broken json", n_msgs=5)
        assert result == []

    def test_missing_segments_key_returns_empty(self):
        result = _parse_llm_segments(json.dumps({"data": []}), n_msgs=5)
        assert result == []

    def test_empty_response_returns_empty(self):
        result = _parse_llm_segments("", n_msgs=5)
        assert result == []

    def test_parse_bot_question_and_user_answer_counts(self):
        """Parser extracts botPromptCount and userResponseCount when present."""
        raw = _raw_json(botPromptCount=3, userResponseCount=2)
        result = _parse_llm_segments(raw, n_msgs=5)
        assert len(result) == 1
        assert result[0]["botPromptCount"] == 3
        assert result[0]["userResponseCount"] == 2

    def test_parse_missing_engagement_counts_defaults_to_none(self):
        """Parser defaults botPromptCount and userResponseCount to None when absent."""
        raw = _raw_json()  # base fixture has no engagement count keys
        result = _parse_llm_segments(raw, n_msgs=5)
        assert len(result) == 1
        assert result[0]["botPromptCount"] is None
        assert result[0]["userResponseCount"] is None

    def test_missing_sentiment_accepted_as_none(self):
        """Bot-only segments may omit sentiment — parser should accept with None."""
        seg = _valid_raw_segment()
        del seg["sentiment"]
        payload = {"segments": [seg]}
        result = _parse_llm_segments(json.dumps(payload), n_msgs=5)
        assert len(result) == 1
        assert result[0]["sentiment"] is None


# ══════════════════════════════════════════════════════════════════════════════
# _build_segments_from_llm
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildSegmentsV2:

    def _llm_seg(self, **overrides) -> dict:
        """Return a minimal parsed LLM segment (output of _parse_llm_segments)."""
        base = {
            "messageIndices": [0, 1],
            "summary": "user discussed match timing",
            "topic": "match_status",
            "subTopic": "match_drop_timing",
            "sentiment": "neutral",
            "labelConfidence": 0.85,
            "botPromptCount": 2,
            "userResponseCount": 2,
        }
        base.update(overrides)
        return base

    def test_single_segment_maps_correctly(self):
        msgs, chat_ids = _make_messages(3)
        llm_segs = [self._llm_seg(messageIndices=[0, 1, 2])]
        user_id = ObjectId()
        result = _build_segments_from_llm(user_id, msgs, chat_ids, llm_segs)
        assert len(result) == 1
        doc = result[0]
        assert doc["chat_messages"] == [str(msgs[0]["_id"]), str(msgs[1]["_id"]), str(msgs[2]["_id"])]
        assert doc["topic"] == "match_status"
        assert doc["summary"] == "user discussed match timing"
        assert doc["sentiment"] == "neutral"
        assert doc["label_confidence"] == 0.85

    def test_multi_segment(self):
        msgs, chat_ids = _make_messages(4)
        llm_segs = [
            self._llm_seg(messageIndices=[0, 1]),
            self._llm_seg(messageIndices=[2, 3], topic="match_feedback", subTopic="post_date_feedback"),
        ]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        assert len(result) == 2

    def test_no_novelty_flags_on_segments(self):
        """Segments must not contain isNewTopic/isNewSubTopic — novelty is tracked in taxonomy."""
        msgs, chat_ids = _make_messages(2)
        llm_segs = [self._llm_seg(topic="match_status", subTopic="invented_subtopic")]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        assert "isNewTopic" not in result[0]
        assert "isNewSubTopic" not in result[0]

    def test_timestamps_from_messages(self):
        msgs, chat_ids = _make_messages(3)
        llm_segs = [self._llm_seg(messageIndices=[0, 2])]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        doc = result[0]
        assert doc["chat_started_at"] == msgs[0]["createdAt"].replace(tzinfo=None) or doc["chat_started_at"] == msgs[0]["createdAt"]
        assert doc["chat_ended_at"] == msgs[2]["createdAt"].replace(tzinfo=None) or doc["chat_ended_at"] == msgs[2]["createdAt"]

    def test_classified_at_is_set(self):
        msgs, chat_ids = _make_messages(2)
        llm_segs = [self._llm_seg()]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        assert result[0]["classified_at"] is not None

    def test_review_fields_not_in_segment(self):
        """Review fields are omitted from segment dicts — PG defaults handle them."""
        msgs, chat_ids = _make_messages(2)
        llm_segs = [self._llm_seg()]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        doc = result[0]
        assert "true_topic" not in doc
        assert "true_sub_topic" not in doc
        assert "reviewed_by" not in doc
        assert "reviewed_at" not in doc

    def test_deferred_fields_are_null(self):
        msgs, chat_ids = _make_messages(2)
        llm_segs = [self._llm_seg()]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        doc = result[0]
        assert doc["cluster"] is None

    def test_has_user_engagement_true_when_user_message_present(self):
        """hasUserEngagement is true when segment contains a user-type message."""
        msgs, chat_ids = _make_messages(3)  # alternating user/assistant/user
        llm_segs = [self._llm_seg(messageIndices=[0, 1])]  # msg 0 is user
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        assert result[0]["has_user_engagement"] is True

    def test_has_user_engagement_false_when_only_assistant_messages(self):
        """hasUserEngagement is false when segment only has assistant messages."""
        chat_id = ObjectId()
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        from datetime import timedelta
        # Create messages that are ALL assistant type
        msgs = [
            {"_id": ObjectId(), "createdAt": base + timedelta(minutes=i),
             "chat": chat_id, "type": "assistant", "message": f"bot msg {i}"}
            for i in range(3)
        ]
        chat_ids = [chat_id] * 3
        llm_segs = [self._llm_seg(messageIndices=[0, 1, 2])]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        assert result[0]["has_user_engagement"] is False

    def test_response_rate_normal(self):
        """responseRate = userResponseCount / botPromptCount, clamped to 1.0."""
        msgs, chat_ids = _make_messages(4)
        llm_segs = [self._llm_seg(
            messageIndices=[0, 1, 2, 3], botPromptCount=2, userResponseCount=2,
        )]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        # 2 answers / 2 questions = 1.0
        assert result[0]["response_rate"] == 1.0

    def test_response_rate_partial(self):
        """responseRate < 1.0 when user answers fewer questions than bot asked."""
        msgs, chat_ids = _make_messages(4)
        llm_segs = [self._llm_seg(
            messageIndices=[0, 1, 2, 3], botPromptCount=3, userResponseCount=1,
        )]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        assert abs(result[0]["response_rate"] - 1 / 3) < 0.01

    def test_response_rate_zero_when_no_user_messages(self):
        """responseRate = 0.0 when LLM reports bot asked questions but user answered none."""
        msgs, chat_ids = _make_messages(4)
        llm_segs = [self._llm_seg(messageIndices=[0, 1, 2], botPromptCount=3, userResponseCount=0)]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        assert result[0]["response_rate"] == 0.0

    def test_response_rate_zero_when_no_bot_questions(self):
        """responseRate is 0.0 when LLM reports 0 bot questions (nothing to respond to)."""
        msgs, chat_ids = _make_messages(2)
        llm_segs = [self._llm_seg(messageIndices=[0, 1], botPromptCount=0, userResponseCount=2)]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        assert result[0]["response_rate"] == 0.0

    def test_response_rate_zero_when_llm_omits_counts(self):
        """responseRate is 0.0 when LLM segment dict lacks botPromptCount/userResponseCount."""
        msgs, chat_ids = _make_messages(2)
        seg = {
            "messageIndices": [0, 1],
            "summary": "no counts",
            "topic": "match_status",
            "subTopic": "match_drop_timing",
            "sentiment": "neutral",
            "labelConfidence": 0.85,
            # intentionally omitting botPromptCount and userResponseCount
        }
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, [seg])
        assert result[0]["response_rate"] == 0.0

    def test_sentiment_null_when_no_user_engagement(self):
        """Segments with only non-user messages must have sentiment=None."""
        chat_id = ObjectId()
        from datetime import datetime, timezone
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # All assistant messages — no user engagement
        msgs = [
            {"_id": ObjectId(), "createdAt": base, "chat": chat_id,
             "type": "assistant", "message": "hello"},
            {"_id": ObjectId(), "createdAt": base, "chat": chat_id,
             "type": "assistant", "message": "world"},
        ]
        chat_ids = [chat_id, chat_id]
        llm_seg = self._llm_seg(
            messageIndices=[0, 1],
            sentiment="neutral",  # LLM provided sentiment, but business rule overrides
        )
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, [llm_seg])
        assert len(result) == 1
        assert result[0]["has_user_engagement"] is False
        assert result[0]["sentiment"] is None
        assert result[0]["label_confidence"] == 1.0

    def test_sentiment_preserved_when_user_engaged(self):
        """Segments with user messages preserve the LLM-assigned sentiment."""
        msgs, chat_ids = _make_messages(2)  # alternating user/assistant
        llm_seg = self._llm_seg(messageIndices=[0, 1], sentiment="positive")
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, [llm_seg])
        assert len(result) == 1
        assert result[0]["has_user_engagement"] is True
        assert result[0]["sentiment"] == "positive"
        assert result[0]["label_confidence"] == 0.85  # LLM value preserved

    def test_response_rate_zero_when_no_user_engagement(self):
        """Segments with no user messages must have responseRate=0.0."""
        chat_id = ObjectId()
        from datetime import datetime, timezone
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # All assistant messages — no user engagement
        msgs = [
            {"_id": ObjectId(), "createdAt": base, "chat": chat_id,
             "type": "assistant", "message": "hello"},
            {"_id": ObjectId(), "createdAt": base, "chat": chat_id,
             "type": "assistant", "message": "world"},
        ]
        chat_ids = [chat_id, chat_id]
        llm_seg = self._llm_seg(
            messageIndices=[0, 1],
            botPromptCount=2,
            userResponseCount=0,
        )
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, [llm_seg])
        assert len(result) == 1
        assert result[0]["has_user_engagement"] is False
        assert result[0]["response_rate"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# load_prompt
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadPrompt:

    def test_load_v3_returns_prompt_template(self):
        pt = load_prompt("v3")
        assert isinstance(pt, PromptTemplate)
        assert pt.version == "v3"

    def test_load_v3_has_callable_methods(self):
        pt = load_prompt("v3")
        assert callable(pt.build_system_prompt)
        assert callable(pt.build_user_prompt)

    def test_load_latest_resolves_to_highest_version(self):
        pt = load_prompt("latest")
        assert isinstance(pt, PromptTemplate)
        assert pt.version >= "v3"

    def test_load_empty_string_same_as_latest(self):
        pt_empty = load_prompt("")
        pt_latest = load_prompt("latest")
        assert pt_empty.version == pt_latest.version

    def test_invalid_version_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("v999")


# ══════════════════════════════════════════════════════════════════════════════
# v3 prompt output
# ══════════════════════════════════════════════════════════════════════════════


class TestV3PromptOutput:

    def setup_method(self):
        self.pt = load_prompt("v3")

    def test_system_prompt_non_empty_and_contains_json(self):
        system = self.pt.build_system_prompt()
        assert isinstance(system, str)
        assert len(system) > 0
        assert "JSON" in system

    def test_user_prompt_includes_history(self):
        history = "0 [user]: hi"
        result = self.pt.build_user_prompt(
            n_msgs=1,
            history=history,
            taxonomy="  • t: d",
            topic_options="t | <new_snake_case_topic>",
            previous_segments="",
        )
        assert "0 [user]: hi" in result

    def test_user_prompt_includes_taxonomy(self):
        result = self.pt.build_user_prompt(
            n_msgs=1,
            history="0 [user]: hi",
            taxonomy="  • t: d",
            topic_options="t | <new_snake_case_topic>",
            previous_segments="",
        )
        # The taxonomy block renders "  • t: d"
        assert "t: d" in result

    def test_user_prompt_includes_previous_segments_when_provided(self):
        context = "## Active Topics (from previous windows)\n- foo / bar: \"example\"\n\n"
        result = self.pt.build_user_prompt(
            n_msgs=1,
            history="0 [user]: hi",
            taxonomy="  • t: d",
            topic_options="t | <new_snake_case_topic>",
            previous_segments=context,
        )
        assert "Active Topics" in result
        assert "foo / bar" in result

    def test_user_prompt_empty_previous_segments_omits_context_block(self):
        result = self.pt.build_user_prompt(
            n_msgs=1,
            history="0 [user]: hi",
            taxonomy="  • t: d",
            topic_options="t | <new_snake_case_topic>",
            previous_segments="",
        )
        assert "Active Topics" not in result


# ══════════════════════════════════════════════════════════════════════════════
# _window_messages
# ══════════════════════════════════════════════════════════════════════════════


def _make_typed_messages(types: list[str]) -> list[dict]:
    """Build messages with specified types."""
    return [{"type": t, "message": f"msg {i}"} for i, t in enumerate(types)]


class TestWindowMessages:

    def test_no_windowing_when_window_size_zero(self):
        msgs = _make_typed_messages(["user", "assistant"] * 150)
        windows = _window_messages(msgs, 0)
        assert len(windows) == 1
        assert windows[0] is msgs

    def test_no_windowing_when_msgs_fit_in_one_window(self):
        msgs = _make_typed_messages(["user", "assistant"] * 50)
        windows = _window_messages(msgs, 200)
        assert len(windows) == 1
        assert windows[0] is msgs

    def test_splits_500_msgs_into_multiple_windows(self):
        # 500 messages, window_size=200 → should produce at least 2 windows
        msgs = [{"type": "user" if i % 2 == 0 else "assistant"} for i in range(500)]
        windows = _window_messages(msgs, 200)
        assert len(windows) >= 2
        total = sum(len(w) for w in windows)
        assert total == 500

    def test_all_messages_covered_exactly_once(self):
        # Every message must appear in exactly one window
        msgs = [{"type": "user" if i % 2 == 0 else "assistant", "_id": i} for i in range(450)]
        windows = _window_messages(msgs, 200)
        all_ids = [m["_id"] for w in windows for m in w]
        assert all_ids == list(range(450))

    def test_each_window_starts_with_user_message(self):
        # Windows 1+ should start with a user message (boundary snapping)
        msgs = [{"type": "user" if i % 2 == 0 else "assistant"} for i in range(500)]
        windows = _window_messages(msgs, 200)
        for win in windows[1:]:
            assert win[0].get("type") == "user", (
                f"Window starting message is not 'user': {win[0]}"
            )

    def test_empty_messages_returns_empty(self):
        assert _window_messages([], 200) == []

    def test_exactly_window_size_returns_one_window(self):
        msgs = _make_typed_messages(["user", "assistant"] * 100)
        windows = _window_messages(msgs, 200)
        assert len(windows) == 1

    def test_window_size_negative_treated_as_no_windowing(self):
        msgs = _make_typed_messages(["user"] * 300)
        windows = _window_messages(msgs, -1)
        assert len(windows) == 1


# ══════════════════════════════════════════════════════════════════════════════
# _build_context_string
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildContextString:

    def _seg(self, topic: str, sub_topic: str, summary: str) -> dict:
        return {"topic": topic, "sub_topic": sub_topic, "summary": summary}

    def test_empty_existing_context_with_new_segments(self):
        new_segs = [self._seg("match_status", "drop_timing", "User asked about timing")]
        result = _build_context_string("", new_segs, offset=0)
        assert "Active Topics (from previous windows)" in result
        assert "match_status / drop_timing" in result
        assert "User asked about timing" in result

    def test_existing_context_is_preserved(self):
        existing = (
            "## Active Topics (from previous windows)\n"
            "- foo / bar: \"old summary\"\n\n"
        )
        new_segs = [self._seg("new_topic", "new_sub", "new summary")]
        result = _build_context_string(existing, new_segs, offset=200)
        assert "foo / bar" in result
        assert "old summary" in result
        assert "new_topic / new_sub" in result

    def test_no_duplicate_header(self):
        existing = (
            "## Active Topics (from previous windows)\n"
            "- foo / bar: \"old summary\"\n\n"
        )
        new_segs = [self._seg("a", "b", "c")]
        result = _build_context_string(existing, new_segs, offset=0)
        assert result.count("## Active Topics") == 1

    def test_empty_existing_and_empty_new_returns_empty(self):
        result = _build_context_string("", [], offset=0)
        assert result == ""


# ══════════════════════════════════════════════════════════════════════════════
# _find_bot_failure_indices
# ══════════════════════════════════════════════════════════════════════════════


class TestFindBotFailureIndices:

    def test_normal_alternating_conversation_no_failures(self):
        """user → assistant → user → assistant has no bot failures."""
        msgs = _make_typed_messages(["user", "assistant", "user", "assistant"])
        assert _find_bot_failure_indices(msgs) == set()

    def test_user_at_end_with_no_reply_is_failure(self):
        """A user message at the end with no subsequent reply is a failure."""
        msgs = _make_typed_messages(["user", "assistant", "user"])
        assert _find_bot_failure_indices(msgs) == {2}

    def test_consecutive_user_messages_first_is_failure(self):
        """user → user → assistant: first user got no reply."""
        msgs = _make_typed_messages(["user", "user", "assistant"])
        assert _find_bot_failure_indices(msgs) == {0}

    def test_noreply_system_message_excuses_silence(self):
        """user → [Tool Call] noReply is NOT a failure."""
        msgs = [
            {"type": "user", "message": "hello"},
            {"type": "system", "message": "[Tool Call] noReply"},
        ]
        assert _find_bot_failure_indices(msgs) == set()

    def test_non_noreply_system_message_does_not_excuse(self):
        """user → system (other content) → end IS a failure."""
        msgs = [
            {"type": "user", "message": "hello"},
            {"type": "system", "message": "[Tool Call] someOtherAction"},
        ]
        assert _find_bot_failure_indices(msgs) == {0}

    def test_automated_counts_as_reply(self):
        """user → automated is NOT a failure."""
        msgs = _make_typed_messages(["user", "automated"])
        assert _find_bot_failure_indices(msgs) == set()

    def test_team_counts_as_reply(self):
        """user → team is NOT a failure."""
        msgs = _make_typed_messages(["user", "team"])
        assert _find_bot_failure_indices(msgs) == set()

    def test_empty_message_list(self):
        assert _find_bot_failure_indices([]) == set()

    def test_all_assistant_messages_no_failures(self):
        msgs = _make_typed_messages(["assistant", "assistant", "assistant"])
        assert _find_bot_failure_indices(msgs) == set()

    def test_single_user_message_is_failure(self):
        """A lone user message with nothing after it is a failure."""
        msgs = _make_typed_messages(["user"])
        assert _find_bot_failure_indices(msgs) == {0}

    def test_multiple_failures_in_conversation(self):
        """user → user → user → assistant: first two are failures."""
        msgs = _make_typed_messages(["user", "user", "user", "assistant"])
        assert _find_bot_failure_indices(msgs) == {0, 1}

    def test_noreply_then_new_user_message_without_reply(self):
        """user → noReply (excused) → user (no reply = failure)."""
        msgs = [
            {"type": "user", "message": "first question"},
            {"type": "system", "message": "[Tool Call] noReply"},
            {"type": "user", "message": "second question"},
        ]
        assert _find_bot_failure_indices(msgs) == {2}

    def test_complex_interleaving(self):
        """Mixed scenario with multiple patterns."""
        msgs = [
            {"type": "user", "message": "q1"},           # 0: replied by assistant at 1
            {"type": "assistant", "message": "a1"},       # 1
            {"type": "user", "message": "q2"},            # 2: no reply → FAILURE
            {"type": "user", "message": "q3"},            # 3: replied by team at 4
            {"type": "team", "message": "t1"},            # 4
            {"type": "user", "message": "q4"},            # 5: excused by noReply
            {"type": "system", "message": "[Tool Call] noReply"},  # 6
            {"type": "user", "message": "q5"},            # 7: no reply → FAILURE
        ]
        assert _find_bot_failure_indices(msgs) == {2, 7}

    def test_assistant_after_gap_still_counts_as_reply(self):
        """user → automated → assistant: user at 0 got reply (automated)."""
        msgs = _make_typed_messages(["user", "automated", "assistant"])
        assert _find_bot_failure_indices(msgs) == set()


# ══════════════════════════════════════════════════════════════════════════════
# hasBotFailure in _build_segments_from_llm
# ══════════════════════════════════════════════════════════════════════════════


class TestHasBotFailureV2:

    def _llm_seg(self, **overrides) -> dict:
        base = {
            "messageIndices": [0, 1],
            "summary": "test",
            "topic": "match_status",
            "subTopic": "match_drop_timing",
            "sentiment": "neutral",
            "labelConfidence": 0.85,
            "botPromptCount": 1,
            "userResponseCount": 1,
        }
        base.update(overrides)
        return base

    def test_no_failure_in_normal_segment(self):
        """Alternating user/assistant — hasBotFailure is False."""
        msgs, chat_ids = _make_messages(4)  # user, assistant, user, assistant
        llm_segs = [self._llm_seg(messageIndices=[0, 1, 2, 3])]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        assert result[0]["has_bot_failure"] is False

    def test_failure_when_user_unanswered(self):
        """Segment contains a user message with no reply — hasBotFailure is True."""
        chat_id = ObjectId()
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        from datetime import timedelta
        msgs = [
            {"_id": ObjectId(), "createdAt": base, "chat": chat_id,
             "type": "user", "message": "hello"},
            {"_id": ObjectId(), "createdAt": base + timedelta(minutes=1),
             "chat": chat_id, "type": "user", "message": "anyone there?"},
            {"_id": ObjectId(), "createdAt": base + timedelta(minutes=2),
             "chat": chat_id, "type": "assistant", "message": "sorry!"},
        ]
        chat_ids = [chat_id] * 3
        # Segment covers msgs 0 and 1 — msg 0 is a bot failure (next is user, not assistant)
        llm_segs = [self._llm_seg(messageIndices=[0, 1])]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        assert result[0]["has_bot_failure"] is True

    def test_two_segments_different_failure_status(self):
        """One segment has failure, other doesn't — flags are independent."""
        chat_id = ObjectId()
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        from datetime import timedelta
        msgs = [
            {"_id": ObjectId(), "createdAt": base, "chat": chat_id,
             "type": "user", "message": "q1"},
            {"_id": ObjectId(), "createdAt": base + timedelta(minutes=1),
             "chat": chat_id, "type": "user", "message": "q2"},        # failure at 0
            {"_id": ObjectId(), "createdAt": base + timedelta(minutes=2),
             "chat": chat_id, "type": "assistant", "message": "a1"},
            {"_id": ObjectId(), "createdAt": base + timedelta(minutes=3),
             "chat": chat_id, "type": "user", "message": "q3"},
            {"_id": ObjectId(), "createdAt": base + timedelta(minutes=4),
             "chat": chat_id, "type": "assistant", "message": "a2"},
        ]
        chat_ids = [chat_id] * 5
        llm_segs = [
            self._llm_seg(messageIndices=[0, 1], summary="seg with failure"),
            self._llm_seg(messageIndices=[3, 4], summary="seg without failure",
                          topic="match_feedback", subTopic="post_date_feedback"),
        ]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        assert result[0]["has_bot_failure"] is True
        assert result[1]["has_bot_failure"] is False

    def test_noreply_excused_segment_no_failure(self):
        """Segment where silence is excused by noReply — hasBotFailure is False."""
        chat_id = ObjectId()
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        from datetime import timedelta
        msgs = [
            {"_id": ObjectId(), "createdAt": base, "chat": chat_id,
             "type": "user", "message": "bye"},
            {"_id": ObjectId(), "createdAt": base + timedelta(minutes=1),
             "chat": chat_id, "type": "system", "message": "[Tool Call] noReply"},
        ]
        chat_ids = [chat_id] * 2
        llm_segs = [self._llm_seg(messageIndices=[0])]
        result = _build_segments_from_llm(ObjectId(), msgs, chat_ids, llm_segs)
        assert result[0]["has_bot_failure"] is False


# ══════════════════════════════════════════════════════════════════════════════
# hasBotFailure in _build_fallback_segments
# ══════════════════════════════════════════════════════════════════════════════


class TestHasBotFailureFallback:

    def test_fallback_segment_with_failure(self):
        """Fallback path detects bot failure when user goes unanswered."""
        chat_id = ObjectId()
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        from datetime import timedelta
        msgs = [
            {"_id": ObjectId(), "createdAt": base, "chat": chat_id,
             "type": "user", "message": "hello"},
            {"_id": ObjectId(), "createdAt": base + timedelta(minutes=1),
             "chat": chat_id, "type": "user", "message": "hello??"},
        ]
        chat_ids = [chat_id] * 2
        result = _build_fallback_segments(ObjectId(), msgs, chat_ids, [(0, 1)])
        assert result[0]["has_bot_failure"] is True

    def test_fallback_segment_without_failure(self):
        """Fallback path: normal conversation has no bot failure."""
        msgs, chat_ids = _make_messages(4)  # alternating user/assistant
        result = _build_fallback_segments(ObjectId(), msgs, chat_ids, [(0, 3)])
        assert result[0]["has_bot_failure"] is False


# ══════════════════════════════════════════════════════════════════════════════
# v3 prompt structure
# ══════════════════════════════════════════════════════════════════════════════


class TestV3PromptStructure:

    def setup_method(self):
        self.pt = load_prompt("v3")
        self.system = self.pt.build_system_prompt()

    def test_system_contains_all_sections(self):
        """System prompt must contain all key subsections."""
        for section in [
            "### Identity",
            "### Task",
            "### Segmentation Rules",
            "### Output Field",
            "### Domain Context",
        ]:
            assert section in self.system, f"Missing section: {section}"

    def test_user_contains_all_sections(self):
        """User template must contain all 3 subsections."""
        user = self.pt.build_user_prompt(
            n_msgs=1, history="test", taxonomy="test",
            topic_options="test", previous_segments="",
        )
        for section in [
            "### Previous Segments",
            "### Message History",
            "### Taxonomy",
        ]:
            assert section in user, f"Missing section: {section}"

    def test_no_topic_options_placeholder_in_system(self):
        """The {topic_options} placeholder must not appear literally in System."""
        assert "{topic_options}" not in self.system

    def test_all_eight_fields_in_output_field(self):
        """Output Field must list all 8 segment fields."""
        output_start = self.system.find("### Output Field")
        output_end = self.system.find("### Domain Context")
        output_section = self.system[output_start:output_end]
        for field in [
            "messageIndices", "summary", "topic", "subTopic",
            "sentiment", "labelConfidence",
            "botPromptCount", "userResponseCount",
        ]:
            assert field in output_section, f"Missing field: {field}"

    def test_event_names_in_system(self):
        """System prompt must list all 4 event names."""
        for event in ["yik-yak", "la-love-yacht", "love-yacht", "nyc-gala"]:
            assert event in self.system, f"Missing event: {event}"


# ══════════════════════════════════════════════════════════════════════════════
# _dedup_non_user_across_segments
# ══════════════════════════════════════════════════════════════════════════════


def _make_dedup_messages(types: list[str]) -> list[dict]:
    """Build messages with specified types, each with _id and createdAt."""
    from datetime import timedelta

    base = datetime(2026, 1, 1, 12, 0, 0)
    return [
        {
            "_id": ObjectId(),
            "type": t,
            "createdAt": base + timedelta(minutes=i),
            "message": f"msg {i}",
        }
        for i, t in enumerate(types)
    ]


def _make_seg(msgs: list[dict], indices: list[int]) -> dict:
    """Build a minimal segment dict from message list and index list."""
    selected = [msgs[i] for i in indices]
    timestamps = [m["createdAt"] for m in selected if m.get("createdAt")]
    return {
        "chat_messages": [msgs[i]["_id"] for i in indices],
        "chat_started_at": min(timestamps) if timestamps else datetime(2026, 1, 1),
        "chat_ended_at": max(timestamps) if timestamps else datetime(2026, 1, 1),
    }


class TestDedupNonUserAcrossSegments:

    def test_dedup_non_user_removes_assistant_duplicate(self):
        """Assistant message in 2 segments → kept in one, removed from other."""
        msgs = _make_dedup_messages(["assistant", "user", "assistant", "user", "assistant"])
        seg0 = _make_seg(msgs, [0, 1, 2])
        seg1 = _make_seg(msgs, [2, 3, 4])
        segments = [seg0, seg1]
        removed = _dedup_non_user_across_segments(segments, msgs)

        assert removed == 1
        # Message 2's _id should appear in exactly one segment
        mid = msgs[2]["_id"]
        count = sum(1 for s in segments if mid in s["chat_messages"])
        assert count == 1

    def test_dedup_user_kept_in_multiple(self):
        """User message in 2 segments → kept in both (no change)."""
        msgs = _make_dedup_messages(["assistant", "user", "assistant", "user"])
        seg0 = _make_seg(msgs, [0, 1])
        seg1 = _make_seg(msgs, [1, 2, 3])
        segments = [seg0, seg1]
        removed = _dedup_non_user_across_segments(segments, msgs)

        assert removed == 0
        mid = msgs[1]["_id"]
        count = sum(1 for s in segments if mid in s["chat_messages"])
        assert count == 2

    def test_dedup_no_duplicates_unchanged(self):
        """No overlapping messages → nothing changes."""
        msgs = _make_dedup_messages(["assistant", "user", "assistant", "user"])
        seg0 = _make_seg(msgs, [0, 1])
        seg1 = _make_seg(msgs, [2, 3])
        segments = [seg0, seg1]
        removed = _dedup_non_user_across_segments(segments, msgs)

        assert removed == 0
        assert len(segments) == 2
        assert len(segments[0]["chat_messages"]) == 2
        assert len(segments[1]["chat_messages"]) == 2

    def test_dedup_empty_segment_removed(self):
        """Segment that loses all messages after dedup is removed."""
        msgs = _make_dedup_messages(["automated", "user", "assistant"])
        # seg0 has only message 0 (automated); seg1 has messages 0, 1, 2
        seg0 = _make_seg(msgs, [0])
        seg1 = _make_seg(msgs, [0, 1, 2])
        segments = [seg0, seg1]
        removed = _dedup_non_user_across_segments(segments, msgs)

        assert removed == 1
        # seg0 lost its only message and should be pruned
        assert len(segments) == 1
        assert msgs[0]["_id"] in segments[0]["chat_messages"]

    def test_dedup_timestamps_recalculated(self):
        """chatStartedAt/chatEndedAt updated after message removal."""
        msgs = _make_dedup_messages(["assistant", "user", "assistant", "user"])
        # seg0 has [0, 1, 2], seg1 has [2, 3]
        # Message 2 (assistant) duplicated. After dedup, seg1 loses msg 2.
        seg0 = _make_seg(msgs, [0, 1, 2])
        seg1 = _make_seg(msgs, [2, 3])
        segments = [seg0, seg1]

        # Before dedup, seg1 starts at t2
        assert seg1["chat_started_at"] == msgs[2]["createdAt"]

        _dedup_non_user_across_segments(segments, msgs)

        # seg1 should now start at t3 (only message 3 remains)
        assert len(segments) == 2
        assert segments[1]["chat_started_at"] == msgs[3]["createdAt"]
        assert segments[1]["chat_ended_at"] == msgs[3]["createdAt"]

    def test_dedup_proximity_picks_better_segment(self):
        """Non-user message kept in segment with more nearby messages."""
        msgs = _make_dedup_messages(
            ["assistant", "assistant", "automated", "assistant", "user", "assistant"]
        )
        # seg0 has [0, 1, 2]: indices 0, 1 are within ±3 of index 2 → score 2
        # seg1 has [2, 3, 4, 5]: indices 3, 4, 5 are within ±3 of index 2 → score 3
        seg0 = _make_seg(msgs, [0, 1, 2])
        seg1 = _make_seg(msgs, [2, 3, 4, 5])
        segments = [seg0, seg1]

        _dedup_non_user_across_segments(segments, msgs)

        mid = msgs[2]["_id"]
        # seg1 has higher proximity score → message 2 should stay in seg1
        assert mid not in segments[0]["chat_messages"]
        assert mid in segments[1]["chat_messages"]
