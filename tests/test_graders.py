"""
Unit tests for segmentation graders (G0.3, G0.7, G0.8, G0.9, G0.10, G0.11, G1.2, G1.4).

Uses lightweight mocks — no real DB connection required.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from bson import ObjectId

from pipeline.config.loader import AnalyzerConfig
from pipeline.graders.segmentation_graders import (
    g010_topic_subtopic_completeness,
    g011_label_confidence_range,
    g03_full_message_coverage,
    g07_pre_segment_completeness,
    g08_non_user_message_uniqueness,
    g09_reviewed_segment_integrity,
    g12_single_message_segments,
    g14_contiguity_check,
)

# ── Mock helpers ─────────────────────────────────────────────────────────────


def _cfg() -> AnalyzerConfig:
    """Build a minimal AnalyzerConfig with default collection names."""
    return AnalyzerConfig(
        model="test",
        prompt_version="v2",
        bot_prompt_version="bot_v1",
        temperature=0.0,
        base_url="",
        drop_existing=False,
        drop_reviewed=False,
        seg_concurrency=1,
        benchmark_mode=False,
        window_size=200,
        bot_gap_seconds=60,
        user_window_days=7,
        cluster_confidence_threshold=0.6,
        template_match_threshold=0.8,
        user_limit=0,
        relabel=False,
        col_input_user="users",
        col_input_chat="sms_chats",
        col_input_chat_message="sms_chat_messages",
        col_input_matching="matchings",
        col_input_message_template="message_templates",
        col_output_chat_segment="sms_chat_segments",
        col_output_matching_signal="matching_signals",
        col_output_template_classification="message_template_classifications",
        col_output_chat_taxonomy="sms_chat_taxonomy",
    )


def _mock_segment_repo(segments: list[dict]) -> MagicMock:
    """Create a mock SegmentRepository that returns given segments (snake_case keys)."""
    repo = MagicMock()
    repo.find_all.return_value = segments
    repo.distinct_user_ids.return_value = list({s["user_id"] for s in segments})
    repo.count_all.return_value = len(segments)
    repo.find_by_user.side_effect = lambda uid, **kw: [s for s in segments if s["user_id"] == uid]
    return repo


class FakeCursor:
    """Wraps a list to support pymongo cursor-like iteration."""

    def __init__(self, docs: list[dict]):
        self._docs = docs

    def __iter__(self):
        return iter(self._docs)

    def sort(self, field: str, direction: int) -> "FakeCursor":
        reverse = direction == -1
        self._docs = sorted(
            self._docs,
            key=lambda d: (d.get(field) is None, d.get(field)),
            reverse=reverse,
        )
        return self


class FakeCollection:
    """Minimal MongoDB collection mock supporting distinct(), find(), find_one(),
    count_documents()."""

    def __init__(self, docs: list[dict]):
        self._docs = docs

    def distinct(self, field: str):
        vals: list = []
        for doc in self._docs:
            v = doc.get(field)
            if v is not None and v not in vals:
                vals.append(v)
        return vals

    def find(self, query: dict | None = None, projection: dict | None = None):
        results = self._docs
        if query:
            results = [d for d in results if self._matches(d, query)]
        if projection:
            # MongoDB always includes _id unless explicitly excluded with {_id: 0}
            keys = set(projection.keys())
            if "_id" not in keys:
                keys.add("_id")
            results = [{k: d.get(k) for k in keys if k in d} for d in results]
        return FakeCursor(list(results))

    def find_one(self, query: dict | None = None, projection: dict | None = None):
        cursor = self.find(query, projection)
        for doc in cursor:
            return doc
        return None

    def count_documents(self, query: dict | None = None):
        if not query:
            return len(self._docs)
        # Special handling for $expr: {$eq: [{$size: "$chatMessages"}, 1]}
        if "$expr" in query:
            expr = query["$expr"]
            if (
                isinstance(expr, dict)
                and "$eq" in expr
                and isinstance(expr["$eq"], list)
                and len(expr["$eq"]) == 2
                and expr["$eq"][0] == {"$size": "$chatMessages"}
                and expr["$eq"][1] == 1
            ):
                return len([d for d in self._docs if len(d.get("chatMessages", [])) == 1])
        return len([d for d in self._docs if self._matches(d, query)])

    @staticmethod
    def _matches(doc: dict, query: dict) -> bool:
        for key, val in query.items():
            if key == "$or":
                # At least one sub-query must match
                if not any(FakeCollection._matches(doc, sub) for sub in val):
                    return False
                continue
            if key == "$expr":
                continue  # handled separately in count_documents
            if key == "$in":
                continue
            if isinstance(val, dict):
                if "$in" in val:
                    if doc.get(key) not in val["$in"]:
                        return False
                elif "$ne" in val:
                    if doc.get(key) == val["$ne"]:
                        return False
                else:
                    return False
            else:
                if doc.get(key) != val:
                    return False
        return True


class FakeDB:
    """Minimal DB mock that returns FakeCollection by name."""

    def __init__(self, collections: dict[str, FakeCollection]):
        self._collections = collections

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.get(name, FakeCollection([]))


# ── Tests ────────────────────────────────────────────────────────────────────


class TestG08NonUserMessageUniqueness:

    def test_no_duplicates_passes(self):
        """Two segments with disjoint chat_messages → PASS."""
        uid = ObjectId()
        mid0, mid1, mid2, mid3 = ObjectId(), ObjectId(), ObjectId(), ObjectId()
        segments = [
            {"user_id": uid, "chat_messages": [mid0, mid1]},
            {"user_id": uid, "chat_messages": [mid2, mid3]},
        ]
        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({"sms_chat_messages": FakeCollection([])})

        result = g08_non_user_message_uniqueness(segment_repo, input_db, _cfg())
        assert result.passed is True
        assert result.failures == 0

    def test_user_duplicate_allowed(self):
        """User message in 2 segments → PASS (allowed)."""
        uid = ObjectId()
        shared_mid = ObjectId()
        mid1, mid2 = ObjectId(), ObjectId()
        segments = [
            {"user_id": uid, "chat_messages": [shared_mid, mid1]},
            {"user_id": uid, "chat_messages": [shared_mid, mid2]},
        ]
        messages = [
            {"_id": shared_mid, "type": "user"},
        ]
        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({"sms_chat_messages": FakeCollection(messages)})

        result = g08_non_user_message_uniqueness(segment_repo, input_db, _cfg())
        assert result.passed is True
        assert result.failures == 0

    def test_assistant_duplicate_fails(self):
        """Assistant message in 2 segments → FAIL."""
        uid = ObjectId()
        shared_mid = ObjectId()
        mid1, mid2 = ObjectId(), ObjectId()
        segments = [
            {"user_id": uid, "chat_messages": [shared_mid, mid1]},
            {"user_id": uid, "chat_messages": [shared_mid, mid2]},
        ]
        messages = [
            {"_id": shared_mid, "type": "assistant"},
        ]
        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({"sms_chat_messages": FakeCollection(messages)})

        result = g08_non_user_message_uniqueness(segment_repo, input_db, _cfg())
        assert result.failures == 1
        assert "assistant" in result.details[0]

    def test_automated_duplicate_fails(self):
        """Automated message in 2 segments → FAIL."""
        uid = ObjectId()
        shared_mid = ObjectId()
        mid1, mid2 = ObjectId(), ObjectId()
        segments = [
            {"user_id": uid, "chat_messages": [shared_mid, mid1]},
            {"user_id": uid, "chat_messages": [shared_mid, mid2]},
        ]
        messages = [
            {"_id": shared_mid, "type": "automated"},
        ]
        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({"sms_chat_messages": FakeCollection(messages)})

        result = g08_non_user_message_uniqueness(segment_repo, input_db, _cfg())
        assert result.failures == 1
        assert "automated" in result.details[0]

    def test_mixed_duplicates_only_non_user_fails(self):
        """Two shared messages: one user (ok), one team (fail). → 1 failure."""
        uid = ObjectId()
        user_mid = ObjectId()
        team_mid = ObjectId()
        mid1, mid2 = ObjectId(), ObjectId()
        segments = [
            {"user_id": uid, "chat_messages": [user_mid, team_mid, mid1]},
            {"user_id": uid, "chat_messages": [user_mid, team_mid, mid2]},
        ]
        messages = [
            {"_id": user_mid, "type": "user"},
            {"_id": team_mid, "type": "team"},
        ]
        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({"sms_chat_messages": FakeCollection(messages)})

        result = g08_non_user_message_uniqueness(segment_repo, input_db, _cfg())
        assert result.failures == 1
        # Only the team message should appear in details
        assert any("team" in d for d in result.details)
        assert not any("user message" in d for d in result.details)


# ── G0.9 — Reviewed segment integrity ────────────────────────────────────────


class TestG09ReviewedSegmentIntegrity:

    def _now(self):
        return datetime.now(timezone.utc)

    def test_reviewed_intact_passes(self):
        """Segment with true_topic, true_sub_topic, reviewed_at all set → PASS."""
        seg = {
            "id": 1,
            "user_id": ObjectId(),
            "true_topic": "onboarding",
            "true_sub_topic": "profile_setup",
            "reviewed_at": self._now(),
        }
        segment_repo = _mock_segment_repo([seg])
        input_db = FakeDB({})

        result = g09_reviewed_segment_integrity(segment_repo, input_db, _cfg())
        assert result.passed is True
        assert result.total == 1
        assert result.failures == 0

    def test_no_reviewed_segments_passes(self):
        """No reviewed segments at all → PASS with total=0."""
        seg = {
            "id": 1,
            "user_id": ObjectId(),
            "true_topic": None,
            "true_sub_topic": None,
            "reviewed_at": None,
        }
        segment_repo = _mock_segment_repo([seg])
        input_db = FakeDB({})

        result = g09_reviewed_segment_integrity(segment_repo, input_db, _cfg())
        assert result.passed is True
        assert result.total == 0
        assert result.failures == 0

    def test_reviewed_missing_true_topic_fails(self):
        """reviewed_at set but true_topic null → FAIL (corrupted)."""
        seg = {
            "id": 1,
            "user_id": ObjectId(),
            "true_topic": None,
            "true_sub_topic": "profile_setup",
            "reviewed_at": self._now(),
        }
        segment_repo = _mock_segment_repo([seg])
        input_db = FakeDB({})

        result = g09_reviewed_segment_integrity(segment_repo, input_db, _cfg())
        assert result.passed is False
        assert result.failures == 1
        assert "true_topic" in result.details[0]

    def test_reviewed_missing_true_sub_topic_fails(self):
        """reviewed_at set but true_sub_topic null → FAIL (corrupted)."""
        seg = {
            "id": 1,
            "user_id": ObjectId(),
            "true_topic": "onboarding",
            "true_sub_topic": None,
            "reviewed_at": self._now(),
        }
        segment_repo = _mock_segment_repo([seg])
        input_db = FakeDB({})

        result = g09_reviewed_segment_integrity(segment_repo, input_db, _cfg())
        assert result.passed is False
        assert result.failures == 1
        assert "true_sub_topic" in result.details[0]

    def test_partial_review_true_topic_only_fails(self):
        """true_topic set but reviewed_at null → FAIL (inconsistent state)."""
        seg = {
            "id": 1,
            "user_id": ObjectId(),
            "true_topic": "onboarding",
            "true_sub_topic": None,
            "reviewed_at": None,
        }
        segment_repo = _mock_segment_repo([seg])
        input_db = FakeDB({})

        result = g09_reviewed_segment_integrity(segment_repo, input_db, _cfg())
        assert result.passed is False
        assert result.failures == 1
        assert "true_sub_topic" in result.details[0]
        assert "reviewed_at" in result.details[0]

    def test_multiple_reviewed_segments_mixed(self):
        """Two reviewed segments: one intact, one corrupted → 1 failure."""
        good_seg = {
            "id": 1,
            "user_id": ObjectId(),
            "true_topic": "onboarding",
            "true_sub_topic": "profile_setup",
            "reviewed_at": self._now(),
        }
        bad_seg = {
            "id": 2,
            "user_id": ObjectId(),
            "true_topic": "matching",
            "true_sub_topic": None,
            "reviewed_at": self._now(),
        }
        segment_repo = _mock_segment_repo([good_seg, bad_seg])
        input_db = FakeDB({})

        result = g09_reviewed_segment_integrity(segment_repo, input_db, _cfg())
        assert result.passed is False
        assert result.total == 2
        assert result.failures == 1


# ── G0.10 — Topic/sub_topic completeness ─────────────────────────────────────


class TestG010TopicSubTopicCompleteness:

    def test_all_segments_have_both_passes(self):
        """Every segment has topic + sub_topic → PASS."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "topic": "onboarding", "sub_topic": "profile_setup"},
            {"id": 2, "user_id": ObjectId(), "topic": "matching", "sub_topic": "match_status"},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g010_topic_subtopic_completeness(segment_repo, _cfg())
        assert result.passed is True
        assert result.total == 2
        assert result.failures == 0

    def test_null_topic_fails(self):
        """Segment with topic=None → FAIL."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "topic": None, "sub_topic": "profile_setup"},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g010_topic_subtopic_completeness(segment_repo, _cfg())
        assert result.passed is False
        assert result.failures == 1
        assert "topic=None" in result.details[0]

    def test_null_subtopic_fails(self):
        """Segment with sub_topic=None → FAIL."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "topic": "onboarding", "sub_topic": None},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g010_topic_subtopic_completeness(segment_repo, _cfg())
        assert result.passed is False
        assert result.failures == 1
        assert "sub_topic=None" in result.details[0]

    def test_empty_string_topic_fails(self):
        """Segment with topic='' → FAIL."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "topic": "", "sub_topic": "profile_setup"},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g010_topic_subtopic_completeness(segment_repo, _cfg())
        assert result.passed is False
        assert result.failures == 1
        assert "topic=''" in result.details[0]

    def test_empty_string_subtopic_fails(self):
        """Segment with sub_topic='' → FAIL."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "topic": "onboarding", "sub_topic": ""},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g010_topic_subtopic_completeness(segment_repo, _cfg())
        assert result.passed is False
        assert result.failures == 1
        assert "sub_topic=''" in result.details[0]

    def test_both_null_fails_once(self):
        """Segment with both topic=None and sub_topic=None → 1 failure, both fields in detail."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "topic": None, "sub_topic": None},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g010_topic_subtopic_completeness(segment_repo, _cfg())
        assert result.passed is False
        assert result.failures == 1
        assert "topic=None" in result.details[0]
        assert "sub_topic=None" in result.details[0]

    def test_no_segments_passes(self):
        """Empty collection → PASS with total=0."""
        segment_repo = _mock_segment_repo([])
        result = g010_topic_subtopic_completeness(segment_repo, _cfg())
        assert result.passed is True
        assert result.total == 0

    def test_mixed_good_and_bad(self):
        """Two good segments + one bad → 1 failure, zero tolerance = FAIL."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "topic": "onboarding", "sub_topic": "profile_setup"},
            {"id": 2, "user_id": ObjectId(), "topic": "matching", "sub_topic": "match_status"},
            {"id": 3, "user_id": ObjectId(), "topic": "matching", "sub_topic": None},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g010_topic_subtopic_completeness(segment_repo, _cfg())
        assert result.passed is False
        assert result.total == 3
        assert result.failures == 1

    def test_unclassified_passes(self):
        """Fallback 'unclassified' values are valid — not null/empty."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "topic": "unclassified", "sub_topic": "unclassified"},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g010_topic_subtopic_completeness(segment_repo, _cfg())
        assert result.passed is True
        assert result.failures == 0


# ── G0.11 — LLM label_confidence range ───────────────────────────────────────


class TestG011LabelConfidenceRange:

    def test_valid_confidence_passes(self):
        """label_confidence in [0.0, 1.0) → PASS."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "label_confidence": 0.0},
            {"id": 2, "user_id": ObjectId(), "label_confidence": 0.5},
            {"id": 3, "user_id": ObjectId(), "label_confidence": 0.99},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g011_label_confidence_range(segment_repo, _cfg())
        assert result.passed is True
        assert result.total == 3
        assert result.failures == 0

    def test_exactly_one_fails(self):
        """label_confidence == 1.0 → FAIL (must be strictly less than 1.0)."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "label_confidence": 1.0},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g011_label_confidence_range(segment_repo, _cfg())
        assert result.passed is False
        assert result.failures == 1
        assert "out of range" in result.details[0]

    def test_above_one_fails(self):
        """label_confidence > 1.0 → FAIL."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "label_confidence": 1.5},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g011_label_confidence_range(segment_repo, _cfg())
        assert result.passed is False
        assert result.failures == 1

    def test_negative_fails(self):
        """label_confidence < 0.0 → FAIL."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "label_confidence": -0.1},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g011_label_confidence_range(segment_repo, _cfg())
        assert result.passed is False
        assert result.failures == 1

    def test_null_excluded(self):
        """Segments with label_confidence=None are excluded — not checked."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "label_confidence": None},
            {"id": 2, "user_id": ObjectId(), "label_confidence": 0.85},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g011_label_confidence_range(segment_repo, _cfg())
        assert result.passed is True
        # Only the non-null segment is checked
        assert result.total == 1
        assert result.failures == 0

    def test_no_segments_passes(self):
        """Empty collection → PASS with total=0."""
        segment_repo = _mock_segment_repo([])
        result = g011_label_confidence_range(segment_repo, _cfg())
        assert result.passed is True
        assert result.total == 0

    def test_mixed_valid_and_invalid(self):
        """Two valid + one at 1.0 → 1 failure, zero tolerance = FAIL."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "label_confidence": 0.7},
            {"id": 2, "user_id": ObjectId(), "label_confidence": 0.85},
            {"id": 3, "user_id": ObjectId(), "label_confidence": 1.0},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g011_label_confidence_range(segment_repo, _cfg())
        assert result.passed is False
        assert result.total == 3
        assert result.failures == 1

    def test_zero_confidence_passes(self):
        """label_confidence == 0.0 → PASS (lower bound is inclusive)."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "label_confidence": 0.0},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g011_label_confidence_range(segment_repo, _cfg())
        assert result.passed is True
        assert result.failures == 0

    def test_bot_only_1_0_passes(self):
        """Bot-only segments (has_user_engagement=False) with label_confidence=1.0 → PASS."""
        segs = [
            {"id": 1, "user_id": ObjectId(),
             "label_confidence": 1.0, "has_user_engagement": False},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g011_label_confidence_range(segment_repo, _cfg())
        assert result.passed is True
        assert result.failures == 0

    def test_bot_only_not_1_0_fails(self):
        """Bot-only segments with label_confidence != 1.0 → FAIL."""
        segs = [
            {"id": 1, "user_id": ObjectId(),
             "label_confidence": 0.8, "has_user_engagement": False},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g011_label_confidence_range(segment_repo, _cfg())
        assert result.passed is False
        assert result.failures == 1
        assert "bot-only" in result.details[0]

    def test_mixed_user_and_bot_segments(self):
        """User-engaged [0.0, 1.0) + bot-only 1.0 → all PASS."""
        segs = [
            {"id": 1, "user_id": ObjectId(),
             "label_confidence": 0.85, "has_user_engagement": True},
            {"id": 2, "user_id": ObjectId(),
             "label_confidence": 1.0, "has_user_engagement": False},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g011_label_confidence_range(segment_repo, _cfg())
        assert result.passed is True
        assert result.total == 2
        assert result.failures == 0


# ── G0.3 — Full message coverage ─────────────────────────────────────────────


class TestG03FullMessageCoverage:

    def test_full_coverage_passes(self):
        """All PROD messages covered by segments → PASS."""
        uid = ObjectId()
        chat_id = ObjectId()
        mid0, mid1, mid2 = ObjectId(), ObjectId(), ObjectId()

        chats = [{"_id": chat_id, "user": uid}]
        messages = [
            {"_id": mid0, "chat": chat_id, "type": "user"},
            {"_id": mid1, "chat": chat_id, "type": "assistant"},
            {"_id": mid2, "chat": chat_id, "type": "user"},
        ]
        segments = [
            {"user_id": uid, "chat_messages": [str(mid0), str(mid1)]},
            {"user_id": uid, "chat_messages": [str(mid2)]},
        ]

        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({
            "sms_chats": FakeCollection(chats),
            "sms_chat_messages": FakeCollection(messages),
        })

        result = g03_full_message_coverage(segment_repo, input_db, _cfg())
        assert result.passed is True
        assert result.failures == 0

    def test_missing_message_fails(self):
        """PROD message not in any segment → FAIL, 'missing' in details."""
        uid = ObjectId()
        chat_id = ObjectId()
        mid0, mid1, mid_missing = ObjectId(), ObjectId(), ObjectId()

        chats = [{"_id": chat_id, "user": uid}]
        messages = [
            {"_id": mid0, "chat": chat_id, "type": "user"},
            {"_id": mid1, "chat": chat_id, "type": "assistant"},
            {"_id": mid_missing, "chat": chat_id, "type": "user"},
        ]
        segments = [
            {"user_id": uid, "chat_messages": [str(mid0), str(mid1)]},
            # mid_missing not in any segment
        ]

        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({
            "sms_chats": FakeCollection(chats),
            "sms_chat_messages": FakeCollection(messages),
        })

        result = g03_full_message_coverage(segment_repo, input_db, _cfg())
        assert result.failures == 1
        assert any("missing" in d for d in result.details)

    def test_overlap_fails(self):
        """Same message in 2 segments → overlap detected, 'overlapping' in details."""
        uid = ObjectId()
        chat_id = ObjectId()
        mid0, mid1 = ObjectId(), ObjectId()

        chats = [{"_id": chat_id, "user": uid}]
        messages = [
            {"_id": mid0, "chat": chat_id, "type": "user"},
            {"_id": mid1, "chat": chat_id, "type": "assistant"},
        ]
        segments = [
            {"user_id": uid, "chat_messages": [str(mid0), str(mid1)]},
            {"user_id": uid, "chat_messages": [str(mid0)]},  # mid0 duplicated
        ]

        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({
            "sms_chats": FakeCollection(chats),
            "sms_chat_messages": FakeCollection(messages),
        })

        result = g03_full_message_coverage(segment_repo, input_db, _cfg())
        assert result.failures >= 1
        assert any("overlapping" in d for d in result.details)

    def test_no_chat_skipped(self):
        """User with no chat record is silently skipped."""
        uid = ObjectId()
        segments = [{"user_id": uid, "chat_messages": [ObjectId()]}]

        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({
            "sms_chats": FakeCollection([]),  # no chat for uid
            "sms_chat_messages": FakeCollection([]),
        })

        result = g03_full_message_coverage(segment_repo, input_db, _cfg())
        assert result.passed is True
        assert result.failures == 0

    def test_no_segments_passes(self):
        """No segmented users → PASS with total=0."""
        segment_repo = _mock_segment_repo([])
        input_db = FakeDB({
            "sms_chats": FakeCollection([]),
            "sms_chat_messages": FakeCollection([]),
        })

        result = g03_full_message_coverage(segment_repo, input_db, _cfg())
        assert result.passed is True
        assert result.total == 0


# ── G0.7 — Pre-segment completeness ──────────────────────────────────────────


class TestG07PreSegmentCompleteness:

    def test_all_messages_covered_passes(self):
        """All user-facing and system noReply messages covered → PASS."""
        uid = ObjectId()
        chat_id = ObjectId()
        mid0, mid1, mid2 = ObjectId(), ObjectId(), ObjectId()

        chats = [{"_id": chat_id, "user": uid}]
        messages = [
            {"_id": mid0, "chat": chat_id, "type": "user"},
            {"_id": mid1, "chat": chat_id, "type": "assistant"},
            {"_id": mid2, "chat": chat_id, "type": "automated"},
        ]
        segments = [{"user_id": uid, "chat_messages": [str(mid0), str(mid1), str(mid2)]}]

        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({
            "sms_chats": FakeCollection(chats),
            "sms_chat_messages": FakeCollection(messages),
        })

        result = g07_pre_segment_completeness(segment_repo, input_db, _cfg())
        assert result.passed is True
        assert result.failures == 0

    def test_missing_automated_fails(self):
        """Automated message not in any segment → FAIL."""
        uid = ObjectId()
        chat_id = ObjectId()
        mid0, mid_auto = ObjectId(), ObjectId()

        chats = [{"_id": chat_id, "user": uid}]
        messages = [
            {"_id": mid0, "chat": chat_id, "type": "user"},
            {"_id": mid_auto, "chat": chat_id, "type": "automated"},
        ]
        segments = [{"user_id": uid, "chat_messages": [str(mid0)]}]  # mid_auto missing

        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({
            "sms_chats": FakeCollection(chats),
            "sms_chat_messages": FakeCollection(messages),
        })

        result = g07_pre_segment_completeness(segment_repo, input_db, _cfg())
        assert result.failures == 1
        assert any("missing" in d for d in result.details)

    def test_system_noreply_included(self):
        """System '[Tool Call] noReply' messages must be covered."""
        uid = ObjectId()
        chat_id = ObjectId()
        mid0, mid_noreply = ObjectId(), ObjectId()

        chats = [{"_id": chat_id, "user": uid}]
        messages = [
            {"_id": mid0, "chat": chat_id, "type": "user"},
            {
                "_id": mid_noreply,
                "chat": chat_id,
                "type": "system",
                "message": "[Tool Call] noReply",
            },
        ]
        # Both messages covered
        segments = [{"user_id": uid, "chat_messages": [str(mid0), str(mid_noreply)]}]

        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({
            "sms_chats": FakeCollection(chats),
            "sms_chat_messages": FakeCollection(messages),
        })

        result = g07_pre_segment_completeness(segment_repo, input_db, _cfg())
        assert result.passed is True
        assert result.failures == 0


# ── G1.2 — Single-message segments ───────────────────────────────────────────


class TestG12SingleMessageSegments:

    def test_no_single_message_passes(self):
        """All segments have multiple messages → PASS."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "chat_messages": [ObjectId(), ObjectId()]},
            {"id": 2, "user_id": ObjectId(), "chat_messages": [ObjectId(), ObjectId(), ObjectId()]},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g12_single_message_segments(segment_repo, _cfg())
        assert result.passed is True
        assert result.failures == 0

    def test_high_rate_fails(self):
        """100% single-message → FAIL (> 20% threshold)."""
        segs = [
            {"id": 1, "user_id": ObjectId(), "chat_messages": [ObjectId()]},
            {"id": 2, "user_id": ObjectId(), "chat_messages": [ObjectId()]},
        ]
        segment_repo = _mock_segment_repo(segs)
        result = g12_single_message_segments(segment_repo, _cfg())
        assert result.passed is False
        assert result.failures == 2

    def test_low_rate_passes(self):
        """10% single-message < 20% threshold → PASS."""
        segs = (
            [{"id": 0, "user_id": ObjectId(), "chat_messages": [ObjectId()]}]
            + [
                {"id": i + 1, "user_id": ObjectId(), "chat_messages": [ObjectId(), ObjectId()]}
                for i in range(9)
            ]
        )
        segment_repo = _mock_segment_repo(segs)
        result = g12_single_message_segments(segment_repo, _cfg())
        assert result.passed is True
        assert result.failures == 1

    def test_empty_collection_passes(self):
        """No segments → PASS with total=0."""
        segment_repo = _mock_segment_repo([])
        result = g12_single_message_segments(segment_repo, _cfg())
        assert result.passed is True
        assert result.total == 0


# ── G1.4 — Contiguity check ───────────────────────────────────────────────────


class TestG14ContiguityCheck:

    def _make_ts(self, offset_seconds: int = 0) -> datetime:
        return datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)

    def test_contiguous_passes(self):
        """Consecutive message indices per segment → PASS."""
        uid = ObjectId()
        chat_id = ObjectId()
        mid0, mid1, mid2, mid3 = ObjectId(), ObjectId(), ObjectId(), ObjectId()

        chats = [{"_id": chat_id, "user": uid}]
        messages = [
            {"_id": mid0, "chat": chat_id, "type": "user", "createdAt": self._make_ts(0)},
            {"_id": mid1, "chat": chat_id, "type": "assistant", "createdAt": self._make_ts(1)},
            {"_id": mid2, "chat": chat_id, "type": "user", "createdAt": self._make_ts(2)},
            {"_id": mid3, "chat": chat_id, "type": "assistant", "createdAt": self._make_ts(3)},
        ]
        segments = [
            {
                "user_id": uid,
                "chat_messages": [str(mid0), str(mid1)],
                "chat_started_at": self._make_ts(0),
            },
            {
                "user_id": uid,
                "chat_messages": [str(mid2), str(mid3)],
                "chat_started_at": self._make_ts(2),
            },
        ]

        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({
            "sms_chats": FakeCollection(chats),
            "sms_chat_messages": FakeCollection(messages),
        })

        result = g14_contiguity_check(segment_repo, input_db, _cfg())
        assert result.passed is True
        assert result.failures == 0

    def test_non_contiguous_fails(self):
        """Segment skips a message → FAIL, 'non-contiguous' in details."""
        uid = ObjectId()
        chat_id = ObjectId()
        mid0, mid1, mid2, mid3 = ObjectId(), ObjectId(), ObjectId(), ObjectId()

        chats = [{"_id": chat_id, "user": uid}]
        messages = [
            {"_id": mid0, "chat": chat_id, "type": "user", "createdAt": self._make_ts(0)},
            {"_id": mid1, "chat": chat_id, "type": "assistant", "createdAt": self._make_ts(1)},
            {"_id": mid2, "chat": chat_id, "type": "user", "createdAt": self._make_ts(2)},
            {"_id": mid3, "chat": chat_id, "type": "assistant", "createdAt": self._make_ts(3)},
        ]
        # Segment 1 skips mid1 (index 1) — non-contiguous
        segments = [
            {
                "user_id": uid,
                "chat_messages": [str(mid0), str(mid2)],
                "chat_started_at": self._make_ts(0),
            },
        ]

        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({
            "sms_chats": FakeCollection(chats),
            "sms_chat_messages": FakeCollection(messages),
        })

        result = g14_contiguity_check(segment_repo, input_db, _cfg())
        assert result.failures == 1
        assert any("non-contiguous" in d for d in result.details)

    def test_overlap_across_segments_fails(self):
        """Message in 2 segments → 'multiple segments' in details."""
        uid = ObjectId()
        chat_id = ObjectId()
        mid0, mid1, mid2 = ObjectId(), ObjectId(), ObjectId()

        chats = [{"_id": chat_id, "user": uid}]
        messages = [
            {"_id": mid0, "chat": chat_id, "type": "user", "createdAt": self._make_ts(0)},
            {"_id": mid1, "chat": chat_id, "type": "assistant", "createdAt": self._make_ts(1)},
            {"_id": mid2, "chat": chat_id, "type": "user", "createdAt": self._make_ts(2)},
        ]
        # mid1 appears in both segments — overlap
        segments = [
            {
                "user_id": uid,
                "chat_messages": [str(mid0), str(mid1)],
                "chat_started_at": self._make_ts(0),
            },
            {
                "user_id": uid,
                "chat_messages": [str(mid1), str(mid2)],
                "chat_started_at": self._make_ts(1),
            },
        ]

        segment_repo = _mock_segment_repo(segments)
        input_db = FakeDB({
            "sms_chats": FakeCollection(chats),
            "sms_chat_messages": FakeCollection(messages),
        })

        result = g14_contiguity_check(segment_repo, input_db, _cfg())
        assert result.failures == 1
        assert any("multiple segments" in d for d in result.details)
